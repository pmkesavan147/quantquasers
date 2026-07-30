import { ReactNode, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { motion } from "framer-motion";

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={clsx(
        "rounded-xl border border-base-700/70 bg-base-900/60 shadow-panel backdrop-blur-sm",
        "light:border-base-200 light:bg-white",
        className
      )}
    >
      {children}
    </div>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-base-400">{children}</div>
  );
}

export function AnimatedNumber({
  value,
  decimals = 1,
  suffix = "%",
  className,
}: {
  value: number;
  decimals?: number;
  suffix?: string;
  className?: string;
}) {
  const [display, setDisplay] = useState(value);
  const prev = useRef(value);

  useEffect(() => {
    const from = prev.current;
    const to = value;
    const duration = 500;
    const start = performance.now();
    let raf: number;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (to - from) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else prev.current = to;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return (
    <span className={clsx("font-mono tabular", className)}>
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}

export function DeltaTag({ value }: { value: number }) {
  const isPos = value > 0.05;
  const isNeg = value < -0.05;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-xs tabular",
        isPos && "bg-signal-up/10 text-signal-up",
        isNeg && "bg-signal-down/10 text-signal-down",
        !isPos && !isNeg && "bg-base-700/60 text-base-300"
      )}
    >
      {isPos ? "▲" : isNeg ? "▼" : "•"} {value > 0 ? "+" : ""}
      {value.toFixed(1)}%
    </span>
  );
}

export function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-base-700/60">
      <motion.div
        className="h-full rounded-full bg-signal-up"
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.4, ease: "easeOut" }}
      />
    </div>
  );
}

export function SentimentBar({ value }: { value: number }) {
  // -1..1 rendered as a bar from center
  const pct = Math.abs(value) * 50;
  const isPos = value >= 0;
  return (
    <div className="relative h-2 w-24 overflow-hidden rounded-full bg-base-700/60">
      <div className="absolute left-1/2 top-0 h-full w-px bg-base-500" />
      <div
        className={clsx("absolute top-0 h-full rounded-full", isPos ? "bg-signal-up" : "bg-signal-down")}
        style={{
          width: `${pct}%`,
          left: isPos ? "50%" : `${50 - pct}%`,
        }}
      />
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  className,
  type = "button",
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "outline";
  className?: string;
  type?: "button" | "submit";
  disabled?: boolean;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-signal-up text-base-950 hover:bg-signal-up/90",
        variant === "outline" && "border border-base-600 text-base-100 hover:bg-base-800",
        variant === "ghost" && "text-base-300 hover:bg-base-800 hover:text-base-100",
        className
      )}
    >
      {children}
    </button>
  );
}
