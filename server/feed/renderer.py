"""
feed/renderer.py - 输出生成
将去重后的 DigestEntry 列表渲染为 Markdown 简报和 HTML 页面
"""
import os
import json
from datetime import datetime
from typing import List, Dict
from collections import defaultdict

from server.feed.models import DigestEntry


def render_markdown(entries: List[DigestEntry], output_dir: str,
                    date_label: str = None) -> str:
    """
    渲染 Markdown 新闻简报

    Args:
        entries: 去重后的 DigestEntry 列表
        output_dir: 输出目录
        date_label: 日期标签 (如 "2026年3月")

    Returns:
        生成的文件路径
    """
    if not date_label:
        date_label = datetime.now().strftime("%Y年%m月")

    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{date_label}_digest.md")

    # 统计
    total_events = len(entries)
    accounts = set()
    companies = set()
    for e in entries:
        accounts.update(e.all_sources)
        if e.canonical.company:
            companies.add(e.canonical.company)

    with open(filename, 'w', encoding='utf-8') as f:
        # 标题
        f.write(f"# HR 情报速递 — {date_label}\n\n")
        f.write(f"> 共 {total_events} 条事件 | 来自 {len(accounts)} 个公众号 | ")
        f.write(f"覆盖 {len(companies)} 家公司 | ")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("---\n\n")

        # 按日期倒序平铺展示
        for idx, entry in enumerate(entries, 1):
            ev = entry.canonical

            f.write(f"### {idx}. {ev.summary}\n\n")

            # 元数据行
            f.write(f"- **日期**: {ev.event_date or '未知'}")
            f.write(f" | **置信度**: {ev.confidence}%")
            f.write(f" | **维度**: {ev.dimension}\n")

            if ev.company:
                f.write(f"- **公司**: {ev.company}\n")

            f.write(f"- **来源**: {ev.source_account}")
            if entry.source_count > 1:
                f.write(f" 等{entry.source_count}个来源")
            f.write("\n")

            # 详情
            if ev.detail:
                f.write(f"\n{ev.detail}\n")

            # 原文链接
            if entry.all_urls:
                f.write(f"\n📎 [查看原文]({entry.all_urls[0]})")
                if len(entry.all_urls) > 1:
                    for i, url in enumerate(entry.all_urls[1:], 2):
                        f.write(f" | [来源{i}]({url})")
                f.write("\n")

            f.write("\n---\n\n")

        # 尾部统计
        f.write("## 统计摘要\n\n")
        f.write(f"| 指标 | 数值 |\n")
        f.write(f"|------|------|\n")
        f.write(f"| 总事件数 | {total_events} |\n")
        f.write(f"| 公众号数 | {len(accounts)} |\n")
        f.write(f"| 涉及公司 | {len(companies)} |\n")

        multi = sum(1 for e in entries if e.source_count > 1)
        f.write(f"| 多源验证 | {multi} |\n")

        # 维度分布
        dim_counts = defaultdict(int)
        for e in entries:
            dim_counts[e.canonical.dimension] += 1
        for dim, count in sorted(dim_counts.items(), key=lambda x: -x[1]):
            f.write(f"| {dim} | {count} |\n")

    print(f"  ✓ Markdown 简报: {filename}")
    return filename


def render_json(entries: List[DigestEntry], output_dir: str,
                date_label: str = None) -> str:
    """
    输出结构化 JSON 数据文件

    Args:
        entries: 去重后的 DigestEntry 列表
        output_dir: 输出目录
        date_label: 日期标签

    Returns:
        生成的文件路径
    """
    if not date_label:
        date_label = datetime.now().strftime("%Y年%m月")

    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{date_label}_digest.json")

    # 统计来源和公司
    all_accounts = set()
    all_companies = set()
    for e in entries:
        all_accounts.update(e.all_sources)
        if e.canonical.company:
            all_companies.add(e.canonical.company)

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date_label": date_label,
        "total_events": len(entries),
        "source_accounts": sorted(all_accounts),
        "companies": sorted(all_companies),
        "entries": [e.to_dict() for e in entries],
    }

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  ✓ JSON 数据: {filename}")
    return filename


