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
