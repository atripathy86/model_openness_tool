# ADR 0001: Python package, CLI naming, and uv workflow

- Status: Accepted
- Date: 2026-07-12

## Context

MOT needs a Python subsystem for evidence collection and deterministic MOF evaluation without moving that logic into Drupal. The product needs a short operator-facing command, a publishable distribution name, and a top-level import that does not collide with unrelated software.

The `mot` name is already registered on PyPI by the unrelated Multi-threaded Optimization Toolbox.

## Decision

- Keep **MOT** as the product name and use **`mot`** as the CLI executable.
- Name the Python distribution **`model-openness-tool`**.
- Name the Python import package **`model_openness_tool`**.
- Keep the uv project in the repository's `mot/` directory.
- Use Python 3.12 or newer.
- Use uv for the managed Python runtime, local `.venv`, lockfile, builds, linting, type checking, and tests.
- Keep uv state local to `mot/` through `.uv-cache`, `.uv-python`, and `.venv`.
- Keep Drupal as the current application and reference implementation while Python parity is established.

## Consequences

The CLI retains the concise MOT name without creating a PyPI/import collision. Contributors use one reproducible Python toolchain and do not need to install dependencies into system Python. The distribution name remains descriptive when discovered independently of this repository.
