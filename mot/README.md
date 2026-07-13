# MOT Python Evaluator

This directory contains the Python implementation of the Model Openness Tool (MOT)
evaluator: an evidence-backed CLI and service for evaluating machine learning models
against the Model Openness Framework (MOF).

The current implementation includes the scoring-parity foundation (a deterministic
port of the existing MOT evaluator) plus a growing set of evidence collectors, the
first of which was the Hugging Face collector. The tool loads the versioned MOF
component catalog, reads the existing MOT license sources, evaluates existing MOT
YAML, and collects revision-pinned evidence from
Hugging Face, GitHub, datasets, papers, PDFs, and documentation pages — without
downloading model weights or released data. Automated results distinguish a
conservative **confirmed** score from an evidence-supported **potential** score.
Model-card mentions and unknown components never enter the potential score, and
ambiguous license scope prevents an automated result from being labeled verified.
Human review is always required before any verified classification.

## Contents

- [Requirements](#requirements)
- [Setup](#setup)
- [Configuration (`.env`)](#configuration-env)
- [CLI usage](#cli-usage)
  - [Output file naming convention](#output-file-naming-convention)
  - [Quick start: evaluate a model](#quick-start-evaluate-a-model)
  - [Collect evidence](#collect-evidence)
  - [Assess saved evidence](#assess-saved-evidence)
  - [Follow linked sources during evaluation](#follow-linked-sources-during-evaluation)
  - [LLM-assisted extraction (optional)](#llm-assisted-extraction-optional)
  - [Human review workflow](#human-review-workflow)
  - [Export reviewed MOT YAML](#export-reviewed-mot-yaml)
- [API service and durable jobs](#api-service-and-durable-jobs)
- [Agent Skill for coding agents](#agent-skill-for-coding-agents)

## Requirements

- Python 3.12+ and [`uv`](https://docs.astral.sh/uv/). The project is developed and
  tested only with a local `uv` environment.
- Optional, depending on which features you use:
  - Docker (PostgreSQL for the API service and durable jobs)
  - An externally provided MinerU VLM inference service (higher-fidelity PDF extraction)
  - An OpenAI-compatible endpoint (LLM-assisted evidence extraction)

A basic public-model evaluation needs none of the optional services and no `.env` file.

## Setup

All examples in this README keep uv's cache and Python installs local to this
directory. Either export the variables once per shell:

```bash
cd mot
export UV_CACHE_DIR=.uv-cache
export UV_PYTHON_INSTALL_DIR=.uv-python
```

or prefix each command with `UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python`
as the examples below do.

Create the environment, check the CLI, and run the tests:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv sync
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run mot --help
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run pytest
```

Alternatively, install `mot` as an isolated standalone CLI tool (no checkout required):

```bash
uv tool install \
  "git+https://github.com/atripathy86/model_openness_tool.git@main#subdirectory=mot"
mot version
mot catalog
```

Replace `main` with a tag or full commit SHA for a reproducible installation; use
`uv tool upgrade model-openness-tool` to upgrade, `uv tool dir --bin` if uv reports its
executable directory is not on `PATH`.

## Configuration (`.env`)

Create local configuration from the complete environment template:

```bash
cp example.env .env
```

The tracked `example.env` lists Hugging Face, GitHub, OpenAI-compatible, MinerU,
API-authentication, log-level, PostgreSQL, and SQLAlchemy variables. The populated
`.env` is local-only and ignored by Git. Pass it to commands with
`uv run --env-file .env ...`.

| Variable | Purpose |
| --- | --- |
| `HF_TOKEN` | Hugging Face token for gated or private repositories; public resources usually need no token |
| `GITHUB_TOKEN` | GitHub token for private repositories or higher API limits |
| `OPENAI_BASE_URL` | OpenAI-compatible endpoint for LLM extraction (`extract-llm`, `llm-eval`) |
| `OPENAI_API_KEY` | Key for that endpoint when authentication is required; optional for unauthenticated local endpoints, never persisted |
| `MINERU_SERVER_URL` | Externally provided MinerU VLM service for PDF collection (alternative to `--mineru-url`) |
| `MOT_API_BEARER_TOKEN` | API bearer authentication; blank or unset disables it |
| `MOT_LOG_LEVEL` | Verbosity of JSON worker/service logs (default `INFO`) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_PORT` | PostgreSQL container settings for `docker compose` |
| `DATABASE_URL` | SQLAlchemy connection URL used by migrations, the API service, and workers |

**Token handling:** put tokens in `HF_TOKEN` / `GITHUB_TOKEN` (or name a different
environment variable with `--token-env`). Do not pass tokens as command-line
arguments — tokens are never accepted as CLI values or written to reports. The
LLM endpoint can likewise be overridden at runtime with `--base-url` without placing a
deployment value in project documentation.

## CLI usage

### Output file naming convention

The CLI does not impose output names — `--output` accepts any path. The examples in
this README follow one consistent scheme, recommended for your own runs:

`<artifact>[-<source>]-<slug>[-<qualifier>].json`

- `<artifact>` — what the file contains: `evidence` (collectors), `assessment`
  (`assess`), `evaluation` (`evaluate`), `proposals` (`extract-llm`), `report`
  (`llm-eval`).
- `<source>` — for evidence files only, the connector that produced them: `hf`,
  `github`, `dataset`, `paper`, `pdf`, or `doc`.
- `<slug>` — a short lowercase identifier for the model, repository, or page (e.g.
  `gpt2`, `transformers`); include the owner when the name alone is ambiguous (e.g.
  `openai-gpt-2`).
- `<qualifier>` — optional detail, e.g. `-linked-github` / `-linked-datasets` /
  `-linked-papers` / `-linked-docs` for evaluations that followed linked sources,
  `-license` for a license-text collection, `-doi` for a DOI-resolved paper.

Review databases follow `.mot/review-<slug>.db`, and exported MOT YAML follows
`<slug>.mot.yml` (the file you would submit to the MOT repository).

### Quick start: evaluate a model

Collect and assess in one command:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate openai-community/gpt2 --repository-root .. \
  --output evaluation-gpt2.json
```

### Collect evidence

Each collector produces a pinned, bounded JSON evidence snapshot.

**Hugging Face model repository** — a revision-pinned snapshot without downloading
model weights:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect openai-community/gpt2 --output evidence-hf-gpt2.json
```

For gated repositories, put the token in `HF_TOKEN` or name a different environment
variable with `--token-env`. Model-card evidence reports also list normalized linked
GitHub repositories, Hugging Face datasets/models, papers, and documentation
candidates.

**GitHub repository** — a pinned file manifest without cloning or executing the
repository:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-github https://github.com/openai/gpt-2 \
  --output evidence-github-openai-gpt-2.json
```

To inspect a source repository with GitHub-identified SPDX license metadata:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-github https://github.com/huggingface/transformers \
  --output evidence-github-transformers.json
```

Use `GITHUB_TOKEN` for private repositories or higher API limits, or select another
environment variable with `--token-env`.

When GitHub does not report an SPDX identifier, the repository's root license text can
supply evidence:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-github https://github.com/openai/gpt-2 \
  --output evidence-github-openai-gpt-2-license.json
```

The connector retrieves only pinned root `LICENSE`/`COPYING` text variants, capped at
128,000 bytes each. Deterministic full-text matching currently recognizes MIT,
Apache-2.0, and BSD-3-Clause. Unknown, abbreviated, custom, or conflicting license
text remains review-required.

**Hugging Face dataset** — a revision-pinned dataset manifest and bounded
dataset-card/license files without downloading released data:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-dataset https://huggingface.co/datasets/openai/gsm8k \
  --output evidence-dataset-gsm8k.json
```

**Paper** — bounded paper metadata without downloading a paper PDF. arXiv papers are
version-pinned by their arXiv version, while DOI papers are content-addressed from
Crossref metadata:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-paper 1810.04805 --output evidence-paper-bert.json
```

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-paper https://doi.org/10.18653/v1/N19-1423 \
  --output evidence-paper-bert-doi.json
```

**PDF** — bounded, content-addressed text from a public PDF:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-pdf \
  https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf \
  --mineru-url http://127.0.0.1:30000 \
  --output evidence-pdf-dummy.json
```

PDF collection accepts at most 10 MB, sends at most the first 100 pages through the
uv-installed MinerU `vlm-http-client`, retains at most 500,000 Markdown characters,
validates source redirects, and blocks local or non-public literal source addresses.
Set `MINERU_SERVER_URL` instead of `--mineru-url` when preferred. The VLM service is
externally provided and MOT does not launch or download it.

When MinerU or its VLM service is unavailable, collection falls back to bounded
`pypdf` text extraction. The snapshot records `pypdf-fallback` and includes the MinerU
failure in its warnings, so lower-fidelity evidence is never silent. Pass
`--no-pdf-fallback` to require MinerU success.

The optional `--backend hybrid-http-client` mode requires installing
`mineru[pipeline]` into the same local uv environment. The default VLM client and
`pypdf` fallback do not require local Torch. Generic PDF Markdown or fallback text
remains neutral review evidence and cannot automatically satisfy a MOF component.

**Documentation page** — a bounded, content-addressed snapshot of a public
documentation page:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-doc https://huggingface.co/docs/transformers/model_doc/bert \
  --output evidence-doc-bert.json
```

The connector accepts bounded public HTTP(S) text, Markdown, and HTML, validates
redirects, blocks local or non-public literal addresses, strips active HTML content,
and identifies the captured revision by its content hash. A retrievable generic page
is retained as review evidence but does not automatically satisfy any MOF component.

Documentation collection also emits deterministic, cited artifact mentions:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-doc https://huggingface.co/docs/transformers/training \
  --output evidence-doc-transformers-training.json
```

Documentation and PDF text can emit line-cited `artifact_mentioned` evidence for
explicit phrases such as training code, preprocessing pipeline, training dataset,
checkpoints, and evaluation results. These findings remain `mentioned_only`: they do
not prove that an artifact is released, do not enter the potential score, and cannot
satisfy a MOF component.

### Assess saved evidence

Create a provisional assessment from a saved collection report:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot assess evidence-hf-gpt2.json --repository-root .. \
  --output assessment-gpt2.json
```

`mot evaluate` (see [Quick start](#quick-start-evaluate-a-model)) performs collection
and assessment in one command.

### Follow linked sources during evaluation

Sources discovered in a model card can be followed and merged into the provisional
assessment. All following is **opt-in**, follows at most three unique sources per type
by default, and has a hard CLI limit of ten. Linked evidence can raise only the
evidence-supported potential score; human review is still required before any verified
classification.

**GitHub repositories** (`--follow-github`) — follow up to three discovered GitHub
repositories and merge their pinned source evidence:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate openai-community/gpt2 --repository-root .. \
  --follow-github --output evaluation-gpt2-linked-github.json
```

Deterministic source rules detect explicit architecture, training, inference,
evaluation, preprocessing, and dependency filenames while excluding test directories.
When GitHub identifies the repository license, its SPDX ID is attached only to the
matched source-code components.

**Datasets** (`--follow-datasets`) — follow structured dataset references and dataset
links discovered in the model card:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate distilbert/distilbert-base-uncased-finetuned-sst-2-english \
  --repository-root .. --follow-datasets \
  --output evaluation-distilbert-sst2-linked-datasets.json
```

Dataset manifests can prove that released data and a data card exist, while exact
training use, provenance, preprocessing, and license applicability remain review
questions. When several linked datasets declare different licenses, the combined
component license is reported as ambiguous rather than selecting one automatically.

**Papers** (`--follow-papers`) — follow arXiv papers discovered in the model card:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate google-bert/bert-base-uncased --repository-root .. \
  --follow-papers --output evaluation-bert-linked-papers.json
```

Paper following covers arXiv, DOI, or generic PDF sources. A resolved arXiv or DOI
paper can prove only the Research paper component. Its metadata does not prove that a
separate technical report, source code, data, or evaluation artifact has been
released. A generic PDF is retained as neutral review evidence and does not
automatically satisfy any MOF component.

**Documentation pages** (`--follow-documentation`) — follow documentation pages
discovered in the model card:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate google-bert/bert-base-uncased --repository-root .. \
  --follow-documentation --output evaluation-bert-linked-docs.json
```

### LLM-assisted extraction (optional)

Request schema-validated LLM evidence proposals from an OpenAI-compatible endpoint:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot extract-llm evidence-doc-transformers-training.json \
  --output proposals-transformers-training.json
```

Set `OPENAI_BASE_URL` for the OpenAI-compatible endpoint and, when authentication is
required, set `OPENAI_API_KEY`. The key is optional for unauthenticated local
endpoints and is never persisted. `--base-url` can override the environment at runtime
without placing a deployment value in project documentation. If `--model` is omitted,
MOT discovers the first model reported by the endpoint. Provider output must pass the
extraction schema and exact line-citation validation. Accepted proposals are recorded
only as review-required `artifact_mentioned` evidence; rejected citations remain
visible in the report, and no LLM proposal directly affects a MOF score.

Run the versioned five-case LLM extraction evaluation against the configured endpoint:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot llm-eval tests/fixtures/llm-evaluation-v1.json \
  --output report-llm-eval.json
```

The command reads `OPENAI_BASE_URL` and optional `OPENAI_API_KEY`, uses the same
strict schema and citation validator as `extract-llm`, and exits nonzero when the gate
fails while still writing the complete report. The initial gate requires all five
cases to complete, at least one true positive, at least 95% precision, 100% raw
citation validity, and zero LLM-only status promotions. Recall is reported but is not
yet a release gate.

### Human review workflow

Import citation-validated LLM proposals into the local SQLite review queue and list
its current state:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot review-import proposals-transformers-training.json
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot review-list
```

Or import the deterministic evidence from a saved evaluation run:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot review-import-run evaluation-gpt2.json --database .mot/review-gpt2.db
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot review-list --database .mot/review-gpt2.db --status pending
```

Append a human decision using an evidence ID returned by `review-list`:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot review-decide <evidence-id> --decision accept \
  --reviewer <reviewer-id> --reason "Citation and component mapping verified."
```

When using a per-run database, pass the same `--database`:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot review-decide <evidence-id> --decision accept \
  --reviewer <reviewer-id> --reason "Verified against the pinned source." \
  --database .mot/review-gpt2.db
```

The default database is `.mot/review.db` and is ignored by Git. Imports are
idempotent. Review items and accept/reject events are immutable; a later decision
supersedes the current status without deleting the earlier audit event. Reviewer
identity is operator-supplied until Phase 5 adds authenticated API boundaries.

### Export reviewed MOT YAML

Export only accepted artifact claims from a reviewed evaluation as MOT-schema YAML:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot export-mot-yaml evaluation-gpt2.json \
  --database .mot/review-gpt2.db --output gpt2.mot.yml
```

`export-mot-yaml` considers only accepted evidence imported from that exact evaluation
snapshot. Accepted `artifact_mentioned` claims never create components. An accepted
`artifact_exists` claim creates a component; without an accepted component-scoped
`license_declared` claim, the component is explicitly exported as `unlicensed`.
Conflicting accepted component licenses stop export for review. Existing output files
are never overwritten. The YAML remains deliberately limited to the existing MOT
schema; evidence, reviewer identity, rationale, and audit timestamps stay in the
review database and evaluation report.

## API service and durable jobs

Prefect is intentionally deferred; durable jobs and the worker loop use the PostgreSQL
service boundary, and Prefect is not required.

### Start PostgreSQL and apply migrations

```bash
cp example.env .env
docker compose --env-file .env up -d postgres
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run --env-file .env alembic upgrade head
```

### Start the FastAPI service

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run --env-file .env uvicorn model_openness_tool.api:app_factory --factory
```

`/health` reports process health without requiring PostgreSQL. `/ready` reports ready
only when `DATABASE_URL` is configured and the database probe succeeds. Versioned
routes are unauthenticated when `MOT_API_BEARER_TOKEN` is unset or blank. When
configured, callers must send that value as a bearer token. Health and readiness
remain public.

### Durable evaluation jobs

Submit a durable evaluation job, process one queued job, and inspect current state:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run --env-file .env mot job-submit openai-community/gpt2
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run --env-file .env mot worker --once
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run --env-file .env mot job-list
```

Recover running jobs abandoned beyond their heartbeat lease:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run --env-file .env mot job-recover --stale-seconds 3600
```

Manually requeue a terminally failed job with one additional allowed attempt:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run --env-file .env mot job-retry <job-id>
```

Workers claim queued jobs with PostgreSQL `FOR UPDATE SKIP LOCKED`, record attempts
and worker identity, refresh a running-job heartbeat, and retry unexpected failures
with bounded exponential delays before terminal failure. Worker lifecycle events are
emitted as JSON logs to standard error; set `MOT_LOG_LEVEL` to control verbosity. Each
worker performs stale-job recovery at startup, and operators can run `mot job-recover`
independently. Use `mot worker --loop` for continuous polling.

### Job HTTP API

The API also exposes `POST /v1/jobs`, `GET /v1/jobs`, `GET /v1/jobs/{job_id}`, and
`POST /v1/jobs/{job_id}/retry` under the same optional bearer-authentication boundary.
Job listings return an opaque `next_cursor`; pass it back as the `cursor` query
parameter to fetch the next stable page. Manual retry is limited to terminally failed
jobs, preserves the job ID and attempt count, and grants exactly one additional
attempt.

## Agent Skill for coding agents

An Agent Skills specification-compatible workflow is available at
[`../skill/mot`](../skill/mot). Install only the `mot` skill from this repository into
Codex, Claude Code, GitHub Copilot CLI, or another client supported by the `skills`
installer:

```bash
npx skills add https://github.com/atripathy86/model_openness_tool --skill mot
```

The skill is a self-contained operating guide that installs the MOT CLI from this fork
with `uv tool install` when authorized, or uses a user-supplied MOT checkout. It
verifies the installed version and catalog, creates a user-selected workspace,
explains optional `.env` configuration, asks for evaluation scope and source limits,
runs the CLI in a safe sequence, interprets cumulative MOF Class III/II/I
requirements, and guides human review and YAML export. It does not modify MOT source
code or bundle credentials and services.

The skill's default CLI setup sequence is:

```bash
uv tool install \
  "git+https://github.com/atripathy86/model_openness_tool.git@main#subdirectory=mot"
mot version
mot catalog
```

It also documents SSH installation, commit-pinned installation, upgrades, PATH
discovery, and checkout-based execution.

Validate the skill locally with:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python UV_TOOL_DIR=.uv-tools \
  uvx --from skills-ref agentskills validate ../skill/mot
```

The repository does not vendor the validator. The official package is named
`skills-ref`; its current CLI executable is `agentskills`.
