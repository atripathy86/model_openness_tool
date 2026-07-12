# ADR 0013: MinerU remote PDF extraction

## Status

Accepted

## Context

The initial generic PDF connector used `pypdf` text extraction. That is deterministic
and lightweight but loses document reading order and does not adequately represent
tables, formulas, scanned pages, images, or complex layouts. These are common in model
papers and technical reports and materially affect later evidence extraction.

MinerU produces Markdown and structured content lists, supports OCR and visual document
parsing, and provides lightweight HTTP-client modes for externally hosted inference.

## Decision

- Replace direct `pypdf` extraction with the uv-installed MinerU CLI.
- Default to `vlm-http-client` and assume an OpenAI-compatible MinerU VLM service is
  supplied separately. The default URL is `http://127.0.0.1:30000`; operators can set
  `MINERU_SERVER_URL` or pass `--mineru-url`.
- Permit `hybrid-http-client` as an explicit backend, while documenting that it requires
  the separate `mineru[pipeline]` extra and local pipeline dependencies.
- Invoke MinerU without a shell, impose a 600-second process timeout, and request at
  most the first 100 pages.
- Require exactly one Markdown result and one `content_list_v2.json` result. Retain at
  most 500,000 Markdown characters and record extraction limits as warnings.
- If the MinerU client, VLM service, or MinerU extraction is unavailable, use bounded
  `pypdf` text extraction by default. Record `pypdf-fallback` as the actual backend and
  preserve the MinerU failure in snapshot warnings. Operators can disable this with
  `--no-pdf-fallback` when reduced-fidelity evidence is unacceptable.
- Continue hashing the downloaded PDF bytes and extracted Markdown separately. Record
  the MinerU backend and installed client version in the evidence snapshot.
- Keep generic PDF evidence neutral until a later reviewed semantic rule identifies the
  document as a particular MOF artifact.

## Dependency and service boundary

The base `mineru` package and direct `pypdf` fallback dependency are installed through
the local uv lock. MinerU supports the
lightweight `vlm-http-client` without local Torch. MinerU 3.x declares the custom
`LicenseRef-MinerU-Open-Source-License`, described by its maintainers as based on Apache
2.0 with additional conditions. Adoption and redistribution of the dependency must
therefore continue to be reviewed against project policy; it must not be represented as
an OSI-approved Apache-2.0 dependency.

The VLM inference server is operational infrastructure, not part of MOT. MOT does not
download or launch the model, and tests replace the extractor with an injected fake.

## Consequences

PDF evidence can preserve substantially more layout and semantic structure, including
tables and OCR-derived text, while keeping GPU inference outside the MOT process. Live
collection now depends on MinerU client compatibility and availability of the configured
remote service. A missing or failed service produces explicitly labeled lower-fidelity
fallback evidence by default, or structured failure when fallback is disabled.
