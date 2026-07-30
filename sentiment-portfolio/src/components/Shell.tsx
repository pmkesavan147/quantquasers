import { NavLink, Outlet } from "react-router-dom";
import { Moon, Sun, Activity } from "lucide-react";
import { useTheme } from "@/lib/theme";
import clsx from "clsx";

const NAV = [
  { to: "/dashboard", label: "Portfolio" },
  { to: "/insights", label: "Sentiment" },
  { to: "/history", label: "History" },
];

export default function Shell() {
  const { theme, toggle } = useTheme();

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-base-800 bg-base-950/80 backdrop-blur light:bg-wash/80 light:border-base-200">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-2">
            <Activity size={18} className="text-signal-up" />
            <span className="font-display text-base font-semibold tracking-tight">Ledger</span>
            <span className="ml-1 hidden font-mono text-[10px] uppercase tracking-widest text-base-400 sm:inline">
              sentiment desk
            </span>
          </div>
          <nav className="flex items-center gap-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  clsx(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive ? "bg-base-800 text-base-50 light:bg-base-100" : "text-base-400 hover:text-base-100"
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
    </div>
  );
}
