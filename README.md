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

Add `--details` to `decompose` to save context, review questions, proposed assumptions, and decomposer provenance alongside the criteria. `analyze --criteria` accepts either this detailed export or the original criteria list. Review metadata is retained in the export; analysis consumes its criteria only. Model decomposition records the requested model, whether a request was attempted, elapsed milliseconds, and provider-reported token usage even if the proposal is rejected. Missing usage stays `null`; no monetary cost is inferred.

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

Authenticated `GET /v1/readiness` reports configuration-presence checks for the model identifier/credential, GitHub App ID/key file, the caller's installation assignment, and webhook secret. It returns booleans only, without credentials or paths. This is a configuration check: key validity, file readability, provider access, billing, and external service health are not verified. Webhook configuration is separate from manual analysis.

Authenticated `GET /v1/metrics` returns process-local request counts, server-error counts, and mean/max elapsed milliseconds grouped by HTTP method, route template, and status class. Unknown paths share one bucket; excess groups share an overflow bucket. Counters reset on restart and are not aggregated across workers. This local-workspace endpoint is not a multi-tenant metrics service.

Responses passing through the request middleware include a generated `X-Request-ID`; incoming IDs are ignored. Enable the `specguard.requests` logger at INFO through your Python/Uvicorn logging configuration for JSON completion records. They contain the generated ID, method, route template, status, duration, and failure flag, without bodies, queries, raw paths, headers, or exception text. These controls apply to SpecGuard's logger only: Uvicorn/proxy logs require separate configuration (`--no-access-log` disables Uvicorn access logs). Unhandled failures outside response middleware may lack the response header but still receive a completion record. Timing covers the ASGI request lifecycle, not separate indexing/retrieval/model stages.

## Review workflow

1. Select a local repository and committed base/head revisions.
2. Paste requirements, decompose explicit lists, and edit each criterion. Wrapped lines and nested bullets stay with their parent criterion; Markdown task markers are removed. Review the resulting contract before analysis. The criteria API also returns introductory context, the decomposer version, and review questions for prose, duplicates, and nested conditions; it does not invent assumptions.
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

For model-assisted requirement decomposition, pass `--model` to `specguard decompose`, or send `use_model: true` to `POST /v1/criteria`. This sends requirement text to the configured provider; the web decomposition button continues to use the offline parser. Proposed criteria must quote exact source text. Invalid responses, provider errors, and recognizable secrets fall back to the offline parser with a review message. Exact quotes establish provenance, not semantic correctness: review the original requirement, proposed assumptions, and clarification questions before analysis. Requests have a 45-second network timeout, a 3,000-token output limit, and a 100 KB response limit; no automatic retries are made.

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

### Verdict evaluation against reviewed labels

Prepare an unreviewed template with `uv run python scripts/prepare_labels.py run.json --group owner/repository --output labels.json`. It accepts a raw saved run or API export and refuses to overwrite an existing file. Fill in the split, expected verdict, reviewer, origin, license, and annotation status; mark each citation `true`/`false` or remove it if unjudged. The draft deliberately fails evaluation until completed. Model predictions remain in the saved run for comparison but are never copied into reference labels; feedback notes are excluded. Use one stable repository group across cases, and combine completed runs/labels into one manifest for aggregate evaluation.

Run `uv run python scripts/evaluate_verdicts.py labels.json --output .specguard/verdict-report.json` to evaluate saved results without calling a model. The manifest contains `version`, `annotation_status` (`synthetic`, `human_reviewed`, or `human_adjudicated`), `runs` (full exported `AnalysisRun` objects), and `labels`. For API exports, use the `run` object inside each export. Each label requires:

```json
{"run_id":"saved-run-id","criterion_id":"saved-criterion-id","group":"repository-identity","split":"test","expected":"satisfied","reviewer":"reviewer-id","source":"case-origin","license":"MIT","citation_correctness":{"evidence-id":true}}
```

Use the actual case license and origin. Supply exactly one final label per saved criterion; reconcile multiple reviewers separately before declaring adjudication. Keep all cases from the same repository group in one split (`development` or `test`). Citation judgments are optional, must refer to the result's evidence IDs, and mean that a reviewer checked whether that citation supports the associated verdict. Omitted judgments remain unknown, not correct. Annotation status and reviewer provenance are declarations, not automatically certified facts.

Reports contain a confusion matrix (expected rows, predicted columns), per-class precision/recall/F1, four-class macro-F1, accuracy, non-abstaining answer coverage/risk, citation correctness and judgment coverage, and confidence-threshold coverage/risk. Undefined ratios are `null`; undefined class F1 contributes zero to macro-F1. Threshold curves exclude abstentions and answers without confidence; the missing-confidence count is explicit. These curves measure observed error, not calibration. Run duration, known token/cost totals, and missing-usage counts are reported separately for each split.

