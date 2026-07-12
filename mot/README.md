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

Collect a revision-pinned Hugging Face dataset manifest and bounded dataset-card/license files without downloading released data:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-dataset https://huggingface.co/datasets/openai/gsm8k \
  --output gsm8k-dataset-evidence.json
```

Structured dataset references and dataset links discovered in a model card can be followed during evaluation:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate distilbert/distilbert-base-uncased-finetuned-sst-2-english \
  --repository-root .. --follow-datasets \
  --output distilbert-linked-evaluation.json
```

Dataset following is opt-in and follows at most three unique datasets by default, with a hard CLI limit of ten. Dataset manifests can prove that released data and a data card exist, while exact training use, provenance, preprocessing, and license applicability remain review questions. When several linked datasets declare different licenses, the combined component license is reported as ambiguous rather than selecting one automatically.

Collect version-pinned arXiv metadata without downloading a paper PDF:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-paper 1810.04805 --output bert-paper-evidence.json
```

Follow arXiv papers discovered in a Hugging Face model card and merge them into the provisional assessment:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate google-bert/bert-base-uncased --repository-root .. \
  --follow-papers --output bert-paper-evaluation.json
```

Paper following is opt-in and follows at most three unique arXiv papers by default, with a hard CLI limit of ten. A resolved paper can prove only the Research paper component. Its metadata does not prove that a separate technical report, source code, data, or evaluation artifact has been released. DOI and generic PDF links remain discovery candidates but are not fetched by this arXiv-only connector.

Collect a bounded, content-addressed snapshot of a public documentation page:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-doc https://huggingface.co/docs/transformers/model_doc/bert \
  --output bert-documentation-evidence.json
```

Follow documentation pages discovered in a Hugging Face model card:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate google-bert/bert-base-uncased --repository-root .. \
  --follow-documentation --output bert-documentation-evaluation.json
```

Documentation following is opt-in and follows at most three unique pages by default, with a hard CLI limit of ten. The connector accepts bounded public HTTP(S) text, Markdown, and HTML, validates redirects, blocks local or non-public literal addresses, strips active HTML content, and identifies the captured revision by its content hash. A retrievable generic page is retained as review evidence but does not automatically satisfy any MOF component.
