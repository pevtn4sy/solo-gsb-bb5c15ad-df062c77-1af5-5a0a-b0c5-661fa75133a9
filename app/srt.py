"""SRT 解析与时间轴就地改写，完整保留原始序号、字幕文本与文件格式。"""
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

# 切行时识别 CRLF / LF / CR 三种换行，与 parse_srt 的换行规范化口径一致
_LINE_BREAK = re.compile(r"(\r\n|\r|\n)")
# 仅含空格/制表符的“空行”，与 _BLANK_LINE 的切块口径一致
_BLANKISH_LINE = re.compile(r"[ \t]*")


def _find_timing_line(lines: list[str], block_no: int) -> tuple[str | None, int]:
    """定位块内时间轴行，返回 (序号, 时间轴行在块内的下标)。

    兼容省略序号行的 SRT：首行是纯数字且下一行是时间轴才视作序号。
    """
    if _INDEX_RE.match(lines[0]) and len(lines) >= 2 and _CUE_TIMING.match(lines[1]):
        return lines[0].strip(), 1
    if _CUE_TIMING.match(lines[0]):
        return None, 0
    raise SrtParseError(
        f"第 {block_no} 个字幕块缺少有效的时间轴行，"
        "结构应为“序号 / 开始 --> 结束 / 字幕文本”。"
    )


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

        index, cursor = _find_timing_line(lines, block_no)

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


def rewrite_srt_timings(content: str, timings: list[tuple[int, int]]) -> str:
    """在原始 SRT 文本上就地把各时间轴行的起止时间码替换为新时间（毫秒）。

    仅改动时间轴行中箭头两侧的时间码；序号、字幕正文、箭头两侧的空格、
    行尾定位参数（如 X1:/X2:）、空行、原有换行符（CRLF/LF/CR）与 BOM
    全部保持原样。``timings`` 按顺序与 parse_srt 解析出的字幕一一对应。
    """
    # BOM 原样保留（与 parse_srt 一样忽略全部前导 BOM，但这里会照搬回输出）
    body = content.lstrip("﻿")
    bom = content[: len(content) - len(body)]

    # 按原换行符切行：切分结果的偶数位是行内容、奇数位是换行符，最后原样拼回
    parts = _LINE_BREAK.split(body)
    lines = parts[0::2]
    breaks = parts[1::2]

    pending = iter(timings)
    block_no = 0
    i = 0
    while i < len(lines):
        if _BLANKISH_LINE.fullmatch(lines[i]):
            i += 1
            continue

        # 收集一个字幕块，并复刻 parse_srt 的首尾空白行裁剪
        block_no += 1
        block_start = i
        block: list[str] = []
        while i < len(lines) and not _BLANKISH_LINE.fullmatch(lines[i]):
            block.append(lines[i])
            i += 1
        while block and not block[0].strip():
            block_start += 1
            block.pop(0)
        while block and not block[-1].strip():
            block.pop()
        if not block:
            continue

        _, offset = _find_timing_line(block, block_no)
        target = block_start + offset
        try:
            new_start, new_end = next(pending)
        except StopIteration as exc:
            raise SrtParseError("时间轴行数量与校正结果条数不一致。") from exc
        lines[target] = _replace_timecodes(lines[target], new_start, new_end)

    if next(pending, None) is not None:
        raise SrtParseError("时间轴行数量与校正结果条数不一致。")

    out = [bom]
    for pos, line in enumerate(lines):
        out.append(line)
        if pos < len(breaks):
            out.append(breaks[pos])
    return "".join(out)


def _replace_timecodes(line: str, start_ms: int, end_ms: int) -> str:
    """只替换时间轴行里箭头两侧的时间码，行内其余字符一律不动。"""
    match = _CUE_TIMING.match(line)
    if match is None:
        raise SrtParseError(f"无法定位时间轴行中的时间码：{line!r}")
    return (
        line[: match.start(1)]
        + format_timecode(start_ms)
        + line[match.end(1) : match.start(2)]
        + format_timecode(end_ms)
        + line[match.end(2) :]
    )


def format_srt(cues: list[Cue]) -> str:
    """把 Cue 列表序列化为标准 SRT 文本（CRLF 统一为 \\n）。"""
    blocks = [
        f"{cue.index}\n"
        f"{format_timecode(cue.start)} --> {format_timecode(cue.end)}\n"
        f"{cue.text}"
        for cue in cues
    ]
    return "\n\n".join(blocks) + "\n"
