"""프레임워크 지식베이스 — frameworks/ 폴더의 마크다운을 로드해 Claude 컨텍스트로 제공."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FrameworkDoc:
    name: str
    path: Path
    text: str


class KnowledgeBase:
    """frameworks/ 하위 모든 .md 를 재귀적으로 로드한다."""

    def __init__(self, frameworks_dir: Path):
        self.dir = frameworks_dir
        self.docs: list[FrameworkDoc] = []
        self._load()

    def _load(self) -> None:
        if not self.dir.exists():
            return
        for md in sorted(self.dir.rglob("*.md")):
            rel = md.relative_to(self.dir).as_posix()
            self.docs.append(
                FrameworkDoc(name=rel, path=md, text=md.read_text(encoding="utf-8"))
            )

    def is_empty(self) -> bool:
        return not self.docs

    def names(self) -> list[str]:
        return [d.name for d in self.docs]

    def as_context(self) -> str:
        """모든 프레임워크 문서를 하나의 컨텍스트 블록으로 결합."""
        parts = []
        for d in self.docs:
            parts.append(f"===== frameworks/{d.name} =====\n{d.text.strip()}")
        return "\n\n".join(parts)
