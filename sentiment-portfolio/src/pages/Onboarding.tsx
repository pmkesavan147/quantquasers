import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import { Button, Card, Eyebrow, ProgressBar } from "@/components/ui";
import { useStore } from "@/lib/store";
import type { OnboardingAnswers } from "@/types";
import clsx from "clsx";

type Step =
  | { key: keyof OnboardingAnswers; kind: "select"; question: string; options: string[] }
  | { key: keyof OnboardingAnswers; kind: "slider"; question: string; min: number; max: number; unit: string }
  | { key: keyof OnboardingAnswers; kind: "textarea"; question: string; placeholder: string };

const STEPS: Step[] = [
  {
    key: "time_horizon",
    kind: "select",
    question: "When you open a position, how long do you typically plan to hold it?",
    options: ["< 1 day", "days to weeks", "months", "years+"],
  },
  {
    key: "experience",
    kind: "select",
    question: "How would you describe your trading experience?",
    options: ["new to this", "some experience", "experienced", "professional"],
  },
  {
    key: "trade_frequency",
    kind: "select",
    question: "How often do you place trades?",
    options: ["multiple times a day", "a few times a week", "monthly", "rarely"],
  },
  {
    key: "capital",
    kind: "slider",
    question: "Roughly how much capital are you planning to allocate?",
    min: 10000,
    max: 5000000,
    unit: "₹",
  },
  {
    key: "drawdown_tolerance",
    kind: "slider",
    question: "What's the maximum portfolio drawdown you could stomach without panicking?",
    min: 5,
    max: 60,
    unit: "%",
  },
  {
    key: "volatility_comfort",
    kind: "slider",
    question: "How comfortable are you with day-to-day price swings?",
    min: 0,
    max: 100,
    unit: "/100",
  },
  {
    key: "primary_goal",
    kind: "select",
    question: "What's the main goal for this portfolio?",
    options: ["grow wealth long-term", "generate income", "active trading profit", "capital preservation"],
  },
  {
    key: "liquidity_need",
    kind: "select",
    question: "How soon might you need to access this money?",
    options: ["not for years", "within a year", "within months", "could need it anytime"],
  },
  {
    key: "sentiment_text",
    kind: "textarea",
    question: "How are you feeling about the markets right now?",
    placeholder: "e.g. Feeling cautious about tech valuations, but bullish on Indian banks this quarter...",
  },
];

export default function Onboarding() {
  const [step, setStep] = useState(0);
  const [answers, setLocalAnswers] = useState<OnboardingAnswers>({});
  const [analyzing, setAnalyzing] = useState(false);
  const { runAnalysis } = useStore();
  const navigate = useNavigate();

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;
  const pct = ((step + 1) / STEPS.length) * 100;

  const value = answers[current.key];
  const canAdvance =
    current.kind === "textarea" ? true : value !== undefined && value !== "" && value !== null;

  const update = (v: string | number) => setLocalAnswers((a) => ({ ...a, [current.key]: v }));

  const handleNext = async () => {
    if (isLast) {
      setAnalyzing(true);
      await runAnalysis(answers);
      navigate("/persona");
      return;
    }
    setStep((s) => s + 1);
  };

  if (analyzing) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <Loader2 className="animate-spin text-signal-up" size={28} />
        <Eyebrow>Analyzing your responses</Eyebrow>
        <p className="max-w-sm text-center text-sm text-base-300">
          Classifying trader profile, scoring market sentiment, and reading your outlook...
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-8">
        <div className="mb-2 flex items-center justify-between">
          <Eyebrow>
            Step {step + 1} of {STEPS.length}
          </Eyebrow>
          <span className="font-mono text-xs text-base-400">{Math.round(pct)}%</span>
        </div>
        <ProgressBar pct={pct} />
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 16 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -16 }}
          transition={{ duration: 0.22, ease: "easeOut" }}
        >
          <Card className="p-8">
            <h2 className="mb-6 font-display text-xl font-semibold leading-snug text-base-50 light:text-base-900">
              {current.question}
            </h2>

            {current.kind === "select" && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {current.options.map((opt) => (
                  <button
                    key={opt}
                    onClick={() => update(opt)}
                    className={clsx(
                      "rounded-lg border px-4 py-3 text-left text-sm transition-colors",
                      value === opt
                        ? "border-signal-up bg-signal-up/10 text-signal-up"
                        : "border-base-700 text-base-200 hover:border-base-500"
                    )}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}

            {current.kind === "slider" && (
              <div>
                <div className="mb-3 font-mono text-2xl text-signal-up tabular">
                  {current.unit === "₹" ? "₹" : ""}
                  {Number(value ?? current.min).toLocaleString("en-IN")}
                  {current.unit !== "₹" ? current.unit : ""}
                </div>
                <input
                  type="range"
                  min={current.min}
                  max={current.max}
                  step={current.unit === "%" || current.unit === "/100" ? 1 : 1000}
                  value={Number(value ?? current.min)}
                  onChange={(e) => update(Number(e.target.value))}
                  className="w-full accent-[#ffb648]"
                />
                <div className="mt-1 flex justify-between font-mono text-xs text-base-400">
                  <span>{current.min.toLocaleString("en-IN")}</span>
                  <span>{current.max.toLocaleString("en-IN")}</span>
                </div>
              </div>
            )}

            {current.kind === "textarea" && (
              <textarea
                value={(value as string) ?? ""}
                onChange={(e) => update(e.target.value)}
                placeholder={current.placeholder}
                rows={5}
                className="w-full resize-none rounded-lg border border-base-700 bg-base-800/60 p-4 text-sm text-base-100 outline-none placeholder:text-base-500 focus:border-signal-up light:bg-white light:text-base-900"
              />
            )}
          </Card>
        </motion.div>
      </AnimatePresence>

      <div className="mt-6 flex items-center justify-between">
        <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>
          <ArrowLeft size={16} /> Back
        </Button>
        <Button onClick={handleNext} disabled={!canAdvance}>
          {isLast ? "Analyze my profile" : "Next"} <ArrowRight size={16} />
        </Button>
      </div>
    </div>
  );
}
