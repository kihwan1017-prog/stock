"""저장소 매뉴얼 기반 읽기 전용 문서 CMS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, status


# 프로젝트 루트: src/stock_platform/operation/ -> ../../../
_REPO_ROOT = Path(__file__).resolve().parents[3]

# 허용 루트 (경로 탈출 방지)
_ALLOWED_ROOTS: tuple[Path, ...] = (
    (_REPO_ROOT / "docs" / "manual").resolve(),
    (_REPO_ROOT / "docs" / "deployment").resolve(),
    (_REPO_ROOT / "docs" / "trading").resolve(),
    (_REPO_ROOT / "docs" / "backend").resolve(),
)


@dataclass(frozen=True, slots=True)
class DocListItem:
    slug: str
    title: str
    category: str
    path: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class DocContent:
    slug: str
    title: str
    category: str
    path: str
    content: str


def _category_of(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(_REPO_ROOT / "docs")
    except ValueError:
        return "other"
    parts = relative.parts
    return parts[0] if parts else "other"


def _title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


def _slug_for(path: Path) -> str:
    relative = path.resolve().relative_to(_REPO_ROOT / "docs")
    return relative.as_posix().removesuffix(".md")


def _resolve_slug(slug: str) -> Path:
    cleaned = slug.strip().replace("\\", "/").lstrip("/")
    if not cleaned or ".." in cleaned.split("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid document slug",
        )
    if not cleaned.endswith(".md"):
        candidate = _REPO_ROOT / "docs" / f"{cleaned}.md"
    else:
        candidate = _REPO_ROOT / "docs" / cleaned

    resolved = candidate.resolve()
    if not any(
        resolved == root or root in resolved.parents
        for root in _ALLOWED_ROOTS
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    if not resolved.is_file() or resolved.suffix.lower() != ".md":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return resolved


class DocumentCmsService:
    """docs/ 아래 허용 경로의 Markdown만 목록·조회한다 (쓰기 없음)."""

    def list_documents(self) -> list[DocListItem]:
        items: list[DocListItem] = []
        for root in _ALLOWED_ROOTS:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.md")):
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                slug = _slug_for(path)
                items.append(
                    DocListItem(
                        slug=slug,
                        title=_title_from_markdown(
                            text,
                            path.stem,
                        ),
                        category=_category_of(path),
                        path=f"docs/{slug}.md",
                        size_bytes=path.stat().st_size,
                    )
                )
        items.sort(key=lambda item: (item.category, item.slug))
        return items

    def get_document(self, slug: str) -> DocContent:
        path = _resolve_slug(slug)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not readable",
            ) from exc
        slug_value = _slug_for(path)
        return DocContent(
            slug=slug_value,
            title=_title_from_markdown(text, path.stem),
            category=_category_of(path),
            path=f"docs/{slug_value}.md",
            content=text,
        )
