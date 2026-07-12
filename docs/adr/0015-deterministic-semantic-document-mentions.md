# ADR 0015: Deterministic semantic document mentions

## Status

Accepted

## Context

Bounded documentation pages and PDF Markdown often describe training data, code,
checkpoints, evaluation, and other MOF artifacts. Treating those descriptions as proof
of release would inflate openness results, while retaining only a neutral document-level
observation discards useful evidence for reviewers.

## Decision

- Add a shared deterministic mention extractor for bounded documentation and PDF text.
- Begin with narrow reviewed phrases for training, inference, evaluation and preprocessing
  code; training and evaluation data; weights and checkpoints; metadata; results; sample
  outputs; and named document artifacts.
- Emit `artifact_mentioned` evidence with the source revision, URL, line locator, bounded
  excerpt, extraction method, and confidence.
- Map matching components to `mentioned_only`, never `present`. Mention evidence cannot
  enter the evidence-supported potential score or satisfy a MOF component.
- Extract at most one cited mention per component per document in this version to bound
  report size and avoid repetitive prose overwhelming review.
- Do not infer availability from phrases such as “we trained” or “we evaluated.” Artifact
  nouns such as code, dataset, checkpoint, or results must be explicit.
- Keep this deterministic layer separate from future schema-validated LLM extraction.

## Consequences

Reviewers receive precise document citations for relevant claims without confusing prose
with released artifacts. The initial phrase set intentionally favors precision and has
false negatives. Pattern additions require fixtures and review because even
`mentioned_only` evidence affects reviewer attention and report size.
