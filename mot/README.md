# MOT Python Evaluator

This directory contains the Python implementation of the Model Openness Tool evaluator. It is developed and tested only with a local `uv` environment.

```bash
cd mot
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv sync
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run mot --help
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python uv run pytest
```

The current implementation is the scoring-parity foundation. It loads the versioned MOF component catalog, reads the existing MOT license sources, evaluates existing MOT YAML, and emits a deterministic JSON report. Hugging Face collection and evidence extraction will be added in later phases.
