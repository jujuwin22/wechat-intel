# wechat-intel — 微信 HR 情报采集与分析系统

自动采集微信公众号 HR 行业文章，通过 AI 精筛和情报管道生成结构化情报速递和趋势分析报告。

## 功能概览

- **微信公众号采集** — 基于 wechat-article-exporter，支持公司名粗筛 + LLM AI 精筛
- **Feed Pipeline** — ingest → 多事件拆分 → 质量精筛 → 跨源去重 → 渲染输出 → 趋势分析
- **Web 面板** — 3 个页面：采集控制（SSE 实时日志）、情报速递（事件列表+筛选）、趋势报告

## 快速开始

### 1. 安装依赖

```bash
# Python 后端
pip install -r server/requirements.txt

# Vue 前端
cd frontend && npm install && cd ..
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入以下配置：
#   LLM_API_KEY      - DeepSeek / OpenAI 兼容 API Key
#   LLM_BASE_URL     - API 地址（默认 https://api.deepseek.com/v1）
#   LLM_MODEL        - 模型名（默认 deepseek-chat）
#   WECHAT_EXPORTER_URL - 微信 exporter 地址（默认 http://localhost:3000）
```

### 3. 启动微信采集容器

```bash
docker-compose up -d
# 访问 http://localhost:3000 扫码登录
```

### 4. 启动应用

```bash
# 启动后端 API（端口 5001）
python3 server/app.py

# 启动前端开发服务器（端口 5173，自动代理 /api → 5001）
cd frontend && npm run dev
```

访问 http://localhost:5173 使用 Web 面板。

### 5. CLI 命令行（可选）

```bash
# 直接运行采集（不通过 Web）
python3 -m server.collector.collector --start-date 2026-03-01 --end-date 2026-03-31

# 运行 Feed Pipeline
python3 -m server.feed.pipeline --month "2026年3月"
python3 -m server.feed.pipeline --month "2026年3月" --no-dedup  # 跳过 LLM 去重
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/collect/status` | 采集运行状态 |
| POST | `/api/collect/run` | 启动采集 (body: `{start_date, end_date}`) |
| GET | `/api/collect/log` | SSE 实时日志流 |
| GET | `/api/collect/watermark` | 采集水位线 |
| GET | `/api/feed/months` | 可用月份列表 |
| GET | `/api/feed?month=2026年3月` | 情报速递数据 |
| POST | `/api/feed/generate` | 触发 Pipeline (body: `{month, no_dedup}`) |
| GET | `/api/report?month=2026年3月` | 趋势报告数据 |

## 项目结构

```
wechat-intel/
├── server/                  # Python 后端
│   ├── app.py               # Flask API 入口（8 个端点 + SSE）
│   ├── requirements.txt     # Python 依赖
│   ├── collector/           # 微信公众号采集模块
│   │   ├── config.py        # 采集配置（从 YAML + env 加载）
│   │   └── collector.py     # 采集核心逻辑
│   ├── feed/                # 情报生成管道
│   │   ├── models.py        # 数据模型（Article, Event, DigestEntry）
│   │   ├── ingest.py        # 加载采集 JSON
│   │   ├── splitter.py      # 多事件拆分
│   │   ├── quality_filter.py # LLM 质量精筛
│   │   ├── dedup.py         # 三阶段去重
│   │   ├── renderer.py      # Markdown/JSON/HTML 输出
│   │   ├── trend_report.py  # 趋势分析报告
│   │   └── pipeline.py      # 管道编排
│   └── config/              # 配置文件
│       ├── companies.yaml   # 目标公司列表
│       ├── wechat_channels.yaml # 公众号配置
│       ├── feed_settings.yaml   # Pipeline 参数
│       ├── source_credibility.yaml # 来源可信度
│       └── prompts/         # LLM prompt 模板
├── frontend/                # Vue 3 + Vite + TailwindCSS 前端
│   └── src/views/           # 采集控制 / 情报速递 / 趋势报告
├── data/                    # 运行时数据（gitignore）
│   ├── cache/results/       # 采集结果 JSON
│   └── output/              # Pipeline 输出
├── docker-compose.yml       # 微信 exporter 容器
├── specs/                   # 需求 & 设计文档
├── skills/                  # Claude Code Skill
│   └── wechat-intel-viewer/ # 市场情报查看器 Skill
└── .env.example             # 环境变量模板
```

---

## 🤖 AI 助手快速接入

无需启动 Web 服务，直接在 Claude Code / CodeBuddy / Cursor 中查询已采集的 HR 情报。

### 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/jujuwin22/wechat-intel/main/install.sh | bash
```

支持自动检测：Claude Code、CodeBuddy、Cursor、Windsurf

### 使用方法

安装完成后，直接在 AI 对话中说：

| 功能 | 示例指令 |
|------|----------|
| **交互式趋势分析** ⭐ | `"生成3月动态"` → AI 让你勾选维度 → 自动生成趋势报告 |
| **快速查询** | `"查一下字节跳动最近的HR动态"` |
| **维度筛选** | `"3月有哪些薪酬激励的新闻"` |
| **导出报告** | `"导出HTML报告"`、`"生成可视化展示"` |

### 功能特性

- **交互式趋势生成**：先展示维度分布，让用户勾选感兴趣的维度，AI 自动生成趋势洞察
- **多维度筛选**：薪酬激励 / 人事变动 / 组织架构 / 人才发展 / 企业文化
- **HTML 可视化**：生成交互式卡片页面，支持维度筛选、置信度展示、原文链接
- **开箱即用**：零配置，安装后直接对话使用

### 数据来源

已采集的数据存放在本仓库 `data/output/` 目录：
- `{YYYY}年{M}月_digest.json` — 情报速递（事件列表）
- `{YYYY}年{M}月_trend_report.json` — 趋势分析报告

数据每月更新，覆盖互联网/地产/金融等行业头部企业 HR 动态。
