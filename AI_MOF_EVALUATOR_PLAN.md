# AI-Assisted Model Openness Framework Evaluator Plan

## 1. Executive summary

This project will extend the existing Model Openness Tool (MOT) with an evidence-backed pipeline that evaluates Hugging Face models against the Model Openness Framework (MOF).

The project should **build on the current repository, not start over**, while placing the new crawler, evidence extraction, license analysis, and scoring implementation in a new Python subsystem. Drupal remains the current application, import surface, and reference implementation while the Python rule engine is proven equivalent.

The evaluator will inspect more than a model card. It will collect and correlate evidence from the Hugging Face model repository, linked code repositories, linked datasets, papers, documentation, and license files. It will produce:

1. a canonical evidence report with per-criterion status, confidence, citations, and reasoning;
2. a deterministic provisional or verified MOF assessment;
3. a review queue for unresolved or ambiguous decisions; and
4. MOT-compatible YAML for reviewed/supported component claims.

The key product principle is:

> A source mentioning an artifact is not evidence that the artifact is available under an applicable open license.

## 2. Goals and non-goals

### Goals

- Evaluate Hugging Face model releases against the versioned MOF component and license rules.
- Capture auditable evidence for every component and license decision.
- Use deterministic inspection first and structured LLM extraction where semantic reading is useful.
- Distinguish present, mentioned-only, absent, unknown, and inaccessible artifacts.
- Distinguish provisional automated assessments from human-verified assessments.
- Reach scoring parity with the current Drupal evaluator before intentionally changing any rule.
- Preserve compatibility with existing MOT model YAML and the Drupal application.
- Support a CLI-first workflow, then batch orchestration and an API.
- Make human review efficient rather than pretending that every MOF decision can be fully automated.

### Non-goals for the first release

- Proving that a model can be reproduced by actually retraining it.
- Downloading or storing large model weights or full datasets by default.
- Treating model-card text alone as authoritative evidence.
- Making legal conclusions about licenses. The tool reports framework decisions and evidence; it is not legal advice.
- Replacing the Drupal UI in the first milestone.
- Automatically publishing model YAML or submitting pull requests without human approval.

## 3. What to reuse from the current repository

### Authoritative behavior to port and test

| Concern | Current source | Planned use |
|---|---|---|
| MOF classification and progress | `web/modules/mof/src/ModelEvaluator.php` | Port into a pure Python rule engine and build parity tests. |
| Component catalog | `web/modules/mof/config/install/mof.settings.yml` | Import/snapshot as a versioned catalog rather than duplicating constants. |
| Component lookup | `web/modules/mof/src/ComponentManager.php` | Reproduce required/optional grouping behavior. |
| License openness and type checks | `web/modules/mof/src/LicenseHandler.php` | Port behavior with versioned license data and parity fixtures. |
| License source data | `web/modules/mof/licenses.json`, `web/modules/mof/mof-licenses.json` | Seed the license registry with source/version metadata. |
| Model serialization/update behavior | `web/modules/mof/src/ModelSerializer.php`, `web/modules/mof/src/ModelUpdater.php` | Preserve field meanings and inheritance behavior. |
| YAML validation | `web/modules/mof/src/ModelValidator.php`, `schema/mof_schema.json` | Validate compatibility output and add Python round-trip tests. |
| Regression cases | `Test_Data/`, `scripts/test-model-files.php` | Create cross-language golden tests for class/progress/license behavior. |

### Prototypes to refactor, not treat as authoritative

| Current source | Useful behavior | Limitation to address |
|---|---|---|
| `tools-py/model_scraper.py` | Hugging Face metadata/card/tree retrieval, basic component and license hints, YAML draft generation | Keyword rules conflate mentions with availability, tree retrieval is shallow, evidence is not normalized, and it cannot produce a defensible score. |
| `tools-py/find_missing_models.py` | Popular-model discovery and comparison with existing MOT records | Needs robust identity resolution, paging, caching, rate-limit handling, and resumable batch state. |
| `tools-py/batch_scrape_missing.sh` | Demonstrates an operator batch workflow | Replace with an observable, resumable Python flow after core evaluation works. |

