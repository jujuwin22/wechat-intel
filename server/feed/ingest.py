"""
feed/ingest.py - 加载采集结果JSON文件
从 data/cache/results/ 目录递归加载所有 *_wechat.json 文件
"""
import os
import json
import glob
from typing import List

from server.feed.models import Article


def load_wechat_articles(results_dir: str, month_filter: str = None) -> List[Article]:
    """
    加载所有微信公众号采集结果

    Args:
        results_dir: 采集结果根目录 (如 data/cache/results)
        month_filter: 可选月份过滤 (如 "2026年3月")，为None则加载全部

    Returns:
        Article 列表
    """
    articles = []
    json_files = []

    # 递归查找所有 *_wechat.json 文件
    for root, dirs, files in os.walk(results_dir):
        for filename in files:
            if filename.endswith('_wechat.json'):
                if month_filter and month_filter not in filename:
                    continue
                json_files.append(os.path.join(root, filename))

    print(f"找到 {len(json_files)} 个 wechat JSON 文件")

    for filepath in sorted(json_files):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            account_name = data.get('account_name', '')
            collect_date = data.get('collect_date', '')

            for raw_article in data.get('articles', []):
                # 跳过没有 ai_summary 的文章（未通过AI精筛）
                if not raw_article.get('ai_summary'):
                    continue

                article = Article(
                    title=raw_article.get('title', ''),
                    url=raw_article.get('url', ''),
                    content=raw_article.get('content', ''),
                    published_at=raw_article.get('published_at', ''),
                    event_date=raw_article.get('event_date'),
                    dimension=raw_article.get('dimension'),
                    ai_summary=raw_article.get('ai_summary'),
                    ai_confidence=raw_article.get('ai_confidence'),
                    hr_details=raw_article.get('hr_details', []),
                    matched_keywords=raw_article.get('matched_keywords', []),
                    dimensions=raw_article.get('dimensions', []),
                    account_name=account_name,
                    collect_date=collect_date,
                )
                articles.append(article)

        except Exception as e:
            print(f"  警告: 无法解析 {os.path.basename(filepath)}: {e}")

    # 按公众号统计
    account_stats = {}
    for a in articles:
        account_stats[a.account_name] = account_stats.get(a.account_name, 0) + 1

    print(f"共加载 {len(articles)} 篇文章:")
    for name, count in sorted(account_stats.items()):
        print(f"  {name}: {count} 篇")

    return articles
