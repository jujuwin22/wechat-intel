"""
feed/trend_report.py - 趋势分析报告 V2
用 LLM 从当月事件中提炼核心趋势，按趋势组织事件，生成 Markdown 报告。
"""
import os
import json
from datetime import datetime
from collections import Counter
from typing import List, Dict, Optional

from server.feed.models import DigestEntry

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_trend_prompt() -> str:
    """加载趋势归纳 prompt 模板"""
    prompt_path = os.path.join(ROOT, 'server', 'config', 'prompts', 'trend-extract.md')
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""


def _format_events_for_llm(entries: List[DigestEntry]) -> str:
    """将事件列表格式化为 LLM 可读文本"""
    lines = []
    for i, entry in enumerate(entries):
        ev = entry.canonical
        company = ev.company or '未知'
        detail_snippet = (ev.detail or '')[:200].strip()
        lines.append(f"【事件 {i}】")
        lines.append(f"公司: {company}")
        lines.append(f"维度: {ev.dimension or '未分类'}")
        lines.append(f"日期: {ev.event_date or '未知'}")
        lines.append(f"来源: {ev.source_account or '未知'}")
        lines.append(f"摘要: {ev.summary or ''}")
        if detail_snippet:
            lines.append(f"详情: {detail_snippet}")
        lines.append("")
    return "\n".join(lines)


