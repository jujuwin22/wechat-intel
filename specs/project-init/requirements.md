# 需求文档: wechat-intel 项目剥离与重构

## 1. 介绍

从现有 hr-intel-tavily 项目中剥离微信公众号采集模块和 Feed 情报生成管道，创建独立项目 `wechat-intel`，并用 Flask API + Vue(Vite) 全栈重写 Web 面板，使其成为一个可独立迭代的微信 HR 情报采集与分析系统。

## 2. 需求与用户故事

### 需求 1: 微信公众号采集模块迁移

**用户故事:** As a HR 情报分析师, I want 从微信公众号自动采集 HR 相关文章, so that 我能获取一手的行业动态信息源。

#### 验收标准

* **WHEN** 用户启动采集脚本并指定日期范围, **THEN** the system **SHALL** 通过 Docker 容器连接微信公众号 API，按配置的 17 个公众号逐一采集文章。
* **WHEN** 采集到文章后, **THEN** the system **SHALL** 执行双层筛选：关键词粗筛（正文匹配）→ AI 精筛（DeepSeek/Claude 判断 HR 相关性并提取事件日期）。
* **WHEN** 筛选完成后, **THEN** the system **SHALL** 输出 `{月份}_{公众号名}_wechat.json` 格式的结构化数据文件到 `data/cache/results/` 目录。
* **IF** 某公众号上次采集的最新文章时间戳已记录（watermark）, **THEN** the system **SHALL** 支持增量采集，仅获取新发布的文章。

---

### 需求 2: Feed 情报生成管道迁移

**用户故事:** As a HR 情报分析师, I want 将采集的原始文章自动加工为结构化的情报速递和趋势报告, so that 我能快速了解当月 HR 市场动态要点。

#### 验收标准

* **WHEN** 用户触发 Pipeline 运行（指定月份）, **THEN** the system **SHALL** 按6步流水线处理：加载数据 → 多事件拆分 → 质量精筛 → 跨源去重 → 速递输出 → 趋势报告。
* **WHEN** 一篇文章包含多家公司或多个独立事件, **THEN** the system **SHALL** 使用 LLM 将其拆分为独立的 Event 对象。
* **WHEN** 多个来源报道了同一事件, **THEN** the system **SHALL** 使用 LLM 判断并合并为一条 DigestEntry，记录多源验证信息。
* **WHEN** Pipeline 完成后, **THEN** the system **SHALL** 输出 Markdown、JSON、HTML 三种格式的情报速递，以及一份 LLM 生成的趋势分析报告。
* **IF** LLM 趋势归纳失败, **THEN** the system **SHALL** 降级为按维度分组的基础报告。

---

### 需求 3: 采集控制页（Web）

**用户故事:** As a HR 情报分析师, I want 在 Web 界面上启动和监控微信采集任务, so that 我不需要登录服务器手动执行命令。

#### 验收标准

* **WHEN** 用户在采集控制页设置日期范围并点击"开始采集", **THEN** the system **SHALL** 在后台启动采集进程，并通过 SSE（Server-Sent Events）实时推送采集日志到前端。
* **WHEN** 采集正在运行时, **THEN** the system **SHALL** 显示运行状态，禁止重复启动，并展示实时日志流。
* **WHEN** 采集完成或失败, **THEN** the system **SHALL** 通过 SSE 发送完成信号，前端更新状态。
* **WHEN** 用户访问采集控制页, **THEN** the system **SHALL** 显示各公众号的上次采集时间（watermark）。

---

### 需求 4: 情报速递页（Web）

**用户故事:** As a HR 情报分析师, I want 在 Web 界面浏览和筛选情报事件, so that 我能快速找到感兴趣的 HR 动态。

#### 验收标准

* **WHEN** 用户访问情报速递页, **THEN** the system **SHALL** 显示最新月份的事件列表，每条事件包含：公司名、维度标签、事件日期、摘要、详情、来源公众号、置信度。
* **WHEN** 用户选择不同月份, **THEN** the system **SHALL** 切换显示对应月份的事件数据。
* **WHEN** 用户按公司名筛选, **THEN** the system **SHALL** 只显示该公司相关的事件。
* **WHEN** 用户按维度（薪酬激励/组织架构/人才发展/企业文化）筛选, **THEN** the system **SHALL** 只显示该维度的事件。
* **WHEN** 用户点击"生成速递"按钮（指定月份）, **THEN** the system **SHALL** 触发 Feed Pipeline 并在完成后刷新页面数据。

---

### 需求 5: 趋势报告页（Web）

**用户故事:** As a HR 情报分析师, I want 查看 LLM 自动归纳的趋势分析报告, so that 我能了解当月 HR 市场的整体趋势和关键洞察。

#### 验收标准

* **WHEN** 用户访问趋势报告页, **THEN** the system **SHALL** 展示最新月份的趋势分析报告，包含：执行摘要（总事件数、趋势数、维度分布）、各趋势章节（标题、概述、关联事件）。
* **WHEN** 用户选择不同月份, **THEN** the system **SHALL** 切换显示对应月份的趋势报告。
* **IF** 某月份尚无趋势报告, **THEN** the system **SHALL** 提示用户先运行 Pipeline 生成。

---

### 需求 6: 项目独立性

**用户故事:** As a 开发者, I want 新项目完全独立于原 hr-intel-tavily 项目, so that 我能独立迭代而不影响原系统。

#### 验收标准

* **WHEN** 新项目部署到新环境, **THEN** the system **SHALL** 只需配置 `.env` 文件（LLM API Key 等）即可运行，不依赖原项目的任何文件或路径。
* **WHEN** 新项目启动, **THEN** the system **SHALL** 不包含任何 Tavily/Serper 搜索相关的代码和配置。
* **WHEN** 检查新项目依赖, **THEN** the system **SHALL** 只包含微信采集、Feed Pipeline 和 Web 面板所需的最小依赖集。
