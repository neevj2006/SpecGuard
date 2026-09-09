"use client";
import { useState } from "react";
import { ArrowRight, FolderGit2, GitPullRequest, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export type GitHubSelection = {
  installation_id: number;
  repository: string;
  number: number;
  title: string;
  requirement: string;
  base: string;
  head: string;
};
type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;
type Pull = {
  number: number;
  title: string;
  body: string;
  base: string;
  head: string;
};

export function GitHubRepositories({
  api,
  onSelect,
}: {
  api: Api;
  onSelect: (selection: GitHubSelection) => void;
}) {
  const [repos, setRepos] = useState<
    { full_name: string; private: boolean; installation_id: number }[]
  >([]);
  const [pulls, setPulls] = useState<Pull[]>([]);
  const [selected, setSelected] = useState<{
    full_name: string;
    installation_id: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  async function perform(task: () => Promise<void>) {
    setLoading(true);
    setError("");
    try {
      await task();
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "GitHub request failed",
      );
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="github-repositories">
      <div className="section-title">
        <GitPullRequest size={21} />
        <h2>GitHub pull requests</h2>
        <Button
          variant="outline"
          disabled={loading}
          onClick={() =>
            perform(async () => {
              const installations = await api<{ id: number }[]>(
                "github/installations",
              );
              const results = await Promise.all(
                installations.map(async (installation) =>
                  (
                    await api<{ full_name: string; private: boolean }[]>(
                      `github/installations/${installation.id}/repositories`,
                    )
                  ).map((repo) => ({
                    ...repo,
                    installation_id: installation.id,
                  })),
                ),
              );
              setRepos(results.flat());
              setLoaded(true);
              setSelected(null);
              setPulls([]);
            })
          }
        >
          {loading ? (
            <Loader2 className="spin" size={14} />
          ) : (
            <FolderGit2 size={14} />
          )}
          Load GitHub repositories
        </Button>
      </div>
      <p className="muted footnote">
        Access is limited to installations assigned to this workspace. Analysis
        is always manual.
      </p>
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      {loaded && !repos.length && (
        <p className="muted footnote">
          No GitHub installation is assigned. Configure the App ID, private key
          file, and installation ID on the analysis service.
        </p>
      )}
      {repos.map((repo) => (
        <div
          className="github-repo-row"
          key={`${repo.installation_id}:${repo.full_name}`}
        >
          <strong>{repo.full_name}</strong>
          <span>{repo.private ? "Private" : "Public"}</span>
          <Button
            variant="ghost"
            disabled={loading}
            onClick={() =>
              perform(async () => {
                setPulls(
                  await api<Pull[]>("github/pulls", "POST", {
                    installation_id: repo.installation_id,
                    repository: repo.full_name,
                  }),
                );
                setSelected(repo);
              })
            }
          >
            Pull requests
            <ArrowRight size={14} />
          </Button>
        </div>
      ))}
      {selected && (
        <div className="github-pulls">
          <h3>Open pull requests · {selected.full_name}</h3>
          {!pulls.length && (
            <p className="muted footnote">No open pull requests were found.</p>
          )}
          {pulls.map((pull) => (
            <div className="github-repo-row" key={pull.number}>
              <span>#{pull.number}</span>
              <strong>{pull.title}</strong>
              <Button
                variant="outline"
                onClick={() =>
                  onSelect({
                    installation_id: selected.installation_id,
                    repository: selected.full_name,
                    number: pull.number,
                    title: pull.title,
                    requirement: pull.body || pull.title,
                    base: pull.base,
                    head: pull.head,
                  })
                }
              >
                Use pull request
                <ArrowRight size={14} />
              </Button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
