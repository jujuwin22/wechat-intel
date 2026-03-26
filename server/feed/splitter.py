"""
feed/splitter.py - 多事件文章拆分
处理"大厂日爆"等综合号文章，将单篇含多个事件的文章拆分为独立Event
"""
import os
import re
import json
import hashlib
from typing import List, Optional

from server.feed.models import Article, Event

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 缓存目录
CACHE_DIR = os.path.join(ROOT, 'data', 'cache', 'split')


def _is_multi_event(article: Article) -> bool:
    """判断文章是否包含多个独立事件"""
    title = article.title or ""

    # 标题含中文分号"；"且长度较长
    semicolons = title.count("；") + title.count(";")
    if semicolons >= 2:
        return True

    # 标题含3+不同段落（用中文分号或逗号分隔）
    segments = re.split(r'[；;]', title)
    if len(segments) >= 3:
        return True

    return False


def _cache_key(url: str) -> str:
    """生成缓存文件名"""
    return hashlib.sha256(url.encode()).hexdigest()[:16] + ".json"


def _load_cache(url: str) -> Optional[List[dict]]:
    """加载拆分缓存"""
    cache_file = os.path.join(CACHE_DIR, _cache_key(url))
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save_cache(url: str, events: List[dict]):
    """保存拆分缓存"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, _cache_key(url))
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"    ⚠ 保存拆分缓存失败: {e}")


def _load_split_prompt() -> str:
    """加载拆分prompt模板"""
    prompt_path = os.path.join(ROOT, 'server', 'config', 'prompts', 'event_split.md')
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        # fallback prompt
        return """你是HR情报分析师。请从以下文章中逐一提取每个独立HR事件，输出JSON数组。
文章标题: {title}
文章发布时间: {published_at}
文章正文: {content}

输出格式: [{{"company":"公司名","event_date":"YYYY-MM-DD","dimension":"薪酬激励|组织架构|人才发展","summary":"一句话摘要","detail":"详细描述","confidence":85}}]"""


def _call_llm_split(article: Article) -> List[dict]:
    """调用LLM拆分多事件文章"""
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(os.path.join(ROOT, '.env'))

    client = OpenAI(
        api_key=os.getenv('LLM_API_KEY'),
        base_url=os.getenv('LLM_BASE_URL'),
    )

    prompt_template = _load_split_prompt()
    # 截断正文避免过长
    content = (article.content or "")[:4000]

    prompt = prompt_template.replace('{title}', article.title or '') \
                            .replace('{published_at}', str(article.published_at or '')) \
                            .replace('{content}', content)

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=os.getenv('LLM_MODEL', 'deepseek-chat'),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()

            # 提取JSON数组
            if '```json' in raw:
                json_str = raw.split('```json')[1].split('```')[0].strip()
            elif '```' in raw:
                json_str = raw.split('```')[1].split('```')[0].strip()
            elif '[' in raw:
                json_str = raw[raw.index('['):raw.rindex(']') + 1]
            else:
                json_str = raw

            events = json.loads(json_str)
            if isinstance(events, list):
                return events
            else:
                return [events]

        except Exception as e:
            if attempt < 2:
                print(f"    LLM拆分重试... ({e})")
                import time
                time.sleep(2)
            else:
                print(f"    LLM拆分失败: {e}")
                return []

    return []


def _article_to_single_event(article: Article) -> Event:
    """将单事件文章直接转为Event（不调LLM）"""
    # 用 hr_details 拼接为详情段落
    detail = ""
    if article.hr_details:
        detail = " ".join(article.hr_details)
    return Event(
        company="",  # 待后续去重阶段识别
        event_date=article.event_date or article.published_at or "",
        dimension=article.dimension or "未分类",
        summary=article.ai_summary or article.title,
        detail=detail,
        confidence=article.ai_confidence or 0,
        source_url=article.url,
        source_account=article.account_name,
        source_title=article.title,
    )


def split_articles(articles: List[Article]) -> List[Event]:
    """
    主入口：将文章列表拆分为事件列表

    - 单事件文章：直接用现有 ai_summary 构造 Event
    - 多事件文章：调用 LLM 从 content 中提取所有事件（有缓存）
    """
    events = []
    multi_count = 0
    split_event_count = 0

    for article in articles:
        if _is_multi_event(article):
            multi_count += 1
            print(f"  🔀 多事件文章: {article.title[:50]}...")

            # 检查缓存
            cached = _load_cache(article.url)
            if cached is not None:
                print(f"    ✓ 使用缓存 ({len(cached)} 个事件)")
                raw_events = cached
            else:
                raw_events = _call_llm_split(article)
                if raw_events:
                    _save_cache(article.url, raw_events)
                    print(f"    ✓ LLM拆分出 {len(raw_events)} 个事件")
                else:
                    # fallback: 拆分失败则保留原始ai_summary作为单事件
                    print(f"    ⚠ 拆分失败，保留原始摘要")
                    events.append(_article_to_single_event(article))
                    continue

            for raw in raw_events:
                event = Event(
                    company=raw.get('company', ''),
                    event_date=raw.get('event_date', article.published_at or ''),
                    dimension=raw.get('dimension', '未分类'),
                    summary=raw.get('summary', ''),
                    detail=raw.get('detail', ''),
                    confidence=raw.get('confidence', 0),
                    source_url=article.url,
                    source_account=article.account_name,
                    source_title=article.title,
                )
                if event.confidence >= 60:
                    events.append(event)
                    split_event_count += 1
        else:
            events.append(_article_to_single_event(article))

    print(f"\n拆分统计:")
    print(f"  单事件文章: {len(articles) - multi_count} 篇 → {len(articles) - multi_count} 个事件")
    print(f"  多事件文章: {multi_count} 篇 → {split_event_count} 个事件")
    print(f"  总计: {len(events)} 个事件")

    return events
