import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import clsx from "clsx";
import { Badge, Button, Card, Empty, ErrorNote, Eyebrow, Spinner } from "@/components/ui";
import { useStore } from "@/lib/store";

// This replaced RebalanceHistory, which showed six randomly generated events
// and kept its thumbs-up/down in React state — so the "history" changed every
// mount and the feedback vanished on reload. This reads the append-only journal
// the engine writes: the same rows an auditor would read.

const KINDS = [
  { value: "", label: "everything" },
  { value: "proposal", label: "proposals" },
  { value: "verdict", label: "verdicts" },
  { value: "fill", label: "fills" },
  { value: "skip", label: "skips" },
  { value: "alert", label: "alerts" },
  { value: "note", label: "notes" },
];

const KIND_TONE: Record<string, "up" | "down" | "warn" | "neutral"> = {
  fill: "up",
  verdict: "neutral",
  proposal: "neutral",
  skip: "warn",
  alert: "down",
  note: "neutral",
};

function summarise(kind: string, payload: Record<string, unknown>): string {
  const get = (k: string) => (payload[k] === undefined ? undefined : String(payload[k]));

  if (kind === "fill") {
    return [
      get("side"),
      get("qty"),
      get("symbol"),
      "@",
      get("price"),
      payload.realised ? `· realised ${Number(payload.realised).toFixed(0)}` : "",
    ]
      .filter(Boolean)
      .join(" ");
  }
  if (kind === "skip") return `${get("symbol") ?? "—"} — ${get("reason") ?? ""}`;
  if (kind === "verdict") {
    return `${get("symbol") ?? "—"} — ${get("rule_fired") ?? get("decision") ?? ""}`;
  }
  if (kind === "note" && payload.event === "account_created") {
    return `account created — ${get("risk_band")} band, capital ${get("capital")}`;
  }
  return Object.entries(payload)
    .slice(0, 4)
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}

export default function Journal() {
  const { journal, loadJournal, dashboard } = useStore();
  const [kind, setKind] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    void loadJournal(kind || undefined);
  }, [kind, loadJournal]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Eyebrow>Audit trail</Eyebrow>
          <h1 className="font-display text-2xl font-semibold text-base-50 light:text-base-900">
            Every decision, in order
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-base-400">
            Append-only. Positions are rebuilt by replaying this, so nothing here
            is ever rewritten — including the refusals.
          </p>
        </div>
        <Button variant="outline" onClick={() => loadJournal(kind || undefined)}>
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>

      {dashboard.error && (
        <ErrorNote message={dashboard.error} onRetry={() => loadJournal(kind || undefined)} />
      )}

      <div className="flex flex-wrap gap-2">
        {KINDS.map((k) => (
          <button
            key={k.value}
            onClick={() => setKind(k.value)}
            className={clsx(
              "rounded-full border px-3 py-1 font-mono text-xs transition-colors",
              kind === k.value
                ? "border-signal-up text-signal-up"
                : "border-base-700 text-base-400 hover:border-base-500",
            )}
          >
            {k.label}
          </button>
        ))}
      </div>

      <Card className="divide-y divide-base-800">
        {journal.length === 0 && (
          <div className="p-6">
            {dashboard.loading ? (
              <Spinner label="loading…" />
            ) : (
              <Empty>Nothing journaled yet. Run a desk on the dashboard.</Empty>
            )}
          </div>
        )}

        {journal.map((entry, i) => (
          <div key={`${entry.ts}-${i}`} className="p-4">
            <button
              onClick={() => setOpen(open === i ? null : i)}
              className="flex w-full flex-wrap items-center justify-between gap-3 text-left"
            >
              <div className="flex min-w-0 items-center gap-3">
                <Badge tone={KIND_TONE[entry.kind] ?? "neutral"}>{entry.kind}</Badge>
                <span className="truncate text-sm text-base-200 light:text-base-700">
                  {summarise(entry.kind, entry.payload)}
                </span>
              </div>
              <span className="shrink-0 font-mono text-xs text-base-500">
                {new Date(entry.ts).toLocaleString("en-IN")}
              </span>
            </button>

            {open === i && (
              <pre className="mt-3 overflow-x-auto rounded-lg bg-base-950/60 p-3 font-mono text-[11px] leading-relaxed text-base-300 light:bg-base-100">
                {JSON.stringify(entry.payload, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </Card>
    </div>
  );
}
