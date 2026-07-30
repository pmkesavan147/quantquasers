// Mirrors core/contracts.py, trading/models.py and the API route payloads.
// One vocabulary across all three tracks: desks are day | swing | long_term,
// and there is no "intraday" or "hybrid" trader type. If you find yourself
// adding a type that the backend does not send, the number behind it is being
// invented in the browser — which is what this rewrite removed.

export type Horizon = "day" | "swing" | "long_term";
export type CapBucket = "large" | "mid" | "small" | "micro";
export type RiskBand = "conservative" | "balanced" | "aggressive";
export type VerdictLevel = "SUITABLE" | "STRETCH" | "OUTSIDE_MANDATE";

export const DESKS: Horizon[] = ["day", "swing", "long_term"];

export const DESK_LABEL: Record<Horizon, string> = {
  day: "Intraday",
  swing: "Swing",
  long_term: "Long-term",
};

// ── the survey (GET /api/quiz) ──────────────────────────────────────────
export type QuestionKind = "single" | "multi" | "number" | "slider" | "text" | "boolean";

export type QuizOption = { value: string; label: string };

export type Question = {
  id: string;
  text: string;
  kind: QuestionKind;
  options?: QuizOption[];
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  placeholder?: string;
  required?: boolean;
  help?: string;
};

export type QuizAnswers = Record<string, string | number | boolean | string[]>;

// ── profile and allocation ──────────────────────────────────────────────
export type RiskProfile = {
  capital: number;
  horizons: Horizon[];
  allowed_caps: CapBucket[];
  max_drawdown_pct: number;
  experience: "new" | "1-3y" | "3y+";
  day_trading: boolean;
  uses_leverage: boolean;
  trader_type: Horizon | null;
  confidence: number;
  sip_amount: number;
  sip_frequency: "none" | "weekly" | "monthly";
};

export type GemmaRead = {
  trader_type: Horizon | null;
  confidence: number;
  reasoning: string;
  rubric_score: number;
  rubric_band: RiskBand;
  band_after: RiskBand;
  moved_band: boolean;
};

export type SipPlan = {
  amount: number;
  frequency: "none" | "weekly" | "monthly";
  target_desk: string | null;
  note: string;
};

export type AllocationExplain = {
  capital: number;
  risk_band: RiskBand;
  rubric_score: number;
  gemma_read: string | null;
  gemma_confidence: number;
  gemma_applied: boolean;
  desks_enabled: string[];
  desks_off: string[];
  allocation_pct: Partial<Record<Horizon, number>>;
  allocation_rupees: Partial<Record<Horizon, number>>;
  sip: SipPlan;
};

export type ModelStatus = {
  backend: "studio" | "remote" | "ollama" | "stub";
  model: string;
  api_key_present: boolean;
  cached_responses: number;
};

export type QuizResult = {
  profile: RiskProfile;
  risk_band: RiskBand;
  rubric_score: number;
  allocation_pct: Partial<Record<Horizon, number>>;
  gemma: GemmaRead;
  created: boolean;
  account?: AllocationExplain & { desks: DeskState[] };
  report?: string;
  model: ModelStatus;
};

// ── sentiment ───────────────────────────────────────────────────────────
export type HeadlineScore = {
  id: string;
  symbol: string;
  title: string;
  source: string;
  url: string;
  published_at: string;
  sentiment: number;
  label: "positive" | "neutral" | "negative";
  event_type: string;
  materiality: number;
  rationale: string;
  model: string;
};

export type SymbolSentiment = {
  symbol: string;
  as_of: string;
  score: number;
  confidence: number;
  n_articles: number;
  top_events: string[];
  drivers: HeadlineScore[];
};

export type MarketMood = {
  score: number;
  confidence: number;
  symbols: number;
  articles: number;
};

export type MarketSentiment = {
  as_of: string;
  mood: MarketMood;
  symbols: Array<{
    symbol: string;
    name: string;
    score: number;
    confidence: number;
    n_articles: number;
    top_events: string[];
    drivers: HeadlineScore[];
  }>;
  provenance: {
    headline_source: Record<string, number>;
    models: Record<string, number>;
  };
};

