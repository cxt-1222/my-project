from __future__ import annotations

import re

from langchain_text_splitters import RecursiveCharacterTextSplitter


_ACTION_HEADER = re.compile(r"(?m)^动作名称\s*[:：].*$")
_ACTION_METADATA_END = re.compile(r"(?m)^动作说明\s*[:：]\s*$")


def split_knowledge_text(content: str, *, chunk_size: int = 200, chunk_overlap: int = 50) -> list[str]:
    """Split knowledge text while repeating an exercise's identity in every step chunk.

    Action entries often exceed one chunk. Repeating the name and metadata prevents
    retrieval from returning an orphaned step that cannot be attributed to an action.
    Non-action documents retain the existing recursive splitter behavior.
    """
    text = (content or "").strip()
    if not text:
        return []

    headers = list(_ACTION_HEADER.finditer(text))
    if not headers:
        return _split_plain(text, chunk_size, chunk_overlap)

    chunks: list[str] = []
    cursor = 0
    for index, match in enumerate(headers):
        # Preserve any introductory material preceding the first structured action.
        if index == 0 and text[cursor:match.start()].strip():
            chunks.extend(_split_plain(text[cursor:match.start()].strip(), chunk_size, chunk_overlap))

        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        entry = text[match.start():end].strip()
        metadata_end = _ACTION_METADATA_END.search(entry)
        if not metadata_end:
            chunks.extend(_split_plain(entry, chunk_size, chunk_overlap))
            cursor = end
            continue

        identity = entry[:metadata_end.end()].strip()
        steps = entry[metadata_end.end():].strip()
        if not steps:
            chunks.append(identity)
        else:
            # Reserve room for repeated identity; the splitter's overlap remains useful
            # for continuity between adjacent instruction fragments.
            step_size = max(80, chunk_size - len(identity) - 2)
            step_overlap = min(chunk_overlap, max(0, step_size // 4))
            chunks.extend(
                f"{identity}\n{part}"
                for part in _split_plain(steps, step_size, step_overlap)
            )
        cursor = end

    return chunks


def _split_plain(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        separators=["。", "！", "？", "；", ";", "\n"],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_text(text)
