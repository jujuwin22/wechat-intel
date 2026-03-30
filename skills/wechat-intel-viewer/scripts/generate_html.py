#!/usr/bin/env python3
"""
HR情报可视化HTML生成器
从digest.json生成交互式HTML报告
"""

import json
import sys
import argparse
from datetime import datetime
from pathlib import Path

# 维度颜色映射
DIMENSION_COLORS = {
    '薪酬激励': '#ff6b6b',
    '人事变动': '#4ecdc4',
    '组织架构': '#45b7d1',
    '人才发展': '#96ceb4',
    '企业文化': '#feca57',
    '未分类': '#dfe6e9'
}

# HTML模板
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f5f7fa;
            padding: 20px;
            line-height: 1.6;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }}
        .header h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .header .stats {{ opacity: 0.9; font-size: 14px; }}
        .filter-bar {{
            display: flex;
            gap: 12px;
            margin-bottom: 24px;
            flex-wrap: wrap;
        }}
        .filter-btn {{
            padding: 8px 16px;
            border: none;
            border-radius: 20px;
            background: white;
            color: #666;
            font-size: 13px;
            cursor: pointer;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            transition: all 0.2s;
        }}
        .filter-btn:hover, .filter-btn.active {{
            background: #667eea;
            color: white;
        }}
        .event-card {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .event-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        .event-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }}
        .event-number {{
            width: 32px;
            height: 32px;
            background: #f0f2f5;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            color: #666;
            font-size: 14px;
        }}
        .dimension-tag {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
            color: white;
        }}
        .event-date {{ color: #999; font-size: 13px; }}
        .event-title {{
            font-size: 17px;
            font-weight: 600;
            color: #1a1a1a;
            margin-bottom: 12px;
            line-height: 1.5;
        }}
        .event-summary {{
            color: #555;
            font-size: 14px;
            margin-bottom: 12px;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 3px solid #e0e0e0;
        }}
        .excerpts {{
            background: #f8f9fa;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }}
        .excerpts-title {{
            font-size: 12px;
            color: #999;
            margin-bottom: 8px;
            font-weight: 500;
        }}
        .excerpt-item {{
            color: #666;
            font-size: 13px;
            line-height: 1.8;
            margin-bottom: 8px;
            padding-left: 12px;
            border-left: 2px solid #e0e0e0;
        }}
        .excerpt-item:last-child {{ margin-bottom: 0; }}
        .event-footer {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
            padding-top: 16px;
            border-top: 1px solid #f0f0f0;
        }}
        .event-meta {{
            display: flex;
            align-items: center;
            gap: 16px;
            font-size: 13px;
            color: #888;
        }}
        .confidence {{
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .confidence-bar {{
            width: 60px;
            height: 6px;
            background: #e0e0e0;
            border-radius: 3px;
            overflow: hidden;
        }}
        .confidence-fill {{
            height: 100%;
            background: linear-gradient(90deg, #4caf50, #8bc34a);
            border-radius: 3px;
        }}
        .source-link {{
            color: #1976d2;
            text-decoration: none;
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .source-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 {title}</h1>
            <div class="stats">{stats}</div>
        </div>
        <div class="filter-bar">
            <button class="filter-btn active" onclick="filterEvents('all')">全部</button>
            <button class="filter-btn" onclick="filterEvents('薪酬激励')">薪酬激励</button>
            <button class="filter-btn" onclick="filterEvents('人事变动')">人事变动</button>
            <button class="filter-btn" onclick="filterEvents('组织架构')">组织架构</button>
            <button class="filter-btn" onclick="filterEvents('人才发展')">人才发展</button>
            <button class="filter-btn" onclick="filterEvents('企业文化')">企业文化</button>
        </div>
        {events}
    </div>
    <script>
        function filterEvents(dimension) {{
            const cards = document.querySelectorAll('.event-card');
            const buttons = document.querySelectorAll('.filter-btn');
            buttons.forEach(btn => {{
                btn.classList.remove('active');
                if (btn.textContent === (dimension === 'all' ? '全部' : dimension)) {{
                    btn.classList.add('active');
                }}
            }});
            cards.forEach(card => {{
                if (dimension === 'all' || card.dataset.dimension === dimension) {{
                    card.style.display = 'block';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}
    </script>
</body>
</html>'''


def generate_event_card(index, entry):
    """生成单个事件卡片HTML"""
    c = entry.get('canonical', {})
    date = c.get('event_date', '未知')
    company = c.get('company') or '未指定'
    dimension = c.get('dimension', '未分类')
    summary = c.get('summary', '')
    detail = c.get('detail', '')
    source = c.get('source_account', '未知')
    confidence = c.get('confidence', 0)
    url = c.get('source_url', '')
    excerpts = c.get('excerpts', [])

    color = DIMENSION_COLORS.get(dimension, '#dfe6e9')

    # 构建摘录HTML
    excerpts_html = ''
    if excerpts:
        excerpt_items = ''.join([
            f'<div class="excerpt-item">{ex}</div>'
            for ex in excerpts[:3] if ex
        ])
        excerpts_html = f'''
        <div class="excerpts">
            <div class="excerpts-title">原文摘录</div>
            {excerpt_items}
        </div>'''

    return f'''
    <div class="event-card" data-dimension="{dimension}">
        <div class="event-header">
            <span class="event-number">{index}</span>
            <span class="dimension-tag" style="background: {color}">{dimension}</span>
            <span class="event-date">{date}</span>
        </div>
        <div class="event-title">{summary}</div>
        <div class="event-summary">{detail}</div>
        {excerpts_html}
        <div class="event-footer">
            <div class="event-meta">
                <span>{company}</span>
                <span>·</span>
                <span>{source}</span>
                <span class="confidence">
                    置信度 {confidence}%
                    <span class="confidence-bar">
                        <span class="confidence-fill" style="width: {confidence}%"></span>
                    </span>
                </span>
            </div>
            <a href="{url}" target="_blank" class="source-link">查看原文 →</a>
        </div>
    </div>'''


def generate_html(input_file, output_file=None):
    """从JSON生成HTML报告"""
    # 读取数据
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    entries = data.get('entries', [])
    entries.sort(key=lambda x: x.get('canonical', {}).get('event_date', ''), reverse=True)

    date_label = data.get('date_label', 'HR情报动态')
    total = len(entries)
    companies = len(set(e.get('canonical', {}).get('company', '') for e in entries if e.get('canonical', {}).get('company')))
    sources = len(set(e.get('canonical', {}).get('source_account', '') for e in entries))

    # 生成事件卡片
    events_html = ''.join([
        generate_event_card(i + 1, entry)
        for i, entry in enumerate(entries)
    ])

    # 组装HTML
    html = HTML_TEMPLATE.format(
        title=f'{date_label}HR情报动态',
        stats=f'共计 {total} 条事件 · 覆盖 {companies} 家企业 · {sources} 个信源',
        events=events_html
    )

    # 确定输出路径
    if not output_file:
        desktop = Path.home() / 'Desktop'
        output_file = desktop / f'HR情报_{date_label}.html'

    # 写入文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'✅ HTML报告已生成: {output_file}')
    print(f'📊 包含 {total} 条事件')
    return output_file


def main():
    parser = argparse.ArgumentParser(description='HR情报HTML生成器')
    parser.add_argument('input', help='输入的JSON文件路径')
    parser.add_argument('-o', '--output', help='输出HTML文件路径（默认为桌面）')

    args = parser.parse_args()
    generate_html(args.input, args.output)


if __name__ == '__main__':
    main()
