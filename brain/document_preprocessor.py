"""Prepare user-referenced documents before the first model request."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_SUPPORTED = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md", ".csv", ".json"}
_QUOTED_PATH = re.compile(r"[\"“”']([A-Za-z]:[\\/][^\"“”']+)[\"“”']")
_PLAIN_PATH = re.compile(
    r"([A-Za-z]:[\\/][^\r\n]+?\.(?:pdf|docx?|xlsx?|txt|md|csv|json))(?=$|[\s，。；;、])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PreparedDocument:
    source_path: Path
    markdown_path: Path
    digest: str
    content: str
    cache_hit: bool


def extract_document_paths(text: str) -> list[Path]:
    values = [match.group(1) for match in _QUOTED_PATH.finditer(str(text or ""))]
    values.extend(match.group(1) for match in _PLAIN_PATH.finditer(str(text or "")))
    paths: list[Path] = []
    for value in values:
        cleaned = value.strip().rstrip("，。；;、)")
        path = Path(cleaned)
        if path.suffix.lower() not in _SUPPORTED or not path.is_file():
            continue
        resolved = path.resolve()
        if resolved not in paths:
            paths.append(resolved)
    return paths


def prepare_documents(text: str, *, max_documents: int = 8,
                      max_total_chars: int = 48_000) -> tuple[str, list[PreparedDocument]]:
    """Convert referenced files once and return bounded Markdown model context."""
    paths = extract_document_paths(text)[:max(1, int(max_documents))]
    if not paths:
        return "", []

    from brain.tools import (
        _convert_with_markitdown, _extract_full_text, _get_document_markdown_cache,
    )

    cache = _get_document_markdown_cache()
    prepared: list[PreparedDocument] = []
    sections: list[str] = []
    remaining = max(1_000, int(max_total_chars))
    for path in paths:
        def extracted_converter(source: Path) -> str:
            content, error = _extract_full_text(source)
            if error:
                raise RuntimeError(error)
            return content
        if path.suffix.lower() in {".docx", ".pdf"}:
            try:
                cached = cache.get_or_create(path, _convert_with_markitdown)
            except Exception:
                content = extracted_converter(path)
                cached = cache.get_or_create(path, lambda _source: content)
        else:
            cached = cache.get_or_create(path, extracted_converter)
        item = PreparedDocument(path, cached.cache_path, cached.digest, cached.content, cached.cache_hit)
        prepared.append(item)
        if remaining <= 0:
            continue
        excerpt = cached.content[:remaining]
        sections.append(
            f"## 文档：{path.name}\n"
            f"原始路径：{path}\nMarkdown 缓存：{cached.cache_path}\n\n{excerpt}"
        )
        remaining -= len(excerpt)
    if not prepared:
        return "", []
    context = (
        "【请求前自动文档预处理】\n"
        "以下内容已在调用模型前转换为 Markdown。请直接阅读这些内容；"
        "除非需要未包含的后续部分，否则不要再次调用 read_file。\n\n"
        + "\n\n---\n\n".join(sections)
    )
    return context, prepared
