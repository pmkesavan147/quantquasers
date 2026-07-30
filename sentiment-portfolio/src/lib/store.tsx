import { createContext, useContext, useState, ReactNode, useCallback } from "react";
import type {
  AllocationBreakdown,
  MarketSentimentItem,
  OnboardingAnswers,
  Persona,
  PersonalSentiment,
  RebalanceEvent,
} from "@/types";
import { classifyPersona, extractPersonalSentiment, fetchMarketSentiment, fetchRebalanceHistory } from "@/services/mockApi";
import { computeAllocation } from "@/lib/allocation";

type Store = {
  answers: OnboardingAnswers;
  setAnswers: (a: OnboardingAnswers) => void;
  persona: Persona | null;
  marketItems: MarketSentimentItem[];
  personal: PersonalSentiment | null;
  breakdown: AllocationBreakdown[];
  aggregateMarketSentiment: number;
  history: RebalanceEvent[];
  loading: boolean;
  runAnalysis: (answers: OnboardingAnswers) => Promise<void>;
  refreshSentiment: () => Promise<void>;
  loadHistory: () => Promise<void>;
  setFeedback: (id: string, fb: "up" | "down") => void;
};

const StoreContext = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [answers, setAnswers] = useState<OnboardingAnswers>({});
  const [persona, setPersona] = useState<Persona | null>(null);
  const [marketItems, setMarketItems] = useState<MarketSentimentItem[]>([]);
  const [personal, setPersonal] = useState<PersonalSentiment | null>(null);
  const [breakdown, setBreakdown] = useState<AllocationBreakdown[]>([]);
  const [aggregateMarketSentiment, setAggregate] = useState(0);
  const [history, setHistory] = useState<RebalanceEvent[]>([]);
  const [loading, setLoading] = useState(false);

  const recompute = useCallback((p: Persona, m: MarketSentimentItem[], ps: PersonalSentiment) => {
    const { breakdown, aggregateMarketSentiment } = computeAllocation(p, m, ps);
    setBreakdown(breakdown);
    setAggregate(aggregateMarketSentiment);
  }, []);

  const runAnalysis = useCallback(
    async (a: OnboardingAnswers) => {
      setLoading(true);
      setAnswers(a);
      const [p, m, ps] = await Promise.all([
        classifyPersona(a),
        fetchMarketSentiment(9),
        extractPersonalSentiment(a.sentiment_text ?? ""),
      ]);
      setPersona(p);
      setMarketItems(m);
      setPersonal(ps);
      recompute(p, m, ps);
      setLoading(false);
    },
    [recompute]
  );

  const refreshSentiment = useCallback(async () => {
    if (!persona) return;
    setLoading(true);
    const [m, ps] = await Promise.all([
      fetchMarketSentiment(9),
      extractPersonalSentiment(answers.sentiment_text ?? ""),
    ]);
    setMarketItems(m);
    setPersonal(ps);
    recompute(persona, m, ps);
    setLoading(false);
  }, [persona, answers, recompute]);

  const loadHistory = useCallback(async () => {
    const h = await fetchRebalanceHistory();
    setHistory(h);
  }, []);

  const setFeedback = useCallback((id: string, fb: "up" | "down") => {
    setHistory((prev) => prev.map((e) => (e.id === id ? { ...e, feedback: e.feedback === fb ? null : fb } : e)));
  }, []);

  return (
    <StoreContext.Provider
      value={{
        answers,
        setAnswers,
        persona,
        marketItems,
        personal,
        breakdown,
        aggregateMarketSentiment,
        history,
        loading,
        runAnalysis,
        refreshSentiment,
        loadHistory,
        setFeedback,
      }}
    >
      {children}
    </StoreContext.Provider>
  );
}

export function useStore() {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used within StoreProvider");
  return ctx;
}
