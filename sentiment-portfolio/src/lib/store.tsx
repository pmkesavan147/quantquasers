import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import * as api from "@/services/api";
import { ApiError } from "@/services/api";
import type {
  Candidate,
  CandidateResponse,
  DeskState,
  Health,
  Horizon,
  JournalEntry,
  MarketSentiment,
  ModelStatus,
  PortfolioState,
  QuizAnswers,
  QuizResult,
  RunResponse,
} from "@/types";

// One store, one source of truth: the backend. The old version kept a
// TypeScript allocation engine here and recomputed weights in the browser from
// sentiment — two systems disagreeing about the same portfolio. Now nothing is
// computed here; state is what the API last said, plus loading and error flags
// so a failed call shows a message instead of an eternal spinner.

const PERSISTED_ANSWERS = "qq.answers";

type AsyncState = { loading: boolean; error: string | null };

type Store = {
  answers: QuizAnswers;
  setAnswers: (a: QuizAnswers) => void;

  quiz: QuizResult | null;
  report: string | null;
  health: Health | null;
  model: ModelStatus | null;
  desks: DeskState[];
  portfolio: PortfolioState | null;
  market: MarketSentiment | null;
  candidates: Partial<Record<Horizon, CandidateResponse>>;
  journal: JournalEntry[];
  lastRun: RunResponse | null;

  onboarding: AsyncState;
  dashboard: AsyncState;
  sentiment: AsyncState;

  submitQuiz: (answers: QuizAnswers) => Promise<QuizResult | null>;
  loadReport: () => Promise<void>;
  refreshStatus: () => Promise<void>;
  refreshDashboard: () => Promise<void>;
  loadCandidates: (horizon: Horizon) => Promise<void>;
  refreshMarket: (limit?: number) => Promise<void>;
  loadJournal: (kind?: string) => Promise<void>;
  runDesk: (desk: string) => Promise<void>;
  togglePause: () => Promise<void>;
  reset: () => void;
};

const StoreContext = createContext<Store | null>(null);

