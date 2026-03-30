"""
feed/quality_filter.py - 事件质量精筛
用 LLM 批量判断事件是否为事实性行业动态，过滤掉八卦/爆料/产品/活动等非HR相关事件
"""
import os
import re
import json
from typing import List

import yaml

from server.feed.models import Event
from server.feed.dedup import _load_company_aliases, _extract_company_from_text

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 加载互联网科技大厂名称（含别名）
def _load_internet_companies() -> set:
    """从 companies.yaml 加载互联网科技大厂名称（含别名）"""
    yaml_path = os.path.join(ROOT, 'server', 'config', 'companies.yaml')
    names = set()
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        for bl in data.get('business_lines', []):
            if bl.get('id') == 'internet_tech':
                for c in bl.get('companies', []):
                    names.add(c['name'])
                    names.update(c.get('aliases', []))
                break
    except Exception:
        pass
    return names


_INTERNET_COMPANIES = None


def _get_internet_companies() -> set:
    global _INTERNET_COMPANIES
    if _INTERNET_COMPANIES is None:
        _INTERNET_COMPANIES = _load_internet_companies()
    return _INTERNET_COMPANIES


# 大厂普通组织调整关键词（非AI相关）
_GENERIC_ORG_PATTERNS = re.compile(
    r'(改名|更名|重命名|搬迁|南迁|动员会|扩编|员工总数|人数增加|人数减少'
    r'|员工人数|架构调整|组织调整|团队整合|部门整合|业务线整合'
    r'|成立新部门|事业部改名|事业部调整|人员优化)'
)
_AI_KEYWORDS = re.compile(r'(AI|人工智能|大模型|LLM|GPT|token|智能体|机器学习|深度学习|强化学习)')


def _is_internet_generic_org(event: Event) -> bool:
    """判断是否为互联网大厂的普通组织调整事件（非AI相关）"""
    company = event.company or ''
    internet = _get_internet_companies()
    # 检查是否是大厂
    is_big_tech = any(name in company for name in internet if len(name) >= 2)
    if not is_big_tech:
        return False
    text = (event.summary or '') + ' ' + (event.detail or '')[:200]
    # 包含普通组织调整关键词
    if not _GENERIC_ORG_PATTERNS.search(text):
        return False
    # 但不包含AI相关关键词
    if _AI_KEYWORDS.search(text):
        return False
    return True


# 高管任免类关键词模式（pipeline 层兜底过滤）
_APPOINTMENT_PATTERNS = [
    r'(?:任命|任职|出任|接任|就任|履新|加盟|加入|入职|跳槽).{0,6}(?:CEO|COO|CFO|CTO|CHO|CHRO|CMO|总裁|总经理|副总裁|副总|董事长|董事|执行董事|首席)',
    r'(?:CEO|COO|CFO|CTO|CHO|CHRO|CMO|总裁|总经理|副总裁|副总|董事长|董事|执行董事|首席).{0,6}(?:任命|任职|出任|接任|就任|履新|加盟|离职|离任|辞职|辞任|退休|免职|免除|卸任)',
    r'(?:离职|离任|辞职|辞任|退休|免职|免除|卸任).{0,6}(?:CEO|COO|CFO|CTO|CHO|CHRO|CMO|总裁|总经理|副总裁|副总|董事长|董事|执行董事|首席)',
    r'(?:前|原).{0,10}(?:加盟|加入|出任|担任|入职)',
    r'(?:确认离职|宣布离职|正式离职|正式加盟|正式入职|正式出任)',
]
_APPOINTMENT_RE = re.compile('|'.join(_APPOINTMENT_PATTERNS))


def _is_personnel_appointment(event: Event) -> bool:
    """判断事件是否为高管任免类新闻（应被过滤）"""
    text = (event.summary or '') + ' ' + (event.detail or '')[:200]
    return bool(_APPOINTMENT_RE.search(text))


