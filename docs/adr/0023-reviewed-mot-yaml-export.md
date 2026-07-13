# ADR 0023: Reviewed MOT YAML export

## Status

Accepted

## Context

MOT-compatible YAML must not turn a provisional assessment, model-card mention, or LLM
confidence into an authoritative component claim. The existing append-only review queue
initially accepted LLM proposals only, while deterministic evaluation evidence also needs a
human decision before entering the existing Drupal import workflow.

## Decision

- Allow deterministic and linked evidence from a saved evaluation run to be imported into
  the existing immutable review-item and append-only decision store.
- Bind imported evidence and export decisions to the exact assessment or snapshot identity.
- Export a component only when the latest review decision accepts an `artifact_exists`
  claim from that run. Never promote an accepted `artifact_mentioned` claim.
- Attach a license only from an accepted `license_declared` claim scoped to that component.
  Export an accepted artifact without such evidence as `unlicensed`, and reject conflicting
  accepted licenses rather than selecting one implicitly.
- Emit only fields supported by the existing MOT YAML schema. Keep evidence identifiers,
  reviewer identity, rationale, and event timestamps in the canonical evaluation and review
  records.
- Refuse to overwrite an existing output file.

## Consequences

Reviewed, evidence-supported components can enter the existing MOT workflow without
extending its schema or overstating mere mentions. Review remains intentionally explicit and
may yield sparse or unlicensed YAML. This slice does not claim that every unresolved
class-affecting decision has been adjudicated or label the export as a verified MOF class.
