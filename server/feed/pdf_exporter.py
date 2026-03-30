"""
PDF导出模块 - 基于WeasyPrint将趋势报告导出为PDF
"""
import os
from weasyprint import HTML, CSS
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_trend_report_pdf(report_data: dict, output_path: str) -> str:
    """
    将趋势报告数据生成PDF文件
    
    Args:
        report_data: 趋势报告JSON数据（包含trends, unclassified, executive_summary等）
        output_path: PDF输出路径
        
    Returns:
        生成的PDF文件路径
    """
    html_content = _render_report_html(report_data)
    css_content = _get_pdf_styles()
    
    # 生成PDF
    HTML(string=html_content).write_pdf(
        output_path,
        stylesheets=[CSS(string=css_content)]
    )
    
    return output_path


def _render_report_html(data: dict) -> str:
    """渲染趋势报告HTML"""
    date_label = data.get('date_label', '')
    executive_summary = data.get('executive_summary', '')
    trends = data.get('trends', [])
    unclassified = data.get('unclassified', [])
    stats = data.get('stats', {})
    
    # 维度颜色映射
    dim_colors = {
        '薪酬激励': '#e74c3c',
        '组织架构': '#3498db',
        '人事变动': '#9b59b6',
        '人才发展': '#2ecc71',
        '企业文化': '#f59e0b',
        '未分类': '#95a5a6',
    }
    
    # 构建HTML
    html = f'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>HR情报趋势报告 - {date_label}</title>
</head>
<body>
    <div class="header">
        <h1>📊 HR情报趋势报告</h1>
        <p class="date">{date_label}</p>
        <p class="generated">生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
    </div>
    
    <!-- 统计概览 -->
    <div class="stats-section">
        <h2>📈 数据概览</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{stats.get('total_events', 0)}</div>
                <div class="stat-label">事件总数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(trends)}</div>
                <div class="stat-label">核心趋势</div>
            </div>
'''
    
    # 添加维度统计
    for dim, count in stats.get('dimensions', {}).items():
        html += f'''
            <div class="stat-card">
                <div class="stat-value" style="color: {dim_colors.get(dim, '#95a5a6')}">{count}</div>
                <div class="stat-label">{dim}</div>
            </div>
'''
    
    html += '''
        </div>
    </div>
'''
    
    # 执行摘要
    if executive_summary:
        html += f'''
    <div class="executive-summary">
        <h2>📋 执行摘要</h2>
        <p>{executive_summary}</p>
    </div>
'''
    
    # 趋势详情
    if trends:
        html += '''
    <div class="trends-section">
        <h2>🔍 核心趋势分析</h2>
'''
        for idx, trend in enumerate(trends, 1):
            html += f'''
        <div class="trend-card">
            <div class="trend-header">
                <span class="trend-number">{idx}</span>
                <h3>{trend.get('title', '')}</h3>
            </div>
            <p class="trend-summary">{trend.get('summary', '')}</p>
            
            <div class="events-list">
                <h4>关联事件 ({len(trend.get('events', []))} 条)</h4>
'''
            for event in trend.get('events', []):
                dim = event.get('dimension', '未分类')
                color = dim_colors.get(dim, '#95a5a6')
                html += f'''
                <div class="event-item">
                    <div class="event-meta">
                        <span class="dimension-tag" style="background: {color}">{dim}</span>
                        <span class="event-date">{event.get('event_date', '')}</span>
                        {f'<span class="company-name">{event.get("company")}</span>' if event.get('company') else ''}
                        {f'<span class="multi-source">🔗{event.get("source_count")}源</span>' if event.get('source_count', 0) > 1 else ''}
                    </div>
                    <p class="event-summary">{event.get('summary', '')}</p>
'''
                # 原文摘要
                if event.get('excerpts'):
                    html += '                    <div class="excerpts">\n'
                    for excerpt in event['excerpts']:
                        html += f'                        <p>{excerpt}</p>\n'
                    html += '                    </div>\n'
                
                # 来源信息（超链接）
                source_account = event.get('source_account', '')
                source_url = event.get('source_url', '')
                if source_url:
                    html += f'                    <p class="source-info">📰 {source_account} | <a href="{source_url}" target="_blank">查看原文</a></p>\n'
                else:
                    html += f'                    <p class="source-info">📰 {source_account}</p>\n'
                
                html += '                </div>\n'
            
            html += '''
            </div>
        </div>
'''
        
        html += '''
    </div>
'''
    
    # 其他动态
    if unclassified:
        html += f'''
    <div class="unclassified-section">
        <h2>📌 其他动态 ({len(unclassified)} 条)</h2>
        <div class="unclassified-list">
'''
        for event in unclassified:
            dim = event.get('dimension', '未分类')
            color = dim_colors.get(dim, '#95a5a6')
            html += f'''
            <div class="unclassified-item">
                <span class="dimension-tag" style="background: {color}">{dim}</span>
                {f'<span class="company-name">{event.get("company")}</span>' if event.get('company') else ''}
                <span class="event-summary">{event.get('summary', '')}</span>
                <span class="event-date">{event.get('event_date', '')}</span>
            </div>
