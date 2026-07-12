"""MOT license catalog loading and parity-compatible license decisions."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from model_openness_tool.domain import ContentType

OPEN_DATA_LICENSES = frozenset(
    {
        "CC0-1.0",
        "CC-BY-1.0",
        "CC-BY-2.0",
        "CC-BY-2.5",
        "CC-BY-2.5-AU",
        "CC-BY-3.0",
        "CC-BY-3.0-AT",
        "CC-BY-3.0-AU",
        "CC-BY-3.0-DE",
        "CC-BY-3.0-IGO",
        "CC-BY-3.0-NL",
        "CC-BY-3.0-US",
        "CC-BY-4.0",
        "CC-BY-SA-1.0",
        "CC-BY-SA-2.0",
        "CC-BY-SA-2.0-UK",
        "CC-BY-SA-2.1-JP",
        "CC-BY-SA-2.5",
        "CC-BY-SA-3.0",
        "CC-BY-SA-3.0-AT",
        "CC-BY-SA-4.0",
        "CDLA-Permissive-1.0",
        "CDLA-Permissive-2.0",
        "CDLA-Sharing-1.0",
        "ODC-PDDL-1.0",
        "ODC-By-1.0",
        "ODbL-1.0",
        "GFDL-1.3",
        "OGL-Canada-2.0",
        "OGL-UK-2.0",
        "OGL-UK-3.0",
    }
)
OPEN_LICENSES = frozenset({"OpenMDW-1.0"})


class LicenseRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    license_id: str
    name: str
    osi_approved: bool = False
    fsf_libre: bool = False
    deprecated: bool = False
    content_types: frozenset[ContentType] = Field(default_factory=frozenset)


class LicenseRegistry:
    def __init__(self, records: dict[str, LicenseRecord], catalog_sha256: str) -> None:
        self._records = records
        self.catalog_sha256 = catalog_sha256

    @classmethod
    def from_mot_files(cls, spdx_path: Path, mof_path: Path) -> LicenseRegistry:
        records: dict[str, LicenseRecord] = {}
        digest = sha256()

        for path in (spdx_path, mof_path):
            raw = path.read_bytes()
            digest.update(path.name.encode())
            digest.update(b"\0")
            digest.update(raw)
            payload: Any = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get("licenses"), list):
                raise ValueError(f"Invalid MOT license catalog: {path}")

            for item in payload["licenses"]:
                if not isinstance(item, dict):
                    raise ValueError(f"Invalid license entry in {path}")
                raw_content_types = item.get("ContentType", [])
                if isinstance(raw_content_types, str):
                    raw_content_types = [raw_content_types]
                content_types = frozenset(
                    ContentType(value)
                    for value in raw_content_types
                    if value in {member.value for member in ContentType}
                )
                record = LicenseRecord(
                    license_id=item["licenseId"],
                    name=item["name"],
                    osi_approved=bool(item.get("isOsiApproved", False)),
                    fsf_libre=bool(item.get("isFsfLibre", False)),
                    deprecated=bool(item.get("isDeprecatedLicenseId", False)),
                    content_types=content_types,
                )
                records[record.license_id] = record

        return cls(records=records, catalog_sha256=digest.hexdigest())

    def record(self, license_id: str) -> LicenseRecord | None:
        return self._records.get(license_id)

    def is_open(self, license_id: str) -> bool:
        record = self.record(license_id)
        return bool(
            (record and (record.osi_approved or record.fsf_libre))
            or license_id in OPEN_DATA_LICENSES
            or license_id in OPEN_LICENSES
        )

    def is_type_appropriate(self, license_id: str, content_type: ContentType) -> bool:
        record = self.record(license_id)
        return bool(record and content_type in record.content_types)
