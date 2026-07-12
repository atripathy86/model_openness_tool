# ADR 0006: GitHub source evidence merging

- Status: Accepted
- Date: 2026-07-12

## Context

Pinned GitHub file manifests can provide stronger evidence for MOF code components than model-card mentions. That evidence must be conservative, attributable to the linked commit, and merged without allowing unknown files or failed sources to inflate the model's potential classification.

## Decision

- Detect source artifacts from pinned file paths using high-precision rules for model architecture, training, inference, evaluation, data preprocessing, and dependency manifests.
- Exclude files under `test` and `tests` directories from positive component detection.
- Record every positive match as evidence with the GitHub repository, commit SHA, blob path, detector version, and a pinned browser URL.
- Record GitHub license-file presence without inferring license identity or scope from the filename alone.
- Merge linked evidence only when it uses the same component catalog hash as the primary Hugging Face report.
- Apply `present` over `mentioned_only` over `unknown` when combining findings, while preserving all selected evidence IDs.
- Keep GitHub following opt-in through `mot evaluate --follow-github`, defaulting to no additional external requests.
- Follow at most three GitHub repositories by default, with a hard CLI limit of ten.
- Include every linked collection result in the evaluation run, but merge only successful evidence reports.
- Feed merged findings into the existing provisional evaluator. Linked evidence can improve the evidence-supported potential score but cannot bypass license-scope review or create a verified score.

## Consequences

Training and tooling evidence can be discovered beyond the Hugging Face model repository without weakening the confirmed-versus-potential boundary. The current rules favor precision and will intentionally miss unconventional filenames. Later semantic extraction can propose additional matches for review without changing these deterministic rules.
