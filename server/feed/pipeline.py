"""
feed/pipeline.py - 管道编排
串联: ingest → split → quality_filter → dedup → render → trend_report

用法:
    python -m server.feed.pipeline                        # 默认处理全部
    python -m server.feed.pipeline --month 2026年3月      # 指定月份
    python -m server.feed.pipeline --no-dedup             # 跳过LLM去重
"""
import os
import sys
import argparse
import yaml
from datetime import datetime

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server.feed.ingest import load_wechat_articles
from server.feed.splitter import split_articles
from server.feed.quality_filter import filter_events_by_quality
from server.feed.dedup import deduplicate_events
from server.feed.renderer import render_markdown, render_json, render_html
from server.feed.trend_report import generate_trend_report, render_trend_markdown, render_trend_json
from server.feed.models import DigestEntry


def _refine_excerpts(entries, threshold: int = 150) -> None:
    """对 excerpts 字数超过 threshold 的事件调 LLM 精炼成 3-5 句核心内容（原地修改）"""
    import os
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(os.path.join(ROOT, '.env'))
    client = OpenAI(
        api_key=os.getenv('LLM_API_KEY'),
        base_url=os.getenv('LLM_BASE_URL'),
    )
    model = os.getenv('LLM_MODEL', 'deepseek-chat')

    import re as _re
    _META_LINE = _re.compile(r'^(文章标题|文章发布时间|发布时间)\s*[:：]')

    def _is_junk_excerpts(ev) -> bool:
        """判断 excerpts 是否全是无意义内容（元数据行/与标题重复/太短）"""
        if not ev.excerpts:
            return False
        title = (ev.source_title or '').strip()
        real = []
        for line in ev.excerpts:
            s = line.strip()
            if not s:
                continue
            if _META_LINE.match(s):
                continue
            # 与文章标题相同
            if title and s == title:
                continue
            # 行太短（少于8个中文字），没有信息量
            cn_count = sum(1 for c in s if '\u4e00' <= c <= '\u9fff')
            if cn_count < 8:
                continue
            real.append(s)
        return len(real) == 0

    # 预清洗：过滤无效 excerpts
    cleaned = 0
    for entry in entries:
        ev = entry.canonical
        if ev.excerpts and _is_junk_excerpts(ev):
            ev.excerpts = []
            cleaned += 1
    if cleaned:
        print(f"  excerpts 预清洗: {cleaned} 条无效摘录已清空")

    refined = 0
    for entry in entries:
        ev = entry.canonical
        if not ev.excerpts:
            continue
        full_text = '\n'.join(ev.excerpts)
        if len(full_text) < threshold:
            continue
        prompt = (
            f'事件摘要：{ev.summary}\n\n'
            f'以下是该事件对应的原文摘录，请从中**直接摘抄**3-5句与事件摘要最相关的原文句子。\n'
            f'要求：\n'
            f'1. 必须是原文中出现的原话，不得改写、总结或补充\n'
            f'2. 每句单独一行，不加编号、标题或任何解释\n'
            f'3. 优先选含具体数字、人名、职级、政策细节的句子\n\n'
            f'原文摘录：\n{full_text[:2000]}'
        )
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.1,
            )
            result = resp.choices[0].message.content.strip()
            lines = [l.strip() for l in result.split('\n') if len(l.strip()) >= 8]
            if lines:
                ev.excerpts = lines
                refined += 1
        except Exception as e:
            pass  # 失败则保留原 excerpts

    if refined:
        print(f"  excerpts LLM提炼: {refined} 条过长摘录已精炼")


