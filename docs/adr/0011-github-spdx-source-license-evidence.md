# ADR 0011: GitHub SPDX Source-License Evidence

## Status

Accepted

## Context

Linked GitHub repositories can provide evidence for source-code components such as
training code, inference code, evaluation code, preprocessing code, model architecture,
and supporting dependencies. Before this decision, the collector retained license-file
presence as review evidence but did not attach an identified repository license to the
source components it detected.

GitHub repository metadata often includes a `license.spdx_id` value when GitHub can
identify the repository license.

## Decision

Use GitHub's repository-level SPDX license identifier as component-specific license
evidence only for source components that are independently detected in the pinned
repository manifest.

Do not use repository license metadata to promote component availability. A component
must first be detected by high-precision source-file rules. The license evidence is then
attached to that component's decision so the provisional evaluator can report a
component-specific license identity and potential score.

Ignore missing, empty, or `NOASSERTION` GitHub license identifiers.

## Boundaries

- Do not infer that every repository file is covered by the repository metadata license.
- Do not treat the license as verified legal advice.
- Do not parse license text in this phase.
- Do not apply GitHub repository license metadata to model weights, datasets, papers,
  documentation, or Hugging Face model-card evidence.

## Consequences

`mot evaluate --follow-github` can now report component-specific source licenses when a
linked GitHub repository both contains detected source artifacts and exposes an SPDX
license through the GitHub API. Verified classification still requires human review.
