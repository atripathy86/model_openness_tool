# ADR 0009: Bounded content-addressed documentation

- Status: Accepted
- Date: 2026-07-12

## Context

Model cards link project pages, API documentation, blog posts, and other web resources that can contain useful review evidence. Generic pages rarely map unambiguously to a particular MOF component, and unrestricted fetching creates payload, redirect, and local-network risks.

## Decision

- Fetch only public HTTP(S) documentation URLs with no embedded credentials and standard web ports.
- Block localhost and non-public literal IP addresses, and revalidate each redirect target before retrieval.
- Follow at most three redirects and accept at most one megabyte of text, Markdown, HTML, or XHTML content.
- Do not execute scripts or render pages. Strip script, style, and noscript content using a standard-library HTML parser.
- Identify each captured revision with the SHA-256 hash of its raw response body and retain normalized extracted text with a separate content hash.
- Record a retrievable documentation page as neutral source evidence with no component ID. Keep every MOF component `unknown` until a source-specific deterministic or reviewed semantic rule maps content to that artifact.
- Keep documentation following opt-in through `mot evaluate --follow-documentation`, with a default of three pages and hard CLI limit of ten.
- Include failed linked collections in the evaluation run, but merge only successful evidence reports using the primary report's component catalog hash.

## Consequences

Documentation becomes reproducible, bounded input for later reviewed or semantic extraction without inflating provisional component scores. The current URL checks block obvious local targets but are not a complete production SSRF defense against DNS rebinding; production deployment should enforce egress policy and destination-address validation at the network transport layer.
