"""Common source adapter contract.

Adapters discover, validate and parse source manifestations. They never promote
canonical identity directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class AdapterCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter_id: str = Field(min_length=1)
    artifact_types: tuple[str, ...] = Field(min_length=1)
    public: bool = True
    authentication_class: str = "NONE"
    supports_discovery: bool = True
    supports_incremental: bool = True


@dataclass(frozen=True)
class RawArtifact:
    source_family_id: str
    locator: str
    content: bytes
    media_type: str
    retrieved_at_iso: str
    http_status: int = 200


class SourceAdapter(Protocol):
    def capabilities(self) -> AdapterCapabilities: ...
    def discover(self, checkpoint: dict[str, Any] | None = None) -> list[str]: ...
    def validate_transport(self, artifact: RawArtifact) -> None: ...
    def fingerprint_schema(self, artifact: RawArtifact) -> str: ...
    def parse(self, artifact: RawArtifact) -> list[dict[str, Any]]: ...
