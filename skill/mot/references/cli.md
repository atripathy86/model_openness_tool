# MOT CLI workflow and options

Use `mot` directly after installation from the fork. When the user supplies a source checkout,
replace `mot` in every example with `uv run --project <checkout>/mot mot`.

## Recommended evaluation sequence

1. Verify the CLI and record the active catalog:

   ```bash
   mot version
   mot catalog
   ```

2. Evaluate the Hugging Face repository without linked expansion:

   ```bash
   mot evaluate <namespace/model> [--revision <revision>] \
     [--cache-dir <directory>] [--token-env <variable>] \
     --output <evaluation.json>
   ```

3. If approved, add bounded linked sources:

   ```text
   --follow-github --max-linked-github <0-10>
   --github-token-env <variable>
   --follow-datasets --max-linked-datasets <0-10>
   --follow-papers --max-linked-papers <0-10>
   --follow-documentation --max-linked-documentation <0-10>
   ```

   Defaults are no linked expansion and a maximum of 3 for each enabled type. Model weights
   and dataset contents are not downloaded by the metadata collectors.

4. Inspect `collection.access_status`, `collection.report.snapshot.resolved_revision`,
   `assessment.confirmed`, `assessment.evidence_supported_potential`, component decisions,
   warnings, and linked collection results.

## Focused collection

Use focused commands when the user asks to inspect or debug one source:

```text
mot collect <hf-model> [--revision REV] [--output FILE]
mot collect-github <repository-url> [--revision REV] [--output FILE]
mot collect-dataset <dataset-url> [--revision REV] [--output FILE]
mot collect-paper <arxiv-or-doi-or-pdf> [--output FILE]
mot collect-doc <public-url> [--output FILE]
mot collect-pdf <public-pdf-url> [--output FILE]
  [--mineru-url URL] [--backend vlm-http-client|hybrid-http-client]
  [--pdf-fallback|--no-pdf-fallback]
mot assess <collection.json> [--output FILE]
mot evaluate-yaml <existing-model.yml>
```

Collection commands can exit nonzero while writing structured inaccessible-source output.
Do not translate that directly into “artifact absent.” PDF collection uses MinerU when
configured and bounded pypdf extraction as the default fallback.

## Optional LLM proposal extraction

Use only when the user wants semantic extraction from collected documentation or PDF text:

```bash
mot extract-llm <document-evidence.json> [--model <model>] \
  --output <proposals.json>
```

The command uses `OPENAI_BASE_URL`, optional `OPENAI_API_KEY`, or an explicit `--base-url`.
If `--model` is omitted, it discovers the first model returned by the endpoint. LLM output is
a citation-validated review proposal, not authoritative component evidence.

Evaluate an extractor configuration against a labeled set with:

```bash
mot llm-eval <evaluation-set.json> [--model <model>] --output <report.json>
```

## Human review and export

Use one SQLite review database per evaluation or clearly related review set:

```bash
mot review-import-run <evaluation.json> --database <review.db>
mot review-list --database <review.db> --status pending
mot review-decide <evidence-id> --decision accept|reject \
  --reviewer <identity> --reason <rationale> --database <review.db>
mot export-mot-yaml <evaluation.json> --database <review.db> \
  --output <reviewed-model.yml>
```

Use `review-import <llm-extraction.json>` only for LLM proposals. Review events are
append-only; the latest event determines current status. Export refuses to overwrite files,
includes only accepted `artifact_exists` evidence from the exact run, and uses only accepted
component-scoped license declarations.

## Durable jobs and API

Use these only when the user wants PostgreSQL-backed processing and `DATABASE_URL` is set:

```text
mot job-submit <hf-model> [--revision REV] [--max-attempts 1-10]
mot job-list [--status queued|running|succeeded|failed] [--limit 1-500]
mot worker --once
mot worker --loop [--poll-seconds 0.1-60]
  [--heartbeat-seconds 1-300] [--stale-seconds SECONDS]
mot job-retry <terminally-failed-job-id>
mot job-recover [--stale-seconds SECONDS]
```

`heartbeat-seconds` must be less than `stale-seconds`. Manual retry grants one additional
attempt. Explain the recovery threshold before running `job-recover` on shared infrastructure.

The optional FastAPI service exposes health/readiness, catalog, job submission/status,
cursor-paginated job listings, and manual retry. Versioned routes require a bearer token only
when `MOT_API_BEARER_TOKEN` is configured.
