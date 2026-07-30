import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { TrendingUp, Zap, Layers, Infinity as InfinityIcon, ArrowRight } from "lucide-react";
import { Button, Card, Eyebrow } from "@/components/ui";
import { useStore } from "@/lib/store";
import type { TraderType } from "@/types";

const META: Record<TraderType, { label: string; desc: string; icon: JSX.Element }> = {
  long_term: {
    label: "Long-Term Investor",
    desc: "You hold through cycles, favoring compounding over timing the market.",
    icon: <InfinityIcon size={28} />,
  },
  swing: {
    label: "Swing Trader",
    desc: "You ride multi-day to multi-week moves, balancing conviction with patience.",
    icon: <TrendingUp size={28} />,
  },
  intraday: {
    label: "Intraday Trader",
    desc: "You trade the day's volatility, closing positions before the bell.",
    icon: <Zap size={28} />,
  },
  hybrid: {
    label: "Hybrid Allocator",
    desc: "You split conviction between a core long-term book and tactical trades.",
    icon: <Layers size={28} />,
  },
};

export default function PersonaReveal() {
  const { persona } = useStore();
  const navigate = useNavigate();

  if (!persona) {
    navigate("/");
    return null;
  }

  const meta = META[persona.trader_type];
  const angle = persona.risk_tolerance * 180 - 90; // -90 to 90 deg

  return (
    <div className="mx-auto max-w-lg">
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
        <Card className="p-8 text-center">
          <Eyebrow>Your trader profile</Eyebrow>

          <div className="my-6 flex flex-col items-center gap-3">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-signal-up/10 text-signal-up">
              {meta.icon}
            </div>
            <h1 className="font-display text-2xl font-semibold text-base-50 light:text-base-900">{meta.label}</h1>
            <p className="max-w-xs text-sm text-base-300">{meta.desc}</p>
          </div>

          <div className="mx-auto mb-2 w-48">
            <svg viewBox="0 0 200 110" className="w-full">
              <path d="M 10 100 A 90 90 0 0 1 190 100" fill="none" stroke="currentColor" className="text-base-700" strokeWidth="10" strokeLinecap="round" />
              <path
                d="M 10 100 A 90 90 0 0 1 190 100"
                fill="none"
                stroke="#ffb648"
                strokeWidth="10"
                strokeLinecap="round"
                strokeDasharray={`${persona.risk_tolerance * 283} 283`}
              />
              <g transform={`rotate(${angle} 100 100)`}>
                <line x1="100" y1="100" x2="100" y2="25" stroke="currentColor" className="text-base-100" strokeWidth="3" strokeLinecap="round" />
              </g>
              <circle cx="100" cy="100" r="5" fill="currentColor" className="text-base-100" />
            </svg>
            <div className="-mt-2 font-mono text-xs text-base-400">
              Risk tolerance · <span className="text-signal-up">{(persona.risk_tolerance * 100).toFixed(0)}/100</span>
            </div>
          </div>

          <div className="mt-6 inline-flex items-center gap-2 rounded-full bg-base-800 px-3 py-1 light:bg-base-100">
            <span className="font-mono text-xs text-base-300">
              Confidence {(persona.confidence * 100).toFixed(0)}%
            </span>
          </div>
          {persona.confidence < 0.65 && (
            <p className="mx-auto mt-3 max-w-xs text-xs text-base-400">
              This is a best estimate based on a few mixed signals in your answers — you can fine-tune it any time
              from the dashboard.
            </p>
          )}

          <div className="mt-8">
            <Button className="w-full" onClick={() => navigate("/dashboard")}>
              View my portfolio <ArrowRight size={16} />
            </Button>
          </div>
        </Card>
      </motion.div>
    </div>
  );
}
