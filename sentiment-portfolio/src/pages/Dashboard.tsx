import { useEffect, useState } from "react";
import { Pause, Play, PlayCircle, RefreshCw, Search } from "lucide-react";
import clsx from "clsx";
import {
  Badge,
  Button,
  Card,
  DeltaTag,
  Empty,
  ErrorNote,
  Eyebrow,
  Spinner,
  Stat,
  VerdictPill,
  crore,
  rupees,
} from "@/components/ui";
import { useStore } from "@/lib/store";
import { DESKS, DESK_LABEL, type Candidate, type Horizon } from "@/types";

// Everything here is rendered from /api/desks, /api/portfolio and
// /api/candidates. There is no client-side allocation maths any more — the
// browser's job is to display what Python decided and to show the refusals.

export default function Dashboard() {
  const {
    desks,
    portfolio,
    candidates,
    dashboard,
    lastRun,
    health,
    refreshDashboard,
    loadCandidates,
    runDesk,
    togglePause,
  } = useStore();

  const [selected, setSelected] = useState<Horizon>("swing");

  useEffect(() => {
    void refreshDashboard();
  }, [refreshDashboard]);

  const active = candidates[selected];
  const enabledDesk = desks.find((d) => d.name === selected);

  if (dashboard.error && !portfolio) {
    return <ErrorNote message={dashboard.error} onRetry={refreshDashboard} />;
  }

  if (!portfolio) {
    return <Spinner label="loading the floor…" />;
  }

  const pnl = portfolio.day_pnl;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Eyebrow>Trading floor</Eyebrow>
          <h1 className="font-display text-2xl font-semibold text-base-50 light:text-base-900">
            {portfolio.risk_band ? (
              <span className="capitalize">{portfolio.risk_band} book</span>
            ) : (
              "Default book"
            )}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={portfolio.mode === "paper" ? "up" : "down"}>
            {portfolio.mode}
          </Badge>
          {health && (
            <Badge tone={health.gate_armed ? "down" : "up"}>
              gate {health.gate_armed ? "armed" : "shut"}
            </Badge>
          )}
          {health && <Badge>quotes: {health.quotes}</Badge>}
          <Button variant="outline" onClick={refreshDashboard} disabled={dashboard.loading}>
            <RefreshCw size={14} className={dashboard.loading ? "animate-spin" : ""} />
            Refresh
          </Button>
          <Button variant={portfolio.halted ? "primary" : "ghost"} onClick={togglePause}>
            {portfolio.halted ? <Play size={14} /> : <Pause size={14} />}
            {portfolio.halted ? "Resume" : "Kill switch"}
          </Button>
        </div>
      </div>

      {portfolio.halted && (
        <div className="rounded-lg border border-signal-down/40 bg-signal-down/5 px-4 py-3 text-sm text-base-200">
          <span className="font-mono text-xs uppercase tracking-wider text-signal-down">
            halted
          </span>
          <span className="ml-3">{portfolio.halt_reason ?? "manual pause"}</span>
        </div>
      )}

      {dashboard.error && <ErrorNote message={dashboard.error} onRetry={refreshDashboard} />}

      {/* Firm-wide numbers */}
      <Card className="grid grid-cols-2 gap-6 p-6 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Capital" value={rupees(portfolio.capital)} />
        <Stat label="Deployed" value={rupees(portfolio.deployed)} />
        <Stat label="Cash" value={rupees(portfolio.cash)} />
        <Stat
          label="Unrealised"
          value={rupees(portfolio.unrealised_pnl, 0)}
          tone={portfolio.unrealised_pnl >= 0 ? "up" : "down"}
        />
        <Stat
          label="Day P&L"
          value={rupees(pnl, 0)}
          tone={pnl >= 0 ? "up" : "down"}
          sub={`${portfolio.orders_today} orders today`}
        />
        <Stat label="Positions" value={portfolio.positions.length} />
      </Card>

      {/* Desks */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {DESKS.map((name) => {
          const desk = desks.find((d) => d.name === name);
          const isSelected = selected === name;
          return (
            <button
              key={name}
              onClick={() => setSelected(name)}
              className={clsx(
                "rounded-xl border p-5 text-left transition-colors",
                isSelected
                  ? "border-signal-up/60 bg-signal-up/5"
                  : "border-base-700/70 bg-base-900/60 hover:border-base-500",
                desk && !desk.enabled && "opacity-60",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="font-display text-sm font-semibold text-base-50 light:text-base-900">
                  {DESK_LABEL[name]}
                </span>
                {desk?.enabled === false ? (
                  <Badge>off</Badge>
                ) : (
                  <Badge tone="up">{desk?.allocation_pct.toFixed(1)}%</Badge>
                )}
              </div>
              <div className="mt-3 font-mono text-lg tabular text-base-100 light:text-base-800">
                {rupees(desk?.capital ?? 0)}
              </div>
              <div className="mt-1 text-xs text-base-400">
                {desk?.enabled === false
                  ? "you opted out of this desk"
                  : `${desk?.open_positions ?? 0} open · max ${desk?.max_positions ?? "—"} · ${desk?.product ?? ""}`}
              </div>
              {desk && desk.enabled && desk.unrealised_pnl !== 0 && (
                <div className="mt-2">
                  <DeltaTag value={(desk.unrealised_pnl / Math.max(desk.capital, 1)) * 100} />
                </div>
              )}
            </button>
          );
        })}
      </div>

      {/* Candidates for the selected desk */}
      <Card className="p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <Eyebrow>{DESK_LABEL[selected]} desk — what the news suggests</Eyebrow>
            {active && (
              <p className="mt-1 text-xs text-base-400">
                {active.report.symbols_scanned} symbols scanned ·{" "}
                {active.report.suitable} suitable · {active.report.stretch} stretch ·{" "}
                {active.report.refused} refused · mood{" "}
                {active.report.market_mood.score >= 0 ? "+" : ""}
                {active.report.market_mood.score.toFixed(2)}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => loadCandidates(selected)}
              disabled={dashboard.loading}
            >
              <Search size={14} />
              Scan the news
            </Button>
            <Button
              onClick={() => runDesk(selected)}
              disabled={dashboard.loading || enabledDesk?.enabled === false}
            >
              <PlayCircle size={14} />
              Run the desk
            </Button>
          </div>
        </div>

        {dashboard.loading && <Spinner label="scoring headlines…" />}

        {!active && !dashboard.loading && (
          <Empty>
            Nothing scanned yet. “Scan the news” reads headlines for this desk's
            horizon, scores each one, and ranks what survives your mandate.
          </Empty>
        )}

        {active && (
          <div className="space-y-3">
            {active.candidates.map((c) => (
              <CandidateRow key={c.symbol} candidate={c} />
            ))}
            <p className="pt-2 text-xs leading-relaxed text-base-500">
              Quant numbers:{" "}
              {Object.entries(active.report.quant_source)
                .filter(([, v]) => v > 0)
                .map(([k, v]) => `${v} ${k}`)
                .join(", ") || "none"}
              . Headlines:{" "}
              {Object.entries(active.report.headline_source)
                .map(([k, v]) => `${v} ${k}`)
                .join(", ") || "none"}
              . Scored by:{" "}
              {Object.entries(active.report.headline_models)
                .map(([k, v]) => `${k} (${v})`)
                .join(", ") || "nothing"}
              .
            </p>
          </div>
        )}
      </Card>

      {/* Result of the last run */}
      {lastRun && (
        <Card className="p-6">
          <Eyebrow>Last run — {lastRun.desk} desk, {lastRun.mode}</Eyebrow>
          <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2">
            <div>
              <div className="mb-2 font-mono text-xs uppercase tracking-wider text-base-400">
                fills ({lastRun.fills.length})
              </div>
              {lastRun.fills.length === 0 ? (
                <Empty>No fills.</Empty>
              ) : (
                <ul className="space-y-1 font-mono text-xs">
                  {lastRun.fills.map((f, i) => (
                    <li key={i} className="flex justify-between gap-3">
                      <span className="text-base-200">
                        {f.side} {f.qty} {f.symbol}
                      </span>
                      <span className="tabular text-base-400">
                        @ {rupees(f.price, 2)}
                        <span className="ml-2 text-base-500">
                          costs {rupees(f.costs, 2)}
                        </span>
                        {f.realised !== 0 && (
                          <span
                            className={clsx(
                              "ml-2",
                              f.realised >= 0 ? "text-signal-up" : "text-signal-down",
                            )}
                          >
                            {f.realised >= 0 ? "+" : ""}
                            {f.realised.toFixed(0)}
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <div className="mb-2 font-mono text-xs uppercase tracking-wider text-base-400">
                refusals ({lastRun.vetoed.length + lastRun.skipped.length})
              </div>
              {lastRun.vetoed.length + lastRun.skipped.length === 0 ? (
                <Empty>Nothing refused.</Empty>
              ) : (
                <ul className="space-y-1 font-mono text-xs">
                  {lastRun.vetoed.map((v, i) => (
                    <li key={`v${i}`} className="flex justify-between gap-3">
                      <span className="text-base-200">{v.symbol}</span>
                      <span className="text-signal-down">{v.rule}</span>
                    </li>
                  ))}
                  {lastRun.skipped.map((s, i) => (
                    <li key={`s${i}`} className="flex justify-between gap-3">
                      <span className="text-base-200">{s.symbol}</span>
                      <span className="text-base-400">{s.reason}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Open positions */}
      <Card className="p-6">
        <Eyebrow>Open positions</Eyebrow>
        {portfolio.positions.length === 0 ? (
          <div className="mt-3">
            <Empty>Flat. Run a desk to open something.</Empty>
          </div>
        ) : (
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="text-left font-mono text-[10px] uppercase tracking-wider text-base-500">
                <th className="pb-2">symbol</th>
                <th className="pb-2">desk</th>
                <th className="pb-2 text-right">qty</th>
                <th className="pb-2 text-right">avg price</th>
                <th className="pb-2 text-right">cost basis</th>
                <th className="pb-2 text-right">product</th>
                <th className="pb-2 text-right">opened</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular">
              {/* No per-position LTP: /api/portfolio reports unrealised P&L
                  firm-wide, and inventing a mark here would be the browser
                  computing a number again. */}
              {portfolio.positions.map((p) => (
                <tr key={`${p.desk}-${p.symbol}`} className="border-t border-base-800">
                  <td className="py-2 text-base-100 light:text-base-800">{p.symbol}</td>
                  <td className="py-2 text-base-400">{p.desk ?? "—"}</td>
                  <td className="py-2 text-right text-base-200">{p.qty}</td>
                  <td className="py-2 text-right text-base-300">{rupees(p.avg_price, 2)}</td>
                  <td className="py-2 text-right text-base-300">
                    {rupees(p.avg_price * p.qty, 0)}
                  </td>
                  <td className="py-2 text-right text-base-400">{p.product ?? "—"}</td>
                  <td className="py-2 text-right text-base-500">
                    {p.opened_at ? new Date(p.opened_at).toLocaleDateString("en-IN") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function CandidateRow({ candidate: c }: { candidate: Candidate }) {
  const [open, setOpen] = useState(false);
  const refused = c.verdict.level === "OUTSIDE_MANDATE";

  return (
    <div
      className={clsx(
        "rounded-lg border p-4",
        refused ? "border-base-800 bg-base-900/40" : "border-base-700/70",
      )}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center justify-between gap-3 text-left"
      >
        <div className="flex min-w-0 items-center gap-3">
          <span
            className={clsx(
              "font-display text-sm font-semibold",
              refused
                ? "text-base-500 line-through"
                : "text-base-50 light:text-base-900",
            )}
          >
            {c.symbol}
          </span>
          <span className="truncate text-xs text-base-400">{c.quant.name}</span>
          <VerdictPill level={c.verdict.level} />
          <Badge>{c.quant.cap_bucket}</Badge>
        </div>
        <div className="flex items-center gap-4 font-mono text-xs tabular">
          <span className="text-base-400">
            score <span className="text-base-100">{c.composite_score.toFixed(1)}</span>
          </span>
          <DeltaTag value={c.sentiment.score * 100} />
          <span className="text-base-400">
            {c.sentiment.n_articles} art · {Math.round(c.sentiment.confidence * 100)}%
          </span>
        </div>
      </button>

      <p className="mt-2 text-sm leading-relaxed text-base-300">{c.explanation}</p>

      {c.verdict.reasons.length > 0 && (
        <ul className="mt-3 space-y-1">
          {c.verdict.reasons.map((r) => (
            <li key={r.code} className="flex items-start gap-2 text-xs">
              <Badge tone={r.severity === "block" ? "down" : "warn"}>{r.code}</Badge>
              <span className="text-base-300">
                {r.text}{" "}
                <span className="font-mono text-base-500">
                  ({r.metric} {r.value} vs {r.threshold})
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <div className="mt-4 grid grid-cols-2 gap-4 border-t border-base-800 pt-4 font-mono text-xs sm:grid-cols-4">
          <Metric label="ltp" value={rupees(c.quant.ltp, 2)} />
          <Metric label="mcap" value={crore(c.quant.mcap_cr)} />
          <Metric label="adtv" value={`${c.quant.adtv_cr.toFixed(1)} Cr`} />
          <Metric label="vol (ann)" value={`${c.quant.annual_vol.toFixed(1)}%`} />
          <Metric label="atr" value={`${c.quant.atr_pct.toFixed(2)}%`} />
          <Metric label="rsi14" value={c.quant.rsi14.toFixed(1)} />
          <Metric label="1y max dd" value={`${c.quant.max_drawdown_1y.toFixed(1)}%`} />
          <Metric label="vs 52w high" value={`${c.quant.dist_52w_high_pct.toFixed(1)}%`} />

          {c.sentiment.drivers.length > 0 && (
            <div className="col-span-2 sm:col-span-4">
              <div className="mb-2 text-[10px] uppercase tracking-wider text-base-500">
                headlines behind the score
              </div>
              <ul className="space-y-2">
                {c.sentiment.drivers.map((d) => (
                  <li key={d.id} className="flex items-start justify-between gap-3">
                    <span className="text-base-300">
                      {d.url ? (
                        <a
                          href={d.url}
                          target="_blank"
                          rel="noreferrer"
                          className="underline decoration-dotted hover:text-base-100"
                        >
                          {d.title}
                        </a>
                      ) : (
                        d.title
                      )}
                      <span className="ml-2 text-base-500">
                        {d.source} · {d.event_type} · m{d.materiality} · {d.model}
                      </span>
                    </span>
                    <span
                      className={clsx(
                        "shrink-0 tabular",
                        d.sentiment >= 0 ? "text-signal-up" : "text-signal-down",
                      )}
                    >
                      {d.sentiment >= 0 ? "+" : ""}
                      {d.sentiment.toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-base-500">{label}</div>
      <div className="tabular text-base-200">{value}</div>
    </div>
  );
}
