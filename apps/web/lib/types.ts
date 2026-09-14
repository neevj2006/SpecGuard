export type Verdict =
  "satisfied" | "partially_satisfied" | "not_satisfied" | "not_verifiable";
export type Criterion = { id: string; text: string; source_text: string };
export type Evidence = {
  id: string;
  path: string;
  start_line: number;
  end_line: number;
  quote: string;
  revision: string;
  symbol: string;
  kind: string;
  score: number;
  changed: boolean;
};
export type Result = {
  criterion: Criterion;
  verdict: Verdict;
  rationale: string;
  evidence: Evidence[];
  confidence: number | null;
  uncertainty: string;
  suggestion: string;
  tests: { status: string };
};
export type Run = {
  id: string;
  repository: string;
  pull_number?: number | null;
  base_sha: string;
  head_sha: string;
  requirement: string;
  created_at: string;
  results: Result[];
  duration_ms: number;
  versions: Record<string, string>;
  excluded: { path: string; reason: string }[];
};

export type UsageDistribution = {
  samples: number;
  mean_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
};
export type UsageReport = {
  version: string;
  scope: string;
  runs: number;
  period: { oldest_created_at: string | null; newest_created_at: string | null };
  criteria: {
    total: number;
    verdicts: Record<string, number>;
    with_citations: number;
    without_citations: number;
    test_states: Record<string, number>;
  };
  verification: {
    instrumented_criteria: number;
    uninstrumented_criteria: number;
    attempted_requests: number;
    skipped_requests: number;
    outcomes: Record<string, number>;
    budget_outcomes: number;
    known_tokens: number;
    requests_with_known_tokens: number;
    requests_with_unknown_tokens: number;
    total_tokens: number | null;
    request_latency: UsageDistribution;
  };
  recorded_run_usage: {
    known_tokens: number;
    runs_with_unknown_tokens: number;
    total_tokens: number | null;
    known_cost_usd: string;
    runs_with_unknown_cost: number;
    total_cost_usd: string | null;
  };
  run_latency: UsageDistribution;
  limitations: string[];
  selection?: { order: string; limit: number; has_more: boolean };
};
