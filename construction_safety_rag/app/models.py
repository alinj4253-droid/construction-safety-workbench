from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List


@dataclass
class Document:
    doc_id: str
    title: str
    issuer: str
    document_no: str
    level: str
    jurisdiction: str
    effective_from: str
    effective_to: str
    status: str
    source_url: str
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    issuer: str
    document_no: str
    status: str
    source_url: str
    section: str
    text: str
    tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