def render_html(entries: List[DigestEntry], output_dir: str,
                date_label: str = None) -> str:
    """
    渲染 HTML 新闻列表页面

    Args:
        entries: 去重后的 DigestEntry 列表
        output_dir: 输出目录
        date_label: 日期标签

    Returns:
        生成的文件路径
    """
    if not date_label:
        date_label = datetime.now().strftime("%Y年%m月")

    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{date_label}_digest.html")

    # 维度颜色映射
    dim_colors = {
        "薪酬激励": "#e74c3c",
        "组织架构": "#3498db",
        "人才发展": "#2ecc71",
        "企业文化": "#f59e0b",
        "未分类": "#95a5a6",
    }

    accounts_set = set()
    companies_set = set()
    for e in entries:
        accounts_set.update(e.all_sources)
        if e.canonical.company:
            companies_set.add(e.canonical.company)

    # 生成事件卡片 HTML（按日期倒序平铺）
    cards_html = []
    current_date = None
    for idx, entry in enumerate(entries, 1):
        ev = entry.canonical
        color = dim_colors.get(ev.dimension, "#95a5a6")

        # 日期分隔线
        event_date = ev.event_date or "未知"
        if event_date != current_date:
            current_date = event_date
            cards_html.append(f'<h2 class="date-header">📅 {current_date}</h2>')

        source_info = ""
        if entry.source_count > 1:
            source_info = f'<span class="multi-source">🔗 {entry.source_count}个来源</span>'

        links = ""
        if entry.all_urls:
            link_parts = [f'<a href="{entry.all_urls[0]}" target="_blank">查看原文</a>']
            for i, url in enumerate(entry.all_urls[1:], 2):
                link_parts.append(f'<a href="{url}" target="_blank">来源{i}</a>')
            links = " | ".join(link_parts)

        card = f'''
        <div class="event-card" data-dimension="{ev.dimension}">
          <div class="event-header">
            <span class="event-idx">{idx}</span>
            <span class="dimension-tag" style="background:{color}">{ev.dimension}</span>
            <span class="confidence">置信度 {ev.confidence}%</span>
            {source_info}
          </div>
          <h3 class="event-title">{ev.summary}</h3>
          <div class="event-meta">
            <span>📅 {event_date}</span>
            {f'<span>🏢 {ev.company}</span>' if ev.company else ''}
            <span>📰 {ev.source_account}</span>
          </div>
          {f'<p class="event-detail">{ev.detail}</p>' if ev.detail else ''}
          <div class="event-links">{links}</div>
        </div>'''
        cards_html.append(card)

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HR 情报速递 — {date_label}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7fa; color: #333; line-height: 1.6; }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 20px; }}
  .header {{ text-align: center; padding: 30px 0; border-bottom: 2px solid #e1e8ed; margin-bottom: 20px; }}
  .header h1 {{ font-size: 1.8em; color: #2c3e50; }}
  .header .stats {{ color: #7f8c8d; margin-top: 8px; font-size: 0.9em; }}
  .filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; padding: 12px; background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .filter-btn {{ padding: 6px 14px; border: 1px solid #ddd; border-radius: 20px; background: #fff; cursor: pointer; font-size: 0.85em; transition: all 0.2s; }}
  .filter-btn:hover, .filter-btn.active {{ background: #3498db; color: #fff; border-color: #3498db; }}
  .date-header {{ font-size: 1.2em; color: #2c3e50; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 2px solid #3498db; }}
  .event-card {{ background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); transition: box-shadow 0.2s; }}
  .event-card:hover {{ box-shadow: 0 3px 10px rgba(0,0,0,0.12); }}
  .event-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }}
  .event-idx {{ background: #ecf0f1; color: #7f8c8d; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.8em; font-weight: bold; }}
  .dimension-tag {{ color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 0.75em; }}
  .confidence {{ color: #7f8c8d; font-size: 0.8em; }}
  .multi-source {{ color: #e67e22; font-size: 0.8em; font-weight: bold; }}
  .event-title {{ font-size: 1.05em; color: #2c3e50; margin-bottom: 8px; }}
  .event-meta {{ display: flex; gap: 16px; color: #7f8c8d; font-size: 0.85em; margin-bottom: 8px; flex-wrap: wrap; }}
  .event-detail {{ color: #555; font-size: 0.9em; margin-bottom: 8px; }}
  .event-links {{ font-size: 0.85em; }}
  .event-links a {{ color: #3498db; text-decoration: none; }}
  .event-links a:hover {{ text-decoration: underline; }}
  .hidden {{ display: none; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>HR 情报速递 — {date_label}</h1>
    <div class="stats">共 {len(entries)} 条事件 | 来自 {len(accounts_set)} 个公众号 | 覆盖 {len(companies_set)} 家公司 | 生成: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
  </div>

  <div class="filters" id="filters">
    <button class="filter-btn active" onclick="filterAll()">全部</button>
    <button class="filter-btn" onclick="filterDim('薪酬激励')">薪酬激励</button>
    <button class="filter-btn" onclick="filterDim('组织架构')">组织架构</button>
    <button class="filter-btn" onclick="filterDim('人才发展')">人才发展</button>
    <button class="filter-btn" onclick="filterDim('企业文化')">企业文化</button>
  </div>

  <div id="feed">
    {"".join(cards_html)}
  </div>
</div>

<script>
function filterAll() {{
  document.querySelectorAll('.event-card').forEach(c => c.classList.remove('hidden'));
  document.querySelectorAll('.date-header').forEach(h => h.classList.remove('hidden'));
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.filter-btn').classList.add('active');
}}
function filterDim(dim) {{
  document.querySelectorAll('.event-card').forEach(c => {{
    c.classList.toggle('hidden', c.dataset.dimension !== dim);
  }});
  document.querySelectorAll('.date-header').forEach(h => {{
    let hasVisible = false;
    let el = h.nextElementSibling;
    while (el && !el.classList.contains('date-header')) {{
      if (el.classList.contains('event-card') && !el.classList.contains('hidden')) hasVisible = true;
      el = el.nextElementSibling;
    }}
    h.classList.toggle('hidden', !hasVisible);
  }});
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
}}
</script>
</body>
</html>'''

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"  ✓ HTML 页面: {filename}")
    return filename