### Known baseline issue to resolve explicitly

The README describes 16 MOF components, while the current `mof.settings.yml` contains 17 configured entries. The new system must not hard-code the count. Phase 0 will document which MOF specification/version and catalog the application is implementing, give the catalog a stable version/hash, and add a test that detects unreviewed catalog drift.

## 4. Proposed architecture

```text
Model reference
      |
      v
Source connectors -------------------------------+
  Hugging Face model/card/repo                   |
  GitHub or linked source repositories           |
  Hugging Face datasets                          |
  papers and documentation                       |
      |                                           |
      v                                           |
Immutable source snapshot + provenance            |
      |                                           |
      +--> deterministic detectors                |
      +--> structured document/LLM extraction     |
      |                                           |
      v                                           |
Normalized evidence store <-----------------------+
      |
      v
Criterion decision layer
  availability + applicability + license
      |
      +--> human review queue
      |
      v
Versioned deterministic MOF rule engine
      |
      +--> canonical assessment JSON
      +--> MOT-compatible YAML draft
      +--> API/CLI report
```

The layers must be independently testable. Connectors collect facts; extractors propose observations; criterion evaluators decide whether those observations meet component requirements; the rule engine calculates framework results. An LLM never directly assigns the final MOF class.

## 5. Recommended technology stack

### Core Python subsystem

- **Python 3.12+** for the new package, subject to repository/hosting compatibility validation.
- **uv** for the local environment, managed Python, dependency lock, builds, and every Python quality/test command. The environment and uv caches remain inside `mot/`; system/global Python environments are not used for implementation or testing.
- **Pydantic v2** for evidence, decision, assessment, and connector contracts.
- **HTTPX** for explicit asynchronous HTTP, timeouts, retry integration, and mockable transports.
- **huggingface_hub** for supported Hugging Face API access and snapshots/metadata.
- **PyYAML or ruamel.yaml** for reading existing data; use a library that can emit stable MOT-compatible YAML.
- **SQLAlchemy 2 + Alembic** for persistence and migrations.
- **PostgreSQL** for production run/evidence/review storage; SQLite may support local development and tests where behavior remains portable.
- **Typer** for the first operator-facing CLI.
- **pytest**, **pytest-asyncio**, **pytest-cov**, **Ruff**, and **mypy or Pyright** for verification.

### Service and orchestration

- **FastAPI** for submission, run status, assessment, evidence, and review endpoints.
- **Prefect** for scheduled/batch runs, retries, concurrency limits, and resumability after the single-model CLI path is stable.
- An object store interface for raw source snapshots and larger evidence payloads; local filesystem in development and S3-compatible storage in deployed environments.

### LLM integration

- Use a small provider-neutral interface with structured-output support.
- Version prompts and extraction schemas.
- Record provider, model identifier, prompt version, input source hashes, output, validation errors, latency, and token/cost metadata where available.
- Permit a fully deterministic mode with LLM extraction disabled.
- Never send gated/private source contents to an external provider unless the deployment policy explicitly permits it.

### Why this stack

FastAPI, Pydantic, and SQLAlchemy provide typed boundaries without coupling the core rules to the web layer. Prefect supplies operational features needed for large Hugging Face scans but should not be introduced into the scoring domain. A CLI-first sequence keeps the first milestones easy to test and debug.

Exact dependency versions will be selected during the foundation milestone and pinned in the lock file after license, compatibility, and maintenance review.

### Naming decision

- Product name: **MOT**.
- CLI executable: **`mot`**.
- Python project directory: **`mot/`**.
- Python distribution: **`model-openness-tool`**. The shorter `mot` distribution name is already registered on PyPI by an unrelated project.
- Python import package: **`model_openness_tool`**, avoiding a top-level import collision with the existing `mot` distribution.
- Agent Skill: **`skill/mot/`**, with `name: mot` in its frontmatter.

## 6. Proposed repository layout

The precise top-level package name will be finalized in the first implementation change. A recommended layout is:

