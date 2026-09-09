"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  CircleDashed,
  CircleAlert,
  Clock3,
  Code2,
  Copy,
  FileCode2,
  GitBranch,
  GitPullRequest,
  Loader2,
  MinusCircle,
  Plus,
  Search,
  Terminal,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Evidence, Run, Verdict } from "@/lib/types";

export const verdictLabels: Record<Verdict, string> = {
  satisfied: "Satisfied",
  partially_satisfied: "Partially satisfied",
  not_satisfied: "Not satisfied",
  not_verifiable: "Not verifiable",
};
const verdictIcons = {
  satisfied: CheckCircle2,
  partially_satisfied: CircleAlert,
  not_satisfied: MinusCircle,
  not_verifiable: CircleDashed,
};

export function VerdictStatus({ verdict }: { verdict: Verdict }) {
  const Icon = verdictIcons[verdict];
  return (
    <span className={`verdict-status ${verdict}`}>
      <Icon size={15} strokeWidth={2} />
      {verdictLabels[verdict]}
    </span>
  );
}

function SyntaxLine({ line }: { line: string }) {
  return (
    <>
      {line
        .split(
          /(\/\/.*$|"[^"\n]*"|'[^'\n]*'|\b(?:export|function|return|const|let|if|async|await|new|throw|true|false|null)\b|\b\d+(?:\.\d+)?\b)/g,
        )
        .map((part, index) => {
          const kind = part.startsWith("//")
            ? "comment"
            : /^["']/.test(part)
              ? "string"
              : /^\d/.test(part)
                ? "number"
                : /^(export|function|return|const|let|if|async|await|new|throw|true|false|null)$/.test(
                      part,
                    )
                  ? "keyword"
                  : "plain";
          return (
            <span key={index} className={`syntax-${kind}`}>
              {part}
            </span>
          );
        })}
    </>
  );
}

function SourceReference({
  evidence,
  example,
}: {
  evidence: Evidence;
  example: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const lines = evidence.quote.split("\n");
  const reference = `${evidence.path}:${evidence.start_line}-${evidence.end_line} @ ${evidence.revision}`;
  return (
    <article className="source-reference">
      <div className="source-title">
        <FileCode2 size={16} />
        <strong>{evidence.path}</strong>
        <span className={`source-origin ${evidence.changed ? "changed" : ""}`}>
          {evidence.changed ? "Changed source" : "Supporting source"}
        </span>
      </div>
      <div className="source-tools">
        <span>
          <code>{evidence.symbol}</code>{" "}
          <span className="source-lines">
            L{evidence.start_line}–{evidence.end_line}
          </span>
        </span>
        <Button
          variant="ghost"
          size="sm"
          aria-label={`Copy reference for ${evidence.path}`}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(reference);
              setCopied(true);
              setError("");
            } catch {
              setError(
                "Clipboard unavailable. Select the path and revision to copy manually.",
              );
            }
          }}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          <span>{copied ? "Copied" : "Copy reference"}</span>
        </Button>
      </div>
      <pre aria-label={`Source code in ${evidence.path}`} tabIndex={0}>
        {(expanded ? lines : lines.slice(0, 5)).map((line, index) => (
          <div className="source-code-line" key={index}>
            <span className="source-line-number">
              {evidence.start_line + index}
            </span>
            <code>
              <SyntaxLine line={line || " "} />
            </code>
          </div>
        ))}
      </pre>
      <div className="source-bottom">
        <span>
          <Check size={12} />
          {example ? "Example snapshot" : "Matched to committed source"}
          <code title={evidence.revision}>{evidence.revision.slice(0, 8)}</code>
        </span>
        {lines.length > 5 && (
          <button
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Collapse" : `Show all ${lines.length} lines`}
            <ChevronDown size={13} className={expanded ? "rotated" : ""} />
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
    </article>
  );
}

type Props = {
  run: Run;
  initialNotes: Record<string, string>;
  onNew: () => void;
  onEdit: () => void;
  onReport: () => void;
  onSaveNote: (criterionId: string, note: string) => Promise<void>;
};

export function ReviewDesk({
  run,
  initialNotes,
  onNew,
  onEdit,
  onReport,
  onSaveNote,
}: Props) {
  const [selected, setSelected] = useState(0);
  const [filter, setFilter] = useState<Verdict | "all">("all");
  const [query, setQuery] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>(initialNotes);
  const [savedNotes, setSavedNotes] =
    useState<Record<string, string>>(initialNotes);
  const [saving, setSaving] = useState(false);
  const [noteError, setNoteError] = useState("");
  const detailRef = useRef<HTMLElement>(null);
  const criteriaRef = useRef<HTMLElement>(null);
  const example = run.id === "example-review";
  const current = run.results[selected];
  const visible = run.results
    .map((result, index) => ({ result, index }))
    .filter(
      ({ result }) =>
        (filter === "all" || result.verdict === filter) &&
        result.criterion.text.toLowerCase().includes(query.toLowerCase()),
    );
  const needsAttention = run.results.filter(
    (r) => r.verdict !== "satisfied",
  ).length;
  const lacksEvidence = run.results.filter((r) => !r.evidence.length).length;
  const note = current ? (notes[current.criterion.id] ?? "") : "";
  const dirty = current
    ? note !== (savedNotes[current.criterion.id] ?? "")
    : false;
  const anyDirty = Object.entries(notes).some(
    ([id, value]) => value !== (savedNotes[id] ?? ""),
  );
  useEffect(() => {
    if (!anyDirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [anyDirty]);
  function selectCriterion(index: number) {
    setSelected(index);
    setNoteError("");
    if (window.matchMedia("(max-width: 650px)").matches) {
      requestAnimationFrame(() =>
        detailRef.current?.scrollIntoView({
          block: "start",
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches
            ? "auto"
            : "smooth",
        }),
      );
    }
  }
  function changeFilter(value: Verdict | "all") {
    setFilter(value);
    setQuery("");
    const next = run.results.findIndex(
      (r) => value === "all" || r.verdict === value,
    );
    setSelected(next);
  }
  return (
    <>
      <section className="desk-heading">
        <div className="desk-context">
          <GitPullRequest size={15} />
          <strong>{run.repository}</strong>
          <span>/</span>
          {example ? "PR #142" : "Committed change"}
          <span className="review-mode">
            {example ? "EXAMPLE" : "COMPLETED"}
          </span>
        </div>
        <div className="desk-title-row">
          <div>
            <h1>
              {example ? "Add promotional discounts" : "Requirement review"}
            </h1>
            <div className="desk-branches">
              <GitBranch size={14} />
              <code>{example ? "main" : run.base_sha.slice(0, 8)}</code>
              <span>←</span>
              <code>
                {example ? "feat/promotion-codes" : run.head_sha.slice(0, 8)}
              </code>
              <span className="branch-sha">{run.head_sha.slice(0, 8)}</span>
            </div>
          </div>
          <div className="desk-actions">
            <Button variant="ghost" onClick={onReport}>
              <ArrowUpRight size={16} />
              Report preview
            </Button>
            <Button onClick={onNew} className="primary-action">
              <Plus size={17} />
              New analysis
            </Button>
          </div>
        </div>
        <div className="coverage-navigation">
          <div className="coverage-caption">
            <strong>
              {needsAttention} <span>criteria need attention</span>
            </strong>
            <p>
              {lacksEvidence}{" "}
              {lacksEvidence === 1 ? "criterion lacks" : "criteria lack"} source
              evidence
            </p>
          </div>
          <div className="coverage-counts" aria-label="Filter by verdict">
            {(Object.keys(verdictLabels) as Verdict[]).map((verdict) => {
              const Icon = verdictIcons[verdict];
              return (
                <button
                  key={verdict}
                  className={`coverage-count ${verdict} ${filter === verdict ? "is-filtered" : ""}`}
                  aria-pressed={filter === verdict}
                  onClick={() =>
                    changeFilter(filter === verdict ? "all" : verdict)
                  }
                >
                  <span>
                    <Icon size={16} />
                    <strong>
                      {run.results.filter((r) => r.verdict === verdict).length}
                    </strong>
                  </span>
                  <span>{verdictLabels[verdict]}</span>
                  <ChevronRight size={12} />
                </button>
              );
            })}
          </div>
        </div>
        <div className="run-context-line">
          <span className="reviewer-avatar">LC</span>
          <span>Local reviewer</span>
          <span className="context-divider" />
          <Clock3 size={12} />
          <time dateTime={run.created_at}>
            Analyzed{" "}
            {new Date(run.created_at)
              .toISOString()
              .slice(0, 16)
              .replace("T", " ")}{" "}
            UTC
          </time>
          <span className="context-divider" />
          <Terminal size={12} />
          <span>
            {run.results.every((r) => r.tests.status === "not_run")
              ? "Tests not run"
              : "See criterion test states"}
          </span>
          {example && (
            <span className="example-caption">
              Illustrative data · not your repository
            </span>
          )}
        </div>
      </section>
      <div className="desk-navigation">
        <span className="desk-nav-active">
          <Code2 size={15} />
          Criteria & evidence <b>{run.results.length}</b>
        </span>
        <button onClick={onEdit}>
          Edit requirement
          <ArrowUpRight size={13} />
        </button>
        <details className="run-details">
          <summary>
            Run details
            <ChevronDown size={13} />
          </summary>
          <div>
            <strong>Analysis provenance</strong>
            <p>
              {(run.duration_ms / 1000).toFixed(2)} seconds ·{" "}
              {run.excluded.length} excluded files
            </p>
            <dl>
              {Object.entries(run.versions).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            {run.excluded.map((file, index) => (
              <p key={index}>
                {file.path}: {file.reason}
              </p>
            ))}
          </div>
        </details>
        {anyDirty && (
          <span className="draft-state">
            <span />
            Unsaved reviewer note
          </span>
        )}
      </div>
      <div className="desk-body">
        <section
          ref={criteriaRef}
          className="criteria-index"
          aria-label="Acceptance criteria"
        >
          <div className="index-heading">
            <strong>Acceptance criteria</strong>
            <span>
              {visible.length} / {run.results.length}
            </span>
          </div>
          <div className="index-search">
            <Search size={15} />
            <input
              aria-label="Search criteria"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a criterion…"
            />
            {query && (
              <button aria-label="Clear search" onClick={() => setQuery("")}>
                <X size={14} />
              </button>
            )}
          </div>
          {filter !== "all" && (
            <button
              className="filter-reset"
              onClick={() => changeFilter("all")}
            >
              Clear {verdictLabels[filter].toLowerCase()} filter
              <X size={12} />
            </button>
          )}
          <div className="index-list">
            {visible.map(({ result, index }) => (
              <button
                className={`index-criterion ${selected === index ? "is-selected" : ""}`}
                key={result.criterion.id}
                aria-pressed={selected === index}
                onClick={() => selectCriterion(index)}
              >
                <span className="criterion-number">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div>
                  <VerdictStatus verdict={result.verdict} />
                  <h3>{result.criterion.text}</h3>
                  <div className="index-metadata">
                    <FileCode2 size={12} />
                    {result.evidence.length}{" "}
                    {result.evidence.length === 1 ? "ref" : "refs"}
                    <span>·</span>Static
                    {notes[result.criterion.id] !== undefined &&
                      notes[result.criterion.id] !==
                        (savedNotes[result.criterion.id] ?? "") && (
                        <span className="note-dot" title="Unsaved note" />
                      )}
                    <ChevronRight size={14} />
                  </div>
                </div>
              </button>
            ))}
          </div>
          {!visible.length && (
            <div className="index-empty">
              <Search size={20} />
              <strong>No matching criteria</strong>
              <p>Try a different search or clear the status filter.</p>
              <Button variant="ghost" onClick={() => changeFilter("all")}>
                Clear filters
              </Button>
            </div>
          )}
          <p className="index-footnote">
            Select a criterion to inspect its evidence.
            <br />
            No automatic merge blocking.
          </p>
        </section>
        {!current ? (
          <section className="criterion-detail detail-empty">
            <CircleHelp size={26} />
            <h2>No criterion selected</h2>
            <p>Choose a criterion or clear the filter to continue reviewing.</p>
            <Button variant="outline" onClick={() => changeFilter("all")}>
              Show all criteria
            </Button>
          </section>
        ) : (
          <section
            ref={detailRef}
            className="criterion-detail"
            aria-label="Selected criterion evidence"
          >
            <button
              className="mobile-back-to-criteria"
              onClick={() =>
                criteriaRef.current?.scrollIntoView({ block: "start" })
              }
            >
              <ChevronRight size={14} />
              Back to criteria
            </button>
            <div className="detail-identity">
              <code>AC-{String(selected + 1).padStart(2, "0")}</code>
              <VerdictStatus verdict={current.verdict} />
              <span>
                {selected + 1} of {run.results.length}
              </span>
            </div>
            <h2>{current.criterion.text}</h2>
            <div className="detail-facts">
              <span>
                <FileCode2 size={13} />
                {current.evidence.length} source{" "}
                {current.evidence.length === 1 ? "reference" : "references"}
              </span>
              <span>
                <GitBranch size={13} />
                <code>{run.head_sha.slice(0, 8)}</code>
              </span>
              <span>
                <Terminal size={13} />
                {current.tests.status.replaceAll("_", " ")}
              </span>
            </div>
            <Tabs defaultValue="evidence" className="review-source-tabs">
              <TabsList aria-label="Evidence views">
                <TabsTrigger value="evidence">
                  <Code2 size={15} />
                  Static evidence
                </TabsTrigger>
                <TabsTrigger value="inference">
                  <CircleHelp size={15} />
                  Inference
                </TabsTrigger>
                <TabsTrigger value="tests">
                  <Terminal size={15} />
                  Tests
                  <span className="test-count">
                    {current.tests.status === "not_run"
                      ? "Not run"
                      : current.tests.status}
                  </span>
                </TabsTrigger>
              </TabsList>
              <TabsContent value="evidence">
                <div className="source-section-heading">
                  <h3>Source references</h3>
                  <span>Read-only snapshot</span>
                </div>
                {current.evidence.map((e) => (
                  <SourceReference key={e.id} evidence={e} example={example} />
                ))}
                {!current.evidence.length && (
                  <div className="evidence-empty">
                    <CircleDashed size={24} />
                    <div>
                      <h3>No source references</h3>
                      <p>
                        {current.uncertainty ||
                          "This search did not find sufficient source evidence."}
                      </p>
                      <p>
                        Confirm the behavior's owning service, or refine the
                        requirement and analyze again. Missing evidence does not
                        establish missing behavior.
                      </p>
                      <Button variant="ghost" onClick={onEdit}>
                        Refine requirement
                        <ArrowRight size={14} />
                      </Button>
                    </div>
                  </div>
                )}
                <section className="review-assessment">
                  <h3>
                    Assessment{" "}
                    <span>
                      {example
                        ? "Illustrative inference"
                        : "Source-based assessment"}
                    </span>
                  </h3>
                  <p>{current.rationale}</p>
                  <details className="confidence-explanation">
                    <summary>
                      <CircleHelp size={13} />
                      {current.confidence === null
                        ? "Confidence unavailable"
                        : `Model confidence ${Math.round(current.confidence * 100)}%`}
                      <ChevronDown size={12} />
                    </summary>
                    <p>
                      {current.confidence === null
                        ? "The offline baseline does not estimate confidence."
                        : "This is an uncalibrated model estimate, not an executed test or a probability of runtime correctness."}{" "}
                      {current.uncertainty}
                    </p>
                  </details>
                </section>
                <details className="next-check">
                  <summary>
                    <Terminal size={15} />
                    <span>Suggested next check</span>
                    <span>Not executed</span>
                    <ChevronDown size={14} />
                  </summary>
                  <p>
                    {current.suggestion ||
                      "Identify an executable test that covers this criterion."}
                  </p>
                </details>
              </TabsContent>
              <TabsContent value="inference">
                <section className="inference-reading">
                  <h3>Reasoning</h3>
                  <p>{current.rationale}</p>
                  <h3>What remains uncertain</h3>
                  <p>
                    {current.uncertainty ||
                      "Source-based inference has not been validated by a test execution."}
                  </p>
                  <h3>Confidence is not proof</h3>
                  <p>
                    {current.confidence === null
                      ? "The offline baseline supplies no confidence estimate."
                      : `The model reported ${Math.round(current.confidence * 100)}% confidence. This estimate is uncalibrated.`}{" "}
                    Inspect the source and execution evidence independently.
                  </p>
                </section>
              </TabsContent>
              <TabsContent value="tests">
                <div className="evidence-empty">
                  <Terminal size={26} />
                  <div>
                    <h3>
                      {current.tests.status === "not_run"
                        ? "No tests executed in this run"
                        : `Test state: ${current.tests.status.replaceAll("_", " ")}`}
                    </h3>
                    <p>
                      Source analysis does not run repository code. A test
                      definition or a generated suggestion cannot establish that
                      a test passed.
                    </p>
                    <p>
                      Run the relevant tests in your trusted development
                      environment. Execution-log import is not available yet.
                    </p>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
            <section className="reviewer-note">
              <div className="note-heading">
                <span className="reviewer-avatar">LC</span>
                <label htmlFor="reviewer-note">Reviewer note</label>
                <span>
                  {dirty
                    ? "Unsaved changes"
                    : savedNotes[current.criterion.id]
                      ? example
                        ? "Saved in this example session"
                        : "Saved to run"
                      : "Only you, in this workspace"}
                </span>
              </div>
              <Textarea
                id="reviewer-note"
                rows={2}
                value={note}
                placeholder="Flag a misleading claim, missing evidence, or a test to add…"
                onChange={(e) => {
                  setNotes({
                    ...notes,
                    [current.criterion.id]: e.target.value,
                  });
                  setNoteError("");
                }}
              />
              <div className="note-actions">
                <small>
                  {example
                    ? "Example notes remain in this session."
                    : "Notes attach to this criterion and source revision."}
                </small>
                <Button
                  variant="ghost"
                  disabled={saving || !dirty || !note.trim()}
                  onClick={async () => {
                    const id = current.criterion.id;
                    const value = note;
                    setSaving(true);
                    try {
                      if (!example) await onSaveNote(id, value);
                      setSavedNotes((previous) => ({
                        ...previous,
                        [id]: value,
                      }));
                      setNoteError("");
                    } catch (error) {
                      setNoteError(
                        error instanceof Error
                          ? error.message
                          : "Note could not be saved. Your draft is retained.",
                      );
                    } finally {
                      setSaving(false);
                    }
                  }}
                >
                  {saving ? (
                    <Loader2 size={14} className="spin" />
                  ) : (
                    <Check size={14} />
                  )}
                  Save note
                </Button>
              </div>
              {noteError && (
                <p role="alert" className="inline-error">
                  {noteError}
                </p>
              )}
            </section>
          </section>
        )}
      </div>
    </>
  );
}
