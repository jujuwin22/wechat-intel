#!/usr/bin/env python3
"""
微信公众号文章采集脚本
基于 wewe-rss JSON Feed API

使用流程:
1. 确保 wewe-rss 服务已启动 (http://localhost:4000)
2. 在 wewe-rss 中订阅目标公众号
3. 运行此脚本: python -m server.collector.collector
"""

import requests
import json
import time
import os
import re
import random
import yaml
from datetime import datetime
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple

# 尝试导入 anthropic SDK
try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("⚠️ 警告: 未安装 anthropic SDK，AI精筛功能将使用 requests 调用")

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _HTMLTextExtractor(HTMLParser):
    """从 HTML 中提取纯文本"""
    def __init__(self):
        super().__init__()
        self._result = []
    def handle_data(self, data):
        self._result.append(data)
    def get_text(self):
        return ''.join(self._result).strip()


def html_to_text(html: str) -> str:
    """将 HTML 转为纯文本"""
    if not html:
        return ""
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(html)
        return extractor.get_text()
    except Exception:
        # 降级：简单正则去标签
        return re.sub(r'<[^>]+>', '', html).strip()


class WechatCollector:
    def __init__(self, config=None):
        """
        Args:
            config: 配置模块，默认从 collector.config 导入
        """
        if config is None:
            from server.collector import config as _cfg
            config = _cfg
        self.config = config

        self.wewe_rss_url = config.WEWE_RSS_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json"
        })

        # 确保导出目录存在
        os.makedirs(config.EXPORT_DIR, exist_ok=True)

        # 加载公司名列表（用于粗筛）
        self.company_names = self._load_company_names()

        # 加载采集水位线（用于去重）
        self.watermark_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watermark.json')
        self.watermark = self._load_watermark()

    def _load_watermark(self) -> Dict:
        """加载采集水位线，用于跳过已采集文章"""
        if os.path.exists(self.watermark_path):
            try:
                with open(self.watermark_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"  ⚠ 加载水位线失败: {e}")
        return {"accounts": {}}

    def _save_watermark(self):
        """保存采集水位线"""
        try:
            with open(self.watermark_path, 'w', encoding='utf-8') as f:
                json.dump(self.watermark, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  ⚠ 保存水位线失败: {e}")

    def _is_article_collected(self, account_name: str, article: Dict) -> bool:
        """检查文章是否已被采集过（基于水位线）"""
        wm = self.watermark.get("accounts", {}).get(account_name)
        if not wm:
            return False  # 首次采集，不跳过

        url = article.get("url", "")

        # 检查 URL 是否在已采集列表中
        if url and url in wm.get("last_collected_urls", []):
            return True

        # 检查 date_modified 是否早于水位线
        last_date = wm.get("last_collected_date", "")
        article_date = article.get("date_modified", "")
        if last_date and article_date and article_date <= last_date:
            return True

        return False

    def _update_watermark(self, account_name: str, articles: List[Dict]):
        """采集完成后更新水位线"""
        if not articles:
            return

        urls = [a.get("url", "") for a in articles if a.get("url")]
        dates = [a.get("date_modified", "") for a in articles if a.get("date_modified")]

        self.watermark.setdefault("accounts", {})
        existing = self.watermark["accounts"].get(account_name, {})

        # 合并 URL 列表（保留最近100条避免无限增长）
        existing_urls = existing.get("last_collected_urls", [])
        all_urls = list(set(existing_urls + urls))[-100:]

        self.watermark["accounts"][account_name] = {
            "last_collected_date": max(dates) if dates else existing.get("last_collected_date", ""),
            "last_collected_urls": all_urls,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        self._save_watermark()

    def _load_company_names(self) -> List[str]:
        """从 companies.yaml 加载所有公司名称和别名"""
        yaml_path = os.path.join(ROOT, 'server', 'config', 'companies.yaml')
        names = []
        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            for bl in data.get('business_lines', []):
                for c in bl.get('companies', []):
                    names.append(c['name'])
                    names.extend(c.get('aliases', []))
        except Exception as e:
            print(f"  ⚠ 加载公司名列表失败: {e}")
        return names

    def check_company_mention(self, title: str, content: str) -> bool:
        """检查标题或正文是否提到目标公司（标题含排除词直接跳过）"""
        title = title or ''
        # 标题含排除词 → 直接跳过（不管是否含公司名）
        if title and any(kw in title for kw in self.config.EXCLUDE_KEYWORDS):
            return False
        text = title + (content or '')
        return any(name in text for name in self.company_names)

    def check_service_status(self) -> bool:
        """检查 wewe-rss 服务是否可达"""
        try:
            response = self.session.get(
                f"{self.wewe_rss_url}/feeds",
                timeout=10
            )
            if response.status_code == 200:
                feeds = response.json()
                print(f"✓ wewe-rss 服务正常，已订阅 {len(feeds)} 个公众号")
                return True
            else:
                print(f"✗ wewe-rss 返回异常状态码: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ wewe-rss 服务不可达: {e}")
            return False

    def fetch_feeds(self) -> List[Dict]:
        """获取 wewe-rss 所有订阅源列表"""
        try:
            response = self.session.get(f"{self.wewe_rss_url}/feeds", timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print(f"  ✗ 获取订阅源列表失败: {e}")
            return []

    def match_feeds_to_channels(self, feeds: List[Dict]) -> List[Dict]:
        """将 wewe-rss 订阅源与 yaml 配置的公众号匹配

        Returns:
            list of dict: [{channel: yaml_config, feed: wewe_feed}, ...]
        """
        matched = []
        feed_map = {f['name']: f for f in feeds}

        for channel in self.config.OFFICIAL_ACCOUNTS:
            ch_name = channel['name']
            feed_id = channel.get('feed_id', '')

            # 优先用 feed_id 精确匹配
            if feed_id:
                feed = next((f for f in feeds if f['id'] == feed_id), None)
                if feed:
                    matched.append({'channel': channel, 'feed': feed})
                    continue

            # 名称精确匹配
            if ch_name in feed_map:
                matched.append({'channel': channel, 'feed': feed_map[ch_name]})
                continue

            # 模糊匹配：名称互相包含
            found = False
            for feed in feeds:
                fname = feed['name']
                if ch_name in fname or fname in ch_name:
                    matched.append({'channel': channel, 'feed': feed})
                    found = True
                    break

            if not found:
                print(f"  ⚠ 未在 wewe-rss 中找到: {ch_name}")

        return matched

    def fetch_feed_articles(self, feed_id: str, limit: int = 100) -> List[Dict]:
        """从 wewe-rss 获取文章列表（轻量模式，不含全文）

        使用 mode=default 参数，响应仅包含标题/URL/时间，~47KB/100篇。
        全文通过 fetch_article_content 按需逐篇拉取。

        Returns:
            list of dict: [{id, title, url, date_modified, ...}]  (content_html 为空)
        """
        all_items = []
        seen_urls = set()
        page = 1
        page_size = 50  # 轻量模式下每页可拉更多

        while len(all_items) < limit:
            try:
                url = f"{self.wewe_rss_url}/feeds/{feed_id}.json"
                params = {"limit": page_size, "page": page, "mode": "default"}
                response = self.session.get(url, params=params, timeout=15)
                if response.status_code != 200:
                    print(f"  ✗ 获取文章失败: HTTP {response.status_code}")
                    break
                data = response.json()
                items = data.get("items", [])
                if not items:
                    break
                new_count = 0
                for item in items:
                    item_url = item.get("url", "")
                    if item_url not in seen_urls:
                        seen_urls.add(item_url)
                        all_items.append(item)
                        new_count += 1
                if new_count == 0 or len(items) < page_size:
                    break
                page += 1
            except Exception as e:
                print(f"  ✗ 获取文章异常 (page {page}): {e}")
                break

        return all_items[:limit]

    def _batch_fetch_content(self, feed_id: str, target_urls: set) -> Dict[str, str]:
        """分页拉取 fulltext，提取目标 URL 的纯文本正文

        wewe-rss 无法按单篇 URL 查询，因此分页拉取 fulltext 模式
        （每页3篇，~9MB），在内存中匹配目标 URL。

        Args:
            feed_id: 公众号 feed ID
            target_urls: 需要全文的文章 URL 集合

        Returns:
            dict: {url: plain_text_content}
        """
        content_map = {}
        remaining = set(target_urls)
        page = 1
        page_size = 3  # fulltext 模式每页少量，避免超时
        miss_streak = 0  # 连续无新发现的页数
        max_miss = 5  # 连续5页无新发现则停止

        while remaining:
            try:
                url = f"{self.wewe_rss_url}/feeds/{feed_id}.json"
                params = {"limit": page_size, "page": page, "mode": "fulltext"}
                response = self.session.get(url, params=params, timeout=60)
                if response.status_code != 200:
                    print(f"    ✗ 拉取全文失败: HTTP {response.status_code}")
                    break
                data = response.json()
                items = data.get("items", [])
                if not items:
                    break

                found_in_page = 0
                for item in items:
                    item_url = item.get("url", "")
                    if item_url in remaining:
                        content_map[item_url] = html_to_text(item.get("content_html", ""))
                        remaining.discard(item_url)
                        found_in_page += 1

                fetched = len(content_map)
                total = len(target_urls)
                print(f"    全文进度: {fetched}/{total} (page {page})")

                if found_in_page > 0:
                    miss_streak = 0
                else:
                    miss_streak += 1
                    if miss_streak >= max_miss:
                        print(f"    ⚠ 连续{max_miss}页无新发现，停止翻页（{len(remaining)}篇未获取）")
                        break

                if len(items) < page_size:
                    break  # 没有更多文章了
                page += 1
            except Exception as e:
                print(f"    ✗ 拉取全文异常 (page {page}): {e}")
                break

        return content_map

    def is_in_date_range(self, article: Dict) -> bool:
        """检查文章是否在配置的日期范围内（基于 date_modified ISO 格式）"""
        config = self.config
        if not config.FILTER_DATE_START and not config.FILTER_DATE_END:
            return True

        date_str = article.get("date_modified", "")
        if not date_str:
            return True

        try:
            # wewe-rss 返回 ISO 格式: "2026-03-26T13:11:29.000Z"
            article_date = date_str[:10]  # 取 YYYY-MM-DD 部分

            if config.FILTER_DATE_START and article_date < config.FILTER_DATE_START:
                return False
            if config.FILTER_DATE_END and article_date > config.FILTER_DATE_END:
                return False

            return True
        except Exception:
            return True

    def ai_filter_article(self, article: Dict, dimensions: List[str]) -> Optional[Dict]:
        """
        使用AI进行文章精筛
        返回: AI判断结果 或 None（如果失败）
        """
        config = self.config
        if not config.ENABLE_AI_FILTER:
            return None

        try:
            # 准备维度标准描述（始终使用全量4维度，避免遗漏）
            all_dimensions = list(config.DIMENSION_CRITERIA.keys())
            dimension_criteria = []
            for dim in all_dimensions:
                dimension_criteria.append(f"- {dim}: {config.DIMENSION_CRITERIA[dim]}")

            # 截断正文（避免过长）
            content = article.get("content", "")[:5000]

            # 获取发布日期（wewe-rss 用 ISO 格式 date_modified）
            date_mod = article.get('date_modified', '')
            published_at = date_mod[:10] if date_mod else '未知'

            # 构建 prompt
            prompt = config.AI_FILTER_PROMPT.format(
                title=article.get("title", ""),
                digest=article.get("digest", ""),
                content=content,
                published_at=published_at,
                dimensions=", ".join(all_dimensions),
                dimension_criteria="\n".join(dimension_criteria)
            )

            # 调用 AI API
            response = self.call_ai_api(prompt)

            if not response:
                return None

            # 解析JSON响应
            try:
                result = self.extract_json_from_response(response)
                result = self._validate_ai_result(result)
                return result
            except Exception as e:
                print(f"    ✗ AI响应解析失败: {e}")
                return None

        except Exception as e:
            print(f"    ✗ AI精筛异常: {e}")
            return None

    def _validate_ai_result(self, result: Optional[Dict]) -> Optional[Dict]:
        """校验AI精筛结果的格式和值范围"""
        if not result or not isinstance(result, dict):
            return None

        # is_relevant 必须是 bool
        if 'is_relevant' not in result:
            return None
        if not isinstance(result['is_relevant'], bool):
            result['is_relevant'] = str(result['is_relevant']).lower() == 'true'

        # confidence_score 归一化到 0-100
        score = result.get('confidence_score', 0)
        if not isinstance(score, (int, float)):
            try:
                score = int(score)
            except (ValueError, TypeError):
                score = 0
        result['confidence_score'] = max(0, min(100, int(score)))

        # dimension 必须是合法值或 null
        valid_dims = set(self.config.DIMENSION_CRITERIA.keys())
        dim = result.get('dimension')
        if dim and dim not in valid_dims:
            result['dimension'] = None

        # summary 非空检查
        if result.get('is_relevant') and not result.get('summary'):
            result['is_relevant'] = False

        return result

    def call_ai_api(self, prompt: str, max_retries: int = 2) -> Optional[str]:
        """调用 AI API (根据配置选择 DeepSeek 或 Claude)，带重试"""
        provider = getattr(self.config, "AI_PROVIDER", "deepseek").lower()

        for attempt in range(max_retries + 1):
            if provider == "deepseek":
                result = self.call_deepseek_api(prompt)
            else:
                result = self.call_claude_api(prompt)

            if result is not None:
                return result

            if attempt < max_retries:
                wait = 2 * (attempt + 1)
                print(f"    ⏳ AI调用失败，{wait}s后重试 ({attempt + 1}/{max_retries})...")
                import time
                time.sleep(wait)

        return None

    def call_deepseek_api(self, prompt: str) -> Optional[str]:
        """调用 DeepSeek API (兼容 OpenAI 格式)"""
        config = self.config
        try:
            api_key = config.DEEPSEEK_API_KEY
            if not api_key:
                print("    ⚠️ 未设置 LLM_API_KEY，跳过AI精筛")
                return None

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": config.DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": "你是一个专业的HR行业分析师，擅长判断文章内容是否属于HR专业领域。请严格按照用户要求返回JSON格式。"},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 1000,
                "temperature": 0
            }

            response = requests.post(
                f"{config.DEEPSEEK_API_BASE}/chat/completions",
                headers=headers,
                json=data,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            else:
                print(f"    ✗ DeepSeek API调用失败: {response.status_code} - {response.text[:100]}")
                return None

        except Exception as e:
            print(f"    ✗ DeepSeek API调用异常: {e}")
            return None

    def call_claude_api(self, prompt: str) -> Optional[str]:
        """调用 Claude API"""
        config = self.config
        try:
            api_key = config.CLAUDE_API_KEY
            if not api_key:
                print("    ⚠️ 未设置 ANTHROPIC_API_KEY，跳过AI精筛")
                return None

            if ANTHROPIC_AVAILABLE:
                client = Anthropic(api_key=api_key)
                response = client.messages.create(
                    model=config.CLAUDE_MODEL,
                    max_tokens=1000,
                    temperature=0,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                return response.content[0].text
            else:
                headers = {
                    "x-api-key": api_key,
                    "content-type": "application/json",
                    "anthropic-version": "2023-06-01"
                }

                data = {
                    "model": config.CLAUDE_MODEL,
                    "max_tokens": 1000,
                    "temperature": 0,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ]
                }

                response = requests.post(
                    f"{config.CLAUDE_API_BASE}/v1/messages",
                    headers=headers,
                    json=data,
                    timeout=60
                )

                if response.status_code == 200:
                    result = response.json()
                    return result["content"][0]["text"]
                else:
                    print(f"    ✗ Claude API调用失败: {response.status_code}")
                    return None

        except Exception as e:
            print(f"    ✗ Claude API调用异常: {e}")
            return None

    def extract_json_from_response(self, response: str) -> Optional[Dict]:
        """从AI响应中提取JSON"""
        # 尝试直接解析
        try:
            return json.loads(response)
        except:
            pass

        # 尝试提取代码块中的JSON
        json_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
        matches = re.findall(json_pattern, response, re.DOTALL)

        for match in matches:
            try:
                return json.loads(match.strip())
            except:
                continue

        # 尝试提取花括号中的JSON
        json_pattern = r'\{[\s\S]*\}'
        matches = re.findall(json_pattern, response)

        for match in matches:
            try:
                return json.loads(match)
            except:
                continue

        raise ValueError("无法从响应中提取JSON")

    def parse_event_date(self, event_date_raw: str) -> Optional[str]:
        """解析 AI 返回的 event_date，统一为 YYYY-MM-DD 格式"""
        if not event_date_raw or event_date_raw.strip().lower() in ('', 'null', 'none'):
            return None

        event_date = event_date_raw.strip()
        date_formats = [
            '%Y-%m-%d',
            '%Y年%m月%d日',
            '%Y/%m/%d',
            '%Y.%m.%d',
            '%Y%m%d',
            '%Y-%m',
            '%Y年%m月',
        ]
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(event_date, fmt)
                return parsed_date.strftime('%Y-%m-%d')
            except ValueError:
                continue
        return None

    def save_to_json(self, account_name: str, articles: List[Dict], date_str: str):
        """保存为统一格式 JSON"""
        config = self.config
        filename = f"{config.EXPORT_DIR}/{date_str}_{account_name}_wechat.json"

        unified_articles = []
        for a in articles:
            ai = a.get('ai_result', {})
            date_mod = a.get('date_modified', '')
            pub_at = date_mod[:10] if date_mod else ''
            unified_articles.append({
                'title': a.get('title', ''),
                'url': a.get('url', ''),
                'content': a.get('content', ''),
                'event_date': self.parse_event_date(ai.get('event_date', '')),
                'dimension': ai.get('dimension'),
                'ai_summary': ai.get('summary', ''),
                'hr_details': ai.get('excerpts', []),
                'matched_keywords': a.get('matched_keywords', []),
                'dimensions': a.get('dimensions', []),
                'ai_confidence': ai.get('confidence_score'),
                'published_at': pub_at,
                'local_path': None,
            })

        # 增量合并：若已有同月同公众号的 JSON，先读取旧文章，以 URL 去重后合并
        old_articles = []
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                old_articles = old_data.get("articles", [])
            except Exception as ex:
                print(f"  ⚠ 读取旧文件失败，将全量覆盖: {ex}")

        if old_articles:
            existing_urls = {a.get("url") for a in unified_articles if a.get("url")}
            added = 0
            for old_a in old_articles:
                if old_a.get("url") not in existing_urls:
                    unified_articles.append(old_a)
                    added += 1
            if added:
                print(f"  增量合并: 保留旧文章 {added} 篇，合并后共 {len(unified_articles)} 篇")

        data = {
            "source": "wechat",
            "company_name": None,
            "account_name": account_name,
            "domain_group": None,
            "collect_date": date_str,
            "total_count": len(unified_articles),
            "articles": unified_articles
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"  ✓ JSON 已保存: {filename}")
        return filename

    def save_to_markdown(self, account_name: str, articles: List[Dict], date_str: str):
        """保存为统一格式 Markdown（从对应JSON读取全量文章，保持与JSON一致）"""
        config = self.config
        filename = f"{config.EXPORT_DIR}/{date_str}_{account_name}_wechat.md"
        json_filename = f"{config.EXPORT_DIR}/{date_str}_{account_name}_wechat.json"

        # 从JSON文件读取完整文章列表（JSON已做增量合并，以其为准）
        all_articles = articles
        if os.path.exists(json_filename):
            try:
                with open(json_filename, "r", encoding="utf-8") as f:
                    json_data = json.load(f)
                all_articles = json_data.get("articles", articles)
            except Exception:
                pass

        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# {account_name} - HR 情报采集\n\n")
            f.write(f"- 来源: wechat (wewe-rss)\n")
            f.write(f"- 公众号: {account_name}\n")
            f.write(f"- 采集日期: {date_str}\n")
            f.write(f"- 共 {len(all_articles)} 条\n\n---\n\n")

            for idx, article in enumerate(all_articles, 1):
                f.write(f"## {idx}. {article['title']}\n\n")

                # 发布时间（优先 published_at，fallback date_modified）
                pub_str = (article.get('published_at') or article.get('date_modified') or '')[:10]
                f.write(f"- **发布时间**: {pub_str}\n")
                f.write(f"- **链接**: {article.get('url', '')}\n")

                if article.get("matched_keywords"):
                    f.write(f"- **匹配关键词**: {', '.join(article['matched_keywords'])}\n")

                f.write(f"- **适用维度**: {', '.join(article.get('dimensions', []))}\n")

                if article.get("ai_result"):
                    ai = article['ai_result']
                    event_date = ai.get('event_date') or ''
                    f.write(f"- **AI精筛**: 通过 (置信度: {ai.get('confidence_score', 0)}%)\n")
                    f.write(f"- **匹配维度**: {ai.get('dimension', '')}\n")
                    if event_date:
                        f.write(f"- **事件时间**: {event_date}\n")

                f.write("\n")

                # AI摘要
                if article.get("ai_result") and article['ai_result'].get("summary"):
                    f.write(f"**AI摘要**: {article['ai_result']['summary']}\n\n")

                # 原文详情
                if article.get("ai_result") and article['ai_result'].get("excerpts"):
                    f.write(f"**原文详情**:\n\n")
                    for excerpt in article['ai_result']['excerpts']:
                        f.write(f"> {excerpt}\n\n")

                f.write("---\n\n")

        print(f"  ✓ Markdown 已保存: {filename}")
        return filename

    def collect_account(self, channel: Dict, feed: Dict, date_str: str) -> Dict:
        """采集单个公众号（两阶段：轻量列表 → 逐篇拉全文）"""
        config = self.config
        name = channel['name']
        dimensions = channel.get('dimensions', [])
        feed_id = feed['id']
        feed_name = feed['name']

        print(f"\n{'='*60}")
        print(f"开始采集: {name} (wewe-rss: {feed_name})")
        print(f"feed_id: {feed_id}")
        print(f"{'='*60}")

        result = {
            "name": name,
            "feed_id": feed_id,
            "total_checked": 0,
            "matched": [],
            "errors": []
        }

        # ── 阶段1: 轻量列表（mode=default, ~47KB/100篇）──────
        print(f"[1/5] 获取文章列表（轻量模式）...")
        raw_articles = self.fetch_feed_articles(feed_id, config.MAX_ARTICLES_PER_ACCOUNT)
        if not raw_articles:
            print(f"  ⚠ 无文章数据")
            result["errors"].append("无文章数据")
            return result

        print(f"  ✓ 共获取 {len(raw_articles)} 篇文章（轻量）")
        result["total_checked"] = len(raw_articles)

        # 1.5 水位线去重
        before_wm = len(raw_articles)
        raw_articles = [a for a in raw_articles if not self._is_article_collected(name, a)]
        skipped = before_wm - len(raw_articles)
        if skipped > 0:
            print(f"  ✓ 水位线去重: 跳过 {skipped} 篇已采集，剩余 {len(raw_articles)} 篇")

        # 2. 日期过滤
        if config.FILTER_DATE_START or config.FILTER_DATE_END:
            print(f"[2/5] 日期过滤 ({config.FILTER_DATE_START or '不限'} ~ {config.FILTER_DATE_END or '不限'})...")
            raw_articles = [a for a in raw_articles if self.is_in_date_range(a)]
            print(f"  ✓ 日期过滤后: {len(raw_articles)} 篇")

        if not raw_articles:
            print(f"  - 无文章需要处理")
            return result

        # 3. 标题粗筛（不需要正文，毫秒级）
        print(f"[3/5] 标题粗筛 ({len(raw_articles)} 篇)...")
        title_matched = []
        title_unmatched = []

        for article in raw_articles:
            if self.check_company_mention(article.get('title', ''), ''):
                article['dimensions'] = dimensions
                title_matched.append(article)
            else:
                title_unmatched.append(article)

        print(f"  ✓ 标题命中: {len(title_matched)} 篇, 未命中: {len(title_unmatched)} 篇")

        # ── 阶段2: 逐篇拉全文（仅对需要的文章）──────────────
        # 标题命中的 → 直接拉全文给 AI 精筛
        # 标题未命中的 → 拉全文做正文粗筛
        need_content_urls = set()
        for a in title_matched:
            need_content_urls.add(a.get('url', ''))
        for a in title_unmatched:
            need_content_urls.add(a.get('url', ''))

        print(f"[4/5] 拉取全文 ({len(need_content_urls)} 篇)...")
        content_map = self._batch_fetch_content(feed_id, need_content_urls)
        print(f"  ✓ 成功获取 {sum(1 for v in content_map.values() if v)} 篇全文")

        # 给所有文章填充正文
        for a in title_matched + title_unmatched:
            url = a.get('url', '')
            a['content'] = content_map.get(url, '')
            a['digest'] = a['content'][:200] if a['content'] else ''

        # 标题未命中的做正文二次粗筛
        content_matched = []
        for article in title_unmatched:
            if article.get('content') and self.check_company_mention('', article['content']):
                article['dimensions'] = dimensions
                content_matched.append(article)

        if content_matched:
            print(f"  ✓ 正文补充命中: {len(content_matched)} 篇")

        company_matched = title_matched + content_matched
        print(f"  ✓ 公司名粗筛合计: {len(company_matched)} 篇")

        # 5. AI精筛
        matched_articles = []

        if config.ENABLE_AI_FILTER and company_matched:
            print(f"[5/5] AI精筛 ({len(company_matched)} 篇)...")

            for idx, article in enumerate(company_matched, 1):
                print(f"  AI精筛 {idx}/{len(company_matched)}: {article.get('title','')[:40]}...", end=" ")

                ai_result = self.ai_filter_article(article, dimensions)

                if ai_result:
                    is_relevant = ai_result.get("is_relevant", False)
                    confidence = ai_result.get("confidence_score", 0)

                    if is_relevant and confidence >= config.AI_CONFIDENCE_THRESHOLD:
                        article['ai_result'] = ai_result
                        matched_articles.append(article)
                        print(f"✓ ({ai_result.get('dimension', '?')}, {confidence}%)")
                    else:
                        reason = ai_result.get("reason", "未匹配")[:30]
                        print(f"✗ ({reason})")
                else:
                    print("✗ AI失败，丢弃")

                time.sleep(1)
        else:
            matched_articles = company_matched

        # 5.5 抽检：粗筛未命中的文章随机抽样走AI精筛
        coarse_unmatched = [a for a in title_unmatched if a not in content_matched]
        spot_check_count = max(1, int(len(coarse_unmatched) * config.SPOT_CHECK_RATIO))
        spot_check_count = min(spot_check_count, len(coarse_unmatched))

        if config.ENABLE_AI_FILTER and coarse_unmatched and spot_check_count > 0:
            spot_sample = random.sample(coarse_unmatched, spot_check_count)
            print(f"  [抽检] 粗筛未命中 {len(coarse_unmatched)} 篇，抽检 {spot_check_count} 篇...")
            spot_hits = 0

            for idx, article in enumerate(spot_sample, 1):
                print(f"    抽检 {idx}/{spot_check_count}: {article.get('title','')[:40]}...", end=" ")
                ai_result = self.ai_filter_article(article, dimensions)

                if ai_result:
                    is_relevant = ai_result.get("is_relevant", False)
                    confidence = ai_result.get("confidence_score", 0)

                    if is_relevant and confidence >= config.AI_CONFIDENCE_THRESHOLD:
                        article['ai_result'] = ai_result
                        article['dimensions'] = dimensions
                        article['spot_check'] = True
                        matched_articles.append(article)
                        spot_hits += 1
                        print(f"✓ 捞回 ({ai_result.get('dimension', '?')}, {confidence}%)")
                    else:
                        print(f"✗")
                else:
                    print("✗ AI失败")

                time.sleep(1)

            miss_rate = spot_hits / spot_check_count * 100 if spot_check_count > 0 else 0
            print(f"  [抽检结果] 抽检 {spot_check_count} 篇，捞回 {spot_hits} 篇，漏判率估计 {miss_rate:.0f}%")
            if miss_rate > 30:
                print(f"  ⚠ 漏判率较高 ({miss_rate:.0f}%)，建议检查粗筛规则")

        result["matched"] = matched_articles

        # 保存结果
        if matched_articles:
            self.save_to_json(name, matched_articles, date_str)
            self.save_to_markdown(name, matched_articles, date_str)
        else:
            print(f"  - 无匹配文章，跳过保存")

        # 更新水位线（对所有拉取的文章列表，非只是匹配的）
        if raw_articles:
            self._update_watermark(name, raw_articles)
            print(f"  ✓ 水位线已更新: {name}")

        return result

    def run(self):
        """运行采集任务"""
        config = self.config
        print("\n" + "="*60)
        print("微信公众号文章采集工具 (wewe-rss)")
        print("="*60)

        # 检查 wewe-rss 服务
        print("\n[检查 wewe-rss 服务]")
        if not self.check_service_status():
            print("\n⚠️ 请先完成以下步骤:")
            print(f"1. 确保 wewe-rss 服务已启动: {self.wewe_rss_url}")
            print("2. 在 wewe-rss 中订阅目标公众号")
            print("3. 重新运行此脚本")
            return

        # 获取订阅源并匹配
        print("\n[匹配订阅源]")
        feeds = self.fetch_feeds()
        matched_pairs = self.match_feeds_to_channels(feeds)

        if not matched_pairs:
            print("✗ 没有匹配到任何公众号，请检查 wewe-rss 订阅和 wechat_channels.yaml 配置")
            return

        print(f"  ✓ 匹配到 {len(matched_pairs)} 个公众号")
        for pair in matched_pairs:
            print(f"    {pair['channel']['name']} → {pair['feed']['name']} ({pair['feed']['id'][:20]}...)")

        # 文件名前缀：用搜索区间而非执行日期
        if config.FILTER_DATE_START:
            parts = config.FILTER_DATE_START.split('-')
            date_str = f"{parts[0]}年{int(parts[1])}月"
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")

        print(f"\n搜索区间: {date_str}")
        print(f"目标公众号: {len(matched_pairs)} 个")
        print(f"导出目录: {config.EXPORT_DIR}")

        # 采集所有公众号
        all_results = []

        for pair in matched_pairs:
            try:
                result = self.collect_account(pair['channel'], pair['feed'], date_str)
                all_results.append(result)
            except Exception as e:
                print(f"\n  ✗ 采集异常: {e}")
                all_results.append({
                    "name": pair['channel']['name'],
                    "error": str(e)
                })

        # 汇总报告
        print("\n" + "="*60)
        print("采集完成 - 汇总报告")
        print("="*60)

        total_checked = sum(r.get("total_checked", 0) for r in all_results)
        total_matched = sum(len(r.get("matched", [])) for r in all_results)

        print(f"\n总计检查文章: {total_checked} 篇")
        print(f"匹配文章: {total_matched} 篇")
        print(f"\n各公众号详情:")

        for result in all_results:
            name = result.get("name", "Unknown")
            checked = result.get("total_checked", 0)
            matched = len(result.get("matched", []))
            errors = result.get("errors", [])

            if errors:
                print(f"  {name}: 检查 {checked} 篇, 匹配 {matched} 篇, 错误: {'; '.join(errors)}")
            else:
                print(f"  {name}: 检查 {checked} 篇, 匹配 {matched} 篇")

        print(f"\n导出文件位置: {config.EXPORT_DIR}")
        print("="*60)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))

    # 直接运行时，使用本模块的 config
    import server.collector.config as config
    collector = WechatCollector(config=config)
    collector.run()