```text
mot/
  pyproject.toml
  uv.lock
  .python-version
  src/model_openness_tool/
    domain/
      framework.py
      components.py
      licenses.py
      evidence.py
      decisions.py
      assessments.py
    connectors/
      huggingface.py
      github.py
      datasets.py
      papers.py
      web_docs.py
    extraction/
      repository_files.py
      model_card.py
      documents.py
      llm.py
    evaluation/
      component_rules.py
      license_rules.py
      scorer.py
      parity.py
    persistence/
      models.py
      repositories.py
      migrations/
    reporting/
      evidence_json.py
      mot_yaml.py
      human_report.py
    orchestration/
      flows.py
      tasks.py
    api/
      app.py
      routes/
    cli.py
skill/
  mot/                         # Created after the CLI contract is stable
    SKILL.md
    references/                # Only when detailed CLI reference is needed
  tests/
    unit/
    integration/
    parity/
    fixtures/
```

The existing `tools-py/` scripts can initially call the new package or be retained as compatibility wrappers. Once replacement commands are documented and proven, the old implementations can be deprecated in a separate approved change.

## 7. Domain and data contracts

### Source snapshot

Each evaluation run freezes the inputs needed to reproduce its conclusions:

- canonical source URL and source type;
- source owner/repository/model/dataset identity;
- revision, commit SHA, tag, or content hash;
- retrieval timestamp and HTTP metadata;
- access result (`available`, `gated`, `private`, `missing`, `error`);
- file manifest and selected content hashes;
- parent/linked source relationship; and
- connector and parser versions.

Do not download large binary artifacts merely to prove their presence. File metadata, LFS pointers, API metadata, hashes, and targeted range/header checks should normally be enough.

### Evidence item

An evidence item is a source-grounded observation, not a final decision. It should contain:

- stable evidence ID and run ID;
- proposed MOF component/field;
- claim type, such as `artifact_exists`, `artifact_described`, `license_declared`, or `artifact_accessible`;
- normalized value;
- source snapshot and precise locator (file path, line/heading/JSON pointer, URL);
- a short excerpt or structured fact within copyright limits;
- extraction method and extractor version;
- confidence score and confidence rationale;
- contradictory evidence links; and
- review state.

### Component decision

Keep these dimensions separate:

- **Availability:** `present`, `mentioned_only`, `absent`, `unknown`, `inaccessible`.
- **Framework applicability:** applicable, not applicable, or review required.
- **License identity:** SPDX/MOF identifier, expression, custom/unknown, or absent.
- **License applicability:** distribution-wide, type-wide, component-specific, ambiguous, or contradicted.
- **License decision:** open/type-appropriate, open/not-type-appropriate, closed, unlicensed, or review required.
- **Satisfaction:** `satisfied`, `not_satisfied`, or `review_required`.
- **Confidence:** numeric or enumerated confidence that does not override satisfaction rules.
- **Evidence:** supporting and contradicting evidence IDs.

### Assessment

An assessment records:

- model release identity and evaluated revision;
- MOF framework/catalog/license-rule versions and hashes;
- evaluator software version;
- per-component decisions;
- per-class progress and classification;
- blocking review items and warnings;
- assessment kind: `provisional` or `verified`;
- reviewer identity/timestamp for verified decisions; and
- generated MOT YAML plus a mapping back to evidence.

## 8. Ingestion strategy

### Hugging Face model source

Collect:

- model metadata and model-card structured metadata;
- full repository tree with pagination/recursive traversal;
- default and resolved revision;
- README/model card and relevant text/config/license files;
- weight/checkpoint metadata without downloading weights;
- tags, pipeline, library, base-model, datasets, papers, and linked repositories;
- gated/private status and access limitations; and
- repository siblings, LFS metadata, and file sizes.

### Linked source repositories

Parse links, normalize repository identity, pin a commit, and inspect:

- training, inference, evaluation, and preprocessing entry points;
- configuration and environment/lock files;
- architecture definitions;
- documentation and release artifacts;
- license files and path-level license scopes; and
- submodules or external dependencies when directly relevant.

Use the GitHub API first and a bounded shallow/partial clone fallback only when content traversal requires it.

### Datasets

For referenced datasets, determine separately:

