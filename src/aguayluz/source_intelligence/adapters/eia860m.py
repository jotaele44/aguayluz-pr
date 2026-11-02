"""Offline-safe reference adapter for EIA-860M.

Network retrieval is intentionally outside this module so source bytes can be
frozen before parsing. This first implementation proves discovery, transport,
container validation and deterministic schema fingerprinting.
"""
from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

from .base import AdapterCapabilities, RawArtifact

SOURCE_FAMILY_ID = "EIA_860M"
INDEX_URL = "https://www.eia.gov/electricity/data/eia860m/"
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def canonical_month_url(month: str, year: int) -> str:
    value = month.strip().lower()
    if value not in MONTHS:
        raise ValueError(f"unknown month {month!r}")
    if year < 2018:
        raise ValueError("Puerto Rico monthly EIA-860M coverage starts in 2018")
    return (
        "https://www.eia.gov/electricity/data/eia860m/archive/xls/"
        f"{value}_generator{year}.xlsx"
    )


class EIA860MAdapter:
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id="eia860m",
            artifact_types=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            authentication_class="NONE",
        )

    def discover(self, checkpoint: dict[str, Any] | None = None) -> list[str]:
        checkpoint = checkpoint or {}
        year = int(checkpoint.get("year", 2026))
        months = checkpoint.get("months", MONTHS)
        return [canonical_month_url(str(month), year) for month in months]

    def validate_transport(self, artifact: RawArtifact) -> None:
        if artifact.http_status != 200:
            raise ValueError(f"unexpected HTTP status {artifact.http_status}")
        if "spreadsheetml.sheet" not in artifact.media_type.lower():
            raise ValueError(f"content type is not XLSX: {artifact.media_type}")
        if not artifact.content.startswith(b"PK"):
            raise ValueError("XLSX magic bytes missing")
        try:
            with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise ValueError("invalid XLSX ZIP container") from exc
        required = {
            "[Content_Types].xml",
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
        }
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"XLSX missing required members: {missing}")

    def _sheet_names(self, artifact: RawArtifact) -> tuple[str, ...]:
        self.validate_transport(artifact)
        with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
            root = ET.fromstring(archive.read("xl/workbook.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        names = tuple(node.attrib["name"] for node in root.findall(".//m:sheets/m:sheet", ns))
        if not names:
            raise ValueError("workbook contains no sheets")
        return names

    def fingerprint_schema(self, artifact: RawArtifact) -> str:
        payload = "\n".join(self._sheet_names(artifact)).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def parse(self, artifact: RawArtifact) -> list[dict[str, Any]]:
        """Emit workbook-structure observations only.

        Production row parsing remains gated on real workbook preamble/header
        inspection so Operating_PR and Retired_PR semantics are not guessed.
        """
        return [{"sheet_name": name} for name in self._sheet_names(artifact)]
