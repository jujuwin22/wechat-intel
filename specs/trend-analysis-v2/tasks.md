# 实施计划: 趋势分析优化 V2

- [x] **任务1:** 重写 `server/config/prompts/trend-extract.md` — 新prompt含角色设定、维度引导、implications字段、executive_summary、明确不强制归类
  - _关联需求: #1, #2, #3_
- [x] **任务2:** 修改 `_format_events_for_llm()` — 增加excerpts摘要提供更多上下文
  - _关联需求: #1_
- [x] **任务3:** 修改 `_llm_extract_trends()` — 适配新JSON输出格式（对象而非数组），增加向后兼容
  - _关联需求: #1, #2_
- [x] **任务4:** 修改 `generate_trend_report()` — 返回值增加executive_summary、implications
  - _关联需求: #3_
- [x] **任务5:** 重写 `render_trend_markdown()` — 新报告结构（执行摘要+趋势+启示+其他动态）
  - _关联需求: #3, #4_
- [x] **任务6:** 重跑pipeline验证效果，人工审阅趋势报告质量
  - _关联需求: 全部_
