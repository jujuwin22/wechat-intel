"""
feed/dedup.py - 三阶段去重
复用 scripts/llm_deduplicator.py 的核心逻辑，适配 Event/DigestEntry 模型

Phase 1: 规则预分组 (公司名+日期窗口+维度)
Phase 2: LLM语义精判 (只合并confidence=high)
Phase 3: Canonical评分 (confidence*0.4 + completeness*0.3 + credibility*0.3)
"""
import os
import re
import json
import yaml
from typing import List, Dict, Tuple
from collections import defaultdict
from datetime import datetime, timedelta

from server.feed.models import Event, DigestEntry

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_feed_settings() -> dict:
    """加载 feed_settings.yaml"""
    config_path = os.path.join(ROOT, 'server', 'config', 'feed_settings.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def _load_company_aliases() -> Dict[str, str]:
    """从 companies.yaml 加载公司别名 → 标准名映射"""
    yaml_path = os.path.join(ROOT, 'server', 'config', 'companies.yaml')
    alias_map = {}
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        for bl in data.get('business_lines', []):
            for c in bl.get('companies', []):
                canonical = c['name']
                alias_map[canonical] = canonical
                for alias in c.get('aliases', []):
                    alias_map[alias] = canonical
    except Exception as e:
        print(f"  ⚠ 加载公司别名失败: {e}")
    return alias_map


def _normalize_company(name: str, alias_map: Dict[str, str]) -> str:
    """归一化公司名"""
    if not name:
        return ""
    # 精确匹配
    if name in alias_map:
        return alias_map[name]
    # 模糊匹配：检查公司名是否包含在别名中
    for alias, canonical in alias_map.items():
        if alias in name or name in alias:
            return canonical
    return name


def _extract_company_from_text(text: str, alias_map: Dict[str, str]) -> str:
    """从summary/detail文本中提取公司名（按别名长度降序匹配，避免短别名误匹配）"""
    if not text:
        return ""
    # 按别名长度降序，优先匹配较长的（更精确）
    for alias, canonical in sorted(alias_map.items(), key=lambda x: len(x[0]), reverse=True):
        if len(alias) >= 2 and alias in text:
            return canonical
    return ""


def _parse_date(date_str: str) -> datetime:
    """解析日期字符串"""
    if not date_str:
        return datetime.min
    for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%Y年%m月%d日']:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return datetime.min


def _dates_within_window(d1: str, d2: str, window_days: int = 3) -> bool:
    """判断两个日期是否在窗口内"""
    dt1 = _parse_date(d1)
    dt2 = _parse_date(d2)
    if dt1 == datetime.min or dt2 == datetime.min:
        return True  # 无法解析日期时，保守认为可能相同
    return abs((dt1 - dt2).days) <= window_days


# ─── Phase 1: 规则预分组 ─────────────────────────────────────

def rule_based_grouping(events: List[Event], alias_map: Dict[str, str],
                        date_window: int = 3) -> List[List[int]]:
    """
    按 (归一化公司名, 维度) 分组，同组内日期相近的归为候选重复组
    只有 group.size > 1 的组才进入LLM精判
    """
    # 按 (公司, 维度) 分桶
    buckets = defaultdict(list)
    for idx, event in enumerate(events):
        company = _normalize_company(event.company, alias_map)
        # 如果event本身没有公司名，从summary和detail中提取
        if not company:
            company = _extract_company_from_text(
                (event.summary or "") + " " + (event.detail or ""), alias_map
            )
        if not company:
            continue  # 确实无法识别公司的事件不参与分组
        key = (company, event.dimension)
        buckets[key].append(idx)

    # 在每个桶内，按日期窗口进一步分组
    candidate_groups = []
    for key, indices in buckets.items():
        if len(indices) < 2:
            continue

        # 简单贪心：按日期排序，相邻日期在窗口内的归为一组
        sorted_indices = sorted(indices, key=lambda i: events[i].event_date or "")
        current_group = [sorted_indices[0]]

        for i in range(1, len(sorted_indices)):
            idx = sorted_indices[i]
            prev_idx = current_group[-1]
            if _dates_within_window(events[idx].event_date, events[prev_idx].event_date, date_window):
                current_group.append(idx)
            else:
                if len(current_group) > 1:
                    candidate_groups.append(current_group)
                current_group = [idx]

        if len(current_group) > 1:
            candidate_groups.append(current_group)

    # 补充：同公司+维度+日期窗口内，summary 词汇重叠度高的事件对也加入候选组
    # 解决跨采集批次增量合并后 LLM 拆分出的语义重复事件漏网问题
    for key, indices in buckets.items():
        if len(indices) < 2:
            continue
        # 已在 candidate_groups 里的组，收集其中的 index pairs 避免重复添加
        already_grouped = set()
        for g in candidate_groups:
            for idx in g:
                already_grouped.add(idx)

        sorted_indices = sorted(indices, key=lambda i: events[i].event_date or "")
        for i in range(len(sorted_indices)):
            for j in range(i + 1, len(sorted_indices)):
                a, b = sorted_indices[i], sorted_indices[j]
                if a in already_grouped and b in already_grouped:
                    continue
                if not _dates_within_window(events[a].event_date, events[b].event_date, date_window):
                    continue
                overlap = _summary_overlap(events[a].summary, events[b].summary)
                # 同公司名出现在两条summary中时，阈值更宽松（0.3）
                company_name = key[0]
                both_mention = (company_name and
                                company_name in (events[a].summary or '') and
                                company_name in (events[b].summary or ''))
                threshold = 0.3 if both_mention else 0.4
                if overlap >= threshold:
                    candidate_groups.append([a, b])
                    already_grouped.add(a)
                    already_grouped.add(b)

    return candidate_groups


def _summary_overlap(s1: str, s2: str) -> float:
    """计算两个 summary 的中文 bigram 单向包含度（短句 bigram 有多少比例出现在长句里）"""
    if not s1 or not s2:
        return 0.0
    import re
    def bigrams(s):
        cn = re.sub(r'[^\u4e00-\u9fff]', '', s)
        return set(cn[i:i+2] for i in range(len(cn) - 1))
    b1, b2 = bigrams(s1), bigrams(s2)
    if not b1 or not b2:
        return 0.0
    shorter, longer = (b2, b1) if len(b2) < len(b1) else (b1, b2)
    return len(shorter & longer) / len(shorter)


# ─── Phase 2: LLM语义精判 ────────────────────────────────────

def _load_dedup_prompt() -> str:
    """加载去重prompt模板"""
    prompt_path = os.path.join(ROOT, 'server', 'config', 'prompts', 'dedup_judge.md')
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""


def _format_events_for_llm(events: List[Event], indices: List[int]) -> str:
    """格式化事件为LLM可读文本"""
    lines = []
    for i, idx in enumerate(indices):
        e = events[idx]
        lines.append(f"\n【事件 {i}】索引: {idx}")
        lines.append(f"公司: {e.company}")
        lines.append(f"维度: {e.dimension}")
        lines.append(f"日期: {e.event_date}")
        lines.append(f"摘要: {e.summary}")
        lines.append(f"来源: {e.source_account}")
        lines.append("-" * 40)
    return "\n".join(lines)


def llm_judge_duplicates(events: List[Event], indices: List[int]) -> dict:
    """用LLM判断一组事件是否真正重复"""
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(os.path.join(ROOT, '.env'))

    client = OpenAI(
        api_key=os.getenv('LLM_API_KEY'),
        base_url=os.getenv('LLM_BASE_URL'),
    )

    events_text = _format_events_for_llm(events, indices)
    prompt_template = _load_dedup_prompt()

    if prompt_template:
        prompt = prompt_template.replace('{events_text}', events_text)
    else:
        prompt = f"判断以下事件是否为同一事件:\n{events_text}\n输出JSON: {{\"is_same_event\": true/false, \"canonical_idx\": 0, \"merge_idxs\": [1], \"reason\": \"...\"}}"

    try:
        resp = client.chat.completions.create(
            model=os.getenv('LLM_MODEL', 'deepseek-chat'),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()

        # 提取JSON
        if '```json' in raw:
            json_str = raw.split('```json')[1].split('```')[0].strip()
        elif '```' in raw:
            json_str = raw.split('```')[1].split('```')[0].strip()
        elif '{' in raw:
            json_str = raw[raw.index('{'):raw.rindex('}') + 1]
        else:
            json_str = raw

        return json.loads(json_str)

    except Exception as e:
        print(f"    LLM去重判断失败: {e}")
        return {"is_same_event": False, "reason": "LLM判断失败"}


# ─── Phase 3: Canonical评分 ──────────────────────────────────

def _score_event(event: Event, settings: dict) -> float:
    """计算事件综合评分"""
    weights = settings.get('scoring', {}).get('weights', {})
    w_conf = weights.get('confidence', 0.4)
    w_comp = weights.get('completeness', 0.3)
    w_cred = weights.get('credibility', 0.3)

    # confidence 归一化到 0-1
    conf_score = (event.confidence or 0) / 100.0

    # 内容完整度：基于 detail 长度
    detail_len = len(event.detail or "")
    comp_score = min(detail_len / 200.0, 1.0)  # 200字为满分

    # 来源可信度
    cred_map = settings.get('scoring', {}).get('account_credibility', {})
    cred_score = cred_map.get(event.source_account, cred_map.get('default', 2)) / 5.0

    return conf_score * w_conf + comp_score * w_comp + cred_score * w_cred


# ─── 主入口 ──────────────────────────────────────────────────

def deduplicate_events(events: List[Event]) -> List[DigestEntry]:
    """
    三阶段去重主函数

    Args:
        events: 拆分后的事件列表

    Returns:
        去重后的 DigestEntry 列表
    """
    if not events:
        return []

    settings = _load_feed_settings()
    alias_map = _load_company_aliases()
    date_window = settings.get('dedup', {}).get('date_window_days', 3)

    print(f"\n开始去重: {len(events)} 个事件")

    # Phase 1: 规则预分组
    candidate_groups = rule_based_grouping(events, alias_map, date_window)
    print(f"  Phase 1 规则预分组: {len(candidate_groups)} 组候选重复")

    for i, group in enumerate(candidate_groups):
        summaries = [events[idx].summary[:30] for idx in group]
        print(f"    组{i+1}: {summaries}")

    # 标记哪些事件参与了去重组
    in_group = set()
    for group in candidate_groups:
        in_group.update(group)

    # Phase 2: LLM语义精判
    merged_indices = set()
    merge_map = {}  # canonical_idx -> [merged_idx1, merged_idx2, ...]

    for group in candidate_groups:
        valid = [idx for idx in group if idx not in merged_indices]
        if len(valid) < 2:
            continue

        result = llm_judge_duplicates(events, valid)

        if result.get('is_same_event'):
            canonical_local = result.get('canonical_idx', 0)
            merge_local = result.get('merge_idxs', [])

            canonical_idx = valid[canonical_local] if canonical_local < len(valid) else valid[0]
            merge_idxs = [valid[i] for i in merge_local if i < len(valid) and valid[i] != canonical_idx]

            if merge_idxs:
                merge_map.setdefault(canonical_idx, []).extend(merge_idxs)
                merged_indices.update(merge_idxs)
                print(f"  Phase 2 合并: {events[canonical_idx].summary[:30]}... ← {len(merge_idxs)} 个重复")

        elif len(valid) >= 3:
            # 整组判断为非同一事件时，回退为两两配对判断
            for pi in range(len(valid)):
                if valid[pi] in merged_indices:
                    continue
                for pj in range(pi + 1, len(valid)):
                    if valid[pj] in merged_indices:
                        continue
                    pair_result = llm_judge_duplicates(events, [valid[pi], valid[pj]])
                    if pair_result.get('is_same_event'):
                        canon_local = pair_result.get('canonical_idx', 0)
                        canon_idx = valid[pi] if canon_local == 0 else valid[pj]
                        merge_idx = valid[pj] if canon_local == 0 else valid[pi]
                        merge_map.setdefault(canon_idx, []).append(merge_idx)
                        merged_indices.add(merge_idx)
                        print(f"  Phase 2 配对合并: {events[canon_idx].summary[:30]}... ← 1 个重复")

    print(f"  Phase 2 LLM精判: 合并 {len(merged_indices)} 个重复事件")

    # Phase 3: 构建 DigestEntry + Canonical评分
    entries = []

    for idx, event in enumerate(events):
        if idx in merged_indices:
            continue  # 已被合并，跳过

        merged_from = merge_map.get(idx, [])
        all_sources = [event.source_account]
        all_urls = [event.source_url]

        for m_idx in merged_from:
            m_event = events[m_idx]
            if m_event.source_account not in all_sources:
                all_sources.append(m_event.source_account)
            if m_event.source_url not in all_urls:
                all_urls.append(m_event.source_url)

        # 如果有多个候选，选评分最高的作为 canonical
        candidates = [event] + [events[i] for i in merged_from]
        best = max(candidates, key=lambda e: _score_event(e, settings))

        entry = DigestEntry(
            canonical=best,
            source_count=len(all_sources),
            all_sources=all_sources,
            all_urls=all_urls,
        )
        entries.append(entry)

    # 按事件日期倒序排列（最新在前）
    entries.sort(key=lambda e: str(e.canonical.event_date or "0000-00-00"), reverse=True)

    print(f"  Phase 3 完成: {len(entries)} 个去重后事件")
    multi = sum(1 for e in entries if e.source_count > 1)
    print(f"    多源验证: {multi} | 单一来源: {len(entries) - multi}")

    return entries
