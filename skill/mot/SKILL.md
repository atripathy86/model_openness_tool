---
name: mot
description: Operate the Model Openness Tool (MOT) CLI to evaluate Hugging Face models against the Model Openness Framework, collect model/repository/dataset/paper evidence, explain Class I/II/III requirements and openness gaps, use optional MinerU or OpenAI-compatible extraction, review evidence, export reviewed MOT YAML, and run durable evaluation jobs. Use when a user asks for a model openness score, MOF classification, missing artifacts or licenses, reproducibility gaps, or help running MOT.
---

# Model Openness Tool

Use the MOT CLI to produce evidence-backed Model Openness Framework assessments. Do not
modify MOT source code. Do not reproduce the scorer in prompts.

## Prepare

1. Run `mot version`. If `mot` is unavailable, ask permission to install the current fork as
   an isolated uv tool. Use HTTPS by default:

   ```bash
   uv tool install \
     "git+https://github.com/atripathy86/model_openness_tool.git@main#subdirectory=mot"
   ```

   If the user requires SSH and already has GitHub SSH access configured, use:

   ```bash
   uv tool install \
     "git+ssh://git@github.com/atripathy86/model_openness_tool.git@main#subdirectory=mot"
   ```

   Run `uv tool dir --bin` if uv reports that its executable directory is not on `PATH`.
   Ask before running `uv tool update-shell` because it changes shell configuration. Then
   verify `mot version` and `mot catalog`. See [configuration](references/configuration.md)
   for pinned revisions, upgrades, checkout-based execution, and workspace setup.

2. Ask the user for a working directory for private configuration, caches, review databases,
   and reports. Create it if approved, work there, and do not place secrets in the installed
   skill directory.
3. Run `mot catalog` and retain its framework version and catalog hash with the result.
4. Read [configuration](references/configuration.md) when credentials, LLM extraction,
   MinerU, API service, or durable jobs may be needed.
5. Ask for any missing choices that affect the evaluation:
   - Hugging Face model ID;
   - revision, or permission to resolve the repository default revision;
   - whether to follow linked GitHub repositories, datasets, papers, and documentation;
   - maximum linked sources per type (default 3, allowed 0–10);
   - whether gated/private resources require user-provided credentials; and
   - output directory and filename.

Do not require LLM, MinerU, PostgreSQL, or API configuration for a basic public-model
evaluation.

## Evaluate

Run the deterministic base evaluation first and save its JSON:

```bash
mot evaluate <namespace/model> [--revision <revision>] \
  --output <model>-evaluation.json
```

If the user requests broader evidence, rerun with the approved source types and bounds:

```bash
mot evaluate <namespace/model> [--revision <revision>] \
  --follow-github --max-linked-github 3 \
  --follow-datasets --max-linked-datasets 3 \
  --follow-papers --max-linked-papers 3 \
  --follow-documentation --max-linked-documentation 3 \
  --output <model>-linked-evaluation.json
```

Omit source types the user does not want. Use exact CLI options from
[the CLI reference](references/cli.md). A nonzero collection exit can still produce a
structured gated, private, missing, or inaccessible result; inspect the saved JSON.

## Explain the result and improvement path

Read [MOF classification](references/mof-classification.md) before explaining a class or
recommending how to reach the next class.

For each class, report:

- satisfied required components;
- missing or unavailable artifacts;
- artifacts that are only mentioned;
- unlicensed, closed, ambiguous, or type-inappropriate licensing;
- confirmed score versus evidence-supported potential score; and
- the smallest concrete release or licensing changes that close the next-class gap.

Call automated output provisional. `mentioned_only` never proves release. Confidence never
changes a mention into a present artifact. Do not describe MOT output as certification or
legal advice.

## Review and export when requested

Follow [the CLI reference](references/cli.md) in this order:

1. `review-import-run` the exact saved evaluation.
2. `review-list --status pending` and present evidence URLs, revisions, paths, and claims.
3. Ask the human reviewer to supply accept/reject, reviewer identity, and rationale.
4. Record each supplied decision with `review-decide`.
5. Run `export-mot-yaml` against the same evaluation and review database.

Never decide on the user's behalf or invent reviewer details. Accepted mentions cannot create
components. Without an accepted component-scoped license, an accepted artifact exports as
`unlicensed`.

## Return results

Give the exact commands run, saved output paths, model revision, followed source types,
confirmed and potential outcomes, unresolved review items, and any inaccessible sources.
