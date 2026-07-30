import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import clsx from "clsx";
import { Card, Eyebrow } from "@/components/ui";
import { useStore } from "@/lib/store";

const LABELS: Record<string, string> = { equity: "Equity", bonds: "Bonds", intraday: "Intraday", cash: "Cash" };

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function RebalanceHistory() {
  const { persona, history, loadHistory, setFeedback } = useStore();
  const navigate = useNavigate();
  const [note, setNote] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!persona) {
      navigate("/");
      return;
    }
    if (history.length === 0) loadHistory();
  }, [persona]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!persona) return null;

  return (
    <div>
      <Eyebrow>Rebalance History</Eyebrow>
      <h1 className="mb-6 font-display text-2xl font-semibold text-base-50 light:text-base-900">
        What changed, and why
      </h1>

      <div className="relative space-y-4 border-l border-base-800 pl-6 light:border-base-200">
        {history.map((ev) => {
          const up = ev.to > ev.from;
          return (
            <div key={ev.id} className="relative">
              <span
                className={clsx(
                  "absolute -left-[29px] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-base-950 light:ring-wash",
                  up ? "bg-signal-up" : "bg-signal-down"
                )}
              />
              <Card className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-medium text-base-100 light:text-base-800">{LABELS[ev.asset_class]}</span>
                    <span className="font-mono text-xs tabular text-base-400">
                      {ev.from}% → {ev.to}%
                    </span>
                    <span className={clsx("font-mono text-xs tabular", up ? "text-signal-up" : "text-signal-down")}>
                      {up ? "+" : ""}
                      {ev.to - ev.from}%
                    </span>
                  </div>
                  <span className="font-mono text-[11px] text-base-500">{formatDate(ev.timestamp)}</span>
                </div>
                <p className="mt-2 text-sm text-base-300">{ev.trigger}</p>

                <div className="mt-3 flex items-center gap-2">
                  <button
                    onClick={() => setFeedback(ev.id, "up")}
                    className={clsx(
                      "rounded-md p-1.5 transition-colors",
                      ev.feedback === "up" ? "bg-signal-up/15 text-signal-up" : "text-base-500 hover:bg-base-800"
                    )}
                    aria-label="This rebalance felt right"
                  >
                    <ThumbsUp size={14} />
                  </button>
                  <button
                    onClick={() => setFeedback(ev.id, "down")}
                    className={clsx(
                      "rounded-md p-1.5 transition-colors",
                      ev.feedback === "down" ? "bg-signal-down/15 text-signal-down" : "text-base-500 hover:bg-base-800"
                    )}
                    aria-label="This rebalance felt off"
                  >
                    <ThumbsDown size={14} />
                  </button>
                  <input
                    value={note[ev.id] ?? ""}
                    onChange={(e) => setNote((n) => ({ ...n, [ev.id]: e.target.value }))}
                    placeholder="This feels off because..."
                    className="ml-1 flex-1 rounded-md border border-base-800 bg-transparent px-2.5 py-1 text-xs text-base-200 outline-none placeholder:text-base-600 focus:border-signal-up light:border-base-200"
                  />
                </div>
              </Card>
            </div>
          );
        })}
        {history.length === 0 && <p className="text-sm text-base-400">Loading history…</p>}
      </div>
    </div>
  );
}
