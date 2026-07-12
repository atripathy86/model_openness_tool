# ADR 0008: Version-pinned arXiv paper evidence

- Status: Accepted
- Date: 2026-07-12

## Context

Model cards frequently link research papers, but a URL mention is weaker than resolving a publicly available paper. Papers can support the MOF Research paper component while their descriptions of code, data, or experiments do not prove that those separate artifacts are released.

## Decision

- Normalize modern and legacy arXiv IDs and URLs into canonical paper identities.
- Resolve paper metadata through the public arXiv Atom API and require the returned identifier to contain an immutable arXiv version.
- Store bounded title, author, abstract, publication/update timestamps, and declared-license metadata. Do not download or parse paper PDFs in this connector.
- Treat a successfully resolved arXiv entry as affirmative evidence only for the Research paper component.
- Treat any arXiv license declaration as component-specific to the Research paper and leave unrecognized or unclear licenses review-required.
- Keep paper following opt-in through `mot evaluate --follow-papers`, defaulting to no additional paper requests.
- Follow at most three unique arXiv papers by default, with a hard CLI limit of ten, and merge only successful reports using the primary report's component catalog hash.
- Retain DOI and generic PDF links as discovery candidates. Do not fetch them until source-specific bounded connectors and policies are defined.

## Consequences

The evaluator can distinguish an arXiv mention from a version-pinned public paper while maintaining a small, auditable metadata boundary. Paper prose cannot inflate code, data, technical-report, or evaluation component decisions. Models whose cards link only DOI or generic PDF sources will continue to require review or a later connector.
