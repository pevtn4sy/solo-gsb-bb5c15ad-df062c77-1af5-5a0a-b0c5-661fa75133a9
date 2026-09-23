# 字幕时间漂移校正工具

基于 **Python + FastAPI** 的轻量 Web 工具：粘贴 SRT 字幕，填入多组人工确认的
「原时间 / 正确时间」锚点，即可校正字幕的时间漂移，在网页预览并下载校正后的 SRT。

## 功能与校正规则

- 粘贴标准 SRT，字幕**序号与文本原样保留**，仅校正开始/结束时间。
- 至少 **2 组**锚点（建议在片头、片中、片尾各取一组，越多越精确）。
- **相邻锚点之间做分段线性插值**；早于第一个锚点或晚于最后一个锚点的字幕，
  沿用最近一个区段（首段 / 末段）的斜率外推。
- 锚点**不自动排序**：原时间列必须严格递增，正确时间列也必须严格递增；
  任一侧出现相等或倒退时，拒绝生成并返回具体原因（指出是第几组锚点）。
- 时间格式 `HH:MM:SS,mmm`（毫秒分隔符逗号、句点均可，毫秒允许 1–3 位）。
- 校正后早于 `00:00:00,000` 的时间会截断为 0，并给出警告。
- 结果可在页面预览、逐条对比，并一键下载 `corrected.srt`（UTF-8 带 BOM）。

## 一条命令启动（Docker Compose）

```bash
docker compose up -d --build
```

启动后访问：

- 工具界面：<http://localhost:8000/>
- 健康检查：<http://localhost:8000/health>
- 接口文档（FastAPI 自带）：<http://localhost:8000/docs>

停止：`docker compose down`

### 配置

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| 端口 | 通过环境变量 `HOST_PORT` 修改宿主机映射端口；容器内固定监听 8000 | `8000` |
| 重启策略 | `restart: unless-stopped`（见 `docker-compose.yml`） | — |

例如改用宿主机 9000 端口：

```bash
HOST_PORT=9000 docker compose up -d --build
# 访问 http://localhost:9000/
```

## 不用 Docker，直接运行（Python 3.10+）

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

同样访问 <http://localhost:8000/>。

## HTTP 接口

`POST /api/correct`

```json
{
  "srt": "1\n00:00:05,000 --> 00:00:08,000\n你好\n",
  "anchors": [
    {"original": "00:00:10,000", "corrected": "00:00:08,000"},
    {"original": "00:02:40,000", "corrected": "00:02:35,000"}
  ]
}
```

成功返回 `corrected_srt`（完整 SRT 文本）、`cues`（逐条前后时间对照）与
`warnings`（如时间截断等提示）。SRT 解析失败或锚点不满足严格递增时返回
`422`，并在 `detail.message` 中给出中文原因。

## 目录结构

```
.
├── app/
│   ├── main.py          # FastAPI 应用与 /api/correct 接口
│   ├── mapping.py       # 锚点校验与分段线性映射
│   ├── srt.py           # SRT 解析/序列化（保留序号与文本）
│   ├── timecode.py      # 时间码解析与格式化
│   └── static/
│       └── index.html   # 轻量网页界面（原生 HTML/CSS/JS）
├── tests/               # 核心算法与接口测试
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