function message(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

function loadPersistedAnswers(): QuizAnswers {
  try {
    const raw = sessionStorage.getItem(PERSISTED_ANSWERS);
    return raw ? (JSON.parse(raw) as QuizAnswers) : {};
  } catch {
    return {};
  }
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [answers, setAnswersState] = useState<QuizAnswers>(loadPersistedAnswers);
  const [quiz, setQuiz] = useState<QuizResult | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [desks, setDesks] = useState<DeskState[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioState | null>(null);
  const [market, setMarket] = useState<MarketSentiment | null>(null);
  const [candidates, setCandidates] = useState<Partial<Record<Horizon, CandidateResponse>>>({});
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [lastRun, setLastRun] = useState<RunResponse | null>(null);

  const [onboarding, setOnboarding] = useState<AsyncState>({ loading: false, error: null });
  const [dashboard, setDashboard] = useState<AsyncState>({ loading: false, error: null });
  const [sentiment, setSentiment] = useState<AsyncState>({ loading: false, error: null });

  // Survives a refresh so a reload mid-demo does not send you back to question
  // one. sessionStorage, not localStorage: a new tab is a new investor.
  const setAnswers = useCallback((a: QuizAnswers) => {
    setAnswersState(a);
    try {
      sessionStorage.setItem(PERSISTED_ANSWERS, JSON.stringify(a));
    } catch {
      /* private mode — losing the draft is survivable */
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const [h, m] = await Promise.all([api.getHealth(), api.getModelStatus()]);
      setHealth(h);
      setModel(m);
    } catch (err) {
      setDashboard((s) => ({ ...s, error: message(err) }));
    }
  }, []);

  const submitQuiz = useCallback(
    async (a: QuizAnswers) => {
      setOnboarding({ loading: true, error: null });
      setAnswers(a);
      try {
        const result = await api.submitQuiz(a, { createAccount: true });
        setQuiz(result);
        setModel(result.model);
        setOnboarding({ loading: false, error: null });
        void refreshStatus();
        return result;
      } catch (err) {
        setOnboarding({ loading: false, error: message(err) });
        return null;
      }
    },
    [refreshStatus, setAnswers],
  );

  const loadReport = useCallback(async () => {
    try {
      const { report: text } = await api.getPersonaReport(answers);
      setReport(text);
    } catch (err) {
      // The prose is the least important thing on the page — a failure here
      // must not blank the persona screen.
      setReport(null);
      setOnboarding((s) => ({ ...s, error: message(err) }));
    }
  }, [answers]);

  const refreshDashboard = useCallback(async () => {
    setDashboard({ loading: true, error: null });
    try {
      const [d, p] = await Promise.all([api.getDesks(), api.getPortfolio()]);
      setDesks(d);
      setPortfolio(p);
      setDashboard({ loading: false, error: null });
    } catch (err) {
      setDashboard({ loading: false, error: message(err) });
    }
  }, []);

  const loadCandidates = useCallback(async (horizon: Horizon) => {
    setDashboard((s) => ({ ...s, loading: true }));
    try {
      const res = await api.getCandidates(horizon, { limit: 8 });
      setCandidates((prev) => ({ ...prev, [horizon]: res }));
      setDashboard({ loading: false, error: null });
    } catch (err) {
      setDashboard({ loading: false, error: message(err) });
    }
  }, []);

  const refreshMarket = useCallback(async (limit = 8) => {
    setSentiment({ loading: true, error: null });
    try {
      setMarket(await api.getMarketSentiment(limit));
      setSentiment({ loading: false, error: null });
    } catch (err) {
      setSentiment({ loading: false, error: message(err) });
    }
  }, []);

  const loadJournal = useCallback(async (kind?: string) => {
    try {
      setJournal(await api.getJournal(80, kind));
    } catch (err) {
      setDashboard((s) => ({ ...s, error: message(err) }));
    }
  }, []);

  const runDesk = useCallback(
    async (desk: string) => {
      setDashboard({ loading: true, error: null });
      try {
        setLastRun(await api.executeDesk(desk));
        await Promise.all([refreshDashboard(), loadJournal()]);
      } catch (err) {
        setDashboard({ loading: false, error: message(err) });
      }
    },
    [loadJournal, refreshDashboard],
  );

  const togglePause = useCallback(async () => {
    try {
      if (portfolio?.halted) await api.resume();
      else await api.pause();
      await Promise.all([refreshDashboard(), refreshStatus()]);
    } catch (err) {
      setDashboard((s) => ({ ...s, error: message(err) }));
    }
  }, [portfolio?.halted, refreshDashboard, refreshStatus]);

  const reset = useCallback(() => {
    setQuiz(null);
    setReport(null);
    setCandidates({});
    setLastRun(null);
    setAnswersState({});
    try {
      sessionStorage.removeItem(PERSISTED_ANSWERS);
    } catch {
      /* ignore */
    }
  }, []);

  // Status drives the header badges on every screen, so it loads once up front
  // rather than per page.
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void refreshStatus();
  }, [refreshStatus]);

  const value = useMemo<Store>(
    () => ({
      answers,
      setAnswers,
      quiz,
      report,
      health,
      model,
      desks,
      portfolio,
      market,
      candidates,
      journal,
      lastRun,
      onboarding,
      dashboard,
      sentiment,
      submitQuiz,
      loadReport,
      refreshStatus,
      refreshDashboard,
      loadCandidates,
      refreshMarket,
      loadJournal,
      runDesk,
      togglePause,
      reset,
    }),
    [
      answers, setAnswers, quiz, report, health, model, desks, portfolio, market,
      candidates, journal, lastRun, onboarding, dashboard, sentiment,
      submitQuiz, loadReport, refreshStatus, refreshDashboard, loadCandidates,
      refreshMarket, loadJournal, runDesk, togglePause, reset,
    ],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): Store {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used within StoreProvider");
  return ctx;
}

export type { Candidate };
