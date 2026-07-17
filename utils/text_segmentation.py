"""桌面端与跨端聊天共用的语义分段。"""

import re


def split_semantic_text(
    text: str,
    *,
    sentence_target: int = 80,
    merge_under: int = 60,
) -> list[str]:
    """按代码块、段落和完整句子分段，不按字符数硬截断。"""
    text = (text or "").strip()
    if not text:
        return []

    structural_parts: list[tuple[str, bool]] = []
    current: list[str] = []
    in_code = False

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                current.append(line)
                structural_parts.append(("\n".join(current), True))
                current = []
            else:
                if current:
                    structural_parts.append(("\n".join(current), False))
                    current = []
                current.append(line)
            in_code = not in_code
        else:
            current.append(line)
    if current:
        structural_parts.append(("\n".join(current), in_code))

    pieces: list[str] = []
    for part, is_code in structural_parts:
        part = part.strip()
        if not part:
            continue
        if is_code:
            pieces.append(part)
            continue
        for paragraph in (item.strip() for item in part.split("\n\n")):
            if not paragraph:
                continue
            if len(paragraph) <= sentence_target:
                pieces.append(paragraph)
            else:
                pieces.extend(_split_complete_sentences(paragraph))

    merged: list[str] = []
    current_text = ""
    for piece in pieces:
        if piece.startswith("```"):
            if current_text:
                merged.append(current_text.strip())
                current_text = ""
            merged.append(piece)
        elif not current_text:
            current_text = piece
        elif len(current_text) + len(piece) < merge_under:
            current_text += " " + piece
        else:
            merged.append(current_text.strip())
            current_text = piece
    if current_text:
        merged.append(current_text.strip())
    return [item for item in merged if item]


def _split_complete_sentences(text: str) -> list[str]:
    parts = re.split(r"([。！？!?]+)", text)
    sentences: list[str] = []
    current = ""
    for part in parts:
        current += part
        if re.fullmatch(r"[。！？!?]+", part):
            sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())
    return sentences
