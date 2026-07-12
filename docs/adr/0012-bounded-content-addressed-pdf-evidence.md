# ADR 0012: Bounded content-addressed PDF evidence

## Status

Superseded by ADR 0013

## Context

Model cards sometimes link technical reports, papers, release notes, or other useful
documents directly as PDF files. The metadata-only arXiv and DOI connectors cannot
collect arbitrary PDF URLs, while treating every PDF as a research paper or technical
report would overstate what the link proves. PDF parsing also needs explicit resource,
redirect, and network-safety limits.

## Original decision

- Add `mot collect-pdf` and allow opt-in paper following to collect generic PDF links.
- Accept only public HTTP(S) URLs on standard web ports, validate every redirect, and
  block local or non-public literal network addresses.
- Accept only PDF content types and cap a response at 10 MB.
- Extract text with `pypdf` from at most the first 100 pages and retain at most 500,000
  normalized characters. Record warnings when either extraction limit is reached.
- Identify the immutable collection revision from the SHA-256 digest of the received
  PDF bytes and separately hash the normalized extracted text.
- Record the retrievable PDF as neutral evidence. Do not automatically classify it as
  a Research paper, Technical report, or any other MOF component until a deterministic
  source-specific or reviewed semantic rule establishes the artifact type.
- Reject image-only PDFs that have no extractable text in this phase. OCR is deferred.

`pypdf` is the only new runtime dependency. The uv lock currently resolves version
6.14.2, whose installed package metadata declares BSD-3-Clause and links to the active
`py-pdf/pypdf` issue tracker. It provides in-process text extraction without requiring a
system Poppler installation in operator environments.

## Consequences

Generic PDF links become bounded, auditable review evidence without inflating the
provisional MOF score. Text-only extraction does not preserve layout or establish the
meaning of diagrams and tables, so semantic extraction and visual/OCR handling remain
future work.
