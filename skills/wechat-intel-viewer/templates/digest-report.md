# HR 情报速递 — {date_label}

> 共 {total_events} 条事件 | 来自 {source_count} 个公众号 | 覆盖 {company_count} 家公司
> 筛选条件：{filter_description}
> 数据更新时间：{generated_at}

---

{for_each_dimension}

## {dimension_name}（{event_count} 条）

{for_each_event}

### {event.summary}

| 字段 | 内容 |
|------|------|
| 公司 | {event.company} |
| 日期 | {event.event_date} |
| 维度 | {event.dimension} |
| 置信度 | {event.confidence}/100 |
| 来源 | {event.source_account}（共 {source_count} 个来源） |

**详情**：{event.detail}

{if_excerpts}
> **原文摘录**：
> {event.excerpts[0]}
{end_if}

[查看原文]({event.source_url})

---

{end_for_each_event}
{end_for_each_dimension}

## 统计概览

| 维度 | 事件数 |
|------|--------|
{dimension_stats_rows}

---
*本报告由 wechat-intel-viewer 自动生成*
