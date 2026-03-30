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
        if entry.source_count > 1:
            lines.append(f"多源验证: {entry.source_count} 个来源")
        lines.append(f"摘要: {ev.summary or ''}")
        if detail_snippet:
            lines.append(f"详情: {detail_snippet}")
        # 原文摘录（取第一段，截断200字）
        if ev.excerpts:
            excerpt = ev.excerpts[0][:200].strip()
            if excerpt:
                lines.append(f"原文摘录: {excerpt}")
        lines.append("")
    return "\n".join(lines)


def _llm_extract_trends(events_text: str, event_count: int) -> Optional[Dict]:
    """调用 LLM 从事件中提炼趋势，返回含 executive_summary + trends 的字典"""
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
        elif raw.startswith('{') or raw.startswith('['):
            json_str = raw
        else:
            # 尝试找到 { ... } 或 [ ... ]
            start_obj = raw.find('{')
            start_arr = raw.find('[')
            if start_obj >= 0:
                end = raw.rfind('}')
                if end > start_obj:
                    json_str = raw[start_obj:end + 1]
                else:
                    json_str = raw
            elif start_arr >= 0:
                end = raw.rfind(']')
                if end > start_arr:
                    json_str = raw[start_arr:end + 1]
                else:
                    json_str = raw
            else:
                print(f"    ⚠ LLM 返回格式异常: {raw[:200]}")
                return None

        result = json.loads(json_str)

        # 兼容旧格式：如果返回的是数组，包装为新格式
        if isinstance(result, list):
            return {
                "executive_summary": "",
                "trends": result,
            }
        elif isinstance(result, dict) and 'trends' in result:
            return result
        else:
            print(f"    ⚠ LLM 返回结构异常: {list(result.keys()) if isinstance(result, dict) else type(result)}")
            return None

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


