# ADR 0014: Bounded GitHub license-text evidence

## Status

Accepted

## Context

GitHub repository metadata sometimes omits `license.spdx_id` even when a pinned source
repository contains a conventional root license file. File presence alone does not
identify the license, and downloading arbitrary repository content would weaken the
metadata-first collection boundary.

## Decision

- Fetch only root `LICENSE`, `COPYING`, and `.md`/`.txt` variants already present in the
  pinned Git tree, using the immutable blob identifier.
- Limit each selected license file to 128,000 bytes, normalize it as UTF-8 review text,
  and retain a SHA-256 content hash in the GitHub snapshot.
- Initially recognize only unambiguous full-text markers for MIT, Apache-2.0, and
  BSD-3-Clause. Partial headers, short notices, custom terms, and unknown texts remain
  unidentified.
- Attach a text-identified license only to source components independently detected in
  that same pinned GitHub repository. License text never creates component availability.
- Prefer GitHub SPDX metadata when text is unidentified or agrees. If GitHub metadata and
  the deterministic text match disagree, attach neither result automatically and require
  review.
- Do not infer that a root repository license governs model weights, datasets, papers,
  documentation, linked repositories, or any other separately distributed artifact.

## Consequences

Source repositories without GitHub SPDX metadata can provide stronger, path-specific
license evidence while retaining conservative applicability. The deliberately small
matcher has false negatives and will grow only through reviewed patterns and regression
fixtures. It is not a general legal document classifier and does not provide legal advice.
