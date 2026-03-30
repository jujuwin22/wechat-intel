# HR 市场趋势分析报告 — {date_label}

> 基于 {total_events} 条事件 | 提炼 {trend_count} 大趋势
> 数据更新时间：{generated_at}

---

## 执行摘要

{executive_summary}

---

{for_each_trend}

## 趋势 {trend_index}：{trend.title}

**概述**：{trend.summary}

### 相关事件

{for_each_event_in_trend}

#### {event.company} — {event.summary}

- **日期**：{event.event_date}
- **维度**：{event.dimension}
- **来源**：{event.source_account}（{event.source_count} 个来源）

{if_excerpts}
> {event.excerpts[0]}
{end_if}

[查看原文]({event.source_url})

{end_for_each_event}

---

{end_for_each_trend}

{if_other_events}

## 其他动态

以下事件未归入上述趋势，但值得关注：

{for_each_other_event}
- **{event.company}**（{event.event_date}）：{event.summary} — [{event.source_account}]({event.source_url})
{end_for_each_other_event}

{end_if}

---

## 维度分布

| 维度 | 事件数 | 占比 |
|------|--------|------|
{dimension_distribution_rows}

---
*本报告由 wechat-intel-viewer 自动生成*
