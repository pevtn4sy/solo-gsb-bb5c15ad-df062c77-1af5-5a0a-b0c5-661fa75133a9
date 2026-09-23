"""核心算法与 FastAPI 接口测试。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mapping import AnchorError, PiecewiseMapping, build_anchors
from app.srt import SrtParseError, format_srt, parse_srt, rewrite_srt_timings
from app.timecode import format_timecode, parse_timecode

client = TestClient(app)


# ---------- 时间码 ----------

def test_parse_and_format_timecode():
    assert parse_timecode("00:01:23,456") == 83_456
    assert parse_timecode("1:2:3.4") == 3_723_400  # 毫秒补 3 位 -> 400
    assert format_timecode(83_456) == "00:01:23,456"
    assert format_timecode(-5) == "00:00:00,000"


def test_invalid_timecode():
    with pytest.raises(ValueError):
        parse_timecode("00:60:00,000")
    with pytest.raises(ValueError):
        parse_timecode("not-a-time")
    with pytest.raises(ValueError):
        parse_timecode("")


# ---------- SRT ----------

SAMPLE = (
    "1\r\n"
    "00:00:05,000 --> 00:00:08,000\r\n"
    "你好\n\n"
    "2\n"
    "00:00:10,000 --> 00:00:12,500\n"
    "第二行上\n第二行下\n"
)


def test_parse_preserves_index_and_text():
    cues = parse_srt(SAMPLE)
    assert len(cues) == 2
    assert cues[0].index == "1"
    assert cues[0].text == "你好"
    assert cues[1].text == "第二行上\n第二行下"
    assert cues[1].end - cues[1].start == 2500


def test_parse_missing_index_auto_numbers():
    cues = parse_srt("00:00:01,000 --> 00:00:02,000\n无序号块\n")
    assert cues[0].index == "1"


def test_parse_errors():
    with pytest.raises(SrtParseError):
        parse_srt("")
    with pytest.raises(SrtParseError):
        parse_srt("1\n00:00:05,000 --> 00:00:05,000\n等长\n")
    with pytest.raises(SrtParseError):
        parse_srt("1\n00:00:05,000 --> 00:00:03,000\n倒退\n")


def test_roundtrip_srt():
    out = format_srt(parse_srt(SAMPLE))
    assert "00:00:05,000 --> 00:00:08,000" in out
    assert "第二行上\n第二行下" in out


# ---------- 无损导出（就地替换时间码） ----------

POSITIONED_SRT = (
    "﻿1\r\n"
    "00:00:05,000 --> 00:00:08,000 X1:100 X2:500 Y1:20 Y2:60\r\n"
    "你好\r\n"
    "\r\n"
    "2\r\n"
    "00:00:10,000  -->  00:00:12,500 position:50%\r\n"
    "第二行上\r\n第二行下\r\n"
)


def test_rewrite_preserves_bom_crlf_and_positioning_params():
    cues = parse_srt(POSITIONED_SRT)
    timings = [(cue.start + 1000, cue.end + 1000) for cue in cues]
    assert rewrite_srt_timings(POSITIONED_SRT, timings) == (
        "﻿1\r\n"
        "00:00:06,000 --> 00:00:09,000 X1:100 X2:500 Y1:20 Y2:60\r\n"
        "你好\r\n"
        "\r\n"
        "2\r\n"
        "00:00:11,000  -->  00:00:13,500 position:50%\r\n"
        "第二行上\r\n第二行下\r\n"
    )


def test_rewrite_preserves_arrow_spacing_and_blank_lines():
    src = (
        "1\n"
        "00:00:01,000-->00:00:02,000\n"
        "紧凑箭头\n"
        "\n\n\n"
        "2\n"
        "00:00:03,000 -->   00:00:04,000\n"
        "稀疏箭头\n"
    )
    cues = parse_srt(src)
    timings = [(cue.start + 500, cue.end + 500) for cue in cues]
    assert rewrite_srt_timings(src, timings) == (
        "1\n"
        "00:00:01,500-->00:00:02,500\n"
        "紧凑箭头\n"
        "\n\n\n"
        "2\n"
        "00:00:03,500 -->   00:00:04,500\n"
        "稀疏箭头\n"
    )


def test_rewrite_ignores_timing_like_text_lines():
    # 正文里恰好形如时间轴的行不是时间轴行，不应被改写
    src = (
        "1\n"
        "00:00:01,000 --> 00:00:02,000\n"
        "00:09:09,000 --> 00:09:10,000\n"
    )
    cues = parse_srt(src)
    out = rewrite_srt_timings(src, [(cues[0].start + 1000, cues[0].end + 1000)])
    assert out == (
        "1\n"
        "00:00:02,000 --> 00:00:03,000\n"
        "00:09:09,000 --> 00:09:10,000\n"
    )


def test_rewrite_count_mismatch_rejected():
    with pytest.raises(SrtParseError):
        rewrite_srt_timings("1\n00:00:01,000 --> 00:00:02,000\n甲\n", [])
    with pytest.raises(SrtParseError):
        rewrite_srt_timings(
            "1\n00:00:01,000 --> 00:00:02,000\n甲\n",
            [(0, 1000), (2000, 3000)],
        )


# ---------- 锚点与映射 ----------

def test_build_anchors_requires_two():
    with pytest.raises(AnchorError, match="至少需要 2 组"):
        build_anchors([("00:00:01,000", "00:00:00,500")])


def test_original_not_strictly_increasing_rejected():
    with pytest.raises(AnchorError, match="原时间未严格递增"):
        build_anchors([
            ("00:00:10,000", "00:00:08,000"),
            ("00:00:10,000", "00:00:09,000"),
        ])
    with pytest.raises(AnchorError, match="原时间未严格递增"):
        build_anchors([
            ("00:00:20,000", "00:00:08,000"),
            ("00:00:10,000", "00:00:09,000"),
        ])


def test_corrected_not_strictly_increasing_rejected():
    with pytest.raises(AnchorError, match="正确时间未严格递增"):
        build_anchors([
            ("00:00:10,000", "00:00:09,000"),
            ("00:00:20,000", "00:00:09,000"),
        ])


def test_invalid_anchor_time_rejected():
    with pytest.raises(AnchorError, match="原时间无效"):
        build_anchors([("bad", "00:00:09,000"), ("00:00:20,000", "00:00:19,000")])


def _mapping():
    # 10s->8s（-2s），100s->92s（-8s），斜率 56/60
    anchors = build_anchors([
        ("00:00:10,000", "00:00:08,000"),
        ("00:01:40,000", "00:01:32,000"),
    ])
    return PiecewiseMapping(anchors)


def test_mapping_hits_anchor_exactly():
    m = _mapping()
    assert m.map_ms(10_000) == 8_000
    assert m.map_ms(100_000) == 92_000


def test_mapping_interpolation_between_anchors():
    m = _mapping()
    # 中间点 55s -> 50s（线性中点）
    assert m.map_ms(55_000) == 50_000


def test_mapping_extrapolates_with_nearest_segment_slope():
    m = _mapping()
    # 右端外推：160s + 60s -> 92s + 56s = 148s
    assert m.map_ms(160_000) == 148_000
    # 左端外推：0 -> 8000 + (0-10000)*56/60 = 8000 - 9333.33 = -1333
    assert m.map_ms(0) == -1333


def test_three_anchor_piecewise_slopes():
    anchors = build_anchors([
        ("00:00:00,000", "00:00:00,000"),
        ("00:01:00,000", "00:00:54,000"),   # 斜率 0.9
        ("00:02:00,000", "00:02:00,000"),   # 斜率 1.1
    ])
    m = PiecewiseMapping(anchors)
    # 第一区段：30s -> 27s
    assert m.map_ms(30_000) == 27_000
    # 第二区段：90s -> 54s + (30s)*1.1 = 87s
    assert m.map_ms(90_000) == 87_000
    # 末段斜率外推：150s -> 120s + 30s*1.1 = 153s
    assert m.map_ms(150_000) == 153_000


# ---------- HTTP 接口 ----------

def request_body():
    return {
        "srt": SAMPLE,
        "anchors": [
            {"original": "00:00:10,000", "corrected": "00:00:08,000"},
            {"original": "00:01:40,000", "corrected": "00:01:32,000"},
        ],
    }


def test_health_and_index():
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/").status_code == 200


def test_api_correct_success():
    resp = client.post("/api/correct", json=request_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["cues"][0]["index"] == "1"
    assert data["cues"][0]["text"] == "你好"
    assert data["cues"][0]["corrected_start"] == format_timecode(
        _mapping().map_ms(5000)
    )
    assert "你好" in data["corrected_srt"]


def test_api_rejects_bad_anchors_with_reason():
    body = request_body()
    body["anchors"][1]["original"] = "00:00:10,000"  # 与第一组相等
    resp = client.post("/api/correct", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]["type"] == "anchors"
    assert "原时间未严格递增" in resp.json()["detail"]["message"]


def test_api_rejects_bad_srt():
    body = request_body()
    body["srt"] = "garbage without timing"
    resp = client.post("/api/correct", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]["type"] == "srt"


def test_api_correct_lossless_export():
    body = request_body()
    body["srt"] = POSITIONED_SRT
    resp = client.post("/api/correct", json=body)
    assert resp.status_code == 200, resp.text
    out = resp.json()["corrected_srt"]

    # 仅时间码被替换为映射结果，BOM、CRLF、定位参数、箭头空格全部原样保留
    m = _mapping()
    expected = POSITIONED_SRT.replace(
        "00:00:05,000 --> 00:00:08,000",
        f"{format_timecode(m.map_ms(5000))} --> {format_timecode(m.map_ms(8000))}",
    ).replace(
        "00:00:10,000  -->  00:00:12,500",
        f"{format_timecode(m.map_ms(10000))}  -->  {format_timecode(m.map_ms(12500))}",
    )
    assert out == expected
