# ADR 0003: Hugging Face SDK and bounded model collection

- Status: Accepted
- Date: 2026-07-12

## Context

The evidence pipeline needs Hugging Face model metadata, a complete repository tree, immutable revision identity, and selected text artifacts. It must not download model weights merely to establish that they exist, and tests must not depend on live network access.

## Decision

- Use the official Apache-2.0-licensed `huggingface-hub` Python SDK behind a small typed adapter.
- Resolve the requested branch/tag/revision to the commit SHA returned by Hugging Face and use that SHA for all subsequent tree and file requests.
- Collect repository file metadata, including LFS hashes and sizes when provided, without downloading binary artifacts.
- Download only bounded text artifacts explicitly needed for evidence extraction. The first implementation downloads `README.md` with a one-megabyte default limit.
- Keep the Hugging Face cache under `mot/.hf-cache` and exclude it from Git.
- Read access tokens only from a named environment variable; never accept them as CLI values or include them in reports.
- Convert SDK-specific responses and errors at the adapter boundary so connector and detector tests use local fakes.
- Treat model-card mentions as `mentioned_only`, not as proof that an artifact is released.

## Consequences

Collection is revision-pinned, bounded, testable, and avoids multi-gigabyte model downloads. The official SDK handles Hub API behavior while the rest of the evaluator remains isolated from SDK-specific types. Linked repositories, datasets, papers, and additional bounded text artifacts remain later work.