'''
        
        html += '''
        </div>
    </div>
'''
    
    html += '''
</body>
</html>
'''
    
    return html


def _get_pdf_styles() -> str:
    """获取PDF样式"""
    return '''
@page {
    size: A4;
    margin: 2cm;
}

body {
    font-family: "SimSun", "Songti SC", "STSong", serif;
    font-size: 10pt;
    line-height: 1.6;
    color: #333;
}

.header {
    text-align: center;
    margin-bottom: 30px;
    border-bottom: 2px solid #3498db;
    padding-bottom: 15px;
}

.header h1 {
    font-size: 24pt;
    color: #2c3e50;
    margin: 0 0 10px 0;
}

.header .date {
    font-size: 14pt;
    color: #7f8c8d;
    margin: 5px 0;
}

.header .generated {
    font-size: 9pt;
    color: #95a5a6;
    margin: 5px 0;
}

.stats-section {
    margin-bottom: 25px;
    page-break-inside: avoid;
}

.stats-section h2 {
    font-size: 14pt;
    color: #2c3e50;
    margin-bottom: 12px;
    border-left: 4px solid #3498db;
    padding-left: 10px;
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-bottom: 15px;
}

.stat-card {
    text-align: center;
    padding: 10px;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    background: #f8f9fa;
}

.stat-value {
    font-size: 18pt;
    font-weight: bold;
    color: #3498db;
}

.stat-label {
    font-size: 8pt;
    color: #7f8c8d;
    margin-top: 3px;
}

.executive-summary {
    background: #f0f8ff;
    border-left: 4px solid #3498db;
    padding: 15px;
    margin-bottom: 25px;
    page-break-inside: avoid;
}

.executive-summary h2 {
    font-size: 14pt;
    color: #2c3e50;
    margin: 0 0 10px 0;
}

.executive-summary p {
    font-size: 10pt;
    line-height: 1.8;
    margin: 0;
}

.trends-section h2 {
    font-size: 14pt;
    color: #2c3e50;
    margin-bottom: 15px;
    border-left: 4px solid #3498db;
    padding-left: 10px;
}

.trend-card {
    margin-bottom: 20px;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 15px;
    page-break-inside: avoid;
}

.trend-header {
    display: flex;
    align-items: center;
    margin-bottom: 8px;
}

.trend-number {
    display: inline-block;
    width: 24px;
    height: 24px;
    background: #3498db;
    color: white;
    text-align: center;
    line-height: 24px;
    border-radius: 50%;
    font-weight: bold;
    font-size: 10pt;
    margin-right: 8px;
}

.trend-header h3 {
    font-size: 12pt;
    color: #2c3e50;
    margin: 0;
}

.trend-summary {
    font-size: 9pt;
    color: #555;
    margin: 8px 0 12px 32px;
    line-height: 1.6;
}

.events-list h4 {
    font-size: 10pt;
    color: #7f8c8d;
    margin: 12px 0 8px 0;
    border-bottom: 1px solid #e0e0e0;
    padding-bottom: 5px;
}

.event-item {
    margin-bottom: 12px;
    padding: 10px;
    background: #fafafa;
    border-left: 3px solid #3498db;
}

.event-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 5px;
    flex-wrap: wrap;
}

.dimension-tag {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    color: white;
    font-size: 8pt;
    font-weight: bold;
}

.event-date {
    font-size: 8pt;
    color: #95a5a6;
}

.company-name {
    font-size: 8pt;
    font-weight: bold;
    color: #2c3e50;
}

.multi-source {
    font-size: 8pt;
    color: #e67e22;
}

.event-summary {
    font-size: 9pt;
    color: #333;
    margin: 5px 0;
    line-height: 1.5;
}

.excerpts {
    background: #f0f0f0;
    border-left: 3px solid #3498db;
    padding: 8px 10px;
    margin: 8px 0;
}

.excerpts p {
    font-size: 8pt;
    color: #555;
    margin: 3px 0;
    line-height: 1.5;
}

.source-info {
    font-size: 8pt;
    color: #7f8c8d;
    margin: 5px 0 0 0;
}

.source-info a {
    color: #3498db;
    text-decoration: none;
}

.unclassified-section {
    margin-top: 25px;
}

.unclassified-section h2 {
    font-size: 14pt;
    color: #2c3e50;
    margin-bottom: 12px;
    border-left: 4px solid #95a5a6;
    padding-left: 10px;
}

.unclassified-list {
    display: grid;
    gap: 6px;
}

.unclassified-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    background: #f8f9fa;
    border-left: 2px solid #95a5a6;
    font-size: 9pt;
}

.unclassified-item .event-summary {
    flex: 1;
    margin: 0;
}
'''
