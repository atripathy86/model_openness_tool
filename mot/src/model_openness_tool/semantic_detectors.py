"""Conservative deterministic mention extraction from bounded document text."""

from __future__ import annotations

import json
import re
from hashlib import sha256

from model_openness_tool.evidence import EvidenceClaim, EvidenceItem

SEMANTIC_MENTION_VERSION = "semantic-mentions-v1"
MAX_EXCERPT_CHARS = 240
MENTION_PATTERNS = {
    7: re.compile(r"\b(?:training|fine[- ]?tuning)\s+(?:code|script|repository)\b", re.I),
    8: re.compile(r"\b(?:inference|prediction|generation)\s+(?:code|script|example)\b", re.I),
    18: re.compile(r"\bevaluation\s+(?:code|script|harness|repository)\b", re.I),
    16: re.compile(r"\b(?:preprocessing|data processing)\s+(?:code|script|pipeline)\b", re.I),
    15: re.compile(r"\b(?:training|pretraining|fine[- ]?tuning)\s+(?:data|dataset|corpus)\b", re.I),
    19: re.compile(r"\b(?:evaluation|validation|test|benchmark)\s+(?:data|dataset|set)\b", re.I),
    12: re.compile(
        r"\b(?:evaluation results?|benchmark results?|accuracy|f1[- ]?score|perplexity)\b", re.I
    ),
    10: re.compile(r"\b(?:final\s+)?(?:model weights?|trained weights?|checkpoint)\b", re.I),
    24: re.compile(r"\b(?:intermediate|training)\s+checkpoints?\b", re.I),
    17: re.compile(
        r"\b(?:training configuration|training hyperparameters?|optimizer states?)\b", re.I
    ),
    20: re.compile(r"\b(?:sample|example)\s+(?:model\s+)?outputs?\b", re.I),
    14: re.compile(r"\bdata card\b", re.I),
    11: re.compile(r"\btechnical report\b", re.I),
    21: re.compile(r"\b(?:research paper|paper)\b", re.I),
}


def extract_semantic_mentions(
    text: str,
    *,
    snapshot_id: str,
    source_url: str,
    revision: str,
    path: str,
    extraction_method: str,
) -> tuple[EvidenceItem, ...]:
    evidence = []
    lines = text.splitlines() or [text]
    for component_id, pattern in MENTION_PATTERNS.items():
        match_line = next(
            (
                (line_number, line, match)
                for line_number, line in enumerate(lines, start=1)
                if (match := pattern.search(line)) is not None
            ),
            None,
        )
        if match_line is None:
            continue
        line_number, line, match = match_line
        excerpt = _bounded_excerpt(line, match.start(), match.end())
        locator = f"{path}#line-{line_number}"
        identity = json.dumps(
            {
                "snapshot": snapshot_id,
                "component": component_id,
                "claim": EvidenceClaim.ARTIFACT_MENTIONED.value,
                "locator": locator,
                "excerpt": excerpt,
                "method": extraction_method,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        evidence.append(
            EvidenceItem(
                evidence_id=sha256(identity.encode()).hexdigest(),
                component_id=component_id,
                claim=EvidenceClaim.ARTIFACT_MENTIONED,
                value=excerpt,
                source_url=source_url,
                revision=revision,
                path=locator,
                extraction_method=extraction_method,
                confidence=0.8,
                excerpt=excerpt,
            )
        )
    return tuple(evidence)


def _bounded_excerpt(line: str, start: int, end: int) -> str:
    normalized = " ".join(line.split())
    if len(normalized) <= MAX_EXCERPT_CHARS:
        return normalized
    original_prefix = len(" ".join(line[:start].split()))
    center = min(original_prefix + (end - start) // 2, len(normalized))
    window_start = max(0, center - MAX_EXCERPT_CHARS // 2)
    window_end = min(len(normalized), window_start + MAX_EXCERPT_CHARS)
    window_start = max(0, window_end - MAX_EXCERPT_CHARS)
    excerpt = normalized[window_start:window_end]
    return f"{'…' if window_start else ''}{excerpt}{'…' if window_end < len(normalized) else ''}"
