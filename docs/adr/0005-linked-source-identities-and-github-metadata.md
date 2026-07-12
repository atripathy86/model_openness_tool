# ADR 0005: Linked-source identities and GitHub metadata collection

- Status: Accepted
- Date: 2026-07-12

## Context

Model cards commonly link to source repositories, datasets, papers, and documentation. These links must be normalized before evidence can be correlated across sources. GitHub source repositories need immutable revision and file metadata without cloning or executing untrusted code.

## Decision

- Extract HTTP(S) links from bounded model-card content and classify supported GitHub repositories, Hugging Face datasets/models, arXiv/DOI/generic PDF papers, and documentation.
- Canonicalize identities and deduplicate them by source type and identifier.
- Reject GitHub navigation pages and non-repository inputs. Ignore common image/media links rather than treating them as documentation.
- Record unknown HTTP(S) pages as documentation candidates but do not fetch them automatically.
- Use GitHub's REST repository, commit, and recursive tree endpoints through the BSD-3-Clause-licensed HTTPX client.
- Resolve the default/requested revision to a commit SHA and use that SHA for the tree request and snapshot URL.
- Collect blob paths, sizes, and hashes only. Do not clone, download, import, build, or execute repository code in this stage.
- Reject truncated trees and enforce a 100,000-file limit rather than producing an incomplete snapshot.
- Read GitHub credentials only from `GITHUB_TOKEN` or another named environment variable and never include credentials in output.

## Consequences

Linked identities and GitHub manifests are deterministic, bounded, and safe to inspect. A later Phase 3 change can run source-specific detectors over these pinned manifests and merge their evidence into the model assessment. Dataset, paper, and documentation retrieval remain separate connectors with their own access and size policies.