// ── candidates ──────────────────────────────────────────────────────────
export type QuantMetrics = {
  symbol: string;
  name: string;
  cap_bucket: CapBucket;
  mcap_cr: number;
  ltp: number;
  annual_vol: number;
  beta: number;
  max_drawdown_1y: number;
  adtv_cr: number;
  atr_pct: number;
  rsi14: number;
  sma20: number;
  sma50: number;
  sma200: number;
  dist_52w_high_pct: number;
  asm_gsm_flag: boolean;
  move_1d_pct: number | null;
  move_5d_pct: number | null;
  move_20d_pct: number | null;
};

export type Reason = {
  code: string;
  severity: "block" | "warn";
  text: string;
  metric: string;
  value: number;
  threshold: number;
};

export type Candidate = {
  symbol: string;
  horizon: Horizon;
  composite_score: number;
  sentiment: SymbolSentiment;
  quant: QuantMetrics;
  verdict: { level: VerdictLevel; reasons: Reason[] };
  explanation: string;
};

export type PipelineReport = {
  horizon: Horizon;
  symbols_scanned: number;
  candidates: number;
  suitable: number;
  stretch: number;
  refused: number;
  // live | snapshot | fixture | none — a deployed instance serves real
  // numbers captured earlier, and says so rather than calling them live.
  quant_source: Record<string, number>;
  headline_source: Record<string, number>;
  headline_models: Record<string, number>;
  market_mood: MarketMood;
  as_of: string;
};

export type CandidateResponse = {
  horizon: Horizon;
  candidates: Candidate[];
  report: PipelineReport;
};

// ── trading ─────────────────────────────────────────────────────────────
export type ProposedOrder = {
  desk: string;
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  price: number;
  product: string;
  reason: string;
  sentiment_score?: number | null;
};

// Mirrors trading/models.py Fill exactly: the price paid is `price`, and
// `realised` is net of costs and non-zero on SELLs only.
export type Fill = {
  desk: string;
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  price: number;
  costs: number;
  mode: string;
  order_id: string;
  product: string;
  reason: string;
  realised: number;
};

export type Position = {
  desk?: string;
  symbol: string;
  qty: number;
  avg_price: number;
  product?: string;
  opened_at?: string;
};

export type DeskState = {
  name: string;
  horizon: Horizon;
  enabled: boolean;
  product: string;
  allocation_pct: number;
  capital: number;
  deployed: number;
  cash: number;
  open_positions: number;
  max_positions: number;
  unrealised_pnl: number;
  realised_pnl_today: number;
};

export type PortfolioState = {
  mode: string;
  halted: boolean;
  halt_reason: string | null;
  risk_band: RiskBand | null;
  allocation: AllocationExplain | null;
  capital: number;
  deployed: number;
  cash: number;
  unrealised_pnl: number;
  realised_pnl_today: number;
  day_pnl: number;
  orders_today: number;
  positions: Position[];
  desks: DeskState[];
};

export type RunResponse = {
  desk: string;
  mode: string;
  fills: Fill[];
  vetoed: Array<{ symbol: string; rule: string }>;
  resized: Array<{ symbol: string; rule: string }>;
  skipped: Array<{ symbol: string; reason: string }>;
  errors: Array<{ symbol: string; error: string }>;
};

// journal.recent() returns `ts`, not `at`. Getting this wrong renders
// "Invalid Date" on every row of the audit trail, which is the one screen that
// has to look trustworthy.
export type JournalEntry = {
  ts: string;
  kind: string;
  payload: Record<string, unknown>;
};

export type Health = {
  db: boolean;
  account_configured: boolean;
  capital: number;
  risk_band: RiskBand | null;
  mode: string;
  gate_armed: boolean;
  gate_shut_because: string[];
  quotes: string;
  kite: Record<string, unknown>;
  halted: boolean;
  halt_reason: string | null;
  desks: string[];
  paper_trading_days: number;
  disclaimer: string;
};