def load_settings() -> dict:
    """加载 feed_settings.yaml"""
    config_path = os.path.join(ROOT, 'server', 'config', 'feed_settings.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def run_pipeline(month: str = None, no_dedup: bool = False,
                 no_split: bool = False, no_cache: bool = False) -> dict:
    """
    运行完整管道

    Args:
        month: 月份过滤 (如 "2026年3月")，None则处理全部
        no_dedup: 跳过LLM去重
        no_split: 跳过多事件拆分

    Returns:
        {"entries": [...], "md_path": "...", "json_path": "...", "html_path": "...", "trend_report_path": "..."}
    """
    settings = load_settings()
    results_dir = os.path.join(ROOT, 'data', 'cache', 'results')
    output_dir = os.path.join(ROOT, settings.get('output', {}).get('output_dir', 'data/output'))

    print("=" * 60)
    print("Feed Pipeline — HR 情报速递")
    print("=" * 60)
    print(f"数据目录: {results_dir}")
    print(f"输出目录: {output_dir}")
    if month:
        print(f"月份过滤: {month}")
    print()

    # Step 1: 加载数据
    print("[Step 1/6] 加载采集数据...")
    articles = load_wechat_articles(results_dir, month_filter=month)

    if not articles:
        print("⚠ 没有找到任何文章，退出")
        return {"entries": [], "md_path": None, "json_path": None, "html_path": None, "trend_report_path": None}

    # Step 2: 多事件拆分
    print(f"\n[Step 2/6] 多事件拆分...")
    if no_cache:
        import server.feed.splitter as _splitter_mod
        _splitter_mod._use_cache = False
        print("  ⚠ 缓存已禁用")
    if no_split:
        from server.feed.splitter import _article_to_single_event
        events = [_article_to_single_event(a) for a in articles]
        print(f"  跳过拆分，直接转换 {len(events)} 个事件")
    else:
        events = split_articles(articles)

    if not events:
        print("⚠ 没有提取到任何事件，退出")
        return {"entries": [], "md_path": None, "json_path": None, "html_path": None, "trend_report_path": None}

    # Step 2.5a: 公司名回填（从summary中提取）
    from server.feed.dedup import _load_company_aliases
    alias_map = _load_company_aliases()
    # 按名称长度降序，优先匹配长名
    alias_names = sorted(alias_map.keys(), key=len, reverse=True)
    backfill_count = 0
    for ev in events:
        if not ev.company or ev.company in ('未知', ''):
            text = (ev.summary or '') + (ev.detail or '') + (ev.source_title or '')
            for name in alias_names:
                if name in text:
                    ev.company = alias_map[name]
                    backfill_count += 1
                    break
    if backfill_count:
        print(f"  公司名回填: {backfill_count} 个事件从摘要中提取到公司名")

    # Step 2.5b: 按事件日期过滤（只保留当月事件）
    if month:
        import re
        m = re.search(r'(\d{4})\D*(\d{1,2})', month)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            prefix = f"{y}-{mo:02d}"
            before = len(events)
            events = [ev for ev in events if ev.event_date and ev.event_date.startswith(prefix)]
            filtered = before - len(events)
            if filtered:
                print(f"  日期过滤: 移除 {filtered} 条非{month}事件，保留 {len(events)} 条")

    # Step 3: 事件质量精筛
    print(f"\n[Step 3/6] 事件质量精筛...")
    events = filter_events_by_quality(events)

    if not events:
        print("⚠ 精筛后没有事件，退出")
        return {"entries": [], "md_path": None, "json_path": None, "html_path": None, "trend_report_path": None}

    # Step 4: 去重
    print(f"\n[Step 4/6] 跨源去重...")
    if no_dedup:
        # 跳过去重，每个事件直接包装为 DigestEntry
        entries = [
            DigestEntry(
                canonical=ev,
                source_count=1,
                all_sources=[ev.source_account],
                all_urls=[ev.source_url],
            )
            for ev in events
        ]
        print(f"  跳过去重，保留 {len(entries)} 个事件")
    else:
        entries = deduplicate_events(events)

    if not entries:
        print("⚠ 去重后没有事件，退出")
        return {"entries": [], "md_path": None, "json_path": None, "html_path": None, "trend_report_path": None}

    # Step 5: 速递输出（增量合并）
    date_label = month or datetime.now().strftime("%Y年%m月")
    print(f"\n[Step 5/6] 生成速递输出...")

    # 增量合并：加载已有的 digest.json，将旧 entries 与新 entries 合并
    existing_json_path = os.path.join(output_dir, f"{date_label}_digest.json")
    import json as _json
    if os.path.exists(existing_json_path):
        try:
            with open(existing_json_path, 'r', encoding='utf-8') as f:
                existing_data = _json.load(f)
            from server.feed.models import Event
            old_entries = []
            for e in existing_data.get('entries', []):
                c = e.get('canonical', {})
                ev = Event(
                    company=c.get('company', ''),
                    event_date=c.get('event_date', ''),
                    dimension=c.get('dimension', ''),
                    summary=c.get('summary', ''),
                    detail=c.get('detail', ''),
                    confidence=c.get('confidence', 0),
                    source_url=c.get('source_url', ''),
                    source_account=c.get('source_account', ''),
                    source_title=c.get('source_title', ''),
                    excerpts=c.get('excerpts', []),
                )
                old_entries.append(DigestEntry(
                    canonical=ev,
                    source_count=e.get('source_count', 1),
                    all_sources=e.get('all_sources', []),
                    all_urls=e.get('all_urls', []),
                ))
            # 以 source_url + summary前30字 为 key 做增量去重：新数据优先（覆盖旧条目）
            # 同一文章可能被拆成多个事件，所以不能仅用 source_url
            def _merge_key(entry):
                url = entry.canonical.source_url or ''
                summ = (entry.canonical.summary or '')[:30]
                return f"{url}|{summ}"

            merged: dict = {}
            for entry in old_entries:
                merged[_merge_key(entry)] = entry
            for entry in entries:
                merged[_merge_key(entry)] = entry  # 新数据覆盖旧数据
            entries = list(merged.values())
            before_rededup = len(entries)
            # 增量合并后对全量 entries 补一次完整去重，消除跨批次语义重复
            all_events = [e.canonical for e in entries]
            entries = deduplicate_events(all_events)
            # 按事件日期倒序排列
            entries.sort(key=lambda e: e.canonical.event_date or '', reverse=True)
            print(f"  增量合并: 旧 {len(old_entries)} 条 + 新增/去重后 = {len(entries)} 条 (合并前 {before_rededup} 条)")
        except Exception as ex:
            print(f"  ⚠ 加载已有数据失败，将全量覆盖: {ex}")

    # Step 5.5: excerpts LLM 二次提炼（仅对字数超过150字的条目）
    print(f"\n[Step 5.5] excerpts 二次提炼...")
    _refine_excerpts(entries, threshold=150)

    md_path = render_markdown(entries, output_dir, date_label)
    json_path = render_json(entries, output_dir, date_label)
    html_path = render_html(entries, output_dir, date_label)

    # Step 6: 趋势分析报告
    print(f"\n[Step 6/6] 生成趋势分析报告...")
    report = generate_trend_report(entries, date_label)
    trend_report_path = render_trend_markdown(report, output_dir)
    render_trend_json(report, output_dir)

    # 汇总
    print(f"\n{'=' * 60}")
    print(f"Pipeline 完成!")
    print(f"{'=' * 60}")
    print(f"  事件总数: {len(entries)}")
    print(f"  Markdown: {md_path}")
    print(f"  JSON:     {json_path}")
    print(f"  HTML:     {html_path}")
    print(f"  趋势报告: {trend_report_path}")

    return {
        "entries": entries,
        "md_path": md_path,
        "json_path": json_path,
        "html_path": html_path,
        "trend_report_path": trend_report_path,
    }


def main():
    parser = argparse.ArgumentParser(description='Feed Pipeline — HR 情报速递')
    parser.add_argument('--month', help='月份过滤 (如 "2026年3月")')
    parser.add_argument('--no-dedup', action='store_true', help='跳过LLM去重')
    parser.add_argument('--no-split', action='store_true', help='跳过多事件拆分')
    parser.add_argument('--no-cache', action='store_true', help='禁用拆分缓存')
    args = parser.parse_args()

    run_pipeline(
        month=args.month,
        no_dedup=args.no_dedup,
        no_split=args.no_split,
        no_cache=args.no_cache,
    )


if __name__ == '__main__':
    main()
