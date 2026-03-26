#!/usr/bin/env python3
"""
微信公众号文章采集脚本
基于 wechat-article-exporter API

使用流程:
1. 先启动 docker-compose up -d
2. 访问 http://localhost:3000 扫码登录
3. 运行此脚本: python collector.py
"""

import requests
import json
import time
import os
import re
import yaml
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlencode

# 尝试导入 anthropic SDK
try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("⚠️ 警告: 未安装 anthropic SDK，AI精筛功能将使用 requests 调用")

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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

        self.base_url = config.BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

        # 设置登录凭证 (从浏览器获取的 auth-key)
        self.auth_key = os.environ.get("WECHAT_AUTH_KEY", "")
        if self.auth_key:
            self.session.cookies.set("auth-key", self.auth_key)

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

        url = article.get("link", "")
        create_time = article.get("create_time", 0)

        # 检查 URL 是否在已采集列表中
        if url and url in wm.get("last_collected_urls", []):
            return True

        # 检查 create_time 是否早于水位线
        last_time = wm.get("last_collected_time", 0)
        if last_time and isinstance(create_time, (int, float)) and create_time <= last_time:
            return True

        return False

    def _update_watermark(self, account_name: str, articles: List[Dict]):
        """采集完成后更新水位线"""
        if not articles:
            return

        urls = [a.get("link", "") for a in articles if a.get("link")]
        create_times = [a.get("create_time", 0) for a in articles
                        if isinstance(a.get("create_time", 0), (int, float))]

        self.watermark.setdefault("accounts", {})
        existing = self.watermark["accounts"].get(account_name, {})

        # 合并 URL 列表（保留最近100条避免无限增长）
        existing_urls = existing.get("last_collected_urls", [])
        all_urls = list(set(existing_urls + urls))[-100:]

        self.watermark["accounts"][account_name] = {
            "last_collected_time": max(create_times) if create_times else existing.get("last_collected_time", 0),
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
        """检查标题或正文是否提到目标公司"""
        text = (title or '') + (content or '')
        return any(name in text for name in self.company_names)

    def check_login_status(self) -> bool:
        """检查登录状态"""
        try:
            # 通过搜索接口验证登录状态
            test_response = self.session.get(
                f"{self.base_url}/api/web/mp/searchbiz",
                params={"keyword": "test", "begin": 0, "size": 1},
                timeout=10
            )
            test_data = test_response.json()

            # 如果 ret == 0 表示 API 调用成功（无论是否有结果）
            if test_data.get("base_resp", {}).get("ret") == 0:
                print("✓ 已登录，API 可正常调用")
                return True
            else:
                err_msg = test_data.get("base_resp", {}).get("err_msg", "未知错误")
                print(f"✗ 未登录或登录已过期: {err_msg}")
                return False
        except Exception as e:
            print(f"✗ 检查登录状态失败: {e}")
            return False

    def search_account(self, name: str, account_id: str = "") -> Optional[Dict]:
        """搜索公众号，优先用名称搜索并验证匹配"""
        try:
            # 优先用公众号名称搜索
            for keyword in [name, account_id] if account_id else [name]:
                url = f"{self.base_url}/api/web/mp/searchbiz"
                params = {"keyword": keyword, "begin": 0, "size": 5}

                response = self.session.get(url, params=params)
                data = response.json()

                if "base_resp" in data and data["base_resp"].get("ret") != 0:
                    continue

                list_data = data.get("list", [])
                if not list_data:
                    continue

                # 验证：检查返回结果的nickname是否包含目标名称
                for item in list_data:
                    nickname = item.get("nickname", "")
                    if name in nickname or nickname in name:
                        return item

                # 如果用名称搜索且第一个结果没匹配，打印警告继续尝试ID
                if keyword == name:
                    candidates = [item.get("nickname", "?") for item in list_data[:3]]
                    print(f"  ⚠ 用名称'{name}'搜索未精确匹配，候选: {candidates}，尝试用ID搜索...")

            print(f"  ✗ 未找到公众号: {name} (ID: {account_id})")
            return None

        except Exception as e:
            print(f"  ✗ 搜索异常: {e}")
            return None

    def get_articles(self, fakeid: str, keyword: str = "", begin: int = 0, count: int = 10) -> List[Dict]:
        """获取公众号文章列表"""
        try:
            url = f"{self.base_url}/api/web/mp/appmsgpublish"
            params = {
                "id": fakeid,
                "keyword": keyword,
                "begin": begin,
                "size": count
            }

            response = self.session.get(url, params=params)
            data = response.json()

            # 检查错误
            if "base_resp" in data and data["base_resp"].get("ret") != 0:
                print(f"  ✗ 获取文章失败: {data['base_resp'].get('err_msg', 'Unknown error')}")
                return []

            # 解析文章列表
            articles = []

            # publish_page 是 JSON 字符串，需要先解析
            publish_page_str = data.get("publish_page", "")
            if publish_page_str:
                try:
                    publish_page = json.loads(publish_page_str)
                    publish_list = publish_page.get("publish_list", [])
                except json.JSONDecodeError:
                    publish_list = []
            else:
                publish_list = []

            for item in publish_list:
                publish_info_str = item.get("publish_info", "")
                if not publish_info_str:
                    continue

                try:
                    publish_info = json.loads(publish_info_str)
                except json.JSONDecodeError:
                    continue

                # 获取文章信息 (从 appmsgex 字段)
                app_msg_ex = publish_info.get("appmsgex", [])
                if not app_msg_ex:
                    continue

                for msg in app_msg_ex:
                    article = {
                        "title": msg.get("title", ""),
                        "digest": msg.get("digest", ""),  # 摘要
                        "link": msg.get("link", ""),
                        "cover": msg.get("cover", ""),
                        "create_time": msg.get("create_time", ""),
                        "update_time": msg.get("update_time", ""),
                        "author": msg.get("author_name", ""),
                        "fakeid": fakeid,
                        "content": "",  # 稍后获取正文
                    }
                    articles.append(article)

            return articles

        except Exception as e:
            print(f"  ✗ 获取文章异常: {e}")
            return []

    def get_article_content(self, link: str) -> str:
        """获取文章正文内容（使用 download API，支持全文获取）"""
        try:
            url = f"{self.base_url}/api/public/v1/download"
            params = {"url": link, "format": "text"}
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code == 200 and response.text:
                return response.text.strip()
            return ""
        except Exception as e:
            print(f"    ✗ 获取正文失败: {e}")
            return ""

    def match_keywords(self, content: str, keywords: List[str]) -> Tuple[bool, List[str]]:
        """
        检查内容是否匹配关键词（或关系）
        返回: (是否匹配, 匹配到的关键词列表)
        """
        if not content or not keywords:
            return False, []

        content_lower = content.lower()
        matched = []

        for keyword in keywords:
            if keyword.lower() in content_lower:
                matched.append(keyword)

        return len(matched) > 0, matched

    def is_in_date_range(self, article: Dict) -> bool:
        """
        检查文章是否在配置的日期范围内
        返回: True 如果在范围内或没有配置日期范围
        """
        config = self.config
        # 如果没有配置日期范围，返回True
        if not config.FILTER_DATE_START and not config.FILTER_DATE_END:
            return True

        # 获取文章创建时间
        create_time = article.get("create_time", "")
        if not create_time:
            return True  # 没有时间信息，默认包含

        try:
            # 时间戳转换
            if isinstance(create_time, (int, float)):
                article_date = datetime.fromtimestamp(create_time)
            else:
                return True

            # 检查日期范围
            if config.FILTER_DATE_START:
                start_date = datetime.strptime(config.FILTER_DATE_START, "%Y-%m-%d")
                if article_date < start_date:
                    return False

            if config.FILTER_DATE_END:
                end_date = datetime.strptime(config.FILTER_DATE_END, "%Y-%m-%d")
                end_date = end_date.replace(hour=23, minute=59, second=59)
                if article_date > end_date:
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
            # 准备维度标准描述
            dimension_criteria = []
            for dim in dimensions:
                if dim in config.DIMENSION_CRITERIA:
                    dimension_criteria.append(f"- {dim}: {config.DIMENSION_CRITERIA[dim]}")

            # 截断正文（避免过长）
            content = article.get("content", "")[:3000]

            # 获取发布日期
            pub_ts = article.get('create_time', '')
            if pub_ts and str(pub_ts).isdigit():
                published_at = datetime.fromtimestamp(int(pub_ts)).strftime('%Y-%m-%d')
            else:
                published_at = str(pub_ts) if pub_ts else '未知'

            # 构建 prompt
            prompt = config.AI_FILTER_PROMPT.format(
                title=article.get("title", ""),
                digest=article.get("digest", ""),
                content=content,
                published_at=published_at,
                dimensions=", ".join(dimensions),
                dimension_criteria="\n".join(dimension_criteria)
            )

            # 调用 AI API
            response = self.call_ai_api(prompt)

            if not response:
                return None

            # 解析JSON响应
            try:
                result = self.extract_json_from_response(response)
                return result
            except Exception as e:
                print(f"    ✗ AI响应解析失败: {e}")
                return None

        except Exception as e:
            print(f"    ✗ AI精筛异常: {e}")
            return None

    def call_ai_api(self, prompt: str) -> Optional[str]:
        """调用 AI API (根据配置选择 DeepSeek 或 Claude)"""
        provider = getattr(self.config, "AI_PROVIDER", "deepseek").lower()

        if provider == "deepseek":
            return self.call_deepseek_api(prompt)
        else:
            return self.call_claude_api(prompt)

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
                "max_tokens": 1000
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
            # published_at：Unix 时间戳转为可读日期字符串
            pub_ts = a.get('create_time', '')
            if pub_ts and str(pub_ts).isdigit():
                pub_at = datetime.fromtimestamp(int(pub_ts)).strftime('%Y-%m-%d')
            else:
                pub_at = str(pub_ts)
            unified_articles.append({
                'title': a.get('title', ''),
                'url': a.get('link', ''),
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
        """保存为统一格式 Markdown"""
        config = self.config
        filename = f"{config.EXPORT_DIR}/{date_str}_{account_name}_wechat.md"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# {account_name} - HR 情报采集\n\n")
            f.write(f"- 来源: wechat\n")
            f.write(f"- 公众号: {account_name}\n")
            f.write(f"- 采集日期: {date_str}\n")
            f.write(f"- 共 {len(articles)} 条\n\n---\n\n")

            for idx, article in enumerate(articles, 1):
                f.write(f"## {idx}. {article['title']}\n\n")
                f.write(f"- **作者**: {article.get('author', '')}\n")

                # 发布时间
                pub_ts = article.get('create_time', '')
                if pub_ts and str(pub_ts).isdigit():
                    pub_str = datetime.fromtimestamp(int(pub_ts)).strftime('%Y-%m-%d')
                else:
                    pub_str = str(pub_ts)
                f.write(f"- **发布时间**: {pub_str}\n")
                f.write(f"- **链接**: {article.get('link', '')}\n")

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

    def collect_account(self, account_info: Tuple, date_str: str) -> Dict:
        """采集单个公众号"""
        config = self.config
        name, account_id, keywords, dimensions = account_info

        print(f"\n{'='*60}")
        print(f"开始采集: {name}")
        print(f"关键词: {', '.join(keywords)}")
        print(f"{'='*60}")

        result = {
            "name": name,
            "account_id": account_id,
            "total_checked": 0,
            "matched": [],
            "errors": []
        }

        # 1. 搜索公众号获取 fakeid
        print(f"[1/3] 搜索公众号...")
        search_result = self.search_account(name, account_id)
        if not search_result:
            result["errors"].append("搜索公众号失败")
            return result

        fakeid = search_result.get("fakeid")
        print(f"  ✓ 找到公众号: {search_result.get('nickname', name)} (fakeid: {fakeid[:20]}...)")

        # 2. 获取文章列表
        print(f"[2/3] 获取文章列表...")
        all_articles = []
        begin = 0

        while len(all_articles) < config.MAX_ARTICLES_PER_ACCOUNT:
            articles = self.get_articles(fakeid, "", begin, config.BATCH_SIZE)
            if not articles:
                break

            all_articles.extend(articles)
            print(f"  已获取 {len(all_articles)} 篇文章...")

            begin += config.BATCH_SIZE
            time.sleep(config.REQUEST_DELAY)

        print(f"  ✓ 共获取 {len(all_articles)} 篇文章")
        result["total_checked"] = len(all_articles)

        # 2.5 水位线去重
        before_watermark = len(all_articles)
        all_articles = [a for a in all_articles if not self._is_article_collected(name, a)]
        skipped = before_watermark - len(all_articles)
        if skipped > 0:
            print(f"  ✓ 水位线去重: 跳过 {skipped} 篇已采集文章，剩余 {len(all_articles)} 篇")

        # 3. 日期过滤
        if config.FILTER_DATE_START or config.FILTER_DATE_END:
            print(f"[3/5] 日期过滤 ({config.FILTER_DATE_START or '不限'} 至 {config.FILTER_DATE_END or '不限'})...")
            date_filtered_articles = []
            for article in all_articles:
                if self.is_in_date_range(article):
                    date_filtered_articles.append(article)
            print(f"  ✓ 日期过滤后: {len(date_filtered_articles)} 篇文章")
            all_articles = date_filtered_articles

        # 4. 公司名粗筛
        print(f"[4/5] 公司名粗筛...")
        company_matched_articles = []

        for idx, article in enumerate(all_articles, 1):
            title = article['title'][:40]
            print(f"  粗筛第 {idx}/{len(all_articles)} 篇: {title}...", end=" ")

            title_match = self.check_company_mention(article['title'], '')
            content = self.get_article_content(article['link'])
            article['content'] = content
            content_match = self.check_company_mention('', content)

            if title_match or content_match:
                article['dimensions'] = dimensions
                company_matched_articles.append(article)
                if title_match and content_match:
                    print("✓ 标题+正文含公司名")
                elif title_match:
                    print("✓ 标题含公司名")
                else:
                    print("✓ 正文含公司名")
            else:
                print("✗")

            time.sleep(config.REQUEST_DELAY)

        print(f"  ✓ 公司名粗筛: {len(company_matched_articles)} 篇命中")

        # 5. AI精筛
        matched_articles = []
        articles_for_ai = company_matched_articles

        if config.ENABLE_AI_FILTER and articles_for_ai:
            print(f"[5/6] AI精筛 ({len(articles_for_ai)}篇文章)...")

            for idx, article in enumerate(articles_for_ai, 1):
                print(f"  AI精筛第 {idx}/{len(articles_for_ai)} 篇: {article['title'][:40]}...", end=" ")

                if not article.get('content'):
                    article['content'] = self.get_article_content(article['link'])

                ai_result = self.ai_filter_article(article, dimensions)

                if ai_result:
                    is_relevant = ai_result.get("is_relevant", False)
                    confidence = ai_result.get("confidence_score", 0)

                    confidence_threshold = config.AI_CONFIDENCE_THRESHOLD
                    if is_relevant and confidence >= confidence_threshold:
                        article['ai_result'] = ai_result
                        matched_articles.append(article)
                        print(f"✓ 通过 ({ai_result.get('dimension', 'Unknown')}, 置信度{confidence})")
                    else:
                        reason = ai_result.get("reason", "未匹配")[:30]
                        print(f"✗ 拒绝 ({reason}...)")
                else:
                    matched_articles.append(article)
                    print("⚠️ AI失败，保留粗筛结果")

                time.sleep(2)
        else:
            matched_articles = company_matched_articles

        # 6. 事件日期后置过滤
        if config.FILTER_DATE_START or config.FILTER_DATE_END:
            print(f"[6/6] 事件日期过滤 ({config.FILTER_DATE_START or '不限'} 至 {config.FILTER_DATE_END or '不限'})...")
            date_filtered_articles = []
            for article in matched_articles:
                ai_result = article.get('ai_result', {})
                event_date_str = ai_result.get('event_date', '')

                event_date = self.parse_event_date(event_date_str)
                if not event_date:
                    pub_ts = article.get('create_time', '')
                    if pub_ts and str(pub_ts).isdigit():
                        event_date = datetime.fromtimestamp(int(pub_ts)).strftime('%Y-%m-%d')
                    else:
                        date_filtered_articles.append(article)
                        continue

                in_range = True
                if config.FILTER_DATE_START:
                    if event_date < config.FILTER_DATE_START:
                        in_range = False
                        print(f"    ✗ 事件日期 {event_date} 早于搜索范围")
                if config.FILTER_DATE_END:
                    if event_date > config.FILTER_DATE_END:
                        in_range = False
                        print(f"    ✗ 事件日期 {event_date} 晚于搜索范围")

                if in_range:
                    date_filtered_articles.append(article)
                else:
                    if ai_result:
                        ai_result['event_date'] = event_date

            matched_articles = date_filtered_articles
            print(f"  ✓ 事件日期过滤后: {len(matched_articles)} 篇文章")

        result["matched"] = matched_articles

        # 保存结果
        if matched_articles:
            self.save_to_json(name, matched_articles, date_str)
            self.save_to_markdown(name, matched_articles, date_str)
        else:
            print(f"  - 无匹配文章，跳过保存")

        # 更新水位线
        if all_articles:
            self._update_watermark(name, all_articles)
            print(f"  ✓ 水位线已更新: {name}")

        return result

    def run(self):
        """运行采集任务"""
        config = self.config
        print("\n" + "="*60)
        print("微信公众号文章采集工具")
        print("="*60)

        # 检查登录状态
        print("\n[检查登录状态]")
        if not self.check_login_status():
            print("\n⚠️ 请先完成以下步骤:")
            print("1. 确保 Docker 服务已启动: docker-compose up -d")
            print("2. 访问 http://localhost:3000")
            print("3. 使用微信扫码登录")
            print("4. 重新运行此脚本")
            return

        # 文件名前缀：用搜索区间而非执行日期
        if config.FILTER_DATE_START:
            parts = config.FILTER_DATE_START.split('-')
            date_str = f"{parts[0]}年{int(parts[1])}月"
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
        print(f"\n搜索区间: {date_str}")
        print(f"目标公众号: {len(config.OFFICIAL_ACCOUNTS)} 个")
        print(f"导出目录: {config.EXPORT_DIR}")

        # 采集所有公众号
        all_results = []

        for account_info in config.OFFICIAL_ACCOUNTS:
            try:
                result = self.collect_account(account_info, date_str)
                all_results.append(result)
                time.sleep(2)
            except Exception as e:
                print(f"\n  ✗ 采集异常: {e}")
                all_results.append({
                    "name": account_info[0],
                    "error": str(e)
                })

        # 汇总报告
        print("\n" + "="*60)
        print("采集完成 - 汇总报告")
        print("="*60)

        total_checked = sum(r.get("total_checked", 0) for r in all_results)
        total_matched = sum(len(r.get("matched", [])) for r in all_results)

        print(f"\n总计检查文章: {total_checked} 篇")
        print(f"匹配关键词文章: {total_matched} 篇")
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
