"""
微信公众号采集配置
从 YAML + 环境变量加载，不硬编码任何路径或密钥
"""
import os
import yaml
import argparse

# 项目根目录 (wechat-intel/)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_wechat_channels(config_path=None):
    """从YAML文件加载公众号配置

    Args:
        config_path: YAML文件路径，默认从项目config目录加载

    Returns:
        list: [(name, id, keywords, dimensions), ...]
    """
    if config_path is None:
        config_path = os.path.join(ROOT, 'server', 'config', 'wechat_channels.yaml')

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        accounts = data.get('official_accounts', [])
        result = []
        for acc in accounts:
            result.append((
                acc['name'],
                acc['id'],
                acc['keywords'],
                acc['dimensions']
            ))
        return result
    except Exception as e:
        print(f"⚠️ 加载公众号配置失败: {e}")
        return []


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='微信公众号HR情报采集')
    parser.add_argument('--account', help='只采集指定公众号（名称或ID）')
    parser.add_argument('--start-date', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--no-ai', action='store_true', help='禁用AI精筛')
    parser.add_argument('--confidence', type=int, default=60, help='AI置信度阈值 (默认60)')
    return parser.parse_args()


# 加载命令行参数
CLI_ARGS = parse_args()

# 加载公众号列表（从YAML）
ALL_OFFICIAL_ACCOUNTS = load_wechat_channels()

# 根据命令行参数过滤
if CLI_ARGS.account:
    OFFICIAL_ACCOUNTS = [
        acc for acc in ALL_OFFICIAL_ACCOUNTS
        if CLI_ARGS.account in acc[0] or CLI_ARGS.account in acc[1]
    ]
    if not OFFICIAL_ACCOUNTS:
        print(f"⚠️ 未找到匹配的公众号: {CLI_ARGS.account}")
        print(f"可用的公众号: {[acc[0] for acc in ALL_OFFICIAL_ACCOUNTS]}")
else:
    OFFICIAL_ACCOUNTS = ALL_OFFICIAL_ACCOUNTS

# API 基础URL（微信 exporter 容器）
BASE_URL = os.environ.get("WECHAT_EXPORTER_URL", "http://localhost:3000")

# 导出目录（相对于项目根目录）
EXPORT_DIR = os.path.join(ROOT, 'data', 'cache', 'results')

# 每次获取文章数量
BATCH_SIZE = 10

# 每个公众号最多采集文章数（防止过多）
MAX_ARTICLES_PER_ACCOUNT = 50

# 请求间隔（秒）
REQUEST_DELAY = 1

# 日期过滤配置 (从命令行参数或环境变量)
FILTER_DATE_START = CLI_ARGS.start_date or os.environ.get("WECHAT_DATE_START", "")
FILTER_DATE_END = CLI_ARGS.end_date or os.environ.get("WECHAT_DATE_END", "")

# ============================================
# AI 精筛配置（统一从环境变量读取，不硬编码密钥）
# ============================================

# 是否启用AI精筛
ENABLE_AI_FILTER = not CLI_ARGS.no_ai

# AI精筛置信度阈值
AI_CONFIDENCE_THRESHOLD = CLI_ARGS.confidence

# AI提供商: "deepseek" 或 "claude"
AI_PROVIDER = os.environ.get("AI_PROVIDER", "deepseek")

# DeepSeek API 配置（从 .env 读取）
DEEPSEEK_API_KEY = os.environ.get("LLM_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
DEEPSEEK_API_BASE = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")

# Claude API 配置
CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_API_BASE = "https://api.anthropic.com"

# 精筛维度定义（与主流程统一为4大维度，不含人事变动）
DIMENSION_CRITERIA = {
    "薪酬激励": "文章主要内容涉及薪酬体系设计、薪酬对标、薪酬改革、股权激励、奖金制度、绩效工资、高管薪酬、核心人才薪酬，以及AI人才薪酬溢价、数字化/科技人才专属激励包、创新贡献奖金等",
    "组织架构": "文章主要内容涉及：架构调整动作（区域合并/拆分、总部精简/放权、事业部/BU拆分合并、管理层级压缩、城市公司整合/撤销）、管控模式变化（集权vs分权、中台建设、核心流程优化、组织扁平化）、组织效能数据（人均产值/利润、人岗匹配、缩编明细、员工总数变化、人员结构调整）、治理与部门调整（三会一层变化、职能部门新设/合并/撤销、岗位体系调整）、战略联动调整（业务布局调整带来的组织架构同步变化）。注意：高管任免/离职/加盟类新闻不属于组织架构，应直接过滤",
    "人才发展": "文章主要内容涉及招聘策略变化（缩招/扩招决策、选拔标准调整）、人才培养（管培生体系、人才梯队、数字化学习）、绩效管理（OKR/KPI优化、绩效与薪酬/晋升联动、末位淘汰）、人才流动趋势数据（跨行业流动数据、核心人才缺口数据、离职率变动数据）、AI与创新人才发展等。注意：具体某人离职/加盟/任命的新闻不属于人才发展，应直接过滤",
    "企业文化": "文章主要内容涉及：福利体系（补充商业保险、企业年金、带薪年假调整、节日福利、餐补/交通补/住房补贴等补充福利标准变化）、工作模式（居家办公/混合办公/弹性工作制规则调整、考勤制度变化、加班管理规则）、人文关怀（女性员工/新手妈妈/职场父母专属保障、员工心理健康支持、退休员工关怀、困难员工帮扶政策）、员工关系（集体劳动合同签订、工会动态、劳动争议事件、员工沟通机制调整）",
}

# AI精筛提示词模板
AI_FILTER_PROMPT = """你是一名专业的HR行业分析师。你的任务是判断文章是否包含**特定企业的事实性 HR 动态**，并准确提取事件日期。

**核心原则：只采集事实性动作，反映企业实际发生的组织或人力资源变化趋势。**

文章标题: {title}
文章摘要: {digest}
文章正文片段: {content}
文章发布时间: {published_at}

该公众号的适用维度为: {dimensions}

## 采集标准：必须同时满足以下两个条件

**条件一：有明确主语企业**
文章必须报道某家具体企业实际发生的 HR 事件，而非泛泛而谈的行业现象或通用方法论。

**条件二：是事实性动态，而非以下内容**
- ❌ 招聘广告、招聘推广（"XX公司招聘！速投！"）
- ❌ 通用 HR 方法论、行业观点文章（"如何做好薪酬体系设计"）
- ❌ 个人薪资爆料、求职者自发分享（"某大学毕业生薪资爆料"）
- ❌ 楼盘推广、产品发布（即使提到公司名）
- ❌ 毕业去向数据（非企业主动发布的人才战略）
- ❌ 行业综述、市场分析（没有具体企业动作）
- ❌ **所有高管任免类新闻**：包括但不限于CEO/总裁/副总裁/CHO任命、离职、跳槽、加盟、接任、免职、退休。无论是否伴随组织调整，只要文章核心是报道"某人担任/离开某职位"，一律判 is_relevant=false
- ❌ 人才引进/加盟新闻（"前XX公司高管加盟YY公司"）

**✅ 应采集的事实性内容：**
- 某企业宣布组织架构重组、区域合并拆分
- 某企业发布新薪酬政策、调整激励方案
- 某企业启动裁员、扩招或缩编
- 某企业薪酬数据、股权激励披露
- 某企业调整员工福利体系、推行弹性办公制度
- 某企业签订集体合同、工会协商新条款

## 各维度的判断标准：
{dimension_criteria}

⚠️ **重要：不设"人事变动"维度。所有高管任免/人才引进/离职跳槽类新闻一律判 is_relevant=false，不归入任何维度。**

## 事件日期提取规则（重要）：
- 文章发布于：{published_at}
- 事件日期必须 ≥ 发布日期（事件不可能发生在文章发布之前）
- 如正文明确提到具体日期，直接提取
- 如只说"年初"、"本月"等相对时间，结合发布日期推算（如2026年3月发布的"年初"→2026年1月）
- 如无法确定具体日期，可返回null或文章发布日期

请严格按以下 JSON 格式回答，不要输出其他内容：
{{
    "is_relevant": true/false,
    "dimension": "薪酬激励/组织架构/人才发展/企业文化",
    "event_date": "YYYY-MM-DD",
    "confidence_score": 85,
    "summary": "一句话总结，必须包含企业名称和具体事实",
    "excerpts": ["原文段落1（完整逐字引用）", "原文段落2（完整逐字引用）"]
}}

注意：
- is_relevant：必须是特定企业的事实性 HR 动态才为 true；招聘广告、方法论、个人爆料、楼盘推广、所有高管任免/离职/加盟类新闻一律为 false
- dimension：匹配的主维度（薪酬激励/组织架构/人才发展/企业文化），不匹配时设为null
- event_date：事件实际发生的日期（YYYY-MM-DD），必须 ≥ 发布日期 {published_at}。提取优先级：①正文中明确提到的事件发生日期 ②公告/报告的发布日期 ③文章中出现的最近日期。严禁凭空编造日期。
- confidence_score：相关度分数（0-100）
- summary：必须包含企业名称和具体事实，不能只写维度类别
- excerpts：从原文中直接摘录与维度最相关的原句或段落（2-4条），保持原文表述，不要改写"""
