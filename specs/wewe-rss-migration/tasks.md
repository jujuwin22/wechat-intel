# 实施计划: wewe-rss 数据源迁移

- [x] **任务1:** 重写 `server/collector/config.py` — `BASE_URL` → `WEWE_RSS_URL`，`load_wechat_channels` 返回含 `feed_id` 的 dict
  - _关联需求: #1_

- [x] **任务2:** 重写 `server/collector/collector.py` — 移除 exporter API 调用，改用 wewe-rss JSON Feed API
  - _关联需求: #1, #2_

- [x] **任务3:** 更新 `server/config/wechat_channels.yaml` — 为12个已订阅公众号添加 `feed_id` 字段
  - _关联需求: #1_

- [x] **任务4:** 更新 `server/app.py` — 新增 `/api/collect/feeds` 端点代理查询 wewe-rss 状态
  - _关联需求: #4_

- [x] **任务5:** 更新 `frontend/src/views/CollectView.vue` — 新增 wewe-rss 订阅源状态卡片（连接状态 + 公众号列表）
  - _关联需求: #4_

- [x] **任务6:** 更新 `.env.example` 和 `docker-compose.yml` — 移除 exporter 配置，添加 `WEWE_RSS_URL`
  - _关联需求: #1_

- [x] **任务7:** 性能优化 — 实现两阶段采集（`mode=default` 轻量列表 + `mode=fulltext` 逐篇拉全文）
  - _关联需求: #3_
  - 重写 `fetch_feed_articles` 使用 `mode=default` 参数
  - 新增 `_batch_fetch_content` 分页匹配目标 URL
  - 重写 `collect_account` 为5步流程（轻量列表→水位线→日期→标题粗筛→全文+AI）
  - 添加 `miss_streak=5` 连续无新发现退出机制

- [x] **任务8:** 端到端验证
  - _关联需求: #1, #2, #3, #4_
  - 语法检查: config.py, collector.py, app.py 全部通过
  - 单公众号 `--no-ai` 测试: 涛哥杂谈 100篇→22篇(日期)→20篇(粗筛)，成功保存 JSON/Markdown
  - 前端验证: 订阅源卡片显示"已连接·12个订阅"，水位线正常更新
  - 后端 API `/api/collect/feeds` 正常返回

- [ ] **待办:** 补充5个未订阅公众号到 wewe-rss（巨潮资讯、地产人力V圈、地产周侃、HR研究网、地产人才官）
  - _关联需求: #1_

- [ ] **待办:** 跑一次12个公众号全量采集（含 AI 精筛）验证完整流程
  - _关联需求: #1, #2, #3_
