# SpecGuard

Requirement-to-code review for JavaScript and TypeScript changes. SpecGuard turns an explicit acceptance list into editable criteria, retrieves committed source, and presents exact file-and-line evidence alongside a conservative assessment.

The current release is a **local development preview**. It includes a working CLI, authenticated FastAPI service, persisted review history, and a Next.js interface. The opening dashboard is an explicitly labeled illustrative review; analyze a repository to replace it with real results.

## Run locally

Install Git, Node.js 22.16 or newer, and [uv](https://docs.astral.sh/uv/). Python 3.12 is selected by `.python-version`. Run commands from this repository's root:

```sh
npm ci
uv sync --locked
uv run python scripts/demo.py .specguard/checkout
uv run specguard analyze .specguard/checkout --base HEAD~1 --requirement .specguard/checkout/requirement.txt
```

The offline baseline retrieves source and returns `not_verifiable`. It does not infer behavior from keyword matches, execute repository code, or label a test as passed because a test definition exists.

Review and edit decomposed criteria before analysis:

```sh
uv run specguard decompose .specguard/checkout/requirement.txt --output .specguard/criteria.json
uv run specguard analyze .specguard/checkout --base HEAD~1 --requirement .specguard/checkout/requirement.txt --criteria .specguard/criteria.json --json
```

For another repository, supply its local path and the base/head revisions to compare. Only committed source is read; uncommitted changes are excluded.

### Web workspace

In a PowerShell terminal:

```powershell
$env:SPECGUARD_REPOSITORY_ROOT = (Resolve-Path '.specguard').Path
$env:SPECGUARD_API_TOKEN = (uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')
Write-Output $env:SPECGUARD_API_TOKEN
uv run uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

Keep the token private. In another terminal:

```sh
npm run dev --workspace @specguard/web
```

Open [the local workspace](http://127.0.0.1:3000), go to **Workspace settings**, and enter the API token. It remains in browser memory until the page reloads. Under **Repositories**, discover the `checkout` fixture, select **Analyze repository**, and review the criteria before running analysis.

On macOS/Linux, use `export SPECGUARD_REPOSITORY_ROOT="$PWD/.specguard"` and `export SPECGUARD_API_TOKEN="$(uv run python -c 'import secrets; print(secrets.token_urlsafe(32))')"` before starting the same API command.

Both servers are intended to run on loopback. This preview is not a public multi-user deployment. A single configured API token identifies the local workspace. Set `SPECGUARD_OWNER_ID` to a stable workspace identifier before creating runs to preserve ownership when rotating the token. Without it, ownership is derived from the token for backward compatibility.

## Review workflow

1. Select a local repository and committed base/head revisions.
2. Paste requirements, decompose explicit lists, and edit each criterion. Wrapped lines and nested bullets stay with their parent criterion; Markdown task markers are removed. Review the resulting contract before analysis.
3. Run offline retrieval or explicitly select the configured model verifier.
4. Inspect criterion evidence, inference, uncertainty, and execution status separately.
5. Save reviewer notes, revisit history, export results and notes as JSON, or copy a report preview.
6. Delete a saved run to remove its results and reviewer notes from the application database.

The interface supports four verdicts:

| Verdict | Meaning |
| --- | --- |
| Satisfied | Cited source supports the complete criterion as an inference. |
| Partially satisfied | Cited source supports some behavior and an identifiable limitation. |
| Not satisfied | Cited source establishes an incompatible or incomplete implementation. |
| Not verifiable | Available evidence cannot establish the answer. |

All non-abstaining verdicts require evidence. Quotes are checked against committed source before a run is accepted. Exact citations establish provenance, **not semantic correctness**: a model can still misinterpret valid source.

## Optional model verification

Set `SPECGUARD_MODEL` to an available model identifier and `SPECGUARD_MODEL_KEY` to its provider credential in the API process, then choose the model option in the web workspace or pass `--model` to the CLI. The adapter currently uses the OpenAI Chat Completions endpoint with structured JSON responses. No credential is needed for offline analysis or tests.

Selecting model mode transmits the criterion and selected repository snippets to the provider. Provider credentials are not persisted by SpecGuard. Model responses must reference supplied evidence IDs; malformed responses, unknown citations, and provider failures downgrade to abstention. Model confidence is uncalibrated and separate from test status. Token usage records provider-reported totals when available and becomes unknown (`null`) if a call's usage cannot be established. Cost remains unknown rather than estimated from unspecified pricing.

Repository content is delimited as untrusted data in the verifier contract. This reduces instruction confusion but is not a claim that prompt injection is solved. Outbound screening withholds an entire evidence packet when it recognizes private-key headers, common credential formats, literal secret assignments, or the configured provider key. The criterion abstains with an explanation. Screening can miss unknown secret formats and can produce false positives; review source before selecting model mode. Local citations remain exact and may contain sensitive text, so protect exports and the database. Responses are streamed with a 100 KB output limit.

## Configuration

Variables are read from the process environment. `.env.example` is a reference, not automatically loaded by the Python API.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SPECGUARD_REPOSITORY_ROOT` | `.` | Allowed root for local repository selection. |
| `SPECGUARD_DATABASE` | `.specguard/runs.sqlite3` | Local result and feedback database. |
| `SPECGUARD_DATABASE_URL` | Unset | Optional SQLAlchemy PostgreSQL URL (`postgresql+psycopg://...`); overrides the local file. |
| `SPECGUARD_OWNER_ID` | Token hash | Stable workspace ownership across credential rotation. |
| `SPECGUARD_API_TOKEN` | Unset | Required bearer token for all analysis endpoints. |
| `SPECGUARD_MODEL` | Unset | Explicit model identifier for optional verification. |
| `SPECGUARD_MODEL_KEY` | Unset | Provider credential, held by the API process. |
| `SPECGUARD_GITHUB_APP_ID` | Unset | GitHub App identifier. |
| `SPECGUARD_GITHUB_PRIVATE_KEY_FILE` | Unset | Private key path outside this checkout; never sent to the browser. |
| `SPECGUARD_GITHUB_INSTALLATIONS` | Unset | Comma-separated installation IDs assigned by the server operator to this workspace. |
| `SPECGUARD_GITHUB_WEBHOOK_SECRET` | Unset | Shared secret for raw-body HMAC verification. |

Runs include source quotes, requirements, revision IDs, and version metadata. Protect the database as source code. Deletion removes application records, dependent feedback, and publication audit records; it does not delete an already published GitHub comment. Authenticated `DELETE /v1/retention?days=30` removes this workspace's runs older than 30 days. Retention is explicitly invoked, not scheduled. Secure disk erasure and backup expiration remain the operator's responsibility.

### GitHub pull requests

Create and install a GitHub App with repository **Contents: read**, **Issues: read**, and **Pull requests: read/write** permissions (write is required only for report publishing). Keep installation scope limited to selected repositories. Configure the App ID, private key file, installation IDs, and webhook secret on the API process. Private keys are read from that protected file; short-lived installation tokens are held only in memory and are not stored in the database.

In **Repositories**, load GitHub repositories, select a pull request, and review the requirement and criteria. Source is read at the recorded head revision. The issue import API (`POST /v1/github/issue`) can fetch issue text for the selected repository. No checkout or package script is executed.

Open **Report preview**, supply the authorized installation ID, load the server preview, then explicitly confirm publishing. The server checks repository access and rejects a stale head revision before writing the comment. Repeated publishing of a recorded run returns its existing comment. Webhooks at `/v1/github/webhook` validate signatures and persist delivery IDs for deduplication; they never trigger analysis. GitHub does not sign an event timestamp, so signature verification alone cannot establish freshness of a previously unseen delivery.

This integration uses operator-assigned installations in a single-user workspace. Self-service OAuth and public multi-user hosting are not implemented. Contract tests use synthetic GitHub responses; a live installation must be validated before operational use.

### Database migrations

SQLite is the default. For PostgreSQL, set `SPECGUARD_DATABASE_URL` and run `uv run alembic upgrade head` before starting the API. The initial migration creates runs, feedback, installation assignments, webhook receipts, and publication records. Run payloads retain the versioned analysis contract, and related rows use foreign keys with cascading deletion.

For an existing preview SQLite database, back it up, start the updated API once to create the additional tables, then run `uv run alembic stamp head` against that same database URL. Do not stamp an unrelated or incomplete database. CI migrates a fresh PostgreSQL 16 database and checks persistence, owner isolation, feedback updates, and deletion.

## Architecture

```text
apps/web             Next.js workspace and local API proxy
services/api         FastAPI transport, authentication, SQLAlchemy persistence
services/analysis    Contracts, Git adapter, BM25, verification, CLI
services/integrations GitHub App transport, webhooks, manual report publishing
infrastructure       Versioned database migrations
indexing             TypeScript compiler AST extraction
tests                Committed fixtures and contract/security tests
scripts/demo.py      Repeatable local fixture creation
```

The API calls the analysis layer; domain code has no dependency on HTTP or storage. The Git adapter reads objects without checking out or executing reviewed code. A Node process parses bounded source using the TypeScript compiler API. BM25 retrieves symbol-sized chunks, with changed-span and symbol boosts. SQLite or PostgreSQL stores validated results transactionally. Repeated identical inputs reuse a stored run before verifier calls, after rebuilding the source index to establish revision identity.

Budgets: 50 criteria, 200 source files, 100 KB per source file, and 2 MB total source per run. Generated/dependency paths, declarations, non-UTF-8 files, symlinks, and syntax-invalid source are omitted. Changed files are considered first. Relative imports are resolved only when the indexed target is unambiguous; a one-hop neighborhood of at most 30 files receives a small ranking boost when lexical evidence also matches. Scores expose BM25, change, symbol, and import-neighbor contributions in exports. A verifier call has a 45-second timeout; later criteria abstain once the inference time budget is reached. The API allows at most two concurrent analyses.

## Development

```sh
npm run check
npm run build --workspace @specguard/web
```

The checks cover formatting, Python lint/type checking, AST spans, retrieval metrics, invalid verdict states, fabricated model citations, revision/path handling, authentication, owner isolation, and the local analysis lifecycle. Tests use synthetic repositories and model responses and require no external credentials. CI runs on Linux; the local workflow also runs on Windows.

## Current limits

Reproduce the synthetic retrieval regression benchmark with `uv run python scripts/evaluate.py`. The report is written to `.specguard/retrieval-report.json`. Ten MIT-licensed toy cases are separated into six development and four test groups, with no group shared between splits. Both ranking variants achieve Recall@3 of 1.0 on these fixtures; import-neighbor boosts improve the four-case test MRR from 0.625 to 1.0. These deliberately small fixtures test ranking mechanics, not general retrieval quality. They are not human-adjudicated and do not measure verdict correctness, calibration, or reviewer time.

- GitHub operations have offline contract coverage; live credentials, installation configuration, and end-to-end provider validation are still required. OAuth self-service is not included.
- The default verifier always abstains. Model-backed verdicts have contract tests but no live-provider evaluation yet.
- Retrieval is BM25 with explicit boosts. Learned embeddings, reranking, fine-tuning, and a human-adjudicated benchmark are not included yet. Metric functions are tested; no retrieval-quality or reviewer-time claims are made.
- Unambiguous relative import paths are resolved. Package exports, aliases, dynamic imports, and runtime call graphs remain unresolved; the neighborhood is a syntactic approximation.
- Deleted source is absent from the head index, and no negative verdict is inferred from its absence. Oversized repositories can omit useful supporting context.
- SQLite and PostgreSQL persistence are implemented. Public multi-user authentication, pgvector, deployment, scheduled retention, and operational monitoring remain pending.
- No test execution sandbox, automatic merge blocking, or formal verification is provided.

## License

MIT. See [LICENSE](LICENSE).