- whether the exact training/evaluation dataset is identified;
- whether the released dataset is the actual artifact or only a source/reference;
- whether preprocessing/filtering/transformation code is available;
- which revision/config/splits were used;
- dataset access restrictions; and
- declared license and provenance.

### Papers and documentation

Resolve paper identifiers and links, then extract artifact claims, training details, dataset identity, evaluation descriptions, and links. A paper can support documentation criteria but does not prove that code/data artifacts are released.

## 9. Extraction strategy

### Deterministic extraction first

Use manifests, filenames, structured metadata, config schemas, importable entry points, and exact links to generate high-precision evidence. Avoid treating generic `.py` files as sufficient proof of model architecture or training code without content checks.

Each detector should define:

- required and supporting signals;
- false-positive exclusions;
- evidence emitted;
- confidence calculation;
- fixture tests; and
- applicable framework/component version.

### Structured LLM extraction

Use an LLM for tasks that require semantic reading, for example:

- determining whether a script actually trains versus only demonstrates inference;
- linking a named dataset to the exact released artifact;
- extracting license-scope statements;
- identifying where evaluation results or data-card information are embedded; and
- surfacing contradictions or missing details.

The LLM must return schema-validated observations with citations into the supplied source. Unsupported claims are rejected or sent to review. LLM confidence alone never satisfies a component.

### Contradiction handling

Do not collapse conflicting sources. Preserve both observations, apply an explicit source precedence policy where safe, and route material ambiguity to review. Examples include a model-card license that differs from a repository `LICENSE`, or a paper naming a dataset version different from the released dataset.

## 10. License analysis

License analysis is a first-class subsystem because MOF classification depends on both artifact availability and licensing.

The implementation will:

1. collect license declarations and files at distribution, content-type, and component scope;
2. normalize SPDX identifiers/expressions and MOT-specific identifiers without guessing custom licenses;
3. determine which license applies using the current MOT precedence rules;
4. evaluate openness and type appropriateness using a versioned ruleset;
5. report unknown, conflicting, missing, or custom terms for human review; and
6. retain the exact source and revision for every license decision.

The current Drupal precedence is component-specific, then type-specific global, then distribution-wide global, then unlicensed. Python parity tests must cover this order.

License lists and their provenance must be updateable independently of code, with change review and regression tests. Automated output should include a clear non-legal-advice notice.

## 11. Scoring and parity strategy

### Parity first

Build a pure deterministic Python scorer with no network, database, or LLM dependency. Feed it normalized component/license decisions and reproduce current Drupal outputs.

Parity fixtures will cover:

- required and optional components by class;
- cumulative class requirements;
- missing, invalid, unlicensed, included, and optional buckets;
- component/type/distribution license inheritance;
- open but not type-appropriate warnings;
- class progress and lower-class gating;
- technical report/research paper substitution behavior; and
- all suitable cases in `Test_Data/`.

Cross-language comparison should serialize the Drupal and Python results into a stable normalized shape. Any mismatch must be classified as a port defect, ambiguous behavior, or an intentional change requiring its own approval and Architecture Decision Record.

The README also describes equivalences involving data-card information and evaluation results embedded in documents. The current evaluator principally implements the technical-report/research-paper special case; other equivalences appear to depend on users recording the component as included. The new system must model these as evidence/criterion decisions and avoid silently inventing new scoring semantics during parity.

### Provisional versus verified results

- A **provisional assessment** may include `review_required` decisions and must identify how they affect possible class outcomes.
- A **verified assessment** requires all class-affecting decisions to be resolved or explicitly adjudicated by a reviewer.
- When unknowns remain, report a conservative confirmed class and a clearly labeled potential class range rather than silently treating unknown as present.

## 12. Outputs and interfaces

### CLI (first interface)

Proposed commands:

```text
mot collect <hf-model> [--revision ...]
mot evaluate <hf-model> [--revision ...] [--no-llm]
mot report <run-id> [--format json|yaml|markdown]
mot review <run-id>
mot export-mot-yaml <run-id>
mot compare-parity <fixture-or-model-yaml>
```

### API (after CLI/core stability)

Provide endpoints for:

- starting a bounded evaluation;
- retrieving run state and diagnostics;
- retrieving evidence and assessments;
- submitting reviewer decisions;
- exporting MOT-compatible YAML; and
- comparing assessment versions.

