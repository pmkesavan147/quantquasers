import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import clsx from "clsx";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Eyebrow,
  SentimentBar,
  Spinner,
  Stat,
} from "@/components/ui";
import { useStore } from "@/lib/store";

// The old version of this screen generated headlines from a template array with
// Math.random() jitter and invented tickers. These are real Indian-market
// headlines scored one at a time by Gemma, aggregated in Python, and labelled
// with which model read them and where they came from.

export default function SentimentInsights() {
  const { market, sentiment, refreshMarket, model } = useStore();
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!market) void refreshMarket(10);
  }, [market, refreshMarket]);

  if (sentiment.error && !market) {
    return <ErrorNote message={sentiment.error} onRetry={() => refreshMarket(10)} />;
  }

  if (!market) return <Spinner label="reading the news…" />;

  const mood = market.mood;
  const origins = Object.entries(market.provenance.headline_source);
  const models = Object.entries(market.provenance.models);
  const live = origins.some(([k]) => k === "rss");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Eyebrow>Market sentiment</Eyebrow>
          <h1 className="font-display text-2xl font-semibold text-base-50 light:text-base-900">
            What the news is saying
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={live ? "up" : "neutral"}>{live ? "live headlines" : "cached / fixtures"}</Badge>
          {model && <Badge>{model.backend === "stub" ? "no model — keyword fallback" : model.model}</Badge>}
          <Button variant="outline" onClick={() => refreshMarket(10)} disabled={sentiment.loading}>
            <RefreshCw size={14} className={sentiment.loading ? "animate-spin" : ""} />
            Re-read
          </Button>
        </div>
      </div>

      {sentiment.error && <ErrorNote message={sentiment.error} onRetry={() => refreshMarket(10)} />}

      <Card className="grid grid-cols-2 gap-6 p-6 sm:grid-cols-4">
        <Stat
          label="Mood"
          value={`${mood.score >= 0 ? "+" : ""}${mood.score.toFixed(2)}`}
          tone={mood.score >= 0 ? "up" : "down"}
          sub="coverage-weighted, −1 to +1"
        />
        <Stat label="Confidence" value={`${Math.round(mood.confidence * 100)}%`} />
        <Stat label="Symbols" value={mood.symbols} />
        <Stat label="Headlines" value={mood.articles} />
      </Card>

      <Card className="p-6">
        <Eyebrow>By symbol</Eyebrow>
        <div className="mt-4 space-y-2">
          {market.symbols.length === 0 && <Empty>No coverage found.</Empty>}
          {market.symbols.map((row) => {
            const open = expanded === row.symbol;
            return (
              <div key={row.symbol} className="rounded-lg border border-base-700/70">
                <button
                  onClick={() => setExpanded(open ? null : row.symbol)}
                  className="flex w-full flex-wrap items-center justify-between gap-3 p-4 text-left"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="font-display text-sm font-semibold text-base-50 light:text-base-900">
                      {row.symbol}
                    </span>
                    <span className="truncate text-xs text-base-400">{row.name}</span>
                    {row.top_events.slice(0, 2).map((e) => (
                      <Badge key={e}>{e.replace("_", " ")}</Badge>
                    ))}
                  </div>
                  <div className="flex items-center gap-4">
                    <SentimentBar value={row.score} />
                    <span
                      className={clsx(
                        "w-14 text-right font-mono text-xs tabular",
                        row.score >= 0 ? "text-signal-up" : "text-signal-down",
                      )}
                    >
                      {row.score >= 0 ? "+" : ""}
                      {row.score.toFixed(2)}
                    </span>
                    <span className="w-24 text-right font-mono text-xs text-base-400">
                      {row.n_articles} art · {Math.round(row.confidence * 100)}%
                    </span>
                  </div>
                </button>

                {open && (
                  <div className="border-t border-base-800 p-4">
                    {row.drivers.length === 0 ? (
                      <Empty>No headlines for this symbol.</Empty>
                    ) : (
                      <ul className="space-y-3">
                        {row.drivers.map((d) => (
                          <li key={d.id} className="text-sm">
                            <div className="flex items-start justify-between gap-3">
                              <span className="text-base-200 light:text-base-700">
                                {d.url ? (
                                  <a
                                    href={d.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="underline decoration-dotted hover:text-base-50"
                                  >
                                    {d.title}
                                  </a>
                                ) : (
                                  d.title
                                )}
                              </span>
                              <span
                                className={clsx(
                                  "shrink-0 font-mono text-xs tabular",
                                  d.sentiment >= 0 ? "text-signal-up" : "text-signal-down",
                                )}
                              >
                                {d.sentiment >= 0 ? "+" : ""}
                                {d.sentiment.toFixed(2)}
                              </span>
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-base-500">
                              <span>{d.source}</span>
                              <span>·</span>
                              <span>{d.event_type.replace("_", " ")}</span>
                              <span>·</span>
                              <span>materiality {d.materiality}/5</span>
                              <span>·</span>
                              <span
                                className={
                                  d.model === "fallback" ? "text-signal-down" : "text-base-400"
                                }
                              >
                                {d.model}
                              </span>
                            </div>
                            <p className="mt-1 text-xs italic text-base-400">{d.rationale}</p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <p className="mt-4 border-t border-base-800 pt-3 text-xs leading-relaxed text-base-500">
          Gemma scores one headline at a time and never sees the set. The symbol
          score is a Python weighting — materiality × recency — and confidence
          falls when coverage is thin, when headlines disagree, or when no model
          could be reached. Sources:{" "}
          {origins.map(([k, v]) => `${v} ${k}`).join(", ") || "none"}. Scored by:{" "}
          {models.map(([k, v]) => `${k} (${v})`).join(", ") || "nothing"}.
        </p>
      </Card>
    </div>
  );
}