def _load_quality_prompt() -> str:
    """加载质量精筛prompt模板"""
    prompt_path = os.path.join(ROOT, 'server', 'config', 'prompts', 'event_quality.md')
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""


def _format_events_batch(events: List[Event], start_idx: int = 0,
                         alias_map: dict = None) -> str:
    """格式化事件批次为LLM可读文本"""
    lines = []
    for i, event in enumerate(events):
        company = event.company
        if not company and alias_map:
            company = _extract_company_from_text(
                (event.summary or "") + " " + (event.detail or ""), alias_map
            )
        lines.append(f"\n【事件 {start_idx + i}】")
        lines.append(f"摘要: {event.summary}")
        lines.append(f"公司: {company or '（从摘要中判断）'}")
        lines.append(f"维度: {event.dimension}")
        lines.append(f"日期: {event.event_date}")
        lines.append(f"来源: {event.source_account}")
        if event.detail:
            lines.append(f"详情: {event.detail[:150]}")
        lines.append("-" * 30)
    return "\n".join(lines)


def filter_events_by_quality(events: List[Event], batch_size: int = 20) -> List[Event]:
    """
    用 LLM 批量过滤低质量事件

    Args:
        events: 待过滤的事件列表
        batch_size: 每批发送给LLM的事件数量

    Returns:
        过滤后的事件列表
    """
    if not events:
        return []

    # 规则预过滤：排除大厂普通组织调整事件
    pre_filtered = []
    for ev in events:
        if _is_internet_generic_org(ev):
            print(f"    ✗ 规则过滤 [{ev.company}] {ev.summary[:40]}... (大厂普通组织调整)")
        else:
            pre_filtered.append(ev)
    if len(pre_filtered) < len(events):
        print(f"  规则预过滤: {len(events)} → {len(pre_filtered)} (排除 {len(events)-len(pre_filtered)} 条大厂普通组织调整)")
    events = pre_filtered

    if not events:
        return []

    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(os.path.join(ROOT, '.env'))

    client = OpenAI(
        api_key=os.getenv('LLM_API_KEY'),
        base_url=os.getenv('LLM_BASE_URL'),
    )

    prompt_template = _load_quality_prompt()
    if not prompt_template:
        print("  ⚠ 未找到质量精筛prompt，跳过过滤")
        return events

    alias_map = _load_company_aliases()
    keep_flags = [True] * len(events)  # 默认保留

    # 分批处理
    for batch_start in range(0, len(events), batch_size):
        batch_end = min(batch_start + batch_size, len(events))
        batch = events[batch_start:batch_end]

        events_text = _format_events_batch(batch, start_idx=batch_start, alias_map=alias_map)
        prompt = prompt_template.replace('{events_text}', events_text)

        try:
            resp = client.chat.completions.create(
                model=os.getenv('LLM_MODEL', 'deepseek-chat'),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()

            # 提取JSON
            if '```json' in raw:
                json_str = raw.split('```json')[1].split('```')[0].strip()
            elif '```' in raw:
                json_str = raw.split('```')[1].split('```')[0].strip()
            elif '[' in raw:
                json_str = raw[raw.index('['):raw.rindex(']') + 1]
            else:
                json_str = raw

            results = json.loads(json_str)

            for item in results:
                idx = item.get('idx', -1)
                keep = item.get('keep', True)
                reason = item.get('reason', '')
                if 0 <= idx < len(events) and not keep:
                    keep_flags[idx] = False
                    print(f"    ✗ 过滤 [{idx}] {events[idx].summary[:40]}... ({reason})")

        except Exception as e:
            print(f"    ⚠ LLM质量精筛批次{batch_start}-{batch_end}失败: {e}")
            # 失败时保留全部，不误删

    filtered = [ev for ev, keep in zip(events, keep_flags) if keep]
    removed = len(events) - len(filtered)
    print(f"  质量精筛完成: {len(events)} → {len(filtered)} 个事件 (过滤 {removed} 个)")

    return filtered
