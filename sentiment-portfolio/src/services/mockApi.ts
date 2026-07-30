import type {
  MarketSentimentItem,
  OnboardingAnswers,
  Persona,
  PersonalSentiment,
  RebalanceEvent,
} from "@/types";

// -----------------------------------------------------------------------
// This module simulates the calls a real backend would make to an LLM for
// persona classification and sentiment extraction, plus a market sentiment
// feed. Swap the bodies of these functions for real fetch() calls to your
// backend/LLM provider later — callers only depend on the shapes below.
// -----------------------------------------------------------------------

const delay = (ms: number) => new Promise((res) => setTimeout(res, ms));

const POSITIVE_WORDS = ["bull", "up", "confident", "growth", "optimis", "great", "good", "excited", "strong"];
const NEGATIVE_WORDS = ["bear", "worried", "crash", "down", "scared", "nervous", "bad", "recession", "uncertain"];
const RISK_SEEKING_WORDS = ["yolo", "aggressive", "leverage", "double down", "all in", "high risk"];
const RISK_AVERSE_WORDS = ["safe", "cautious", "protect", "capital preservation", "conservative", "worried"];

function naiveScore(text: string, words: string[]): number {
  const lower = text.toLowerCase();
  let hits = 0;
  for (const w of words) if (lower.includes(w)) hits++;
  return hits;
}

const TICKER_POOL = ["NIFTY50", "SENSEX", "AAPL", "TSLA", "NVDA", "RELIANCE", "TCS", "HDFCBANK", "USD/INR", "GOLD"];

const HEADLINE_TEMPLATES: Array<{ text: string; sentiment: number }> = [
  { text: "Tech earnings beat expectations, rally broadens across sector", sentiment: 0.72 },
  { text: "Central bank signals rate cut path remains on track", sentiment: 0.55 },
  { text: "Inflation print comes in hotter than forecast", sentiment: -0.58 },
  { text: "Global chip demand softens on inventory glut", sentiment: -0.4 },
  { text: "Retail investor participation hits multi-quarter high", sentiment: 0.35 },
  { text: "Geopolitical tension raises volatility across risk assets", sentiment: -0.66 },
  { text: "Manufacturing PMI expands for third straight month", sentiment: 0.48 },
  { text: "Currency depreciation pressures import-heavy sectors", sentiment: -0.3 },
  { text: "Bond yields ease as safe-haven demand cools", sentiment: 0.22 },
  { text: "Regulatory clarity boosts sentiment in fintech names", sentiment: 0.6 },
  { text: "Crude prices spike on supply disruption fears", sentiment: -0.45 },
  { text: "AI infrastructure spend accelerates across cloud providers", sentiment: 0.68 },
];

function randomBetween(min: number, max: number) {
  return min + Math.random() * (max - min);
}

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

/** Simulates an LLM classifying the onboarding answers into a trader persona. */
export async function classifyPersona(answers: OnboardingAnswers): Promise<Persona> {
  await delay(900);

  const horizonScore: Record<string, number> = {
    "< 1 day": 3,
    "days to weeks": 2,
    "months": 1,
    "years+": 0,
  };
  const freqScore: Record<string, number> = {
    "multiple times a day": 3,
    "a few times a week": 2,
    "monthly": 1,
    "rarely": 0,
  };

  const h = horizonScore[answers.time_horizon ?? ""] ?? 1;
  const f = freqScore[answers.trade_frequency ?? ""] ?? 1;
  const combined = (h + f) / 6; // 0-1

  let trader_type: Persona["trader_type"];
  if (combined > 0.7) trader_type = "intraday";
  else if (combined > 0.45) trader_type = "swing";
  else if (combined > 0.2) trader_type = "hybrid";
  else trader_type = "long_term";

  const drawdown = (answers.drawdown_tolerance ?? 30) / 100;
  const volatility = (answers.volatility_comfort ?? 50) / 100;
  const risk_tolerance = clamp01(drawdown * 0.5 + volatility * 0.5);

  // Confidence dips when signals disagree (e.g. long horizon but high frequency)
  const disagreement = Math.abs(h / 3 - f / 3);
  const confidence = clamp01(0.9 - disagreement * 0.4 + randomBetween(-0.05, 0.05));

  return { trader_type, risk_tolerance, confidence };
}

