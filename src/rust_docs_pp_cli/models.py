from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(slots=True)
class Example:
    language: str
    code: str


@dataclass(slots=True)
class Page:
    url: str
    title: str
    source: str
    section: str
    slug: str
    content: str
    headings: list[str] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)

    @property
    def id(self) -> str:
        return hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:24]


@dataclass(slots=True)
class SyncResult:
    source: str
    pages: int
    examples: int
    detail: str = ""
    truncated: bool = False

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "source": self.source,
            "pages_indexed": self.pages,
            "examples_stored": self.examples,
        }
        if self.detail:
            result["detail"] = self.detail
        if self.truncated:
            result["truncated"] = True
        return result
