# ADR 0007: Hugging Face dataset evidence

- Status: Accepted
- Date: 2026-07-12

## Context

Hugging Face model cards can name or link datasets, but a mention does not prove that data is released. Dataset repositories can establish stronger artifact evidence, while exact training use, provenance, preprocessing, access restrictions, and license scope still require separate decisions.

## Decision

- Resolve each Hugging Face dataset repository to an immutable revision SHA and retain its complete bounded file manifest.
- Download only root dataset-card and license files within the connector's size limits. Never download parquet, archive, or other released dataset content.
- Treat structured model-card dataset metadata and normalized dataset links as discovery candidates, not affirmative dataset evidence.
- Detect the Datasets component from recognized released data-file paths and the Data card component from a repository `README.md`.
- Cite at most twenty representative released data-file paths per dataset report while retaining the full manifest and reporting the total match count.
- Apply declared dataset licenses specifically to the Datasets component rather than assuming they cover the model or unrelated components.
- Preserve conflicting or unknown declarations across multiple linked datasets as ambiguous, review-required license evidence.
- Keep dataset following opt-in through `mot evaluate --follow-datasets`, defaulting to no additional external requests.
- Follow at most three unique datasets by default, with a hard CLI limit of ten, and merge only successful reports using the primary report's component catalog hash.

## Consequences

The evaluator can distinguish a model-card dataset mention from a revision-pinned released dataset without transferring dataset payloads. This can raise only the evidence-supported potential assessment. It cannot prove that the release is the exact training corpus, reconstruct preprocessing, settle provenance, or produce a verified MOF classification without review.
