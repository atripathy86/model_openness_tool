# ADR 0016: Provider-neutral LLM evidence proposals

## Status

Accepted

## Context

Some MOF evidence requires semantic reading beyond deterministic phrases. Phase 4 needs
LLM assistance without allowing a model to assign framework status, invent citations, or
couple the evaluator to one hosted provider.

## Decision

- Define a provider-neutral structured-client protocol and implement the first adapter
  against an OpenAI-compatible HTTP API.
- Read the endpoint from the standard `OPENAI_BASE_URL` environment variable unless an
  operator supplies an explicit runtime override, and discover the first endpoint model
  when none is specified. Allow local endpoints without authorization; when a key is
  required, read it only from `OPENAI_API_KEY`. Keep deployment-specific endpoint values
  out of project documentation.
- Request strict JSON-schema output with at most 50 claim proposals. Every proposal must
  name a catalog component, provide an exact source quote and inclusive line range, a
  bounded rationale, and confidence.
- Reject unknown component IDs, reversed or out-of-range citations, and quotes that do
  not occur verbatim inside the cited source lines.
- Convert accepted proposals only to `artifact_mentioned` evidence. All LLM extraction
  reports remain review-required and cannot directly alter component availability,
  satisfaction, or MOF scores.
- Limit an extraction request to the first 60,000 source characters and record whether
  truncation occurred.
- Record source/content hashes, endpoint, provider, model, prompt/extractor versions,
  duration, token usage, accepted evidence, and rejected proposals. Never persist the API
  key.
- Use local SQLite for the review queue and append-only override audit in the next Phase 4
  slice, retaining PostgreSQL migration for Phase 5.
- Evaluate on five labeled document excerpts. Require at least 95% precision, 100% valid
  citations for accepted claims, and zero LLM-only promotion to `present` or `satisfied`.
  Report recall without gating the initial release.

## Consequences

LLM output becomes untrusted, reproducible review input rather than a scoring authority.
The first adapter works with LM Studio, vLLM, and other compatible endpoints, while the
domain extractor can accept future providers. A five-example evaluation set is useful for
early iteration but is not statistically strong enough for broad production claims and
must grow before deployment at scale.
