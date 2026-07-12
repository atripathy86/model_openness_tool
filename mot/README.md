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

To inspect a source repository with GitHub-identified SPDX license metadata:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-github https://github.com/huggingface/transformers \
  --output transformers-source.json
```

Use `GITHUB_TOKEN` for private repositories or higher API limits, or select another environment variable with `--token-env`. Tokens are never accepted as CLI values or written to reports.

To follow up to three discovered GitHub repositories and merge their pinned source evidence into the provisional assessment:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate openai-community/gpt2 --repository-root .. \
  --follow-github --output gpt2-linked-evaluation.json
```

GitHub following is opt-in. Deterministic source rules detect explicit architecture, training, inference, evaluation, preprocessing, and dependency filenames while excluding test directories. When GitHub identifies the repository license, its SPDX ID is attached only to the matched source-code components. Linked evidence can raise only the evidence-supported potential score; human review is still required before any verified classification.

Inspect a repository whose root license text supplies evidence when GitHub does not report an SPDX identifier:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-github https://github.com/openai/gpt-2 \
  --output gpt2-source-license-evidence.json
```

The connector retrieves only pinned root `LICENSE`/`COPYING` text variants, capped at 128,000 bytes each. Deterministic full-text matching currently recognizes MIT, Apache-2.0, and BSD-3-Clause. Unknown, abbreviated, custom, or conflicting license text remains review-required.

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

Collect bounded paper metadata without downloading a paper PDF. arXiv papers are
version-pinned by their arXiv version, while DOI papers are content-addressed from
Crossref metadata:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-paper 1810.04805 --output bert-paper-evidence.json
```

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-paper https://doi.org/10.18653/v1/N19-1423 \
  --output bert-doi-paper-evidence.json
```

Follow arXiv papers discovered in a Hugging Face model card and merge them into the provisional assessment:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot evaluate google-bert/bert-base-uncased --repository-root .. \
  --follow-papers --output bert-paper-evaluation.json
```

Paper following is opt-in and follows at most three unique arXiv, DOI, or generic PDF sources by default, with a hard CLI limit of ten. A resolved arXiv or DOI paper can prove only the Research paper component. Its metadata does not prove that a separate technical report, source code, data, or evaluation artifact has been released. A generic PDF is retained as neutral review evidence and does not automatically satisfy any MOF component.

Collect bounded, content-addressed text from a public PDF:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-pdf \
  https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf \
  --mineru-url http://127.0.0.1:30000 \
  --output dummy-pdf-evidence.json
```

PDF collection accepts at most 10 MB, sends at most the first 100 pages through the uv-installed MinerU `vlm-http-client`, retains at most 500,000 Markdown characters, validates source redirects, and blocks local or non-public literal source addresses. Set `MINERU_SERVER_URL` instead of `--mineru-url` when preferred. The VLM service is externally provided and MOT does not launch or download it.

When MinerU or its VLM service is unavailable, collection falls back to bounded `pypdf` text extraction. The snapshot records `pypdf-fallback` and includes the MinerU failure in its warnings, so lower-fidelity evidence is never silent. Pass `--no-pdf-fallback` to require MinerU success.

The optional `--backend hybrid-http-client` mode requires installing `mineru[pipeline]` into the same local uv environment. The default VLM client and `pypdf` fallback do not require local Torch. Generic PDF Markdown or fallback text remains neutral review evidence and cannot automatically satisfy a MOF component.

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

Collect documentation with deterministic, cited artifact mentions:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot collect-doc https://huggingface.co/docs/transformers/training \
  --output transformers-training-documentation-evidence.json
```

Documentation and PDF text can emit line-cited `artifact_mentioned` evidence for explicit phrases such as training code, preprocessing pipeline, training dataset, checkpoints, and evaluation results. These findings remain `mentioned_only`: they do not prove that an artifact is released, do not enter the potential score, and cannot satisfy a MOF component.

Request schema-validated LLM evidence proposals from an OpenAI-compatible endpoint:

```bash
UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python \
  uv run mot extract-llm transformers-training-documentation-evidence.json \
  --output transformers-training-llm-proposals.json
```

Set `OPENAI_BASE_URL` for the OpenAI-compatible endpoint and, when authentication is required, set `OPENAI_API_KEY`. The key is optional for unauthenticated local endpoints and is never persisted. `--base-url` can override the environment at runtime without placing a deployment value in project documentation. If `--model` is omitted, MOT discovers the first model reported by the endpoint. Provider output must pass the extraction schema and exact line-citation validation. Accepted proposals are recorded only as review-required `artifact_mentioned` evidence; rejected citations remain visible in the report, and no LLM proposal directly affects a MOF score.
