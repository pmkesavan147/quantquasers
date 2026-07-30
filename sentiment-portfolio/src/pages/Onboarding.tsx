import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import clsx from "clsx";
import { Button, Card, ErrorNote, Eyebrow, ProgressBar, rupees } from "@/components/ui";
import { useStore } from "@/lib/store";
import { getQuiz } from "@/services/api";
import { ApiError } from "@/services/api";
import type { Question, QuizAnswers } from "@/types";

// The questions come from GET /api/quiz, not from a const in this file. That is
// the fix for the integration bug that mattered most: the old build hard-coded
// its own options ("years+", "multiple times a day") which no backend field
// accepted, so onboarding could never produce a valid RiskProfile.

function defaultFor(q: Question, answers: QuizAnswers) {
  const current = answers[q.id];
  if (current !== undefined) return current;
  if (q.kind === "slider" || q.kind === "number") return q.min ?? 0;
  if (q.kind === "boolean") return true;
  if (q.kind === "multi") return [];
  return "";
}

function isAnswered(q: Question, value: unknown): boolean {
  if (q.required === false) return true;
  if (q.kind === "multi") return Array.isArray(value) && value.length > 0;
  if (q.kind === "boolean") return typeof value === "boolean";
  if (q.kind === "slider" || q.kind === "number") return typeof value === "number";
  return value !== undefined && value !== "";
}

function formatSlider(q: Question, value: number): string {
  if (q.unit === "₹") return rupees(value);
  return `${value.toLocaleString("en-IN")}${q.unit ?? ""}`;
}

export default function Onboarding() {
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const { answers, setAnswers, submitQuiz, onboarding } = useStore();
  const navigate = useNavigate();

  const load = () => {
    setLoadError(null);
    getQuiz()
      .then((body) => setQuestions(body.questions))
      .catch((err: unknown) =>
        setLoadError(err instanceof ApiError ? err.message : String(err)),
      );
  };

  useEffect(load, []);

  const current = questions?.[step];
  const value = useMemo(
    () => (current ? defaultFor(current, answers) : undefined),
    [current, answers],
  );

  if (loadError) {
    return (
      <div className="mx-auto max-w-xl">
        <ErrorNote message={loadError} onRetry={load} />
      </div>
    );
  }

  if (!questions || !current) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center gap-2 text-base-400">
        <Loader2 className="animate-spin" size={18} /> loading the survey…
      </div>
    );
  }

  const isLast = step === questions.length - 1;
  const pct = ((step + 1) / questions.length) * 100;
  const update = (v: QuizAnswers[string]) => setAnswers({ ...answers, [current.id]: v });

  const toggleMulti = (option: string) => {
    const list = Array.isArray(value) ? [...(value as string[])] : [];
    const at = list.indexOf(option);
    if (at >= 0) list.splice(at, 1);
    else list.push(option);
    update(list);
  };

  const next = async () => {
    if (!isLast) {
      setStep((s) => s + 1);
      return;
    }
    const result = await submitQuiz(answers);
    if (result) navigate("/persona");
  };

  if (onboarding.loading) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <Loader2 className="animate-spin text-signal-up" size={28} />
        <Eyebrow>Scoring your answers</Eyebrow>
        <p className="max-w-sm text-center text-sm text-base-300">
          A hand-written rubric bands your risk, Gemma reads your own words as a
          second opinion, and the desk split follows from both.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-8">
        <div className="mb-2 flex items-center justify-between">
          <Eyebrow>
            Step {step + 1} of {questions.length}
          </Eyebrow>
          <span className="font-mono text-xs text-base-400">{Math.round(pct)}%</span>
        </div>
        <ProgressBar pct={pct} />
      </div>

      {onboarding.error && (
        <div className="mb-4">
          <ErrorNote message={onboarding.error} onRetry={next} />
        </div>
      )}

      <AnimatePresence mode="wait">
        <motion.div
          key={current.id}
          initial={{ opacity: 0, x: 16 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -16 }}
          transition={{ duration: 0.22, ease: "easeOut" }}
        >
          <Card className="p-8">
            <h2 className="font-display text-xl font-semibold leading-snug text-base-50 light:text-base-900">
              {current.text}
            </h2>
            {current.help && (
              <p className="mb-6 mt-2 text-sm leading-relaxed text-base-400">{current.help}</p>
            )}
            {!current.help && <div className="mb-6" />}

            {(current.kind === "single" || current.kind === "multi") && (
              <div className="grid grid-cols-1 gap-2">
                {current.options?.map((opt) => {
                  const selected =
                    current.kind === "multi"
                      ? Array.isArray(value) && (value as string[]).includes(opt.value)
                      : value === opt.value;
                  return (
                    <button
                      key={opt.value}
                      onClick={() =>
                        current.kind === "multi" ? toggleMulti(opt.value) : update(opt.value)
                      }
                      aria-pressed={selected}
                      className={clsx(
                        "rounded-lg border px-4 py-3 text-left text-sm transition-colors",
                        selected
                          ? "border-signal-up bg-signal-up/10 text-signal-up"
                          : "border-base-700 text-base-200 hover:border-base-500",
                      )}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            )}

            {current.kind === "boolean" && (
              <div className="grid grid-cols-2 gap-2">
                {[
                  { v: true, label: "Yes" },
                  { v: false, label: "No" },
                ].map((opt) => (
                  <button
                    key={String(opt.v)}
                    onClick={() => update(opt.v)}
                    aria-pressed={value === opt.v}
                    className={clsx(
                      "rounded-lg border px-4 py-3 text-sm transition-colors",
                      value === opt.v
                        ? "border-signal-up bg-signal-up/10 text-signal-up"
                        : "border-base-700 text-base-200 hover:border-base-500",
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            )}

            {(current.kind === "slider" || current.kind === "number") && (
              <div>
                <div className="mb-3 font-mono text-2xl tabular text-signal-up">
                  {formatSlider(current, Number(value ?? current.min ?? 0))}
                </div>
                <input
                  type="range"
                  min={current.min ?? 0}
                  max={current.max ?? 100}
                  step={current.step ?? 1}
                  value={Number(value ?? current.min ?? 0)}
                  onChange={(e) => update(Number(e.target.value))}
                  aria-label={current.text}
                  className="w-full accent-[#ffb648]"
                />
                <div className="mt-1 flex justify-between font-mono text-xs text-base-400">
                  <span>{formatSlider(current, current.min ?? 0)}</span>
                  <span>{formatSlider(current, current.max ?? 0)}</span>
                </div>
              </div>
            )}

            {current.kind === "text" && (
              <textarea
                value={String(value ?? "")}
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
        <Button onClick={next} disabled={!isAnswered(current, value)}>
          {isLast ? "See my profile" : "Next"} <ArrowRight size={16} />
        </Button>
      </div>

      <p className="mt-8 text-center text-xs leading-relaxed text-base-500">
        Paper trading only. Educational analysis, not investment advice, and not
        issued by a SEBI-registered Research Analyst or Investment Adviser.
      </p>
    </div>
  );
}
