"use client";

import { ReviewDesk } from "@/components/review-desk";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { exampleRun } from "@/lib/example";
import type { Criterion, Run, Verdict } from "@/lib/types";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  FolderGit2,
  GitPullRequest,
  History,
  Loader2,
  Play,
  Plus,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { useState } from "react";

const labels: Record<Verdict, string> = {
  satisfied: "Satisfied",
  partially_satisfied: "Partially satisfied",
  not_satisfied: "Not satisfied",
  not_verifiable: "Not verifiable",
};
type View = "review" | "new" | "history" | "repositories" | "settings";
function download(run: Run) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(run, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `specguard-${run.id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Dashboard() {
  const [view, setView] = useState<View>("review");
  const [run, setRun] = useState<Run>(exampleRun);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [history, setHistory] = useState<Run[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [repositories, setRepositories] = useState<
    { name: string; path: string }[]
  >([]);
  const [repository, setRepository] = useState(".");
  const [base, setBase] = useState("HEAD~1");
  const [head, setHead] = useState("HEAD");
  const [requirement, setRequirement] = useState(exampleRun.requirement);
  const [criteria, setCriteria] = useState<Criterion[]>(
    exampleRun.results.map((r) => r.criterion),
  );
  const [useModel, setUseModel] = useState(false);
  const [report, setReport] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const demo = run.id === "example-review";

  async function api<T>(
    path: string,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    const response = await fetch(`/api/v1/${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const data = await response
        .json()
        .catch(() => ({ detail: "Request failed" }));
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "Check the input values and try again.",
      );
    }
    return response.status === 204 ? (undefined as T) : response.json();
  }
  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  function navigate(next: View) {
    setView(next);
    setError("");
    setNotice("");
  }
  const reportText = `## SpecGuard requirement review\n\n${demo ? "Illustrative example — not an analysis of a real pull request.\n\n" : ""}Revision: ${run.head_sha}\n\n${run.results.map((r) => `- **${labels[r.verdict]}** — ${r.criterion.text}\n  ${r.rationale}\n  ${r.evidence.map((e) => `${e.path}:${e.start_line}-${e.end_line}`).join(", ") || "No supporting evidence"}\n  Tests: ${r.tests.status}`).join("\n\n")}\n\nStatic inference is not proof of runtime correctness.`;

  return (
    <div className="workspace">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="SpecGuard home">
          <span className="brand-symbol">
            <ShieldCheck size={21} />
          </span>
          SpecGuard
          <span className="brand-dot" />
        </a>
        <div className="workspace-switch">
          <span className="avatar">S</span>
          <div>
            <strong>Local workspace</strong>
            <small>Developer edition</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {(
            [
              { id: "review", label: "Review desk", icon: GitPullRequest },
              { id: "repositories", label: "Repositories", icon: FolderGit2 },
              { id: "history", label: "Run history", icon: History },
            ] as const
          ).map((n) => (
            <Button
              key={n.id}
              variant="ghost"
              className={`nav-item ${view === n.id ? "active" : ""}`}
              onClick={() => navigate(n.id)}
            >
              <n.icon size={17} />
              {n.label}
              {n.id === "review" && (
                <span className="nav-count">{run.results.length}</span>
              )}
            </Button>
          ))}
        </nav>
        <div className="sidebar-rule" />
        <div className="nav-label">CURRENT REVIEW</div>
        <button className="repo-nav" onClick={() => navigate("review")}>
          <span className="repo-dot" />
          {run.repository}
          <ChevronRight size={13} />
        </button>
        <div className="sidebar-bottom">
          <div className="quiet-note">
            <ShieldCheck size={16} />
            <div>
              <strong>Evidence before confidence.</strong>
              <p>Every claim should lead back to source.</p>
            </div>
          </div>
          <Button
            variant="ghost"
            className={`nav-item ${view === "settings" ? "active" : ""}`}
            onClick={() => navigate("settings")}
          >
            <Settings2 size={17} />
            Workspace settings
          </Button>
          <div className="profile">
            <span className="avatar">LC</span>
            <div>
              <strong>Local reviewer</strong>
              <small>Manual analysis</small>
            </div>
            <span className="online-dot" />
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div>
            <span className="muted">Workspace</span>
            <ChevronRight size={13} />
            <span>
              {
                {
                  review: "Review desk",
                  new: "New analysis",
                  history: "Run history",
                  repositories: "Repositories",
                  settings: "Settings",
                }[view]
              }
            </span>
          </div>
          <span className="local-indicator">
            <span className="online-dot" />
            Local environment
          </span>
        </header>
        {error && (
          <div className="message error" role="alert">
            <CircleHelp size={16} />
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              ×
            </button>
          </div>
        )}
        {notice && (
          <div className="message" role="status">
            <CheckCircle2 size={16} />
            <span>{notice}</span>
            <button
              aria-label="Dismiss notification"
              onClick={() => setNotice("")}
            >
              ×
            </button>
          </div>
        )}
        <div className="review-root" hidden={view !== "review"}>
          <ReviewDesk
            key={run.id}
            run={run}
            onNew={() => navigate("new")}
            onEdit={() => {
              setRequirement(run.requirement);
              setCriteria(run.results.map((r) => r.criterion));
              navigate("new");
            }}
            onReport={() => setReport(true)}
            onSaveNote={async (criterionId, note) => {
              await api(`runs/${run.id}/feedback`, "POST", {
                criterion_id: criterionId,
                note,
              });
            }}
          />
        </div>
        {view === "new" && (
          <section className="page-content new-analysis-page">
            <div className="eyebrow">
              NEW ANALYSIS{" "}
              <span className="form-draft">Draft · not analyzed</span>
            </div>
            <div className="heading-row">
              <div>
                <h1>Start with the requirement.</h1>
                <p>
                  Choose a committed change. Review the criteria before running
                  analysis.
                </p>
              </div>
              <Button variant="ghost" onClick={() => navigate("review")}>
                <ArrowLeft size={15} />
                Back to review
              </Button>
            </div>
            <ol className="analysis-stepper" aria-label="Analysis workflow">
              <li>
                <span>01</span>
                <div>
                  <strong>Select change</strong>
                  <small>Repository and revisions</small>
                </div>
              </li>
              <li>
                <span>02</span>
                <div>
                  <strong>Describe behavior</strong>
                  <small>Explicit acceptance criteria</small>
                </div>
              </li>
              <li className={criteria.length ? "step-ready" : ""}>
                <span>03</span>
                <div>
                  <strong>Review contract</strong>
                  <small>
                    {criteria.length
                      ? `${criteria.length} criteria to review`
                      : "Waiting for decomposition"}
                  </small>
                </div>
              </li>
            </ol>
            {!token && (
              <div className="connection-guidance">
                <CircleHelp size={16} />
                <span>
                  Connect the local API to decompose requirements and run
                  analysis.
                </span>
                <Button variant="ghost" onClick={() => navigate("settings")}>
                  Configure connection
                  <ArrowRight size={14} />
                </Button>
              </div>
            )}
            <div className="editor-grid">
              <div>
                <div className="form-section">
                  <div className="section-title">
                    <span className="step">1</span>
                    <h2>Select the change</h2>
                  </div>
                  <label htmlFor="repo">
                    Repository path{" "}
                    <span>Relative to the configured repository root</span>
                  </label>
                  <Input
                    id="repo"
                    value={repository}
                    onChange={(e) => setRepository(e.target.value)}
                  />
                  <div className="two-fields">
                    <div>
                      <label htmlFor="base">Base revision</label>
                      <Input
                        id="base"
                        value={base}
                        onChange={(e) => setBase(e.target.value)}
                      />
                    </div>
                    <div>
                      <label htmlFor="head">Head revision</label>
                      <Input
                        id="head"
                        value={head}
                        onChange={(e) => setHead(e.target.value)}
                      />
                    </div>
                  </div>
                </div>
                <div className="form-section">
                  <div className="section-title">
                    <span className="step">2</span>
                    <h2>Describe the intended behavior</h2>
                  </div>
                  <label htmlFor="requirement">
                    Requirement or acceptance criteria
                  </label>
                  <Textarea
                    id="requirement"
                    rows={7}
                    value={requirement}
                    onChange={(e) => {
                      setRequirement(e.target.value);
                      setCriteria([]);
                    }}
                  />
                  <div className="form-footer">
                    <small>
                      Decompose splits numbered or bulleted requirements into
                      editable criteria. Review each item before analysis.
                    </small>
                    <Button
                      variant="outline"
                      disabled={busy || !requirement.trim()}
                      onClick={() =>
                        perform(async () => {
                          const data = await api<{ criteria: Criterion[] }>(
                            "criteria",
                            "POST",
                            { text: requirement },
                          );
                          setCriteria(data.criteria);
                        })
                      }
                    >
                      {busy ? (
                        <Loader2 className="spin" size={14} />
                      ) : (
                        <SlidersHorizontal size={14} />
                      )}
                      Decompose into criteria
                    </Button>
                  </div>
                </div>
              </div>
              <div className="criteria-editor">
                <div className="section-title">
                  <span className="step">3</span>
                  <h2>Review the contract</h2>
                  <span className="pill">{criteria.length} criteria</span>
                </div>
                <p className="muted">
                  This is the contract the analyzer will review. Keep each
                  criterion observable and independently testable.
                </p>
                {!criteria.length && (
                  <div className="contract-empty">
                    <SlidersHorizontal size={22} />
                    <h3>Your review contract starts here</h3>
                    <p>
                      Describe the intended behavior, then choose Decompose into
                      criteria. You can also add criteria manually.
                    </p>
                  </div>
                )}
                {criteria.map((c, i) => (
                  <div className="editable-criterion" key={c.id}>
                    <code>AC-{String(i + 1).padStart(2, "0")}</code>
                    <Textarea
                      aria-label={`Criterion ${i + 1}`}
                      rows={2}
                      value={c.text}
                      onChange={(e) =>
                        setCriteria(
                          criteria.map((item, j) =>
                            j === i ? { ...item, text: e.target.value } : item,
                          ),
                        )
                      }
                    />
                    <button
                      aria-label={`Remove criterion ${i + 1}`}
                      onClick={() =>
                        setCriteria(criteria.filter((_, j) => i !== j))
                      }
                    >
                      ×
                    </button>
                  </div>
                ))}
                <Button
                  variant="ghost"
                  onClick={() =>
                    setCriteria([
                      ...criteria,
                      {
                        id: crypto.randomUUID(),
                        text: "",
                        source_text: "Reviewer-added criterion",
                      },
                    ])
                  }
                >
                  <Plus size={14} />
                  Add criterion
                </Button>
                <div className="analysis-options">
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={useModel}
                      onChange={(e) => setUseModel(e.target.checked)}
                    />
                    Use configured model verifier
                  </label>
                  <p>
                    {useModel
                      ? "Selected source will be sent to the configured model provider."
                      : "Offline baseline: retrieve evidence and abstain from behavioral claims."}
                  </p>
                </div>
                <Button
                  className="full-width"
                  disabled={
                    busy ||
                    !criteria.length ||
                    criteria.some((c) => !c.text.trim())
                  }
                  onClick={() =>
                    perform(async () => {
                      const result = await api<Run>("runs", "POST", {
                        repository,
                        base,
                        head,
                        requirement,
                        criteria,
                        use_model: useModel,
                      });
                      setRun(result);
                      setHistoryLoaded(true);
                      setHistory([
                        result,
                        ...history.filter((r) => r.id !== result.id),
                      ]);
                      navigate("review");
                    })
                  }
                >
                  {busy ? (
                    <Loader2 className="spin" size={15} />
                  ) : (
                    <Play size={15} />
                  )}
                  {busy ? "Analyzing change…" : "Analyze change"}
                  <ArrowRight size={15} />
                </Button>
              </div>
            </div>
          </section>
        )}
        {view === "history" && (
          <section className="page-content">
            <div className="eyebrow">ANALYSIS ARCHIVE</div>
            <div className="heading-row">
              <div>
                <h1>Run history</h1>
                <p>
                  Revisit a decision with its original inputs and source
                  revision.
                </p>
              </div>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() =>
                  perform(async () => {
                    setHistory(await api<Run[]>("runs"));
                    setHistoryLoaded(true);
                  })
                }
              >
                <History size={15} />
                Load saved runs
              </Button>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Repository & run</th>
                    <th>Revision</th>
                    <th>Criteria</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(history.length
                    ? history
                    : historyLoaded
                      ? []
                      : [exampleRun]
                  ).map((r) => (
                    <tr key={r.id}>
                      <td>
                        <button
                          className="text-button"
                          onClick={() => {
                            setRun(r);
                            navigate("review");
                          }}
                        >
                          <FolderGit2 size={16} />
                          {r.repository}
                        </button>
                        <small>
                          {r.id === "example-review"
                            ? "Illustrative example"
                            : r.id}
                        </small>
                      </td>
                      <td>
                        <code>{r.head_sha.slice(0, 8)}</code>
                      </td>
                      <td>{r.results.length} criteria</td>
                      <td>
                        {new Date(r.created_at).toISOString().slice(0, 10)}
                      </td>
                      <td>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => download(r)}
                        >
                          Export
                        </Button>
                        {r.id !== "example-review" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDeleteId(r.id)}
                          >
                            Delete
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {historyLoaded && !history.length && (
                    <tr>
                      <td colSpan={5}>
                        <div className="history-empty">
                          <History size={22} />
                          <strong>No saved runs yet</strong>
                          <p>
                            Start an analysis to create a review with source
                            evidence and revision history.
                          </p>
                          <Button onClick={() => navigate("new")}>
                            New analysis
                            <Plus size={14} />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="muted footnote">
              Saved runs retain exact revision and verifier versions. Example
              data is never saved as a real run.
            </p>
          </section>
        )}
        {view === "repositories" && (
          <section className="page-content">
            <div className="eyebrow">SOURCE WORKSPACES</div>
            <div className="heading-row">
              <div>
                <h1>Repositories</h1>
                <p>
                  Analyze JavaScript and TypeScript from committed local
                  repositories.
                </p>
              </div>
              <Button
                disabled={busy}
                onClick={() =>
                  perform(async () =>
                    setRepositories(await api("repositories")),
                  )
                }
              >
                <FolderGit2 size={15} />
                Discover repositories
              </Button>
            </div>
            {repositories.length ? (
              <div className="repo-cards">
                {repositories.map((r) => (
                  <article key={r.path}>
                    <FolderGit2 size={23} />
                    <h2>{r.name}</h2>
                    <code>{r.path}</code>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setRepository(r.path);
                        navigate("new");
                      }}
                    >
                      Analyze repository
                      <ArrowRight size={14} />
                    </Button>
                  </article>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <FolderGit2 size={34} />
                <h2>Your source stays under your control.</h2>
                <p>
                  Connect the local API in Settings, then discover repositories
                  inside the configured root.
                </p>
                <Button variant="outline" onClick={() => navigate("settings")}>
                  Configure connection
                  <ArrowRight size={14} />
                </Button>
              </div>
            )}
            <div className="integration-note">
              <GitPullRequest size={21} />
              <div>
                <h3>GitHub integration</h3>
                <p>
                  Installation, pull request selection, and report publishing
                  require a configured GitHub App. The local workspace does not
                  connect to GitHub automatically.
                </p>
              </div>
            </div>
          </section>
        )}
        {view === "settings" && (
          <section className="page-content settings-content">
            <div className="eyebrow">WORKSPACE SETTINGS</div>
            <h1>Connection & data</h1>
            <p>Connect your browser session to the local analysis service.</p>
            <div className="form-section">
              <h2>Analysis service</h2>
              <label htmlFor="endpoint">API endpoint</label>
              <Input id="endpoint" value="http://127.0.0.1:8000" readOnly />
              <label htmlFor="token">API access token</label>
              <Input
                id="token"
                type="password"
                autoComplete="off"
                placeholder="Enter SPECGUARD_API_TOKEN"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
              <p className="muted footnote">
                Held in memory for this browser session. Never written to
                browser storage.
              </p>
              <Button
                disabled={busy || !token}
                onClick={() =>
                  perform(async () => {
                    await api("runs");
                    setNotice("Connected to the local analysis service.");
                  })
                }
              >
                <CheckCircle2 size={15} />
                Test connection
              </Button>
            </div>
            <div className="form-section">
              <h2>Data & retention</h2>
              <p>
                Export or delete individual runs from Run history. Deleting a
                run also deletes its reviewer notes.
              </p>
              <Button variant="outline" onClick={() => navigate("history")}>
                Manage saved runs
                <ArrowRight size={14} />
              </Button>
            </div>
            <div className="form-section">
              <h2>Execution policy</h2>
              <p>
                Analysis reads committed source. It does not install
                dependencies or execute code from reviewed repositories. Model
                verification is opt-in for each run.
              </p>
            </div>
          </section>
        )}
        <footer className="workspace-footer">
          <span>
            SpecGuard <span className="muted">/</span> Requirement-to-code
            review
          </span>
          <span>
            <ShieldCheck size={12} />
            Review with evidence. Decide with context.
          </span>
        </footer>
      </main>
      <nav className="mobile-navigation" aria-label="Mobile navigation">
        {(
          [
            { id: "review", label: "Review", icon: GitPullRequest },
            { id: "new", label: "Analyze", icon: Plus },
            { id: "repositories", label: "Repos", icon: FolderGit2 },
            { id: "history", label: "History", icon: History },
            { id: "settings", label: "Settings", icon: Settings2 },
          ] as const
        ).map((item) => (
          <button
            key={item.id}
            aria-current={view === item.id ? "page" : undefined}
            onClick={() => navigate(item.id)}
          >
            <item.icon size={20} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <Dialog open={report} onOpenChange={setReport}>
        <DialogContent className="report-dialog">
          <DialogHeader>
            <DialogTitle>Review report</DialogTitle>
            <DialogDescription>
              Inspect the report before copying it. Publishing to GitHub is not
              configured.
            </DialogDescription>
          </DialogHeader>
          <pre className="report-text">{reportText}</pre>
          <DialogFooter>
            <Button variant="outline" onClick={() => download(run)}>
              <ArrowDownToLine size={14} />
              Export JSON
            </Button>
            <Button
              onClick={() =>
                perform(async () => {
                  await navigator.clipboard.writeText(reportText);
                  setReport(false);
                  setNotice("Report copied.");
                })
              }
            >
              Copy report
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={!!deleteId} onOpenChange={() => setDeleteId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this saved run?</DialogTitle>
            <DialogDescription>
              The run and its reviewer notes will be removed from the local
              database.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteId(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() =>
                perform(async () => {
                  await api(`runs/${deleteId}`, "DELETE");
                  setHistory(history.filter((r) => r.id !== deleteId));
                  setDeleteId(null);
                  setNotice("Run deleted.");
                })
              }
            >
              Delete run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
