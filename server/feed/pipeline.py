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
from server.feed.trend_report import generate_trend_report, render_trend_markdown
from server.feed.models import DigestEntry


def load_settings() -> dict:
    """加载 feed_settings.yaml"""
    config_path = os.path.join(ROOT, 'server', 'config', 'feed_settings.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def run_pipeline(month: str = None, no_dedup: bool = False,
                 no_split: bool = False) -> dict:
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
    if no_split:
        from server.feed.splitter import _article_to_single_event
        events = [_article_to_single_event(a) for a in articles]
        print(f"  跳过拆分，直接转换 {len(events)} 个事件")
    else:
        events = split_articles(articles)

    if not events:
        print("⚠ 没有提取到任何事件，退出")
        return {"entries": [], "md_path": None, "json_path": None, "html_path": None, "trend_report_path": None}

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

    # Step 5: 速递输出
    date_label = month or datetime.now().strftime("%Y年%m月")
    print(f"\n[Step 5/6] 生成速递输出...")

    md_path = render_markdown(entries, output_dir, date_label)
    json_path = render_json(entries, output_dir, date_label)
    html_path = render_html(entries, output_dir, date_label)

    # Step 6: 趋势分析报告
    print(f"\n[Step 6/6] 生成趋势分析报告...")
    report = generate_trend_report(entries, date_label)
    trend_report_path = render_trend_markdown(report, output_dir)

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
    args = parser.parse_args()

    run_pipeline(
        month=args.month,
        no_dedup=args.no_dedup,
        no_split=args.no_split,
    )


if __name__ == '__main__':
    main()
