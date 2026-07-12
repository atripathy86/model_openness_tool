"""Conservative linked-source extraction and canonical identity normalization."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from model_openness_tool.evidence import LinkedSource, LinkedSourceType, TextArtifact

URL_PATTERN = re.compile(r"https?://[^\s<>\]\[(){}\"']+")
GITHUB_RESERVED_OWNERS = frozenset(
    {
        "about",
        "collections",
        "customer-stories",
        "enterprise",
        "features",
        "login",
        "marketplace",
        "organizations",
        "orgs",
        "pricing",
        "search",
        "settings",
        "sponsors",
        "topics",
    }
)
NON_DOCUMENT_SUFFIXES = (".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp")


def extract_linked_sources(model_card: TextArtifact | None) -> tuple[LinkedSource, ...]:
    if model_card is None:
        return ()
    sources: dict[tuple[LinkedSourceType, str], LinkedSource] = {}
    for match in URL_PATTERN.finditer(model_card.content):
        raw_url = match.group(0).rstrip(".,;:!?")
        source = normalize_linked_source(raw_url, discovered_in=model_card.path)
        if source is None:
            continue
        key = (source.source_type, source.identifier.casefold())
        sources.setdefault(key, source)
    return tuple(sorted(sources.values(), key=lambda item: (item.source_type, item.identifier)))


def normalize_linked_source(url: str, *, discovered_in: str) -> LinkedSource | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").casefold()
    parts = [unquote(part) for part in parsed.path.split("/") if part]

    if host in {"github.com", "www.github.com"}:
        return _github_source(parts, discovered_in)
    if host in {"huggingface.co", "www.huggingface.co"}:
        return _huggingface_source(parts, discovered_in)
    if host in {"arxiv.org", "www.arxiv.org"}:
        return _arxiv_source(parts, discovered_in)
    if host in {"doi.org", "dx.doi.org"} and parts:
        identifier = "/".join(parts)
        return LinkedSource(
            source_type=LinkedSourceType.PAPER,
            identifier=f"doi:{identifier}",
            canonical_url=f"https://doi.org/{identifier}",
            discovered_in=discovered_in,
            confidence=0.98,
        )
    if parsed.path.casefold().endswith(NON_DOCUMENT_SUFFIXES):
        return None
    if parsed.path.casefold().endswith(".pdf"):
        return LinkedSource(
            source_type=LinkedSourceType.PAPER,
            identifier=url,
            canonical_url=url,
            discovered_in=discovered_in,
            confidence=0.75,
        )
    return LinkedSource(
        source_type=LinkedSourceType.DOCUMENTATION,
        identifier=url,
        canonical_url=url,
        discovered_in=discovered_in,
        confidence=0.6,
    )


def normalize_github_repository(url: str) -> LinkedSource | None:
    source = normalize_linked_source(url, discovered_in="direct-input")
    if source is None or source.source_type != LinkedSourceType.GITHUB_REPOSITORY:
        return None
    return source


def normalize_arxiv_paper(value: str) -> LinkedSource | None:
    candidate = value.strip()
    if candidate.casefold().startswith("arxiv:"):
        candidate = candidate.split(":", maxsplit=1)[1]
    if "://" not in candidate:
        candidate = f"https://arxiv.org/abs/{candidate}"
    source = normalize_linked_source(candidate, discovered_in="direct-input")
    if source is None or source.source_type != LinkedSourceType.PAPER:
        return None
    if not source.identifier.startswith("arxiv:"):
        return None
    return source


def dataset_sources_from_ids(
    dataset_ids: tuple[str, ...],
    *,
    discovered_in: str,
) -> tuple[LinkedSource, ...]:
    sources = {}
    for dataset_id in dataset_ids:
        identifier = dataset_id.strip().strip("/")
        if not identifier or identifier.startswith("http://") or identifier.startswith("https://"):
            continue
        source = LinkedSource(
            source_type=LinkedSourceType.HUGGINGFACE_DATASET,
            identifier=identifier,
            canonical_url=f"https://huggingface.co/datasets/{identifier}",
            discovered_in=discovered_in,
            confidence=0.95,
        )
        sources[identifier.casefold()] = source
    return tuple(sorted(sources.values(), key=lambda item: item.identifier))


def _github_source(parts: list[str], discovered_in: str) -> LinkedSource | None:
    if len(parts) < 2 or parts[0].casefold() in GITHUB_RESERVED_OWNERS:
        return None
    owner = parts[0]
    repository = parts[1].removesuffix(".git")
    if not owner or not repository:
        return None
    identifier = f"{owner}/{repository}"
    return LinkedSource(
        source_type=LinkedSourceType.GITHUB_REPOSITORY,
        identifier=identifier,
        canonical_url=f"https://github.com/{identifier}",
        discovered_in=discovered_in,
        confidence=0.98,
    )


def _huggingface_source(parts: list[str], discovered_in: str) -> LinkedSource | None:
    if not parts:
        return None
    if parts[0].casefold() == "datasets":
        if len(parts) < 2:
            return None
        identifier = "/".join(parts[1:3]) if len(parts) >= 3 else parts[1]
        return LinkedSource(
            source_type=LinkedSourceType.HUGGINGFACE_DATASET,
            identifier=identifier,
            canonical_url=f"https://huggingface.co/datasets/{identifier}",
            discovered_in=discovered_in,
            confidence=0.95,
        )
    if len(parts) < 2 or parts[0] in {"docs", "spaces", "tasks"}:
        return None
    identifier = "/".join(parts[:2])
    return LinkedSource(
        source_type=LinkedSourceType.HUGGINGFACE_MODEL,
        identifier=identifier,
        canonical_url=f"https://huggingface.co/{identifier}",
        discovered_in=discovered_in,
        confidence=0.9,
    )


def _arxiv_source(parts: list[str], discovered_in: str) -> LinkedSource | None:
    if len(parts) < 2 or parts[0].casefold() not in {"abs", "pdf"}:
        return None
    identifier = "/".join(parts[1:]).removesuffix(".pdf")
    return LinkedSource(
        source_type=LinkedSourceType.PAPER,
        identifier=f"arxiv:{identifier}",
        canonical_url=f"https://arxiv.org/abs/{identifier}",
        discovered_in=discovered_in,
        confidence=0.98,
    )
