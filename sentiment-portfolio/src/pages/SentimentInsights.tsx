import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Eyebrow, SentimentBar } from "@/components/ui";
import { useStore } from "@/lib/store";

function timeAgo(iso: string) {
  const hours = (Date.now() - new Date(iso).getTime()) / 3.6e6;
  if (hours < 1) return `${Math.round(hours * 60)}m ago`;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function SentimentInsights() {
  const { persona, marketItems, personal, aggregateMarketSentiment } = useStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (!persona) navigate("/");
  }, [persona, navigate]);

  if (!persona || !personal) return null;

  return (
    <div>
      <Eyebrow>Sentiment Insights</Eyebrow>
      <h1 className="mb-6 font-display text-2xl font-semibold text-base-50 light:text-base-900">
        What's driving the tilt
      </h1>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Market panel */}
        <Card className="p-6">
          <div className="mb-4 flex items-center justify-between">
            <Eyebrow>Market sentiment</Eyebrow>
            <div className="flex items-center gap-2">
              <SentimentBar value={aggregateMarketSentiment} />
              <span className="font-mono text-xs tabular text-base-300">
                {aggregateMarketSentiment > 0 ? "+" : ""}
                {aggregateMarketSentiment.toFixed(2)}
              </span>
            </div>
          </div>
          <div className="space-y-3">
            {marketItems.map((item, i) => (
              <div key={i} className="border-b border-base-800 pb-3 last:border-0 light:border-base-200">
                <p className="mb-1.5 text-sm text-base-100 light:text-base-800">{item.headline}</p>
                <div className="flex flex-wrap items-center gap-2">
                  <SentimentBar value={item.sentiment} />
                  <span className="font-mono text-[11px] tabular text-base-400">
                    {item.sentiment > 0 ? "+" : ""}
                    {item.sentiment.toFixed(2)}
                  </span>
                  <span className="font-mono text-[11px] text-base-500">· {(item.confidence * 100).toFixed(0)}% conf</span>
                  <span className="font-mono text-[11px] text-base-500">· {timeAgo(item.timestamp)}</span>
                  <div className="ml-auto flex gap-1">
                    {item.entities.map((e) => (
                      <span key={e} className="rounded bg-base-800 px-1.5 py-0.5 font-mono text-[10px] text-base-300 light:bg-base-100">
                        {e}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Personal panel */}
        <Card className="p-6">
          <Eyebrow>Personal sentiment</Eyebrow>
          <div className="mt-4 flex items-center gap-4">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-base-500">Overall</div>
              <div className="flex items-center gap-2">
                <SentimentBar value={personal.overall_sentiment} />
                <span className="font-mono text-sm tabular text-base-100">
                  {personal.overall_sentiment > 0 ? "+" : ""}
                  {personal.overall_sentiment.toFixed(2)}
                </span>
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-base-500">Risk signal</div>
              <span className="rounded-full bg-base-800 px-2 py-0.5 font-mono text-xs capitalize text-base-200 light:bg-base-100">
                {personal.risk_signal.replace("_", " ")}
              </span>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-base-500">Confidence</div>
              <span className="font-mono text-xs tabular text-base-300">{(personal.confidence * 100).toFixed(0)}%</span>
            </div>
          </div>

          {personal.mentioned_assets.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 text-[10px] uppercase tracking-wide text-base-500">Mentioned assets</div>
              <div className="flex flex-wrap gap-2">
                {personal.mentioned_assets.map((a) => (
                  <div key={a} className="flex items-center gap-2 rounded-lg bg-base-800 px-2.5 py-1.5 light:bg-base-100">
                    <span className="font-mono text-xs text-base-100 light:text-base-800">{a}</span>
                    <SentimentBar value={personal.asset_sentiment[a] ?? 0} />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-5">
            <div className="mb-2 text-[10px] uppercase tracking-wide text-base-500">Your check-in, verbatim</div>
            <div className="rounded-lg border border-base-800 bg-base-900/60 p-4 text-sm italic text-base-300 light:bg-base-50 light:border-base-200">
              {personal.raw_text ? `"${personal.raw_text}"` : "No text was entered — using a neutral baseline."}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
