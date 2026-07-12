# ADR 0004: Conservative provisional assessment bounds

- Status: Accepted
- Date: 2026-07-12

## Context

Automated Hugging Face inspection can establish that some artifacts are present, but model-card mentions do not prove release availability and a declared model license may not clearly apply to every code, data, and document component. Reporting such evidence as a verified MOF class would overstate what the sources support.

## Decision

- Automated output is `provisional` until class-affecting decisions are reviewed.
- Report two deterministic score summaries:
  - **Confirmed:** includes only components whose availability and applicable open license are resolved as satisfied.
  - **Evidence-supported potential:** includes only directly present artifacts when the declared license normalizes to a known open MOT/SPDX license.
- Exclude `mentioned_only`, `unknown`, and `inaccessible` components from the potential score.
- Treat a model-level declared license as having ambiguous component scope until reviewed. It may support the potential score but never the confirmed score by itself.
- Normalize license identifiers using case-insensitive exact matching against the current MOT license catalog. Do not guess custom licenses or expressions.
- Use the existing deterministic parity scorer for both summaries so class gating and special cases remain consistent with Drupal.
- Include all review-required component IDs, evidence/catalog/rule hashes, warnings, and a non-legal-advice disclaimer.

## Consequences

Most unreviewed Hugging Face assessments will have a conservative confirmed class of unclassified. The potential score is useful for prioritizing review but is explicitly not a MOF certification. Human decisions can later promote supported components into a verified assessment without changing the underlying scoring engine.
