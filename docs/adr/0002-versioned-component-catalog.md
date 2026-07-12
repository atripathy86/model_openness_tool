# ADR 0002: Versioned component catalog and parity baseline

- Status: Accepted
- Date: 2026-07-12

## Context

The repository README describes 16 MOF components, while the current Drupal configuration at `web/modules/mof/config/install/mof.settings.yml` contains 17 entries. Scoring behavior depends on the configured component IDs, class assignments, required flags, and content types.

The evaluator must remain reproducible when the framework or application configuration changes.

## Decision

- Treat the current Drupal configuration as the implementation baseline for parity, without claiming that the 16-versus-17 discrepancy is resolved at the framework level.
- Package a versioned catalog snapshot at `mot/src/model_openness_tool/catalogs/mof-1.0.yaml`.
- Record the upstream source path and Git revision in the snapshot.
- Hash the catalog bytes and include the hash in every score report.
- Test that the packaged component fields match the Drupal source so drift cannot pass unnoticed.
- Load component counts from the catalog and never hard-code 16 or 17 in scoring logic.
- Require a reviewed catalog version/change when upstream component semantics change.

## Consequences

Python scoring can reproduce the current application while making the documentation/configuration discrepancy explicit. Catalog changes become reviewable data changes and old assessments remain attributable to the exact rules they used.
