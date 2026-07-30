import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { RefreshCw } from "lucide-react";
import { AnimatedNumber, Button, Card, DeltaTag, Eyebrow } from "@/components/ui";
import { useStore } from "@/lib/store";
import { TILT_CAPS } from "@/lib/allocation";
import type { AssetClass } from "@/types";

const COLORS: Record<AssetClass, string> = {
  equity: "#ffb648",
  bonds: "#5b6b78",
  intraday: "#ff5470",
  cash: "#8b98a3",
};

const LABELS: Record<AssetClass, string> = {
  equity: "Equity",
  bonds: "Bonds",
  intraday: "Intraday",
  cash: "Cash",
};

export default function Dashboard() {
  const { persona, breakdown, loading, refreshSentiment } = useStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (!persona) navigate("/");
  }, [persona, navigate]);

  if (!persona || breakdown.length === 0) return null;

  const pieData = breakdown.map((b) => ({ name: LABELS[b.asset_class], value: b.final, key: b.asset_class }));

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Eyebrow>Portfolio Dashboard</Eyebrow>
          <h1 className="font-display text-2xl font-semibold text-base-50 light:text-base-900">
            Current allocation
          </h1>
        </div>
        <Button variant="outline" onClick={refreshSentiment} disabled={loading}>
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          Refresh sentiment
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* Donut */}
        <Card className="p-6 lg:col-span-2">
          <Eyebrow>Final weights</Eyebrow>
          <div className="relative mx-auto mt-2 h-64 w-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={70}
                  outerRadius={100}
                  paddingAngle={3}
                  animationDuration={500}
                  stroke="none"
                >
                  {pieData.map((d) => (
                    <Cell key={d.key} fill={COLORS[d.key as AssetClass]} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v: number) => `${v.toFixed(1)}%`}
                  contentStyle={{
                    background: "#161c23",
                    border: "1px solid #2b3540",
                    borderRadius: 8,
                    fontSize: 12,
                    fontFamily: "IBM Plex Mono, monospace",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="font-mono text-[10px] uppercase tracking-widest text-base-400">Persona</span>
              <span className="font-display text-sm font-semibold capitalize text-base-50 light:text-base-900">
                {persona.trader_type.replace("_", " ")}
              </span>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap justify-center gap-3">
            {breakdown.map((b) => (
              <div key={b.asset_class} className="flex items-center gap-1.5 text-xs">
                <span className="h-2 w-2 rounded-full" style={{ background: COLORS[b.asset_class] }} />
                <span className="text-base-300">{LABELS[b.asset_class]}</span>
                <AnimatedNumber value={b.final} className="text-base-100" />
              </div>
            ))}
          </div>
        </Card>

        {/* Baseline vs final tilt bars */}
        <Card className="p-6 lg:col-span-3">
          <div className="mb-4 flex items-center justify-between">
            <Eyebrow>Baseline → final</Eyebrow>
            <span className="rounded-full bg-base-800 px-2 py-0.5 font-mono text-[10px] text-base-400 light:bg-base-100">
              tilt capped at ±{(TILT_CAPS.market * 100).toFixed(0)}% market / ±{(TILT_CAPS.conviction * 100).toFixed(0)}% conviction
            </span>
          </div>
          <div className="space-y-5">
            {breakdown.map((b) => {
              const totalTilt = b.market_tilt + b.conviction_tilt;
              return (
                <div key={b.asset_class}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="font-medium text-base-100 light:text-base-800">{LABELS[b.asset_class]}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-base-400 tabular">{b.baseline.toFixed(1)}%</span>
                      <span className="text-base-500">→</span>
                      <AnimatedNumber value={b.final} className="text-sm text-base-50 light:text-base-900" />
                      <DeltaTag value={totalTilt} />
                    </div>
                  </div>
                  <div className="relative h-2 w-full overflow-hidden rounded-full bg-base-800">
                    <div
                      className="absolute h-full rounded-full opacity-30"
                      style={{ width: `${b.baseline}%`, background: COLORS[b.asset_class] }}
                    />
                    <div
                      className="absolute h-full rounded-full transition-all duration-500"
                      style={{ width: `${b.final}%`, background: COLORS[b.asset_class] }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      {/* Reason cards */}
      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {breakdown.map((b) => (
          <Card key={b.asset_class} className="p-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-sm font-medium text-base-100 light:text-base-800">
                <span className="h-2 w-2 rounded-full" style={{ background: COLORS[b.asset_class] }} />
                {LABELS[b.asset_class]}
              </span>
              <DeltaTag value={b.market_tilt + b.conviction_tilt} />
            </div>
            <div className="mb-3 grid grid-cols-3 gap-2 font-mono text-xs text-base-400">
              <div>
                <div className="text-[10px] uppercase text-base-500">Base</div>
                {b.baseline.toFixed(1)}%
              </div>
              <div>
                <div className="text-[10px] uppercase text-base-500">Tilt</div>
                {(b.market_tilt + b.conviction_tilt).toFixed(1)}%
              </div>
              <div>
                <div className="text-[10px] uppercase text-base-500">Final</div>
                {b.final.toFixed(1)}%
              </div>
            </div>
            <p className="text-xs leading-relaxed text-base-300">{b.reason}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}
