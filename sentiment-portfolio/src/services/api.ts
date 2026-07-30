// The only place this app talks to the outside world.
//
// It replaced services/mockApi.ts, which generated portfolios with Math.random()
// — refreshing the dashboard changed your allocation for no reason. Every number
// rendered anywhere in this app now comes from a FastAPI response.

import type {
  CandidateResponse,
  DeskState,
  Health,
  Horizon,
  JournalEntry,
  MarketSentiment,
  ModelStatus,
  PortfolioState,
  ProposedOrder,
  Question,
  QuizAnswers,
  QuizResult,
  RiskProfile,
  RunResponse,
  SymbolSentiment,
  HeadlineScore,
} from "@/types";

export const API_BASE = (import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (cause) {
    // A dead backend is the single most likely demo failure, so it gets a
    // message that says what to do rather than "Failed to fetch".
    throw new ApiError(
      `Cannot reach the API at ${API_BASE}. Start it with: uvicorn api.main:app --reload`,
      0,
      cause,
    );
  }

  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = await resp.text().catch(() => "");
    }
    const message =
      typeof detail === "object" && detail && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : `${resp.status} ${resp.statusText}`;
    throw new ApiError(message, resp.status, detail);
  }

  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

const post = <T,>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

// ── onboarding ──────────────────────────────────────────────────────────
export const getQuiz = () =>
  call<{ questions: Question[]; note: string }>("/api/quiz");

export const submitQuiz = (
  answers: QuizAnswers,
  opts: { createAccount?: boolean; includeReport?: boolean } = {},
) =>
  post<QuizResult>("/api/quiz/submit", {
    answers,
    create_account: opts.createAccount ?? true,
    include_report: opts.includeReport ?? false,
  });

/** Score the answers without touching the engine — for the live preview. */
export const previewQuiz = (answers: QuizAnswers) =>
  post<QuizResult>("/api/quiz/submit", {
    answers,
    create_account: false,
    use_gemma: false,
  });

export const getPersonaReport = (answers: QuizAnswers) =>
  post<{ report: string; model: string }>("/api/persona/report", { answers });

export const getAccount = () =>
  call<Record<string, unknown>>("/api/account");

// ── sentiment ───────────────────────────────────────────────────────────
export const getMarketSentiment = (limit = 8, offline = false) =>
  call<MarketSentiment>(
    `/api/sentiment/market?limit=${limit}&offline=${offline}`,
  );

export const getSymbolSentiment = (symbol: string, offline = false) =>
  call<{
    symbol: string;
    name: string;
    sentiment: SymbolSentiment;
    headlines: Array<HeadlineScore & { origin: string }>;
  }>(`/api/sentiment/${symbol}?offline=${offline}`);

// ── candidates ──────────────────────────────────────────────────────────
export const getCandidates = (
  horizon: Horizon,
  opts: { limit?: number; offline?: boolean; explain?: boolean } = {},
) =>
  post<CandidateResponse>("/api/candidates", {
    horizon,
    limit: opts.limit ?? 8,
    offline: opts.offline ?? false,
    explain: opts.explain ?? true,
  });

export const candidatesToDesk = (
  horizon: Horizon,
  opts: { limit?: number; offline?: boolean } = {},
) =>
  post<
    CandidateResponse & {
      proposed_orders: ProposedOrder[];
      skipped: Array<{ symbol: string; reason: string }>;
      refused: Array<{ symbol: string; reasons: unknown[] }>;
    }
  >("/api/candidates/to-desk", {
    horizon,
    limit: opts.limit ?? 8,
    offline: opts.offline ?? false,
    explain: false,
  });

// ── trading ─────────────────────────────────────────────────────────────
export const getDesks = () => call<DeskState[]>("/api/desks");

export const getPortfolio = () => call<PortfolioState>("/api/portfolio");

export const proposeOrders = (desk: string) =>
  post<ProposedOrder[]>("/api/orders/propose", { desk });

export const executeDesk = (desk: string) =>
  post<RunResponse>("/api/orders/execute", { desk });

export const getJournal = (limit = 60, kind?: string) =>
  call<JournalEntry[]>(
    `/api/journal?limit=${limit}${kind ? `&kind=${kind}` : ""}`,
  );

export const pause = (reason = "manual pause from the dashboard") =>
  post<{ halted: boolean; reason: string }>(
    `/api/control/pause?reason=${encodeURIComponent(reason)}`,
  );

export const resume = () =>
  post<{ halted: boolean; reason: string | null }>("/api/control/resume");

// ── status ──────────────────────────────────────────────────────────────
export const getHealth = () => call<Health>("/api/health");

export const getModelStatus = () => call<ModelStatus>("/api/gemma/status");

export const getUniverse = () =>
  call<{
    count: number;
    buckets: Record<string, number>;
    symbols: Array<{
      symbol: string;
      name: string;
      cap_bucket: string;
      mcap_cr: number;
      asm_gsm_flag: boolean;
    }>;
    note: string;
  }>("/api/universe");

export type { RiskProfile };
