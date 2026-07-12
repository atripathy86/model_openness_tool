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
