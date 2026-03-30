"""
feed/models.py - 数据模型定义
使用 dataclass 而非 Pydantic，避免新增依赖
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Article:
    """从JSON加载的原始文章"""
    title: str
    url: str
    content: str
    published_at: str
    event_date: Optional[str] = None
    dimension: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_confidence: Optional[int] = None
    hr_details: List[str] = field(default_factory=list)
    matched_keywords: List[str] = field(default_factory=list)
    dimensions: List[str] = field(default_factory=list)
    account_name: str = ""
    collect_date: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "published_at": self.published_at,
            "event_date": self.event_date,
            "dimension": self.dimension,
            "ai_summary": self.ai_summary,
            "ai_confidence": self.ai_confidence,
            "hr_details": self.hr_details,
            "matched_keywords": self.matched_keywords,
            "dimensions": self.dimensions,
            "account_name": self.account_name,
            "collect_date": self.collect_date,
        }


@dataclass
class Event:
    """拆分后的独立事件"""
    company: str
    event_date: str
    dimension: str              # 薪酬激励/组织架构/人才发展
    summary: str                # 一句话摘要
    detail: str                 # 2-3句详细描述
    confidence: int             # 0-100
    source_url: str
    source_account: str
    source_title: str = ""
    excerpts: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "event_date": self.event_date,
            "dimension": self.dimension,
            "summary": self.summary,
            "detail": self.detail,
            "confidence": self.confidence,
            "source_url": self.source_url,
            "source_account": self.source_account,
            "source_title": self.source_title,
            "excerpts": self.excerpts,
        }


@dataclass
class DigestEntry:
    """去重后的最终条目"""
    canonical: Event            # 最佳事件
    source_count: int           # 被多少个来源报道
    all_sources: List[str] = field(default_factory=list)   # 所有来源公众号
    all_urls: List[str] = field(default_factory=list)      # 所有来源URL

    def to_dict(self) -> dict:
        return {
            "canonical": self.canonical.to_dict(),
            "source_count": self.source_count,
            "all_sources": self.all_sources,
            "all_urls": self.all_urls,
        }
