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

# 模块级缓存开关（pipeline可通过 splitter._use_cache = False 禁用）
_use_cache = True


def _unescape_and_strip(fragment: str) -> str:
    """对HTML片段做反转义+去标签，返回纯文本"""
    bs = chr(92)
    if bs + 'x3c' in fragment:
        fragment = fragment.replace(bs + 'x3c', '<').replace(bs + 'x3e', '>') \
                          .replace(bs + 'x26', '&').replace(bs + 'x22', '"') \
                          .replace(bs + 'x27', "'").replace(bs + 'x0a', '\n')
    # 去标签
    text = re.sub(r'<[^>]{0,500}>', ' ', fragment)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
    text = re.sub(r'&#?\w{1,10};', '', text)
    # 清理 JS 包装
    text = re.sub(r"JsDecode\(['\"]?", '', text)
    text = re.sub(r"['\"]?\)\s*,?\s*", ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def _extract_text_for_llm(raw: str, max_chars: int = 5000) -> str:
    """从原始HTML中提取纯文本给LLM（关键词定位+局部反转义）"""
    if not raw:
        return ""
    if '<' not in raw[:500] and chr(92) + 'x3c' not in raw[:2000]:
        return raw[:max_chars]

    # 在原始内容中找第一个中文密集区域
    # 扫描找到连续中文>=20字的起始位置
    cn_run = 0
    body_start = 0
    for idx, ch in enumerate(raw):
        if '\u4e00' <= ch <= '\u9fff':
            cn_run += 1
            if cn_run >= 20:
                body_start = max(0, idx - 200)
                break
        else:
            cn_run = 0

    # 取 body_start 后足够大的片段做局部处理
    region = raw[body_start:body_start + max_chars * 5]
    text = _unescape_and_strip(region)

    # 按换行拆段，过滤垃圾
    paragraphs = []
    total = 0
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        cn = sum(1 for c in line if '\u4e00' <= c <= '\u9fff')
        if cn >= 8:
            paragraphs.append(line)
            total += len(line)
            if total >= max_chars:
                break

    return '\n'.join(paragraphs)


def _extract_around_keywords(content: str, keywords: List[str], window: int = 6000) -> List[str]:
    """在原始content中按关键词定位，取周围片段做局部反转义+去标签，返回段落列表"""
    if not content or not keywords:
        return []

    # 按长度降序排列关键词（长的更精准）
    sorted_kws = sorted(keywords, key=lambda k: -len(k))

    chunks = []
    seen = set()
    for kw in sorted_kws[:10]:
        pos = 0
        while pos < len(content):
            idx = content.find(kw, pos)
            if idx == -1:
                break
            bucket = idx // window
            if bucket not in seen:
                seen.add(bucket)
                lo = max(0, idx - window)
                hi = min(len(content), idx + window)
                text = _unescape_and_strip(content[lo:hi])
                # 拆行，只保留含中文且>=30字的段落
                for seg in text.split('\n'):
                    seg = seg.strip()
                    cn = sum(1 for c in seg if '\u4e00' <= c <= '\u9fff')
                    if cn >= 15 and len(seg) >= 30:
                        chunks.append(seg)
            pos = idx + len(kw)
            if len(chunks) >= 20:
                break
        if len(chunks) >= 20:
            break
    return chunks


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

    # 正文侧启发式：提取前5000字纯文本检查
    content = _extract_text_for_llm(article.content or "", max_chars=3000)
    if content:
        # 正文含序号模式 "1/2/3..." 或 "一、二、三、"
        numbered = re.findall(r'(?:^|\n)\s*(?:\d{1,2}[.、]|[一二三四五六七八九十]+、)', content)
        if len(numbered) >= 3:
            return True
        # 正文中出现3个以上不同公司名（2字以上中文词+公司/集团/科技后缀）
        company_pats = re.findall(r'[\u4e00-\u9fff]{2,6}(?:集团|公司|科技|控股)', content)
        if len(set(company_pats)) >= 3:
            return True

    return False


def _prompt_hash() -> str:
    """计算当前拆分prompt的内容hash（4位），prompt变化时缓存自动失效"""
    prompt_path = os.path.join(ROOT, 'server', 'config', 'prompts', 'event_split.md')
    try:
        with open(prompt_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()[:4]
    except Exception:
        return '0000'


def _cache_key(url: str) -> str:
    """生成缓存文件名（含prompt版本hash）"""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"{url_hash}_{_prompt_hash()}.json"


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
    # 截断正文避免过长 — 先提取纯文本再截断
    content = _extract_text_for_llm(article.content or "", max_chars=8000)

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


def _strip_html(html: str) -> str:
    """将HTML转为纯文本"""
    # 移除 script/style 块
    text = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 将 br/p/div/li 转为换行
    text = re.sub(r'<(?:br|/p|/div|/li|/h[1-6])[^>]*>', '\n', text, flags=re.IGNORECASE)
    # 移除剩余标签
    text = re.sub(r'<[^>]+>', '', text)
    # HTML 实体
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&#?\w+;', '', text)
    # 移除 JS 残留代码
    text = re.sub(r'JsDecode\([^)]*\)', '', text)
    text = re.sub(r'try\s*\{.*?\}\s*catch\s*\([^)]*\)\s*\{.*?\}', '', text, flags=re.DOTALL)
    text = re.sub(r'var\s+\w+\s*=.*?;', '', text)
    text = re.sub(r'document\.\w+.*?;', '', text)
    text = re.sub(r'window\.\w+.*?;', '', text)
    text = re.sub(r'navigator\.\w+.*?;', '', text)
    # 清理多余空白
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _is_junk_paragraph(p: str) -> bool:
    """判断段落是否为JS代码/标题行等垃圾内容"""
    # JS 代码特征
    if any(kw in p for kw in ['function(', 'var ', 'const ', 'document.', 'window.', 'navigator.', 'JsDecode', '.test(', '.style.']):
        return True
    # 纯标点/符号/数字
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', p))
    if chinese_chars < 10:
        return True
    # title: 前缀
    if p.startswith('title:'):
        return True
    return False


# 段落分隔符：多事件文章常用 "一、" "二、" "三、" 等分段
_SECTION_PAT = re.compile(r'[一二三四五六七八九十]+、')


def _scan_chinese_text(content: str, start: int, max_chars: int = 500,
                      stop_company: str = "") -> str:
    """从start位置开始，在原始content中逐字符扫描，收集中文+标点+数字文本。
    跳过HTML标签和JS转义序列。遇到下一个段落分隔符（X、+不同公司名）时停止。"""
    result = []
    i = start
    length = len(content)
    bs = chr(92)
    collected_cn = 0  # 已收集的中文字符数

    while i < length and len(result) < max_chars * 3:
        ch = content[i]

        # 跳过HTML标签 <...>，遇到</p>插入换行
        if ch == '<':
            end = content.find('>', i)
            if end != -1:
                tag = content[i:end+1].lower()
                if '</p' in tag or '<br' in tag:
                    result.append('\n')
                i = (end + 1) if end != -1 else (i + 1)
            else:
                i += 1
            continue

        # 跳过JS转义标签 \x3c...\x3e，遇到</p>插入换行
        if ch == bs and i + 3 < length and content[i+1:i+4] == 'x3c':
            close = content.find(bs + 'x3e', i + 4)
            if close != -1:
                tag = content[i+4:close].lower()
                if '/p' in tag or 'br' in tag:
                    result.append('\n')
                i = close + 4
            else:
                i += 4
            continue
        # 跳过其他JS转义序列
        if ch == bs and i + 3 < length and content[i+1] == 'x':
            i += 4
            continue

        # 收集：中文、中文标点、数字、英文、常用符号
        if ('\u4e00' <= ch <= '\u9fff' or
            '\u3000' <= ch <= '\u303f' or
            '\uff00' <= ch <= '\uffef' or
            ch in '，。；：！？、（）""''—…·/-+%' or
            ch.isalnum() or ch == ' '):
            result.append(ch)
            if '\u4e00' <= ch <= '\u9fff':
                collected_cn += 1
        elif ch in '\n\r':
            result.append(' ')

        i += 1

        # 段落边界检测：每收集100个中文字符检查一次
        if collected_cn > 80 and collected_cn % 20 == 0:
            text_so_far = ''.join(result)
            # 找最后一个段落分隔符 "X、"
            for m in _SECTION_PAT.finditer(text_so_far):
                sep_pos = m.start()
                if sep_pos < 50:
                    continue  # 跳过开头的分隔符
                # 分隔符后面的内容不含当前公司名 → 截断
                after = text_so_far[sep_pos:]
                if stop_company and stop_company not in after:
                    result = list(text_so_far[:sep_pos].rstrip())
                    break
            else:
                continue
            break  # 内层for找到截断点后退出while

    text = ''.join(result).strip()
    text = re.sub(r' {2,}', ' ', text)
    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'\n +', '\n', text)
    # 去掉开头重复的公司名
    if stop_company:
        for cn in re.findall(r'[\u4e00-\u9fff]{2,}', stop_company):
            while text.startswith(cn + cn):
                text = text[len(cn):]
    return text


# 应截断/删除的垃圾内容模式
_JUNK_LINE_PATTERNS = re.compile(
    r'(本周爆料有奖|爆料有奖|礼物中任选|可随意挑选|三八节将至|四月快乐'
    r'|参与爆料的朋友|之前参与爆料|晚24点之前|爆料有奖'
    r'|雅诗兰黛|兰蔻|星巴克礼品卡|京东购物卡|麦卢卡蜂蜜|富士拍立得|大疆OM'
    r'|三月的最后一周|周[一二三四五六日]（\d+月|节快乐'
    r'|createtime|cdnurl|JsDecode|htmlDecode'
    r'|在小说阅读器中沉浸阅读|Original\s|关注：点击上方蓝字'
    r'|欢迎置顶或设为星标|快速获取地产干货|大家好，我是'
    r'|mmbizqpiccn|wxfmtjpeg|mmbizjpg'
    r'|https?//[a-zA-Z0-9./_-]{20,})', re.IGNORECASE
)


def _clean_excerpt(text: str) -> str:
    """清洗 excerpt：逐行过滤垃圾内容，保留有意义的段落"""
    # 先清理元数据前缀
    text = re.sub(r'(?:title|desc|contentnoencode)\s*JsDecode', '', text)
    text = re.sub(r'\bnbsp\b', '', text)
    # 清除残留的 HTML 属性碎片（如 data-itemshowtype0 linktypetext data-linktype2）
    text = re.sub(r'\bdata-[a-zA-Z0-9_-]+=?[a-zA-Z0-9_-]*', ' ', text)
    text = re.sub(r'\blinktype[a-zA-Z0-9_-]*', ' ', text)
    text = re.sub(r'\bquot\b', '"', text)
    text = re.sub(r' {2,}', ' ', text)
    lines = text.split('\n')
    clean = []
    for line in lines:
        line = line.strip()
        if not line:
            if clean and clean[-1] != '':
                clean.append('')  # 保留一个空行作分段
            continue
        # 跳过垃圾行
        if _JUNK_LINE_PATTERNS.search(line):
            # 前面已有足够有效内容(>=50字)则截断，否则仅跳过此行
            clean_text = ''.join(clean)
            if sum(1 for c in clean_text if '\u4e00' <= c <= '\u9fff') >= 50:
                break
            continue
        # 跳过纯英文/URL/太短的行
        cn_count = sum(1 for c in line if '\u4e00' <= c <= '\u9fff')
        if cn_count < 4 and len(line) < 20:
            continue
        clean.append(line)
    # 合并
    result = '\n'.join(clean).strip()
    return result


def _find_body_start(content: str) -> int:
    """找到微信HTML正文区域起点：\x3c 密集区 或 JsDecode 密集区的开头"""
    bs = chr(92)
    mk = bs + 'x3c'
    prev = content.find(mk)
    while prev >= 0:
        nxt = content.find(mk, prev + 4)
        if nxt >= 0 and nxt - prev < 200:
            return prev
        prev = nxt
    # fallback：找 JsDecode 密集区（两个 JsDecode 相距 < 2000 字节）
    jd = 'JsDecode('
    prev = content.find(jd)
    while prev >= 0:
        nxt = content.find(jd, prev + len(jd))
        if nxt >= 0 and nxt - prev < 2000:
            return prev
        prev = nxt
    return 0


def _extract_jsdecode_text(content: str, start: int, max_chars: int = 2000) -> str:
    """从 JsDecode('...') 中提取纯文本，解码 \\x0a 等转义"""
    jd = 'JsDecode('
    result_parts = []
    pos = start
    total = 0
    while pos < len(content) and total < max_chars:
        idx = content.find(jd, pos)
        if idx == -1 or idx - start > 200000:
            break
        # 找字符串开始引号
        q_idx = idx + len(jd)
        if q_idx >= len(content):
            break
        quote = content[q_idx]
        if quote not in ('"', "'"):
            pos = q_idx
            continue
        # 找对应结束引号（简单查找，不处理嵌套）
        end = content.find(quote + ')', q_idx + 1)
        if end == -1 or end - q_idx > 10000:
            pos = q_idx + 1
            continue
        raw = content[q_idx + 1:end]
        # 解码转义
        raw = raw.replace('\\x0a', '\n').replace('\\n', '\n')
        raw = raw.replace('\\x26amp;lt;', '<').replace('\\x26amp;gt;', '>')
        raw = raw.replace('\\x26lt;', '<').replace('\\x26gt;', '>')
        raw = raw.replace('\\x3c', '<').replace('\\x3e', '>')
        raw = raw.replace('\\x26amp;', '&').replace('\\x26', '&')
        raw = re.sub(r'<[^>]{0,200}>', ' ', raw)
        result_parts.append(raw.strip())
        total += len(raw)
        pos = end + 2
    return '\n'.join(p for p in result_parts if p)


def _extract_excerpts_from_content(content: str, keywords: List[str], company: str = "") -> List[str]:
    """从原文中提取含关键词的完整段落。
    
    在正文区域内搜索所有关键词位置，用多关键词交叉验证选最佳位置，
    然后从该位置扫描收集中文文本。
    """
    if not content or not keywords:
        return []

    company_words = re.findall(r'[\u4e00-\u9fff]{2,}', company)
    # 长公司名用滑动窗口生成2字子串（"拼多多"→"拼多","多多"）
    company_short = list(company_words)
    for w in company_words:
        if len(w) > 2:
            for j in range(len(w) - 1):
                company_short.append(w[j:j+2])
    company_short = list(dict.fromkeys(company_short))  # 去重保序
    all_kws = company_short + [k for k in keywords if k not in company_short]

    body_start = _find_body_start(content)

    # 如果正文区域是 JsDecode 格式，先直接提取解码后的文本搜索
    jsdecode_text = ""
    if 'JsDecode(' in content[body_start:body_start + 500]:
        jsdecode_text = _extract_jsdecode_text(content, body_start, max_chars=3000)

    # 收集所有候选位置及评分
    candidates = []  # [(score, idx)]
    seen_buckets = set()

    for kw in all_kws[:12]:
        pos = body_start
        found = 0
        while pos < len(content) and found < 5:
            idx = content.find(kw, pos)
            if idx == -1:
                break
            found += 1
            bucket = idx // 1500
            if bucket not in seen_buckets:
                seen_buckets.add(bucket)
                window = content[idx:idx + 3000]
                score = sum(1 for k in all_kws[:12] if k in window)
                candidates.append((score, idx))
            pos = idx + max(len(kw), 50)

    if not candidates:
        return []

    # 按分数降序，依次尝试scan+clean直到找到有效excerpt
    candidates.sort(key=lambda x: -x[0])
    # 优先：如果有 JsDecode 解码文本，直接在里面找含最多关键词的最短段落
    if jsdecode_text:
        lines = [l.strip() for l in jsdecode_text.split('\n')
                 if sum(1 for c in l if '\u4e00' <= c <= '\u9fff') >= 4]
        best_line, best_score = '', 0
        for line in lines:
            score = sum(1 for kw in all_kws[:12] if kw in line)
            if score > best_score or (score == best_score and best_line and len(line) < len(best_line)):
                best_score, best_line = score, line
        if best_score > 0 and len(best_line) >= 10:
            text = _clean_excerpt(best_line[:600])
            if len(text) >= 10:
                return [text]

    for score, idx in candidates[:8]:
        text = _scan_chinese_text(content, idx, max_chars=600,
                                  stop_company=company)
        text = _clean_excerpt(text)
        if not text:
            continue
        if len(text) >= 20:
            if len(text) > 600:
                text = text[:600] + "..."
            return [text]

    return []




def _build_keywords(company: str, summary: str, detail: str = "") -> List[str]:
    """从公司名+摘要+详情中提取搜索关键词，按长度降序"""
    kw_source = f"{company} {summary} {detail}"
    kws = set()
    # 提取2-4字中文词
    kws.update(re.findall(r'[\u4e00-\u9fff]{2,4}', kw_source))
    # 也提取纯2字词保证短关键词覆盖
    kws.update(re.findall(r'[\u4e00-\u9fff]{2}', kw_source))
    # 英文词
    kws.update(w for w in re.findall(r'[A-Za-z]+', kw_source) if len(w) >= 3)
    return sorted(kws, key=lambda k: -len(k))


def _article_to_single_event(article: Article) -> Event:
    """将单事件文章直接转为Event（不调LLM）"""
    # 用 hr_details 拼接为详情段落
    detail = ""
    if article.hr_details:
        detail = " ".join(article.hr_details)

    # excerpts 兑底：如果 hr_details 太短，从原文中按关键词提取
    raw_details = article.hr_details if article.hr_details else []
    # 过滤纯元数据行（文章标题行、发布时间行、与文章标题相同的行）
    _META_PAT = re.compile(r'^(文章标题|文章发布时间|发布时间)\s*[:：]')
    article_title = (article.title or '').strip()
    meaningful = [
        e for e in raw_details
        if not _META_PAT.match(e) and e.strip() != article_title
    ]
    excerpts = meaningful if meaningful else []
    avg_len = sum(len(e) for e in excerpts) / max(len(excerpts), 1)
    if avg_len < 50:
        content = article.content or ""
        if content:
            kws = _build_keywords("", article.ai_summary or "", article.title or "")
            extracted = _extract_excerpts_from_content(content, kws)
            if extracted:
                excerpts = extracted

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
        excerpts=excerpts,
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
            cached = _load_cache(article.url) if _use_cache else None
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

            article_content = article.content or ""

            for raw in raw_events:
                # excerpts: 用关键词在原始content中定位+局部提取
                kws = _build_keywords(
                    raw.get('company', ''),
                    raw.get('summary', ''),
                    raw.get('detail', ''),
                )
                raw_excerpts = _extract_excerpts_from_content(
                    article_content, kws, company=raw.get('company', '')
                )
                # 如果匹配失败，用LLM返回的excerpts兜底
                if not raw_excerpts:
                    raw_excerpts = raw.get('excerpts', [])

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
                    excerpts=raw_excerpts,
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