The 20 MB input limit bounds CLI manifests. Reports include an input fingerprint and omit requirement text, citations, and reviewer identities. Source-bearing manifests should remain private. The metric tests use synthetic labels with hand-calculated expected values; no human-reviewed verdict benchmark or real-world accuracy result is bundled. Choose thresholds on development data before inspecting test results.

### Independent review and adjudication

Two completed label manifests can be compared before settling on final reference labels:

```sh
uv run python scripts/compare_reviews.py reviewer-a.json reviewer-b.json --output agreement.json
uv run python scripts/compare_reviews.py reviewer-a.json reviewer-b.json --template --output decisions.json
uv run python scripts/compare_reviews.py reviewer-a.json reviewer-b.json --decisions decisions.json --output adjudicated.json
uv run python scripts/evaluate_verdicts.py adjudicated.json
```

The first command reports per-split verdict agreement, unweighted Cohen's kappa, citation agreement among jointly judged citations, and a disagreement queue identified by run/criterion IDs. Missing citation judgments are counted separately and never treated as negative judgments. Perfect single-class agreement yields `null` kappa because chance agreement is also one. Agreement is not accuracy, and the tool cannot establish reviewer independence beyond checking distinct identifiers.

Both reviews must cover exactly the same runs, criteria, evidence, repository groups, splits, origins, and licenses. Saved-run creation timestamps may differ; source and prediction contents must match. Reports omit source text and reviewer names, but identifiers and review decisions can still be sensitive. Keep source-bearing input manifests private.

The template binds both input files with fingerprints and leaves every final verdict and adjudicator identifier blank, including cases where reviewers agree. Fill every decision, choose `synthetic` or `human_adjudicated` annotation status, and add explicit citation judgments where reviewed; omitted judgments remain unknown. The apply command rejects stale inputs, missing/duplicate decisions, changed provenance, or promotion of synthetic inputs to human adjudication. The final manifest is directly accepted by the verdict evaluator. Input files are limited to 20 MB each and output files must be new, so existing review work is not overwritten.

### Offline hybrid retrieval experiments

The evaluation CLI can compare both sparse baselines with cosine-similarity retrieval and reciprocal-rank fusion (RRF). Production analysis still uses BM25. Export the exact queries and source documents for an embedding model you run separately:

```sh
uv run python scripts/evaluate.py --export-inputs .specguard/embedding-inputs.json
uv run python scripts/evaluate.py --embeddings .specguard/vectors.json --window 50 --rrf-k 60 --output .specguard/hybrid-report.json
```

The input export maps SHA-256 keys to UTF-8 texts. Encode each text with the same model and pinned revision, retaining its key. Supply a JSON bundle with `model`, `revision`, `dimensions`, and `vectors` (a mapping from those keys to numeric arrays). Document text is exactly `path + "\n" + symbol + "\n" + quote`; query text is unchanged. Hashes prevent reuse for changed text. Exports contain source code: keep them local unless you explicitly choose a provider. No embedding service is called by these commands.

Bundles must contain finite, nonzero, equal-dimensional vectors. Missing inputs fail explicitly. The CLI caps bundles at 20 MB. Dense ranking includes positive cosine scores only; fusion gives each ranking a contribution of `1 / (rrf_k + rank)` within the candidate window. Ties are deterministic, and original source citations are preserved. Reports retain split-level Recall@K, MRR and nDCG, per-case rankings, fusion contributions, model/revision, parameters, and a bundle fingerprint.

Choose model and fusion parameters using development cases, then evaluate the frozen test split. The supplied tests use explicitly synthetic vectors to verify mechanics; they do not establish learned-model quality. Encoding, training, reranking, and a human-reviewed semantic benchmark remain separate work.

- GitHub operations have offline contract coverage; live credentials, installation configuration, and end-to-end provider validation are still required. OAuth self-service is not included.
- The default verifier always abstains. Model-backed verdicts have contract tests but no live-provider evaluation yet.
- Production retrieval is BM25 with explicit boosts. Offline vector-bundle experiments support dense retrieval and hybrid fusion; a bundled learned encoder, reranking, fine-tuning, and a human-adjudicated benchmark are not included yet. Metric functions are tested; no general retrieval-quality or reviewer-time claims are made.
- Unambiguous relative import paths are resolved. Package exports, aliases, dynamic imports, and runtime call graphs remain unresolved; the neighborhood is a syntactic approximation.
- Deleted source is absent from the head index, and no negative verdict is inferred from its absence. Oversized repositories can omit useful supporting context.
- SQLite and PostgreSQL persistence are implemented. Public multi-user authentication, pgvector, deployment, scheduled retention, and operational monitoring remain pending.
- No test execution sandbox, automatic merge blocking, or formal verification is provided.

## License

MIT. See [LICENSE](LICENSE).