def _llm_extract_trends(events_text: str, event_count: int) -> Optional[List[Dict]]:
    """调用 LLM 从事件中提炼趋势"""
    prompt_template = _load_trend_prompt()
    if not prompt_template:
        print("    ⚠ 未找到趋势归纳prompt (config/prompts/trend-extract.md)")
        return None

    prompt = prompt_template.replace('{event_count}', str(event_count))
    prompt = prompt.replace('{events_text}', events_text)

    try:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv(os.path.join(ROOT, '.env'))

        client = OpenAI(
            api_key=os.getenv('LLM_API_KEY'),
            base_url=os.getenv('LLM_BASE_URL'),
        )

        resp = client.chat.completions.create(
            model=os.getenv('LLM_MODEL', 'deepseek-chat'),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()

        # 提取 JSON
        if '```json' in raw:
            json_str = raw.split('```json')[1].split('```')[0].strip()
        elif '```' in raw:
            json_str = raw.split('```')[1].split('```')[0].strip()
        elif raw.startswith('['):
            json_str = raw
        else:
            # 尝试找到 [ ... ]
            start = raw.find('[')
            end = raw.rfind(']')
            if start >= 0 and end > start:
                json_str = raw[start:end + 1]
            else:
                print(f"    ⚠ LLM 返回格式异常: {raw[:200]}")
                return None

        trends = json.loads(json_str)
        if not isinstance(trends, list):
            return None

        return trends

    except Exception as e:
        print(f"    ⚠ LLM 趋势归纳失败: {e}")
        return None


def _fallback_by_dimension(entries: List[DigestEntry]) -> List[Dict]:
    """降级策略：按维度分组"""
    from collections import defaultdict
    dim_groups = defaultdict(list)
    for i, entry in enumerate(entries):
        dim_groups[entry.canonical.dimension or '未分类'].append(i)

    trends = []
    for dim, indices in dim_groups.items():
        if indices:
            trends.append({
                'title': f'{dim}相关动态',
                'summary': f'本月共有 {len(indices)} 条{dim}相关事件。',
                'event_indices': indices,
            })
    trends.sort(key=lambda t: len(t['event_indices']), reverse=True)
    return trends


def generate_trend_report(entries: List[DigestEntry], date_label: str = None) -> Dict:
    """
    生成趋势分析报告数据

    Args:
        entries: 去重后的 DigestEntry 列表
        date_label: 日期标签

    Returns:
        趋势报告数据字典
    """
    if not date_label:
        date_label = datetime.now().strftime("%Y年%m月")

    # 维度分布
    dim_counter = Counter()
    for entry in entries:
        dim_counter[entry.canonical.dimension or '未分类'] += 1

    # LLM 趋势归纳
    trends = []
    if len(entries) >= 3:
        events_text = _format_events_for_llm(entries)
        llm_trends = _llm_extract_trends(events_text, len(entries))
        if llm_trends:
            trends = llm_trends
            print(f"    LLM 提炼出 {len(trends)} 条趋势")
        else:
            print("    LLM 失败，回退到按维度分组")
            trends = _fallback_by_dimension(entries)
    elif entries:
        trends = _fallback_by_dimension(entries)

    # 找出未归类事件
    classified_indices = set()
    for trend in trends:
        for idx in trend.get('event_indices', []):
            if 0 <= idx < len(entries):
                classified_indices.add(idx)
    unclassified_indices = [i for i in range(len(entries)) if i not in classified_indices]

    return {
        'date_label': date_label,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'stats': {
            'total_events': len(entries),
            'trend_count': len(trends),
            'dimensions': dict(dim_counter),
        },
        'trends': trends,
        'unclassified_indices': unclassified_indices,
        'entries': entries,
    }


def render_trend_markdown(report: Dict, output_dir: str) -> str:
    """
    将趋势报告渲染为 Markdown 文件

    Args:
        report: generate_trend_report() 的返回值
        output_dir: 输出目录

    Returns:
        生成的文件路径
    """
    date_label = report['date_label']
    stats = report['stats']
    trends = report['trends']
    entries = report['entries']
    unclassified = report['unclassified_indices']

    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{date_label}_trend_report.md")

    lines = []

    # 标题
    lines.append(f"# HR 市场情报趋势分析报告 — {date_label}")
    lines.append("")
    lines.append(f"**生成时间**: {report['generated_at']}")
    lines.append("")

    # 执行摘要
    lines.append("## 执行摘要")
    lines.append("")
    lines.append(f"- **总事件数**: {stats['total_events']}")
    lines.append(f"- **提炼趋势**: {stats['trend_count']} 条")
    dims = stats.get('dimensions', {})
    dim_parts = [f"{k} {v}" for k, v in dims.items() if v > 0]
    if dim_parts:
        lines.append(f"- **维度分布**: {' / '.join(dim_parts)}")
    lines.append("")

    # 各趋势章节
    for t_idx, trend in enumerate(trends, 1):
        title = trend.get('title', f'趋势 {t_idx}')
        summary = trend.get('summary', '')
        event_indices = trend.get('event_indices', [])

        lines.append(f"## 趋势{t_idx}: {title}")
        lines.append("")
        if summary:
            lines.append(f"*{summary}*")
            lines.append("")

        for idx in event_indices:
            if idx < 0 or idx >= len(entries):
                continue
            entry = entries[idx]
            ev = entry.canonical
            company = ev.company or '未知'
            source = ev.source_account or ''
            date = ev.event_date or ''

            lines.append(f"### {company} — {(ev.summary or '')[:60]}")
            lines.append("")

            # 详情（hr_details 原文段落）
            detail = (ev.detail or '').strip()
            if detail:
                # 取前 500 字作为详情引用
                snippet = detail[:500]
                if len(detail) > 500:
                    snippet += '...'
                lines.append(f"> {snippet}")
                lines.append("")

            lines.append(f"- **来源**: {source} | **日期**: {date}")
            if entry.source_count > 1:
                lines.append(f"- **多源验证**: {entry.source_count} 个来源")
            lines.append("")

        lines.append("---")
        lines.append("")

    # 未归类事件
    if unclassified:
        lines.append("## 其他动态")
        lines.append("")
        for idx in unclassified:
            if idx < 0 or idx >= len(entries):
                continue
            entry = entries[idx]
            ev = entry.canonical
            company = ev.company or '未知'
            summary_text = (ev.summary or '')[:80]
            source = ev.source_account or ''
            date = ev.event_date or ''
            lines.append(f"- **{company}**: {summary_text} （{source}, {date}）")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("*报告由 HR 情报趋势分析系统自动生成*")

    content = '\n'.join(lines)
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  ✓ 趋势报告: {filename}")
    return filename