Use idempotency keys, authentication for mutations/review, rate limits, and audit logs.

### Reports

Human-readable reports should show, per component:

- decision and confidence;
- applied license and license decision;
- concise rationale;
- direct source links/locations;
- contradictions and missing evidence;
- whether human review is required; and
- what the decision means for each MOF class.

MOT YAML output should include only claims supported under the export policy. Evidence and confidence belong in the canonical assessment report unless/until the MOT schema is deliberately extended.

## 13. Human review workflow

Prioritize review by impact and uncertainty:

1. decisions that could change the achieved MOF class;
2. conflicting or custom license cases;
3. dataset identity/provenance and preprocessing availability;
4. inaccessible/gated sources;
5. low-confidence semantic extraction; and
6. informational metadata cleanup.

A reviewer must be able to accept, reject, or replace a proposed decision, cite new evidence, add a note, and see the assessment recalculated deterministically. All overrides are append-only audit events rather than destructive edits to source observations.

## 14. Delivery phases

### Phase 0 — Baseline and decisions

- Confirm the implemented MOF specification/version and component catalog.
- Document the 16-versus-17 component discrepancy.
- Freeze reference scoring/license fixtures and current behavior.
- Decide package name, Python version, lock strategy, and storage migration conventions.
- Add initial Architecture Decision Records.

**Exit:** documented baseline, reproducible fixture set, and approved foundation design.

### Phase 1 — Python foundation and scoring parity

- Add the `mot/` uv project, `pyproject.toml`, lock file, package skeleton, quality tooling, and CI checks.
- Define component, license, decision, and assessment models.
- Load a versioned component/license catalog.
- Port deterministic evaluator behavior.
- Convert/import Drupal regression cases and compare outputs.
- Implement stable assessment JSON and MOT YAML serialization tests.

**Exit:** Python scorer matches the accepted Drupal baseline for all parity fixtures.

### Phase 2 — Hugging Face evidence MVP

- Implement revision-pinned Hugging Face connector and local cache.
- Parse structured metadata, full file manifests, model cards, configs, and license files.
- Add deterministic detectors for high-confidence components.
- Produce a no-LLM evidence report and provisional assessment.
- Refactor `tools-py/model_scraper.py` into a wrapper or document its replacement.

**Exit:** one public, one gated/inaccessible, and several fixture models produce reproducible evidence reports without large downloads.

### Phase 3 — Linked resources and license depth

- Add GitHub/source repository inspection.
- Add dataset, paper, and documentation connectors.
- Add identity resolution and contradiction tracking.
- Complete scoped license discovery/normalization and review cases.
- Add cache/rate-limit/resume behavior.

**Exit:** linked evidence is revision-pinned and materially improves training/data/evaluation component decisions.

### Phase 4 — AI-assisted extraction and review

- Add provider-neutral structured LLM extraction.
- Version prompts and record provenance/cost.
- Add citation validation and deterministic fallback.
- Implement reviewer queue and override audit model.
- Measure extraction accuracy on a labeled evaluation set.

**Exit:** LLM-assisted decisions meet agreed precision/coverage targets and every material claim remains reviewable.

### Phase 5 — API, orchestration, and operations

- Add FastAPI endpoints and authentication boundaries.
- Add PostgreSQL/Alembic persistence.
- Add Prefect batch flows, retry/concurrency policy, and run observability.
- Add metrics, structured logs, retention policy, and operational documentation.
- Adapt missing-model discovery to schedule prioritized evaluation runs.

**Exit:** resilient batch evaluations can be operated, monitored, resumed, and audited.

### Phase 6 — MOT integration and productization

- Integrate reviewed output with the Drupal import/UI flow.
- Decide whether evidence links require an additive MOT schema version.
- Add assessment comparison and re-evaluation on source/rule changes.
- Run security, privacy, performance, and accessibility reviews.
- Document deployment and reviewer operations.

**Exit:** reviewed assessments can safely enter the MOT workflow without breaking existing records.

### Phase 7 — MOT Agent Skill

