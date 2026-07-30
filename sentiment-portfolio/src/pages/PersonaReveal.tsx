import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Sparkles } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Eyebrow,
  Spinner,
  Stat,
  rupees,
} from "@/components/ui";
import { useStore } from "@/lib/store";
import { DESK_LABEL, type Horizon } from "@/types";

const DESK_COLOR: Record<Horizon, string> = {
  day: "#ff5470",
  swing: "#ffb648",
  long_term: "#8b98a3",
};

const BAND_COPY = {
  conservative: "Capital preservation first. The intraday desk gets the smallest slice.",
  balanced: "A working mix: swing carries the most, intraday stays contained.",
  aggressive: "Intraday and swing carry the weight, with long-term as ballast.",
} as const;

export default function PersonaReveal() {
  const { quiz, report, loadReport, onboarding, answers } = useStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (!quiz) navigate("/", { replace: true });
  }, [quiz, navigate]);

  useEffect(() => {
    if (quiz && report === null) void loadReport();
    // Intentionally not depending on loadReport's identity churn: one fetch per
    // arrival on this screen is the behaviour we want.
  }, [quiz]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!quiz) return null;

  const account = quiz.account;
  const pcts = Object.entries(quiz.allocation_pct) as Array<[Horizon, number]>;
  const rupeesByDesk = account?.allocation_rupees ?? {};
  const pieData = pcts.map(([desk, pct]) => ({
    name: DESK_LABEL[desk],
    value: pct,
    key: desk,
  }));
  const gemma = quiz.gemma;
  const hasText = ["open_reaction", "open_rhythm", "open_goal"].some(
    (id) => String(answers[id] ?? "").trim().length > 0,
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="mx-auto w-full max-w-4xl"
    >
      <Eyebrow>Your profile</Eyebrow>
      <h1 className="mt-1 font-display text-3xl font-semibold capitalize text-base-50 light:text-base-900">
        {quiz.risk_band}
      </h1>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-base-300">
        {BAND_COPY[quiz.risk_band]} Scored {quiz.rubric_score}/11 by a
        hand-written rubric over your own answers — not by a model.
      </p>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-5">
        <Card className="p-6 lg:col-span-2">
          <Eyebrow>Capital split</Eyebrow>
          <div className="relative mx-auto mt-2 h-56 w-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={62}
                  outerRadius={92}
                  paddingAngle={3}
                  stroke="none"
                >
                  {pieData.map((d) => (
                    <Cell key={d.key} fill={DESK_COLOR[d.key]} />
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
              <span className="font-mono text-[10px] uppercase tracking-widest text-base-400">
                capital
              </span>
              <span className="font-mono text-sm text-base-50 light:text-base-900">
                {rupees(quiz.profile.capital)}
              </span>
            </div>
          </div>

          <div className="mt-4 space-y-2">
            {pcts.map(([desk, pct]) => (
              <div key={desk} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2 text-base-200 light:text-base-700">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: DESK_COLOR[desk] }}
                  />
                  {DESK_LABEL[desk]}
                </span>
                <span className="font-mono tabular text-base-100 light:text-base-800">
                  {pct.toFixed(1)}%
                  {rupeesByDesk[desk] !== undefined && (
                    <span className="ml-2 text-base-400">
                      {rupees(rupeesByDesk[desk] as number)}
                    </span>
                  )}
                </span>
              </div>
            ))}
            {account?.desks_off?.map((desk) => (
              <div key={desk} className="flex items-center justify-between text-sm">
                <span className="text-base-500 line-through">
                  {DESK_LABEL[desk as Horizon] ?? desk}
                </span>
                <Badge>off — you opted out</Badge>
              </div>
            ))}
          </div>
        </Card>

        <div className="space-y-6 lg:col-span-3">
          <Card className="p-6">
            <div className="mb-4 flex items-center justify-between">
              <Eyebrow>What Gemma read</Eyebrow>
              <Badge tone={gemma.moved_band ? "warn" : "neutral"}>
                {gemma.moved_band ? "moved the band one notch" : "band unchanged"}
              </Badge>
            </div>

            {hasText ? (
              <>
                <div className="grid grid-cols-3 gap-4">
                  <Stat
                    label="Reads you as"
                    value={gemma.trader_type ? DESK_LABEL[gemma.trader_type] : "no read"}
                  />
                  <Stat label="Confidence" value={`${Math.round(gemma.confidence * 100)}%`} />
                  <Stat
                    label="Rubric"
                    value={`${gemma.rubric_score}/11`}
                    sub={gemma.rubric_band}
                  />
                </div>
                <p className="mt-4 text-sm leading-relaxed text-base-300">{gemma.reasoning}</p>
              </>
            ) : (
              <p className="text-sm leading-relaxed text-base-300">
                You skipped the free-text questions, so the model had nothing to
                read and the rubric stands alone.
              </p>
            )}

            <p className="mt-4 border-t border-base-800 pt-3 text-xs leading-relaxed text-base-500">
              A model never sets an allocation here. Its read can shift your band
              by one notch, and only above 70% confidence — everything else is
              deterministic Python.
            </p>
          </Card>

          <Card className="p-6">
            <div className="mb-3 flex items-center gap-2">
              <Sparkles size={14} className="text-signal-up" />
              <Eyebrow>Your personality note</Eyebrow>
            </div>
            {report === null && !onboarding.error && <Spinner label="writing…" />}
            {onboarding.error && report === null && (
              <ErrorNote message={onboarding.error} onRetry={loadReport} />
            )}
            {report && (
              <p className="whitespace-pre-line text-sm leading-relaxed text-base-200 light:text-base-700">
                {report}
              </p>
            )}
          </Card>

          {account?.sip && account.sip.amount > 0 && (
            <Card className="p-6">
              <Eyebrow>Your SIP</Eyebrow>
              <div className="mt-2 flex items-baseline gap-3">
                <span className="font-mono text-xl text-base-50 light:text-base-900">
                  {rupees(account.sip.amount)}
                </span>
                <span className="text-sm text-base-400">{account.sip.frequency}</span>
                <Badge>→ {account.sip.target_desk}</Badge>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-base-500">{account.sip.note}</p>
            </Card>
          )}
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <span className="font-mono text-xs text-base-500">
          model: {quiz.model.backend} · {quiz.model.model}
        </span>
        <Button onClick={() => navigate("/dashboard")}>
          Open the trading floor <ArrowRight size={16} />
        </Button>
      </div>
    </motion.div>
  );
}