/** Simulates extracting structured personal sentiment from free-text. */
export async function extractPersonalSentiment(text: string): Promise<PersonalSentiment> {
  await delay(700);
  const raw = text.trim();
  const pos = naiveScore(raw, POSITIVE_WORDS);
  const neg = naiveScore(raw, NEGATIVE_WORDS);
  const seeking = naiveScore(raw, RISK_SEEKING_WORDS);
  const averse = naiveScore(raw, RISK_AVERSE_WORDS);

  let overall_sentiment = 0;
  if (pos + neg > 0) overall_sentiment = (pos - neg) / (pos + neg);
  else overall_sentiment = randomBetween(-0.15, 0.15);

  let risk_signal: PersonalSentiment["risk_signal"] = "unclear";
  if (seeking > averse && seeking > 0) risk_signal = "risk_seeking";
  else if (averse > seeking && averse > 0) risk_signal = "risk_averse";
  else if (raw.length > 20) risk_signal = "neutral";

  const mentioned = TICKER_POOL.filter((t) => raw.toLowerCase().includes(t.toLowerCase().split("/")[0].slice(0, 4)));
  const sample = mentioned.length > 0 ? mentioned : raw.length > 15 ? [pick(TICKER_POOL), pick(TICKER_POOL)] : [];
  const uniqueAssets = Array.from(new Set(sample)).slice(0, 3);

  const asset_sentiment: Record<string, number> = {};
  for (const a of uniqueAssets) {
    asset_sentiment[a] = clamp(overall_sentiment + randomBetween(-0.2, 0.2), -1, 1);
  }

  const confidence = clamp01(raw.length === 0 ? 0.2 : Math.min(0.95, 0.4 + raw.length / 220));

  return {
    overall_sentiment: clamp(overall_sentiment, -1, 1),
    confidence,
    mentioned_assets: uniqueAssets,
    asset_sentiment,
    risk_signal,
    raw_text: raw,
  };
}

/** Simulates a market sentiment feed (would be a news+NLP pipeline in production). */
export async function fetchMarketSentiment(count = 8): Promise<MarketSentimentItem[]> {
  await delay(600);
  const items: MarketSentimentItem[] = [];
  const pool = [...HEADLINE_TEMPLATES];
  for (let i = 0; i < count; i++) {
    const template = pool[i % pool.length];
    const jitter = randomBetween(-0.08, 0.08);
    const hoursAgo = randomBetween(0.5, 48);
    items.push({
      headline: template.text,
      sentiment: clamp(template.sentiment + jitter, -1, 1),
      confidence: clamp01(randomBetween(0.55, 0.95)),
      entities: [pick(TICKER_POOL), pick(TICKER_POOL)].filter((v, idx, a) => a.indexOf(v) === idx),
      timestamp: new Date(Date.now() - hoursAgo * 3.6e6).toISOString(),
    });
  }
  return items.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
}

const TRIGGER_TEMPLATES = [
  "Positive tech earnings shifted market sentiment aggregate",
  "Your check-in text signalled a more cautious outlook",
  "Inflation print pushed a flight to safety",
  "Risk-seeking language in your update raised equity conviction",
  "Overnight volatility spike triggered a defensive tilt",
  "Improved market breadth lifted equity allocation",
];

/** Simulates a persisted history of rebalance events. */
export async function fetchRebalanceHistory(): Promise<RebalanceEvent[]> {
  await delay(500);
  const classes: RebalanceEvent["asset_class"][] = ["equity", "bonds", "intraday", "cash"];
  const events: RebalanceEvent[] = [];
  for (let i = 0; i < 6; i++) {
    const ac = pick(classes);
    const from = Math.round(randomBetween(10, 55));
    const delta = randomBetween(-8, 8);
    const to = clamp(Math.round(from + delta), 0, 80);
    events.push({
      id: `rb-${i}`,
      timestamp: new Date(Date.now() - i * 26 * 3.6e6).toISOString(),
      asset_class: ac,
      from,
      to,
      trigger: pick(TRIGGER_TEMPLATES),
      feedback: null,
    });
  }
  return events;
}

function clamp01(v: number) {
  return Math.max(0, Math.min(1, v));
}
function clamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}
