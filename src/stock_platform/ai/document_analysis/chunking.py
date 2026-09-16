"""STEP 11-6 — 제한적 Chunking (무제한 Map-Reduce 금지)."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.document_analysis.constants import (
    CHUNK_OVERLAP_CHARS,
    MAX_CHUNK_CHARS,
    MAX_CHUNKS,
    MAX_DOCUMENT_CHARS,
)


def plan_chunks(
    text: str,
    *,
    max_document_chars: int = MAX_DOCUMENT_CHARS,
    max_chunk_chars: int = MAX_CHUNK_CHARS,
    max_chunks: int = MAX_CHUNKS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> dict[str, Any]:
    """
    섹션 제목 우선 분할, 없으면 고정 길이.
    이번 STEP: 메타/요약 중심이므로 대부분 단일 청크.
    """

    warnings: list[str] = []
    body = text or ""
    if len(body) > max_document_chars:
        body = body[:max_document_chars]
        warnings.append("document_truncated_to_max_chars")

    if len(body) <= max_chunk_chars:
        return {
            "chunks": [{"index": 0, "text": body, "start": 0, "end": len(body)}],
            "chunk_count": 1,
            "warnings": warnings,
            "strategy": "single",
        }

    # 섹션 힌트: 줄 시작의 대괄호/숫자.제목
    sections = _split_sections(body)
    chunks: list[dict[str, Any]] = []
    if len(sections) > 1:
        buf = ""
        start = 0
        for sec in sections:
            candidate = (buf + "\n" + sec).strip() if buf else sec
            if len(candidate) <= max_chunk_chars:
                if not buf:
                    start = body.find(sec)
                buf = candidate
            else:
                if buf:
                    chunks.append(
                        {
                            "index": len(chunks),
                            "text": buf,
                            "start": start,
                            "end": start + len(buf),
                        }
                    )
                if len(chunks) >= max_chunks:
                    warnings.append("max_chunks_reached")
                    break
                buf = sec[:max_chunk_chars]
                start = body.find(sec)
                if len(sec) > max_chunk_chars:
                    warnings.append("section_truncated")
        if buf and len(chunks) < max_chunks:
            chunks.append(
                {
                    "index": len(chunks),
                    "text": buf,
                    "start": start,
                    "end": start + len(buf),
                }
            )
        strategy = "section"
    else:
        strategy = "fixed"
        pos = 0
        while pos < len(body) and len(chunks) < max_chunks:
            end = min(len(body), pos + max_chunk_chars)
            chunks.append(
                {
                    "index": len(chunks),
                    "text": body[pos:end],
                    "start": pos,
                    "end": end,
                }
            )
            if end >= len(body):
                break
            pos = max(0, end - overlap)
        if pos + max_chunk_chars < len(body):
            warnings.append("max_chunks_reached")

    return {
        "chunks": chunks,
        "chunk_count": len(chunks),
        "warnings": warnings,
        "strategy": strategy,
    }


def _split_sections(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        is_heading = bool(
            stripped.startswith("[")
            or (
                len(stripped) > 2
                and stripped[0].isdigit()
                and stripped[1] in {".", ")"}
            )
        )
        if is_heading and buf:
            parts.append("\n".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        parts.append("\n".join(buf))
    return parts if parts else [text]
