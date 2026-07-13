# MOT CLI reference

Complete reference for `mot` commands, options, limits, and operational details.
For setup, configuration, and an end-to-end walkthrough, see the [README](../README.md).

Examples assume the local uv environment from the README's Setup section, with
`UV_CACHE_DIR=.uv-cache` and `UV_PYTHON_INSTALL_DIR=.uv-python` exported in the
current shell. When `mot` is installed as a standalone tool (`uv tool install`),
replace `uv run mot` with `mot`.

## Contents

- [Output file naming convention](#output-file-naming-convention)
- [Evidence collectors](#evidence-collectors)
- [Assessment commands](#assessment-commands)
- [Following linked sources](#following-linked-sources)
- [LLM-assisted extraction](#llm-assisted-extraction)
- [Human review queue](#human-review-queue)
- [Exporting reviewed MOT YAML](#exporting-reviewed-mot-yaml)
- [API service and durable jobs](#api-service-and-durable-jobs)

## Output file naming convention

The CLI does not impose output names — `--output` accepts any path. The examples in
this documentation follow one consistent scheme, recommended for your own runs:

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

## Evidence collectors

Each collector produces a pinned, bounded JSON evidence snapshot.

### `mot collect` — Hugging Face model repository

A revision-pinned snapshot without downloading model weights:

```bash
uv run mot collect openai-community/gpt2 --output evidence-hf-gpt2.json
```

For gated repositories, put the token in `HF_TOKEN` or name a different environment
variable with `--token-env`. Do not pass tokens as command-line arguments.
Model-card evidence reports also list normalized linked GitHub repositories, Hugging
Face datasets/models, papers, and documentation candidates.

### `mot collect-github` — GitHub repository

A pinned file manifest without cloning or executing the repository:

```bash
uv run mot collect-github https://github.com/openai/gpt-2 \
  --output evidence-github-openai-gpt-2.json
```

To inspect a source repository with GitHub-identified SPDX license metadata:

```bash
uv run mot collect-github https://github.com/huggingface/transformers \
  --output evidence-github-transformers.json
```

Use `GITHUB_TOKEN` for private repositories or higher API limits, or select another
environment variable with `--token-env`. Tokens are never accepted as CLI values or
written to reports.

When GitHub does not report an SPDX identifier, the repository's root license text can
supply evidence:

```bash
uv run mot collect-github https://github.com/openai/gpt-2 \
  --output evidence-github-openai-gpt-2-license.json
```

The connector retrieves only pinned root `LICENSE`/`COPYING` text variants, capped at
128,000 bytes each. Deterministic full-text matching currently recognizes MIT,
Apache-2.0, and BSD-3-Clause. Unknown, abbreviated, custom, or conflicting license
text remains review-required.

### `mot collect-dataset` — Hugging Face dataset

A revision-pinned dataset manifest and bounded dataset-card/license files without
downloading released data:

```bash
uv run mot collect-dataset https://huggingface.co/datasets/openai/gsm8k \
  --output evidence-dataset-gsm8k.json
```

### `mot collect-paper` — arXiv or DOI paper

Bounded paper metadata without downloading a paper PDF. arXiv papers are
version-pinned by their arXiv version, while DOI papers are content-addressed from
Crossref metadata:

```bash
uv run mot collect-paper 1810.04805 --output evidence-paper-bert.json
```

```bash
uv run mot collect-paper https://doi.org/10.18653/v1/N19-1423 \
  --output evidence-paper-bert-doi.json
```

### `mot collect-pdf` — public PDF

Bounded, content-addressed text from a public PDF:

```bash
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

### `mot collect-doc` — public documentation page

A bounded, content-addressed snapshot of a public documentation page:

```bash
uv run mot collect-doc https://huggingface.co/docs/transformers/model_doc/bert \
  --output evidence-doc-bert.json
```

The connector accepts bounded public HTTP(S) text, Markdown, and HTML, validates
redirects, blocks local or non-public literal addresses, strips active HTML content,
and identifies the captured revision by its content hash. A retrievable generic page
is retained as review evidence but does not automatically satisfy any MOF component.

Documentation collection also emits deterministic, cited artifact mentions:

```bash
uv run mot collect-doc https://huggingface.co/docs/transformers/training \
  --output evidence-doc-transformers-training.json
```

Documentation and PDF text can emit line-cited `artifact_mentioned` evidence for
explicit phrases such as training code, preprocessing pipeline, training dataset,
checkpoints, and evaluation results. These findings remain `mentioned_only`: they do
not prove that an artifact is released, do not enter the potential score, and cannot
satisfy a MOF component.

## Assessment commands

### `mot assess` — assess saved evidence

Create a provisional assessment from a saved collection report:

```bash
uv run mot assess evidence-hf-gpt2.json --repository-root .. \
  --output assessment-gpt2.json
```

### `mot evaluate` — collect and assess in one command

```bash
uv run mot evaluate openai-community/gpt2 --repository-root .. \
  --output evaluation-gpt2.json
```

Automated results distinguish a conservative confirmed score from an
evidence-supported potential score. Model-card mentions and unknown components never
enter the potential score, and ambiguous license scope prevents an automated result
from being labeled verified.

## Following linked sources

Sources discovered in a model card can be followed and merged into the provisional
assessment. All following is **opt-in**, follows at most three unique sources per type
by default, and has a hard CLI limit of ten. Linked evidence can raise only the
evidence-supported potential score; human review is still required before any verified
classification.

### `--follow-github`

Follow up to three discovered GitHub repositories and merge their pinned source
evidence:

```bash
uv run mot evaluate openai-community/gpt2 --repository-root .. \
  --follow-github --output evaluation-gpt2-linked-github.json
```

Deterministic source rules detect explicit architecture, training, inference,
evaluation, preprocessing, and dependency filenames while excluding test directories.
When GitHub identifies the repository license, its SPDX ID is attached only to the
matched source-code components.

### `--follow-datasets`

Follow structured dataset references and dataset links discovered in the model card:

```bash
uv run mot evaluate distilbert/distilbert-base-uncased-finetuned-sst-2-english \
  --repository-root .. --follow-datasets \
  --output evaluation-distilbert-sst2-linked-datasets.json
```

Dataset manifests can prove that released data and a data card exist, while exact
training use, provenance, preprocessing, and license applicability remain review
questions. When several linked datasets declare different licenses, the combined
component license is reported as ambiguous rather than selecting one automatically.

### `--follow-papers`

Follow arXiv papers discovered in the model card:

```bash
uv run mot evaluate google-bert/bert-base-uncased --repository-root .. \
  --follow-papers --output evaluation-bert-linked-papers.json
```

Paper following covers arXiv, DOI, or generic PDF sources. A resolved arXiv or DOI
paper can prove only the Research paper component. Its metadata does not prove that a
separate technical report, source code, data, or evaluation artifact has been
released. A generic PDF is retained as neutral review evidence and does not
automatically satisfy any MOF component.

### `--follow-documentation`

Follow documentation pages discovered in the model card:

```bash
uv run mot evaluate google-bert/bert-base-uncased --repository-root .. \
  --follow-documentation --output evaluation-bert-linked-docs.json
```

## LLM-assisted extraction

### `mot extract-llm`

Request schema-validated LLM evidence proposals from an OpenAI-compatible endpoint:

```bash
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

### `mot llm-eval`

Run the versioned five-case LLM extraction evaluation against the configured endpoint:

```bash
uv run mot llm-eval tests/fixtures/llm-evaluation-v1.json \
  --output report-llm-eval.json
```

The command reads `OPENAI_BASE_URL` and optional `OPENAI_API_KEY`, uses the same
strict schema and citation validator as `extract-llm`, and exits nonzero when the gate
fails while still writing the complete report. The initial gate requires all five
cases to complete, at least one true positive, at least 95% precision, 100% raw
citation validity, and zero LLM-only status promotions. Recall is reported but is not
yet a release gate.

## Human review queue

### `mot review-import` — import LLM proposals

Import citation-validated LLM proposals into the local SQLite review queue and list
its current state:

```bash
uv run mot review-import proposals-transformers-training.json
uv run mot review-list
```

### `mot review-import-run` — import evaluation evidence

Import the deterministic evidence from a saved evaluation run into the append-only
review queue:

```bash
uv run mot review-import-run evaluation-gpt2.json --database .mot/review-gpt2.db
uv run mot review-list --database .mot/review-gpt2.db --status pending
```

### `mot review-decide` — record a decision

Append a human decision using an evidence ID returned by `review-list`:

```bash
uv run mot review-decide <evidence-id> --decision accept \
  --reviewer <reviewer-id> --reason "Citation and component mapping verified."
```

When using a per-run database, pass the same `--database`:

```bash
uv run mot review-decide <evidence-id> --decision accept \
  --reviewer <reviewer-id> --reason "Verified against the pinned source." \
  --database .mot/review-gpt2.db
```

### Review database semantics

The default database is `.mot/review.db` and is ignored by Git. Imports are
idempotent. Review items and accept/reject events are immutable; a later decision
supersedes the current status without deleting the earlier audit event. Reviewer
identity is operator-supplied until Phase 5 adds authenticated API boundaries.

## Exporting reviewed MOT YAML

Export only accepted artifact claims from a reviewed evaluation as MOT-schema YAML:

```bash
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
uv run --env-file .env alembic upgrade head
```

### Start the FastAPI service

```bash
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
uv run --env-file .env mot job-submit openai-community/gpt2
uv run --env-file .env mot worker --once
uv run --env-file .env mot job-list
```

Recover running jobs abandoned beyond their heartbeat lease:

```bash
uv run --env-file .env mot job-recover --stale-seconds 3600
```

Manually requeue a terminally failed job with one additional allowed attempt:

```bash
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