def generate_trend_report(entries: List[DigestEntry], date_label: str = None,
                          dimensions: List[str] = None) -> Dict:
    """
    生成趋势分析报告数据

    Args:
        entries: 去重后的 DigestEntry 列表
        date_label: 日期标签
        dimensions: 可选维度过滤列表，如 ['薪酬激励', '人事变动']

    Returns:
        趋势报告数据字典
    """
    if not date_label:
        date_label = datetime.now().strftime("%Y年%m月")

    # 按维度过滤
    if dimensions:
        entries = [e for e in entries if (e.canonical.dimension or '未分类') in dimensions]
        print(f"    维度过滤: {dimensions} → {len(entries)} 条事件")

    # 维度分布
    dim_counter = Counter()
    for entry in entries:
        dim_counter[entry.canonical.dimension or '未分类'] += 1

    # LLM 趋势归纳
    trends = []
    executive_summary = ""
    if len(entries) >= 3:
        events_text = _format_events_for_llm(entries)
        llm_result = _llm_extract_trends(events_text, len(entries))
        if llm_result:
            trends = llm_result.get('trends', [])
            executive_summary = llm_result.get('executive_summary', '')
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
        'executive_summary': executive_summary,
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
    executive_summary = report.get('executive_summary', '')

    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{date_label}_trend_report.md")

    lines = []

    # 标题
    lines.append(f"# HR 市场情报趋势分析报告 — {date_label}")
    lines.append("")
    lines.append(f"> 生成时间: {report['generated_at']}　|　"
                 f"事件总数: {stats['total_events']}　|　"
                 f"核心趋势: {stats['trend_count']} 条")
    lines.append("")

    # 执行摘要
    lines.append("## 📋 执行摘要")
    lines.append("")
    if executive_summary:
        lines.append(executive_summary)
    else:
        dims = stats.get('dimensions', {})
        dim_parts = [f"{k} {v}条" for k, v in dims.items() if v > 0]
        lines.append(f"本月共采集 {stats['total_events']} 条HR动态事件，"
                     f"提炼出 {stats['trend_count']} 条核心趋势。"
                     f"维度分布：{'、'.join(dim_parts)}。")
    lines.append("")

    # 各趋势章节
    for t_idx, trend in enumerate(trends, 1):
        title = trend.get('title', f'趋势 {t_idx}')
        summary = trend.get('summary', '')
        event_indices = trend.get('event_indices', [])

        lines.append(f"## 趋势{t_idx}: {title}")
        lines.append("")
        if summary:
            lines.append(f"**趋势概述**: {summary}")
            lines.append("")
        # 关联事件
        lines.append(f"**关联事件** ({len(event_indices)}条):")
        lines.append("")
        for idx in event_indices:
            if idx < 0 or idx >= len(entries):
                continue
            entry = entries[idx]
            ev = entry.canonical
            company = ev.company or '未知'
            source = ev.source_account or ''
            date = ev.event_date or ''
            summary_text = (ev.summary or '')[:80]
            multi = f" 🔗{entry.source_count}源" if entry.source_count > 1 else ""

            lines.append(f"- **{company}**: {summary_text} （{source}, {date}{multi}）")
            # 原文链接
            if ev.source_url:
                lines.append(f"  - [📎 查看原文]({ev.source_url})")
            # 原文摘要（取第一段excerpts，截断150字）
            if ev.excerpts:
                excerpt = ev.excerpts[0][:150].strip()
                if excerpt:
                    if len(ev.excerpts[0]) > 150:
                        excerpt += '...'
                    lines.append(f"  > {excerpt}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 未归类事件
    if unclassified:
        lines.append("## 📌 其他动态")
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
            url_link = f" [[查看原文]({ev.source_url})]" if ev.source_url else ""
            lines.append(f"- **{company}**: {summary_text} （{source}, {date}）{url_link}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("*报告由 HR 情报趋势分析系统自动生成*")

    content = '\n'.join(lines)
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  ✓ 趋势报告: {filename}")
    return filename


def _refine_excerpts_for_trends(trends_expanded: List[Dict]) -> List[Dict]:
    """用LLM对每个趋势下的事件excerpts做二次提炼，只保留与趋势强相关的内容"""
    if not trends_expanded:
        return trends_expanded

    try:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv(os.path.join(ROOT, '.env'))
        client = OpenAI(
            api_key=os.getenv('LLM_API_KEY'),
            base_url=os.getenv('LLM_BASE_URL'),
        )

        # 构建batch prompt：一次调用处理所有趋势
        lines = []
        lines.append("你是HR情报编辑。以下是多条趋势及其关联事件的原文摘录。")
        lines.append("请对每个事件的原文摘录进行精简，**只保留与该趋势主题直接相关的内容**，删除无关段落、广告、其他公司的内容。")
        lines.append("保持原文措辞，不要改写，只做删减。如果整段都相关则保留全文。\n")

        event_map = {}  # (trend_idx, event_idx) -> original excerpt
        global_idx = 0
        for t_idx, trend in enumerate(trends_expanded):
            lines.append(f"## 趋势: {trend['title']}")
            lines.append(f"概述: {trend['summary']}\n")
            for e_idx, ev in enumerate(trend.get('events', [])):
                excerpts = ev.get('excerpts', [])
                if not excerpts or not excerpts[0].strip():
                    continue
                excerpt_text = excerpts[0][:800]
                lines.append(f"【{global_idx}】{ev.get('company','')} - {ev.get('summary','')[:60]}")
                lines.append(f"原文: {excerpt_text}\n")
                event_map[global_idx] = (t_idx, e_idx)
                global_idx += 1

        if not event_map:
            return trends_expanded

        lines.append("\n请输出JSON数组，每项包含编号和精简后的原文：")
        lines.append('```json')
        lines.append('[{"idx": 0, "refined": "精简后的原文摘录"}, ...]')
        lines.append('```')
        lines.append("注意：只做删减不做改写，保留关键数字/人名/政策细节。")

        prompt = "\n".join(lines)

        resp = client.chat.completions.create(
            model=os.getenv('LLM_MODEL', 'deepseek-chat'),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()

        # 解析JSON
        if '```json' in raw:
            json_str = raw.split('```json')[1].split('```')[0].strip()
        elif '```' in raw:
            json_str = raw.split('```')[1].split('```')[0].strip()
        elif '[' in raw:
            json_str = raw[raw.index('['):raw.rindex(']') + 1]
        else:
            json_str = raw

        results = json.loads(json_str)

        # 回写精简后的excerpts
        refined_count = 0
        for item in results:
            idx = item.get('idx', -1)
            refined = item.get('refined', '').strip()
            if idx in event_map and refined:
                t_idx, e_idx = event_map[idx]
                trends_expanded[t_idx]['events'][e_idx]['excerpts'] = [refined]
                refined_count += 1

        print(f"    LLM 二次提炼 {refined_count}/{len(event_map)} 条事件excerpts")

    except Exception as e:
        print(f"    ⚠ LLM二次提炼失败，使用原始excerpts: {e}")

    return trends_expanded


def render_trend_json(report: Dict, output_dir: str) -> str:
    """
    将趋势报告保存为结构化 JSON 文件（供前端API读取）

    Args:
        report: generate_trend_report() 的返回值
        output_dir: 输出目录

    Returns:
        生成的文件路径
    """
    date_label = report['date_label']
    entries = report['entries']

    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{date_label}_trend_report.json")

    # 将 trends 中的 event_indices 展开为实际事件数据
    trends_expanded = []
    for trend in report['trends']:
        events = []
        for idx in trend.get('event_indices', []):
            if 0 <= idx < len(entries):
                entry = entries[idx]
                ev = entry.canonical
                events.append({
                    'company': ev.company or '',
                    'summary': ev.summary or '',
                    'event_date': ev.event_date or '',
                    'dimension': ev.dimension or '',
                    'source_account': ev.source_account or '',
                    'source_count': entry.source_count,
                    'excerpts': ev.excerpts or [],
                    'source_url': entry.all_urls[0] if entry.all_urls else '',
                })
        trends_expanded.append({
            'title': trend.get('title', ''),
            'summary': trend.get('summary', ''),
            'events': events,
        })

    # LLM二次提炼：只保留与趋势主题强相关的excerpts
    trends_expanded = _refine_excerpts_for_trends(trends_expanded)

    # 未归类事件
    unclassified = []
    for idx in report.get('unclassified_indices', []):
        if 0 <= idx < len(entries):
            entry = entries[idx]
            ev = entry.canonical
            unclassified.append({
                'company': ev.company or '',
                'summary': ev.summary or '',
                'event_date': ev.event_date or '',
                'dimension': ev.dimension or '',
                'source_account': ev.source_account or '',
                'source_url': entry.all_urls[0] if entry.all_urls else '',
            })

    data = {
        'date_label': date_label,
        'generated_at': report['generated_at'],
        'executive_summary': report.get('executive_summary', ''),
        'stats': report['stats'],
        'trends': trends_expanded,
        'unclassified': unclassified,
    }

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  ✓ 趋势报告JSON: {filename}")
    return filename
