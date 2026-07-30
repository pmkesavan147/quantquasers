import type {
  AllocationBreakdown,
  AssetClass,
  MarketSentimentItem,
  PersonalSentiment,
  Persona,
} from "@/types";

// Baseline weights per persona. Sums to 1.
const BASELINES: Record<Persona["trader_type"], Record<AssetClass, number>> = {
  long_term: { equity: 0.6, bonds: 0.3, intraday: 0.0, cash: 0.1 },
  swing: { equity: 0.5, bonds: 0.15, intraday: 0.2, cash: 0.15 },
  intraday: { equity: 0.25, bonds: 0.05, intraday: 0.6, cash: 0.1 },
  hybrid: { equity: 0.45, bonds: 0.2, intraday: 0.25, cash: 0.1 },
};

const MARKET_TILT_CAP = 0.12; // +/-12%
const CONVICTION_TILT_CAP = 0.06; // +/-6%, more conservative

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

function recencyWeightedAggregate(items: MarketSentimentItem[]): number {
  if (items.length === 0) return 0;
  const now = Date.now();
  let weightedSum = 0;
  let weightTotal = 0;
  for (const item of items) {
    const ageHours = Math.max(0, (now - new Date(item.timestamp).getTime()) / 3.6e6);
    const weight = Math.exp(-ageHours / 24) * item.confidence;
    weightedSum += item.sentiment * weight;
    weightTotal += weight;
  }
  return weightTotal > 0 ? weightedSum / weightTotal : 0;
}

/**
 * How much a given asset class should move for a given aggregate market sentiment.
 * Equity and intraday move with sentiment; bonds and cash move against it
 * (flight to safety when sentiment is negative).
 */
function marketTilt(assetClass: AssetClass, aggregateSentiment: number): number {
  const direction: Record<AssetClass, number> = {
    equity: 1,
    intraday: 0.8,
    bonds: -0.6,
    cash: -0.4,
  };
  const raw = aggregateSentiment * direction[assetClass] * MARKET_TILT_CAP;
  return clamp(raw, -MARKET_TILT_CAP, MARKET_TILT_CAP);
}

/**
 * Personal conviction tilt: driven by overall sentiment and risk_signal,
 * scaled by confidence in the extraction.
 */
function convictionTilt(assetClass: AssetClass, personal: PersonalSentiment): number {
  const riskMultiplier =
    personal.risk_signal === "risk_seeking" ? 1 : personal.risk_signal === "risk_averse" ? -1 : 0.3;
  const direction: Record<AssetClass, number> = {
    equity: 1,
    intraday: 1,
    bonds: -0.7,
    cash: -0.7,
  };
  const raw =
    personal.overall_sentiment *
    direction[assetClass] *
    riskMultiplier *
    personal.confidence *
    CONVICTION_TILT_CAP;
  return clamp(raw, -CONVICTION_TILT_CAP, CONVICTION_TILT_CAP);
}

function reasonFor(
  assetClass: AssetClass,
  marketT: number,
  convictionT: number,
  aggregateSentiment: number,
  personal: PersonalSentiment
): string {
  const label: Record<AssetClass, string> = {
    equity: "Equity",
    bonds: "Bonds",
    intraday: "Intraday",
    cash: "Cash",
  };
  const total = marketT + convictionT;
  if (Math.abs(total) < 0.005) {
    return `${label[assetClass]} held near baseline — sentiment signals were roughly neutral.`;
  }
  const sign = total > 0 ? "+" : "";
  const marketPhrase =
    Math.abs(marketT) >= 0.01
      ? aggregateSentiment > 0
        ? "positive market sentiment"
        : "negative market sentiment"
      : null;
  const personalPhrase =
    Math.abs(convictionT) >= 0.01
      ? personal.risk_signal === "risk_seeking"
        ? "your risk-seeking tone"
        : personal.risk_signal === "risk_averse"
        ? "your cautious tone"
        : "your stated outlook"
      : null;
  const drivers = [marketPhrase, personalPhrase].filter(Boolean).join(" and ");
  return `${label[assetClass]} nudged ${sign}${(total * 100).toFixed(1)}% — ${drivers || "mixed signals"}.`;
}

export function computeAllocation(
  persona: Persona,
  marketItems: MarketSentimentItem[],
  personal: PersonalSentiment
): { breakdown: AllocationBreakdown[]; aggregateMarketSentiment: number } {
  const baseline = BASELINES[persona.trader_type];
  const aggregateMarketSentiment = recencyWeightedAggregate(marketItems);

  const assetClasses: AssetClass[] = ["equity", "bonds", "intraday", "cash"];

  const raw = assetClasses.map((ac) => {
    const b = baseline[ac];
    const mt = marketTilt(ac, aggregateMarketSentiment);
    const ct = convictionTilt(ac, personal);
    const finalRaw = Math.max(0, b + mt + ct);
    return { ac, b, mt, ct, finalRaw };
  });

  const totalRaw = raw.reduce((s, r) => s + r.finalRaw, 0) || 1;

  const breakdown: AllocationBreakdown[] = raw.map(({ ac, b, mt, ct, finalRaw }) => {
    const final = finalRaw / totalRaw;
    // rescale reported tilts proportionally so baseline + market_tilt + conviction_tilt ≈ final
    const scale = totalRaw !== 0 ? 1 / totalRaw : 1;
    const scaledMt = mt * scale;
    const scaledCt = ct * scale;
    const scaledB = b * scale;
    return {
      asset_class: ac,
      baseline: Math.round(scaledB * 1000) / 10,
      market_tilt: Math.round(scaledMt * 1000) / 10,
      conviction_tilt: Math.round(scaledCt * 1000) / 10,
      final: Math.round(final * 1000) / 10,
      reason: reasonFor(ac, mt, ct, aggregateMarketSentiment, personal),
    };
  });

  return { breakdown, aggregateMarketSentiment };
}

export const TILT_CAPS = { market: MARKET_TILT_CAP, conviction: CONVICTION_TILT_CAP };
