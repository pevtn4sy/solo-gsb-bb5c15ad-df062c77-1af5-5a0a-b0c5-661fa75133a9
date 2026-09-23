"""极简 SRT 解析与序列化，完整保留原始序号与字幕文本。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .timecode import TIMECODE_PATTERN, format_timecode, parse_timecode


class SrtParseError(ValueError):
    """SRT 内容无法解析。"""


@dataclass
class Cue:
    index: str
    start: int
    end: int
    text: str


# 时间码行尾可能携带 X1:/Position 等排版信息，这里只取箭头两侧的时间码
_CUE_TIMING = re.compile(
    rf"^\s*({TIMECODE_PATTERN})\s*-->\s*({TIMECODE_PATTERN})(?:\s|$)"
)
_INDEX_RE = re.compile(r"^\s*\d+\s*$")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def parse_srt(content: str) -> list[Cue]:
    """把 SRT 文本解析为 Cue 列表；块结构为“序号 / 时间轴 / 一行或多行文本”。"""
    if content is None or not content.strip():
        raise SrtParseError("内容为空。")

    text = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    blocks = _BLANK_LINE.split(text.strip())

    cues: list[Cue] = []
    auto_index = 0

    for block_no, raw_block in enumerate(blocks, start=1):
        lines = raw_block.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue

        # 兼容省略序号行的 SRT：首行是纯数字且下一行是时间轴才视作序号
        cursor = 0
        index: str | None = None
        if _INDEX_RE.match(lines[0]) and len(lines) >= 2 and _CUE_TIMING.match(lines[1]):
            index = lines[0].strip()
            cursor = 1
        elif _CUE_TIMING.match(lines[0]):
            cursor = 0
        else:
            raise SrtParseError(
                f"第 {block_no} 个字幕块缺少有效的时间轴行，"
                "结构应为“序号 / 开始 --> 结束 / 字幕文本”。"
            )

        timing = _CUE_TIMING.match(lines[cursor])
        assert timing is not None
        try:
            start = parse_timecode(timing.group(1))
            end = parse_timecode(timing.group(2))
        except ValueError as exc:
            raise SrtParseError(f"第 {block_no} 个字幕块的时间码无效：{exc}") from exc

        if end <= start:
            raise SrtParseError(
                f"第 {block_no} 个字幕块的结束时间必须严格晚于开始时间。"
            )

        body = "\n".join(lines[cursor + 1 :])
        if not body.strip():
            raise SrtParseError(f"第 {block_no} 个字幕块缺少文本内容。")

        auto_index += 1
        cues.append(Cue(index=index or str(auto_index), start=start, end=end, text=body))

    if not cues:
        raise SrtParseError("未解析到任何字幕，请粘贴有效的 SRT 内容。")
    return cues


def format_srt(cues: list[Cue]) -> str:
    """把 Cue 列表序列化为标准 SRT 文本（CRLF 统一为 \\n）。"""
    blocks = [
        f"{cue.index}\n"
        f"{format_timecode(cue.start)} --> {format_timecode(cue.end)}\n"
        f"{cue.text}"
        for cue in cues
    ]
    return "\n\n".join(blocks) + "\n"
