import { NavLink, Outlet } from "react-router-dom";
import { Activity, Moon, Sun } from "lucide-react";
import clsx from "clsx";
import { useTheme } from "@/lib/theme";
import { useStore } from "@/lib/store";
import { Badge } from "@/components/ui";

const NAV = [
  { to: "/dashboard", label: "Floor" },
  { to: "/insights", label: "Sentiment" },
  { to: "/journal", label: "Audit" },
];

export default function Shell() {
  const { theme, toggle } = useTheme();
  const { health, model } = useStore();

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-base-800 bg-base-950/80 backdrop-blur light:border-base-200 light:bg-wash/80">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-6 py-3">
          <div className="flex items-center gap-2">
            <Activity size={18} className="text-signal-up" />
            <span className="font-display text-base font-semibold tracking-tight">
              QuantQuasers
            </span>
            <span className="ml-1 hidden font-mono text-[10px] uppercase tracking-widest text-base-400 sm:inline">
              sentiment desk
            </span>
          </div>

          <div className="flex items-center gap-2">
            {/* Mode and gate live in the header on every screen: nobody should
                ever have to wonder whether this is placing real orders. */}
            <Badge tone={health?.mode === "paper" ? "up" : "down"}>
              {health?.mode ?? "…"}
            </Badge>
            <Badge
              tone={health?.gate_armed ? "down" : "neutral"}
              title={health?.gate_shut_because?.join(" · ")}
            >
              gate {health?.gate_armed ? "armed" : "shut"}
            </Badge>
            {model && (
              <Badge
                tone={model.backend === "stub" ? "warn" : "neutral"}
                title={`${model.model} · ${model.cached_responses} cached responses`}
              >
                {model.backend === "stub" ? "keyword fallback" : model.backend}
              </Badge>
            )}
          </div>

          <nav className="flex items-center gap-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  clsx(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-base-800 text-base-50 light:bg-base-100 light:text-base-900"
                      : "text-base-400 hover:text-base-100",
                  )
                }
              >
                {n.label}
              </NavLink>
            ))}
            <button
              onClick={toggle}
              aria-label="Toggle theme"
              className="ml-2 rounded-md p-2 text-base-400 hover:bg-base-800 hover:text-base-100"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-6xl px-6 pb-10">
        <p className="border-t border-base-800 pt-4 text-xs leading-relaxed text-base-500">
          {health?.disclaimer ??
            "Educational analysis only. Not investment advice. Not issued by a SEBI-registered Research Analyst or Investment Adviser."}
          {health && ` · paper trading day ${health.paper_trading_days}`}
        </p>
      </footer>
    </div>
  );
}