- Create `skill/mot/SKILL.md` after the CLI actions and their output/error contracts are stable.
- Follow the [Agent Skills specification](https://agentskills.io/specification): directory/frontmatter name matching, concise triggering description, progressive disclosure, and relative one-level references.
- Make the skill invoke the `mot` CLI for collection, evaluation, reports, review, export, and parity comparison rather than reimplementing those behaviors in prompts or scripts.
- Include environment/preflight guidance, safe defaults, interpretation of provisional versus verified results, and handling for gated or review-required cases.
- Add focused references only when needed for command/output schemas; do not add a skill README or duplicate package documentation.
- Validate with the skill-creator `quick_validate.py` and the official `skills-ref validate ./skill/mot` validator.
- Forward-test representative prompts against the actual CLI before considering the skill complete.

**Exit:** an Agent Skills-compliant `mot` skill reliably drives the released CLI and passes both validators and representative forward tests.

## 15. Testing and quality strategy

### Unit tests

- Pure scoring/classification and progress.
- Component rules and special cases.
- License resolution, normalization, openness, and type appropriateness.
- Source identity and link normalization.
- Parsers/detectors with local fixtures.
- Confidence calculation and review routing.

### Contract and integration tests

- Mock Hugging Face/GitHub/dataset/paper API responses.
- Validate pagination, redirects, rate limits, gated access, retries, and cache behavior.
- Validate schema evolution and database migrations.
- Validate deterministic reports from frozen source snapshots.

### Parity tests

- Run all accepted `Test_Data/` cases through Drupal and Python.
- Compare normalized buckets, licenses, warnings, class progress, and classification.
- Detect component and license catalog drift.

### Evaluation set for AI extraction

Create a human-labeled, versioned set of diverse public models covering:

- well-documented and sparse cards;
- separate and monorepo code;
- gated and inaccessible assets;
- custom/conflicting licenses;
- base models and fine-tunes;
- language, image, audio, and multimodal models; and
- datasets referenced versus actually released.

Track per-component precision, recall/coverage, calibration, citation validity, abstention/review rate, assessment stability, latency, and cost. Optimize for precision and appropriate abstention, especially for class-affecting decisions.

## 16. Security, privacy, and operational safeguards

- Never log or persist Hugging Face, GitHub, or LLM credentials.
- Apply SSRF protections to discovered links: allow supported schemes, resolve/validate hosts, block private/link-local targets, cap redirects and payload sizes.
- Treat all cards, repository files, papers, and LLM output as untrusted input.
- Do not execute downloaded model code, notebooks, build scripts, or repository hooks.
- Parse in resource-bounded processes where appropriate and protect against archive/path traversal.
- Enforce file count/size/content-type limits.
- Respect API terms, robots/access requirements where applicable, and rate limits.
- Define retention rules for source content, especially gated or private material.
- Maintain dependency scanning and review transitive licenses.
- Sanitize report content before rendering it in Drupal or a web UI.

## 17. Observability and reproducibility

Every run should expose:

- correlation/run ID and state transitions;
- connector requests, cache hits, retries, and rate-limit waits without secrets;
- source revisions and hashes;
- detector/extractor/rule versions;
- component decision counts by state;
- review-required reasons;
- timing and failure category by stage; and
- LLM usage/cost metadata when enabled.

Re-running the evaluator against the same frozen evidence, framework catalog, license rules, and software version must yield the same deterministic assessment.

## 18. Initial success criteria

The first usable milestone is successful when:

- Python scoring matches every accepted Drupal parity fixture;
- a Hugging Face model can be evaluated by immutable revision from the CLI;
- every satisfied component includes inspectable evidence and a license decision;
- mentions are not reported as released artifacts;
- unknown/gated/conflicting cases are preserved and routed to review;
- output clearly says provisional or verified;
- reviewed output validates against the existing MOT schema; and
- no model weights, secrets, or unbounded source content are stored.

Product-level targets for automation coverage or accuracy should be set only after measuring the labeled evaluation set. The earlier estimate that much of the process can be automated is a hypothesis, not a release guarantee.

## 19. Initial backlog

1. Add an ADR template and record the Python-subsystem decision.
2. Inventory current Drupal component and license behavior into machine-readable golden fixtures.
3. Resolve/document the framework version and component-count discrepancy.
4. Scaffold the typed Python package and quality checks.
5. Port and parity-test license resolution and component scoring.
6. Define canonical evidence and assessment JSON schemas.
7. Implement a revision-pinned Hugging Face connector with mocked fixtures.
8. Implement high-precision deterministic detectors.
9. Generate the first no-LLM provisional report.
10. Review results on a small, diverse model set before adding linked-resource and LLM complexity.
11. After the CLI contract is stable, create and validate the `skill/mot` Agent Skill.

## 20. Decisions requiring explicit project approval

The following choices should be reviewed before implementation commits that depend on them:

- the canonical MOF specification/catalog version;
- any future change to the approved MOT naming split (product/CLI `mot`, distribution `model-openness-tool`, import `model_openness_tool`);
- whether new code lives in this repository long term or may later become a separately released package;
- supported LLM provider(s) and gated-content policy;
- production storage/object-store environment;
- the policy for converting unresolved evidence into conservative class/range reporting;
- any change from current Drupal scoring semantics; and
- any extension/versioning of the public MOT YAML schema.

## 21. Git and delivery policy

Development occurs on the `atripathy86/model_openness_tool` fork using the `fork` remote. The LFAI repository remains `origin` for upstream synchronization. No commits are created without explicit user approval, and no push is performed unless explicitly requested. Commit author/committer identity is `atripathy86 <atripathy86@gmail.com>`, with DCO sign-off as required by `CONTRIBUTING.md`.

## 22. Implementation status

As of 2026-07-12:

- Phase 0 baseline decisions and Phase 1 scoring foundation are implemented.
- The uv-managed `model-openness-tool` distribution exposes the `mot` CLI.
- The Python scorer matches the current named Drupal `Test_Data` progress fixtures.
- Phase 2 is implemented: `mot collect`, offline `mot assess`, and end-to-end `mot evaluate` provide revision-pinned Hugging Face evidence and conservative provisional assessments.
- Bounded model cards, selected configs, and license files are collected; weight presence is established from repository/LFS metadata without downloading weights.
- Confirmed and evidence-supported potential scores are reported separately, with model-level license scope held for review.
- The legacy `tools-py/model_scraper.py` draft-YAML workflow is documented as non-authoritative; new evaluator work uses the uv-managed `mot/` package.
- Phase 3 is in progress: model-card links are normalized into source identities, and `mot collect-github` produces commit-pinned, metadata-only GitHub tree snapshots without cloning or executing code.
- Pinned GitHub manifests now provide conservative source-component evidence, and `mot evaluate --follow-github` can merge up to three linked repositories into the evidence-supported potential assessment.
- GitHub SPDX repository license metadata is now attached as component-specific evidence only for source components detected in the pinned linked repository manifest.
- `mot collect-dataset` now records revision-pinned Hugging Face dataset manifests plus bounded card/license content without downloading dataset files. Structured and linked dataset identities can be followed with `mot evaluate --follow-datasets`.
- Released data-file and data-card evidence is merged conservatively. Dataset license declarations apply specifically to the dataset component, and conflicting declarations remain ambiguous and review-required.
- `mot collect-paper` now resolves arXiv references to version-pinned, bounded Atom metadata and DOI references to content-addressed Crossref metadata without downloading PDFs. `mot evaluate --follow-papers` can merge resolved papers as Research paper evidence only.
- `mot collect-doc` now captures bounded public text/HTML documentation as content-addressed review evidence. `mot evaluate --follow-documentation` follows normalized documentation links without automatically promoting any MOF component.
- `mot collect-pdf` now prefers an injected MinerU remote HTTP-client backend to capture bounded, content-addressed Markdown and structured page evidence from public generic PDFs. When MinerU is unavailable, an explicit `pypdf-fallback` preserves lower-fidelity evidence and the failure warning. Generic PDFs remain neutral evidence.
- Semantic documentation/PDF extraction and source-license text extraction are the next Phase 3 slices.
- The `skill/mot` Agent Skill remains intentionally deferred until the CLI contract is stable.
