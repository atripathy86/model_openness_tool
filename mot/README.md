# MOT Python Evaluator

This directory contains the Python implementation of the Model Openness Tool evaluator. It is developed and tested only with a local `uv` environment.

```bash
cd mot
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv sync
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run mot --help
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run pytest
```

The current implementation includes the scoring-parity foundation and the first Hugging Face evidence collector. It loads the versioned MOF component catalog, reads the existing MOT license sources, evaluates existing MOT YAML, and collects revision-pinned repository evidence.

Collect a revision-pinned Hugging Face repository snapshot without downloading model weights:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect openai-community/gpt2 --output gpt2-evidence.json
```

For gated repositories, put the token in `HF_TOKEN` or name a different environment variable with `--token-env`. Do not pass tokens as command-line arguments.

Create a provisional assessment from a saved collection report:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot assess gpt2-evidence.json --repository-root .. \
  --output gpt2-assessment.json
```

Or collect and assess in one command:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate openai-community/gpt2 --repository-root .. \
  --output gpt2-evaluation.json
```

Automated results distinguish a conservative confirmed score from an evidence-supported potential score. Model-card mentions and unknown components never enter the potential score, and ambiguous license scope prevents an automated result from being labeled verified.

Model-card evidence reports also list normalized linked GitHub repositories, Hugging Face datasets/models, papers, and documentation candidates. Collect a pinned GitHub file manifest without cloning or executing the repository:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-github https://github.com/openai/gpt-2 \
  --output openai-gpt2-source.json
```

Use `GITHUB_TOKEN` for private repositories or higher API limits, or select another environment variable with `--token-env`. Tokens are never accepted as CLI values or written to reports.

To follow up to three discovered GitHub repositories and merge their pinned source evidence into the provisional assessment:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate openai-community/gpt2 --repository-root .. \
  --follow-github --output gpt2-linked-evaluation.json
```

GitHub following is opt-in. Deterministic source rules detect explicit architecture, training, inference, evaluation, preprocessing, and dependency filenames while excluding test directories. Linked evidence can raise only the evidence-supported potential score; license scope still requires review before any verified classification.
