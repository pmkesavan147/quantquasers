export type TraderType = "long_term" | "swing" | "intraday" | "hybrid";

export type Persona = {
  trader_type: TraderType;
  risk_tolerance: number; // 0-1
  confidence: number; // 0-1
};

export type MarketSentimentItem = {
  headline: string;
  sentiment: number; // -1 to 1
  confidence: number; // 0-1
  entities: string[];
  timestamp: string;
};

export type PersonalSentiment = {
  overall_sentiment: number; // -1 to 1
  confidence: number;
  mentioned_assets: string[];
  asset_sentiment: Record<string, number>;
  risk_signal: "risk_averse" | "risk_seeking" | "neutral" | "unclear";
  raw_text: string;
};

export type AssetClass = "equity" | "bonds" | "intraday" | "cash";

export type AllocationBreakdown = {
  asset_class: AssetClass;
  baseline: number;
  market_tilt: number;
  conviction_tilt: number;
  final: number;
  reason: string;
};

export type RebalanceEvent = {
  id: string;
  timestamp: string;
  asset_class: AssetClass;
  from: number;
  to: number;
  trigger: string;
  feedback?: "up" | "down" | null;
};

export type OnboardingAnswers = {
  time_horizon?: string;
  experience?: string;
  capital?: number;
  drawdown_tolerance?: number;
  trade_frequency?: string;
  income_need?: string;
  volatility_comfort?: number;
  primary_goal?: string;
  liquidity_need?: string;
  sentiment_text?: string;
};
