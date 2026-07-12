# AGENTS.md

## Scope

These instructions apply to the entire repository. More specific `AGENTS.md` files may be added in subdirectories later; when present, the closest file to the code being changed takes precedence.

## Project direction

This fork extends the Model Openness Tool (MOT) with an AI-assisted evaluator for Hugging Face models and linked resources. Read `AI_MOF_EVALUATOR_PLAN.md` before making architectural or feature changes.

The goal is an evidence-backed evaluator, not a model-card keyword scorer. The system must distinguish an artifact that is actually available under an applicable open license from an artifact that is merely mentioned.

## Git and approval rules

- Treat `origin` (`git@github.com:lfai/model_openness_tool.git`) as the upstream, read-only repository.
- Treat `fork` (`git@github.com:atripathy86/model_openness_tool.git`) as the development remote.
- Never push to `origin`.
- Do not force-push, rewrite history, rebase shared branches, or delete branches unless the user explicitly approves that operation.
- **Do not create any commit without the user's explicit approval.** Approval to edit files, run tests, or continue development is not approval to commit.
- Before requesting commit approval, provide:
  - a concise summary of the proposed commit;
  - the proposed commit message;
  - the files/diff to be included;
  - tests run and their results; and
  - any known limitations or follow-up work.
- After presenting the proposed commit, wait for explicit approval before running `git commit`.
- Commits must use `atripathy86 <atripathy86@gmail.com>` as author and committer.
- Contributions require DCO sign-off. Use `git commit -s` so the commit contains `Signed-off-by: atripathy86 <atripathy86@gmail.com>`.
- Do not push commits unless the user explicitly asks for a push. When asked, push only to `fork` unless the user explicitly changes this policy.
- Keep unrelated user changes out of proposed commits.

## Architecture boundaries

- Keep the existing Drupal/PHP application operational. It remains the reference implementation and current presentation/import layer.
- Build the new evaluator as a testable Python subsystem rather than embedding crawling, evidence extraction, or LLM calls in Drupal.
- Preserve compatibility with `schema/mof_schema.json` and existing `models/*.yml` records.
- Use these current sources of truth during the parity phase:
  - `web/modules/mof/src/ModelEvaluator.php` for classification and progress behavior;
  - `web/modules/mof/src/ComponentManager.php` and `web/modules/mof/config/install/mof.settings.yml` for component definitions;
  - `web/modules/mof/src/LicenseHandler.php`, `web/modules/mof/licenses.json`, and `web/modules/mof/mof-licenses.json` for license behavior;
  - `schema/mof_schema.json` and `schema/sample_model.yml` for MOT YAML compatibility;
  - `Test_Data/` and `scripts/test-model-files.php` for scoring regression cases; and
  - `tools-py/model_scraper.py` and `tools-py/find_missing_models.py` as ingestion prototypes, not as authoritative scoring logic.
- Do not silently change MOF semantics while porting them. Record suspected defects or specification ambiguities, add tests that expose them, and separate parity changes from intentional behavior changes.
- Do not hard-code the number of MOF components. Load the versioned component catalog; the current repository documentation and configuration are not fully consistent on the count.

## Evidence and scoring requirements

- Every affirmative component decision must cite retrievable evidence: source URL, repository revision when available, file path or document section, retrieval time, and extraction method.
- Keep source observations separate from deterministic MOF decisions.
- Keep confidence separate from status. Confidence must not turn “mentioned” or “unknown” into “present.”
- Use explicit states such as `present`, `mentioned_only`, `absent`, `unknown`, and `inaccessible`; map them to `satisfied`, `not_satisfied`, or `review_required` in a separate decision step.
- License identity, applicability, openness, and type appropriateness are separate questions and must retain separate evidence.
- A model card statement that a dataset, script, paper, or result exists is not proof that the artifact is released or openly licensed.
- Report provisional and verified outcomes distinctly. Never present a provisional automated classification as a definitive MOF classification.
- LLM output is untrusted structured evidence extraction. Validate it against schemas and deterministic rules, retain source citations, and make it reviewable.
- Prefer deterministic detectors for repository files and metadata before LLM extraction.

