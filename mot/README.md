# MOT Python Evaluator

This directory contains the Python implementation of the Model Openness Tool (MOT)
evaluator: an evidence-backed CLI and service for evaluating machine learning models
against the Model Openness Framework (MOF).

## The MOF, and how MOT helps

The [Model Openness Framework](https://lfaidata.foundation/wp-content/uploads/sites/3/2025/01/05_White_paper_MOF_Specification.pdf)
classifies machine learning models by both **completeness** (which of 16 code, data,
and documentation components are included in a model distribution) and **openness**
(whether each component carries a type-appropriate open license). Models qualify for
three cumulative classes: Class III (Open Model), Class II (Open Tooling Model), and
Class I (Open Science Model).

Assessing a model against the MOF by hand means chasing artifacts and licenses across
model repositories, source code, datasets, papers, and documentation. This tool
automates that evidence gathering while keeping every result verifiable:

- It collects **revision-pinned, bounded evidence** from Hugging Face, GitHub,
  datasets, papers, PDFs, and documentation pages — without downloading model weights
  or released data.
- Automated results distinguish a conservative **confirmed** score from an
  evidence-supported **potential** score. Model-card mentions and unknown components
  never enter the potential score, and ambiguous license scope prevents an automated
  result from being labeled verified.
- **Human review is always required** before any verified classification: reviewers
  accept or reject individual evidence claims in an auditable queue, and only accepted
  claims reach the exported MOT YAML.

The current implementation includes the scoring-parity foundation (a deterministic
port of the existing MOT evaluator) plus a growing set of evidence collectors, the
first of which was the Hugging Face collector. It loads the versioned MOF component
catalog, reads the existing MOT license sources, and evaluates existing MOT YAML.

## Install the CLI

Requirements: Python 3.12+ and [`uv`](https://docs.astral.sh/uv/). A basic
public-model evaluation needs no optional services and no `.env` file; Docker
(PostgreSQL), a MinerU VLM service, and an OpenAI-compatible endpoint are needed only
for the advanced features described in the [CLI reference](docs/CLI.md).

Install `mot` as an isolated standalone CLI tool (no checkout required):

```bash
uv tool install \
  "git+https://github.com/atripathy86/model_openness_tool.git@main#subdirectory=mot"
mot version
mot catalog
```

Replace `main` with a tag or full commit SHA for a reproducible installation; use
`uv tool upgrade model-openness-tool` to upgrade, `uv tool dir --bin` if uv reports
its executable directory is not on `PATH`.

To work from a source checkout instead, see
[Development setup](#development-setup).

## The easy path: Agent Skill for coding tools

The quickest way to run MOT evaluations is through the bundled Agent Skill, an Agent
Skills specification-compatible workflow at [`../skill/mot`](../skill/mot). Install
only the `mot` skill from this repository into Codex, Claude Code, GitHub Copilot CLI,
or another client supported by the `skills` installer:

```bash
npx skills add https://github.com/atripathy86/model_openness_tool --skill mot
```

Then ask your coding tool for a model openness evaluation. The skill is a
self-contained operating guide that installs the MOT CLI from this fork with
`uv tool install` when authorized, or uses a user-supplied MOT checkout. It verifies
the installed version and catalog, creates a user-selected workspace, explains
optional `.env` configuration, asks for evaluation scope and source limits, runs the
CLI in a safe sequence, interprets cumulative MOF Class III/II/I requirements, and
guides human review and YAML export. It does not modify MOT source code or bundle
credentials and services.

The skill's default CLI setup sequence is:

```bash
uv tool install \
  "git+https://github.com/atripathy86/model_openness_tool.git@main#subdirectory=mot"
mot version
mot catalog
```

It also documents SSH installation, commit-pinned installation, upgrades, PATH
discovery, and checkout-based execution.

## Configuration (`.env`)

Optional. Create local configuration from the complete environment template:

```bash
cp example.env .env
```

The tracked `example.env` lists Hugging Face, GitHub, OpenAI-compatible, MinerU,
API-authentication, log-level, PostgreSQL, and SQLAlchemy variables. The populated
`.env` is local-only and ignored by Git. When running from a source checkout, pass it
to commands with `uv run --env-file .env ...`.

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
arguments — tokens are never accepted as CLI values or written to reports. The LLM
endpoint can likewise be overridden at runtime with `--base-url` without placing a
deployment value in project documentation.

## Walkthrough: evaluating GPT-2 end to end

This walkthrough evaluates `openai-community/gpt2` from evidence collection through
reviewed YAML export. It uses the installed `mot` executable; from a source checkout
(see [Development setup](#development-setup)), prefix commands with `uv run`. Output
file names follow the naming convention described in the
[CLI reference](docs/CLI.md#output-file-naming-convention)
(`<artifact>[-<source>]-<slug>.json`, `.mot/review-<slug>.db`, `<slug>.mot.yml`).

The complete flow at a glance:

```bash
# 1. Collect pinned evidence: the model repo, plus its linked GitHub source
mot collect openai-community/gpt2 --output evidence-hf-gpt2.json
mot collect-github https://github.com/openai/gpt-2 \
  --output evidence-github-openai-gpt-2.json

# 2. Evaluate (collect + assess in one step), following linked GitHub repos
mot evaluate openai-community/gpt2 --repository-root .. \
  --follow-github --output evaluation-gpt2-linked-github.json

# Optional: LLM-assisted mention extraction from collected documentation
# (requires OPENAI_BASE_URL; proposals never affect scores directly)
# mot collect-doc <documentation-url> --output evidence-doc-gpt2.json
# mot extract-llm evidence-doc-gpt2.json --output proposals-gpt2.json
# mot review-import proposals-gpt2.json

# 3. Human review: import the evaluation's evidence, inspect, decide
mot review-import-run evaluation-gpt2-linked-github.json \
  --database .mot/review-gpt2.db
mot review-list --database .mot/review-gpt2.db --status pending
mot review-decide <evidence-id> --decision accept \
  --reviewer <reviewer-id> --reason "Verified against the pinned source." \
  --database .mot/review-gpt2.db

# 4. Export accepted claims as MOT-schema YAML, ready for submission
mot export-mot-yaml evaluation-gpt2-linked-github.json \
  --database .mot/review-gpt2.db --output gpt2.mot.yml
```

The sections below explain each stage in detail.

### 1. Collect evidence

Take a revision-pinned snapshot of the model repository, without downloading model
weights:

```bash
mot collect openai-community/gpt2 --output evidence-hf-gpt2.json
```

The report pins the exact repository revision and lists the files, licenses, and
normalized links (GitHub repositories, datasets, papers, documentation) discovered in
the model card.

### 2. Evaluate

Create a provisional assessment from the saved evidence:

```bash
mot assess evidence-hf-gpt2.json --repository-root .. \
  --output assessment-gpt2.json
```

Or collect and assess in one command:

```bash
mot evaluate openai-community/gpt2 --repository-root .. \
  --output evaluation-gpt2.json
```

The evaluation reports, per MOF class, which components are confirmed, which are
supported by evidence, and which are missing or unlicensed — yielding the confirmed
and potential scores. To broaden the evidence, opt-in flags such as `--follow-github`,
`--follow-datasets`, `--follow-papers`, and `--follow-documentation` follow links
discovered in the model card (bounded per type); see
[Following linked sources](docs/CLI.md#following-linked-sources).

### 3. Review the evidence

Import the deterministic evidence from the saved evaluation into a local, append-only
SQLite review queue, and list what is pending:

```bash
mot review-import-run evaluation-gpt2.json --database .mot/review-gpt2.db
mot review-list --database .mot/review-gpt2.db --status pending
```

Record a human decision for each evidence ID returned by `review-list`:

```bash
mot review-decide <evidence-id> --decision accept \
  --reviewer <reviewer-id> --reason "Verified against the pinned source." \
  --database .mot/review-gpt2.db
```

Review databases are Git-ignored, imports are idempotent, and decisions are immutable
audit events; see [Human review queue](docs/CLI.md#human-review-queue) for full
semantics.

### 4. Export reviewed MOT YAML

Export only the accepted artifact claims as MOT-schema YAML, ready for submission to
the MOT repository:

```bash
mot export-mot-yaml evaluation-gpt2.json \
  --database .mot/review-gpt2.db --output gpt2.mot.yml
```

Export considers only accepted evidence from that exact evaluation snapshot and never
overwrites existing files; the full export rules are in
[Exporting reviewed MOT YAML](docs/CLI.md#exporting-reviewed-mot-yaml).

## Going further

The [CLI reference](docs/CLI.md) documents every command, option, limit, and caveat:

- [Evidence collectors](docs/CLI.md#evidence-collectors) for GitHub repositories
  (including SPDX and root-license-text detection), Hugging Face datasets, arXiv/DOI
  papers, public PDFs (via MinerU with `pypdf` fallback), and documentation pages —
  including their size caps and safety bounds.
- [Following linked sources](docs/CLI.md#following-linked-sources) — per-type
  semantics and limits for `--follow-github`, `--follow-datasets`, `--follow-papers`,
  and `--follow-documentation`.
- [LLM-assisted extraction](docs/CLI.md#llm-assisted-extraction) — schema-validated,
  line-cited evidence proposals from an OpenAI-compatible endpoint (`extract-llm`) and
  the gated extraction evaluation (`llm-eval`).
- [API service and durable jobs](docs/CLI.md#api-service-and-durable-jobs) — the
  FastAPI service, PostgreSQL migrations, the durable job queue and worker loop, and
  the job HTTP API.

## Development setup

The project is developed and tested only with a local `uv` environment. All
development examples keep uv's cache and Python installs local to this directory.
Export the variables once per shell (or prefix each command with them):

```bash
cd mot
export UV_CACHE_DIR=.uv-cache
export UV_PYTHON_INSTALL_DIR=.uv-python
```

Create the environment, check the CLI, and run the tests:

```bash
uv sync
uv run mot --help
uv run pytest
```

From a checkout, run any CLI command by prefixing it with `uv run` (e.g.
`uv run mot evaluate ...`).

Validate the bundled Agent Skill locally with:

```bash
UV_TOOL_DIR=.uv-tools uvx --from skills-ref agentskills validate ../skill/mot
```

The repository does not vendor the validator. The official package is named
`skills-ref`; its current CLI executable is `agentskills`.
