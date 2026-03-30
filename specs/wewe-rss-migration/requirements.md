# 需求文档: wewe-rss 数据源迁移

## 1. 介绍

将微信公众号文章采集管道从 wechat-article-exporter 迁移到 wewe-rss，解决旧方案依赖微信登录态不稳定的问题，同时保持现有筛选逻辑和下游 Pipeline 兼容性。

## 2. 需求与用户故事

### 需求 1: 替换数据源为 wewe-rss

**用户故事:** As a 情报采集运营人员, I want 使用 wewe-rss 订阅源替代 wechat-article-exporter, so that 无需维护微信登录态，采集更稳定可靠.

#### 验收标准
* **WHEN** 系统启动采集任务, **THEN** 系统 **SHALL** 从 wewe-rss JSON Feed API 获取文章，而非调用 wechat-article-exporter API.
* **IF** wewe-rss 服务不可用, **THEN** 系统 **SHALL** 输出明确错误信息并终止采集.
* **WHEN** 采集完成, **THEN** 输出的 JSON/Markdown 文件格式 **SHALL** 与旧方案完全兼容，下游 Pipeline（ingest → digest → report）无需修改.

---

### 需求 2: 保持公司名粗筛 + AI 精筛逻辑

**用户故事:** As a 情报分析人员, I want 现有的公司名关键词粗筛和 LLM AI 精筛逻辑保持不变, so that 采集质量不因数据源切换而下降.

#### 验收标准
* **WHEN** 文章标题或正文包含目标公司名, **THEN** 系统 **SHALL** 将其标记为粗筛命中.
* **IF** AI 精筛启用且 API 可用, **THEN** 系统 **SHALL** 对粗筛命中的文章调用 LLM 进行语义分类，保留置信度达标的文章.

---

### 需求 3: 采集性能优化（两阶段拉取）

**用户故事:** As a 系统管理员, I want 采集过程不因全文 HTML 体积过大而超时, so that 12 个公众号的全量采集能在合理时间内完成.

#### 验收标准
* **WHEN** 获取文章列表, **THEN** 系统 **SHALL** 使用 `mode=default` 轻量模式（~47KB/100篇），而非拉取含全文的 fulltext 模式（~300MB/100篇）.
* **WHEN** 需要正文内容（粗筛或 AI 精筛）, **THEN** 系统 **SHALL** 仅对标题粗筛命中或需正文验证的文章逐篇拉取全文.
* **IF** 全文拉取连续 5 页无新发现, **THEN** 系统 **SHALL** 停止翻页避免无效请求.

---

### 需求 4: 前端展示 wewe-rss 订阅源状态

**用户故事:** As a 运营人员, I want 在采集控制页看到 wewe-rss 订阅源的连接状态和公众号列表, so that 快速确认数据源是否正常.

#### 验收标准
* **WHEN** 打开采集控制页, **THEN** 页面 **SHALL** 显示 wewe-rss 连接状态（已连接/未连接）和订阅公众号数量.
* **IF** wewe-rss 不可达, **THEN** 页面 **SHALL** 显示红色"未连接"状态和错误信息.