## Python development conventions

- Treat `MOT` as the product name and `mot` as the CLI command. Use `model-openness-tool` for the Python distribution and `model_openness_tool` for the import package because the `mot` distribution name is already occupied on PyPI.
- Keep the Python project in `mot/` and use `uv` for every environment, dependency, build, lint, type-check, and test operation.
- Keep the uv environment and caches local to `mot/`. Use `mot/.venv`, `mot/.uv-cache`, and `mot/.uv-python`; do not install project dependencies into the system Python or a global environment.
- Run Python tooling from `mot/` with local uv paths, for example: `UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv sync` and `UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run pytest`.
- New production Python code should live in a proper package with a `pyproject.toml`; do not continue growing a single monolithic script.
- Use type hints and Pydantic models at external and persistence boundaries.
- Keep connectors, extraction, evidence normalization, license analysis, scoring, persistence, orchestration, API, and reporting as separable layers.
- Network access must be injectable/mockable. Unit tests must not depend on live Hugging Face, GitHub, paper, LLM, or license services.
- Store test fixtures that are small, attributable, and legally suitable. Do not check in model weights, credentials, access tokens, or large scraped snapshots.
- Secrets must come from environment variables or an approved secret store. Never print or persist tokens in reports or logs.
- Use bounded concurrency, timeouts, retries with backoff, caching, and source-specific rate-limit handling.
- Ensure generated output is deterministic for the same evidence snapshot, framework version, and rule version.

## Existing application conventions

- PHP changes should follow the existing Drupal module structure and Drupal coding standards.
- Model YAML must validate against `schema/mof_schema.json`.
- Preserve existing model data unless the task specifically calls for changing it.
- Avoid editing generated or vendored dependencies directly.

## Verification

Run the smallest relevant checks during development, followed by broader checks before proposing a commit.

For existing MOT changes, relevant checks include:

```bash
composer validate
php scripts/validate-model.php models/<model>.yml
vendor/bin/drush scr scripts/test-model-files.php
```

The Drupal scoring regression command requires a configured local Drupal installation. If it cannot be run, state that explicitly.

For end-to-end UI changes:

```bash
cd tests-e2e
npx playwright test
```

For the new Python subsystem, provide formatter, linter, type-check, unit-test, and coverage commands through `pyproject.toml` and document the canonical commands once introduced. Tests should include:

- parity fixtures derived from `Test_Data/`;
- deterministic component and license rules;
- parser and connector fixtures with mocked network responses;
- schema round trips for evidence JSON and MOT YAML; and
- failure cases for missing, gated, ambiguous, and contradictory evidence.

Do not claim a check passed unless it was actually run. Report skipped checks and the reason.

## Documentation and change discipline

- Update `AI_MOF_EVALUATOR_PLAN.md` when an architectural decision, milestone, or scope assumption changes.
- Add Architecture Decision Records for choices that are difficult to reverse, especially framework-version handling, storage schema, LLM provider strategy, and changes to MOF semantics.
- Keep pull requests and proposed commits focused and reviewable.
- Prefer tests and documentation in the same proposed commit as the behavior they cover.
- Do not add a dependency without documenting why it is needed and checking its license and maintenance posture.

## Agent Skill deliverable

- After the `mot` CLI actions are implemented and stable, create an Agent Skills specification-compliant skill at `skill/mot/`.
- The required entry point is `skill/mot/SKILL.md` with `name: mot`; the directory name and frontmatter name must match.
- The skill should teach agents to use the CLI rather than duplicate evaluator logic. Keep deterministic behavior in the CLI/package.
- Follow progressive disclosure: keep `SKILL.md` concise and place detailed CLI/reference material under `skill/mot/references/` only when needed.
- Validate the finished skill with both the local skill-creator validator and the official `skills-ref validate ./skill/mot` command when available.
- Do not create the skill prematurely from unstable or placeholder CLI behavior.
