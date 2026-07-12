# ADR 0018: Five-case LLM extraction evaluation

## Status

Accepted

## Context

Phase 4 requires a measurable quality gate for LLM evidence proposals. The initial
iteration needs a small, reviewable set that can run against local models without using
copyrighted model cards or transmitting private source material.

## Decision

- Begin with five synthetic labeled excerpts covering source code artifacts, data and
  results, weights and metadata, activity language without released artifacts, and named
  document artifacts.
- Store the labeled set as a versioned JSON fixture with expected MOF component IDs.
- Run each case through the same schema validation and exact-citation checks used by
  `mot extract-llm`.
- Count citation-validated expected component proposals as true positives, unexpected
  accepted components as false positives, and missing expected components as false
  negatives. Count every citation-rejected proposal as a false positive.
- Report precision, recall, raw citation validity, per-case errors, and per-case component
  differences.
- Require all five requests to succeed, at least one true positive, precision of at least
  95%, raw citation validity of 100%, and zero LLM-only status promotions. Report recall
  without using it as an initial release gate.
- Exit nonzero when the gate fails while still writing the complete report.

## Consequences

The harness prevents vacuous empty output from passing and makes local model changes
measurable. Five synthetic examples are appropriate only for early experimentation; they
do not establish production generalization. The labeled set must expand with attributable,
reviewed examples before deployment claims or broad model comparisons.
