# ADR 0010: Content-Addressed DOI Paper Metadata

## Status

Accepted

## Context

Model cards frequently cite papers through DOI links. Earlier paper collection supported
arXiv identifiers only, which left DOI links as discovery candidates that could not be
resolved by `mot collect-paper` or `mot evaluate --follow-papers`.

The evaluator needs DOI support without expanding the phase into generic PDF fetching,
publisher scraping, or full text extraction.

## Decision

Add a Crossref-backed DOI connector that retrieves bounded work metadata for DOI
references. The connector records title, authors, abstract when available, published
timestamp, updated/deposited timestamp, license URL when Crossref declares one, and the
canonical DOI URL.

Crossref metadata does not provide an immutable paper revision equivalent to arXiv
version IDs. DOI paper snapshots therefore use a deterministic SHA-256 hash of the
normalized Crossref work metadata as `resolved_revision`.

DOI metadata can satisfy only the Research paper component. It does not prove that a
separate technical report, source code, data, model weights, evaluation code, or PDF is
released.

## Boundaries

- Do not download publisher PDFs.
- Do not render or scrape publisher pages.
- Do not treat DOI landing pages as license evidence unless Crossref metadata declares
  a license URL.
- Do not infer that a cited paper's described artifacts are available.
- Preserve unresolved or unsupported generic PDF links as discovery candidates for a
  later phase.

## Consequences

`mot collect-paper` now accepts arXiv IDs/URLs, DOI URLs, `doi:` identifiers, and bare
DOI identifiers. `mot evaluate --follow-papers` follows both arXiv and DOI candidates,
up to the existing bounded linked-paper limit.
