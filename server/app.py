"""
Flask API 入口
提供采集控制、情报速递、趋势报告的 REST API 和 SSE 日志流
"""
import os
import sys
import json
import glob
import threading
import subprocess
import time
from datetime import datetime
from flask import Flask, jsonify, request, Response, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

load_dotenv(os.path.join(ROOT, '.env'))

app = Flask(__name__, static_folder=os.path.join(ROOT, 'frontend', 'dist'))
CORS(app)

# ─── 全局状态 ─────────────────────────────────────────────────

_collect_running = False
_collect_done = False
_collect_log_lines = []


# ─── 采集控制 API ──────────────────────────────────────────────

@app.route('/api/collect/status')
def collect_status():
    """获取采集状态"""
    return jsonify({
        'running': _collect_running,
        'log_count': len(_collect_log_lines),
    })


@app.route('/api/collect/run', methods=['POST'])
def collect_run():
    """启动采集任务"""
    global _collect_running, _collect_log_lines, _collect_done

    if _collect_running:
        return jsonify({'status': 'error', 'message': '采集正在运行中，请勿重复启动'}), 409

    data = request.get_json() or {}
    start_date = data.get('start_date', '')
    end_date = data.get('end_date', '')
    accounts = data.get('accounts', [])

    # 清空旧日志
    _collect_log_lines = []
    _collect_done = False

    def _run_collect():
        global _collect_running, _collect_done
        _collect_running = True
        _collect_done = False

        try:
            cmd = [sys.executable, '-m', 'server.collector.collector']
            if start_date:
                cmd.extend(['--start-date', start_date])
            if end_date:
                cmd.extend(['--end-date', end_date])
            if accounts:
                cmd.extend(['--accounts', ','.join(accounts)])

            _log(f"启动采集: {' '.join(cmd)}")

            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'

            proc = subprocess.Popen(
                cmd,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )

            for line in proc.stdout:
                line = line.rstrip('\n')
                _log(line)

            proc.wait()
            if proc.returncode == 0:
                _log("✓ 采集完成")
            else:
                _log(f"✗ 采集失败 (exit code: {proc.returncode})")

        except Exception as e:
            _log(f"✗ 采集异常: {e}")
        finally:
            _collect_running = False
            _collect_done = True
            _log("[DONE]")

    thread = threading.Thread(target=_run_collect, daemon=True)
    thread.start()

    return jsonify({'status': 'ok', 'message': '采集已启动'})


def _log(line: str):
    """写入日志行"""
    ts = datetime.now().strftime('%H:%M:%S')
    entry = f"[{ts}] {line}"
    _collect_log_lines.append(entry)


@app.route('/api/collect/log')
def collect_log_sse():
    """SSE 日志流 — 基于列表轮询，支持多客户端、快速结束场景"""
    def generate():
        cursor = 0
        while True:
            # 推送新增日志
            current_lines = _collect_log_lines
            if cursor < len(current_lines):
                for line in current_lines[cursor:]:
                    yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
                cursor = len(current_lines)

            # 任务已完成且所有日志已推送
            if _collect_done and cursor >= len(_collect_log_lines):
                yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
                break

            # 未完成则短暂等待后继续轮询
            if not _collect_done:
                time.sleep(0.3)
            else:
                # done 但可能还有尾部日志
                time.sleep(0.1)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/collect/watermark')
def collect_watermark():
    """获取水位线数据"""
    watermark_path = os.path.join(ROOT, 'server', 'collector', 'watermark.json')
    try:
        with open(watermark_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except FileNotFoundError:
        return jsonify({'accounts': {}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/collect/watermark', methods=['DELETE'])
def collect_watermark_clear_all():
    """清除全部水位线"""
    watermark_path = os.path.join(ROOT, 'server', 'collector', 'watermark.json')
    try:
        with open(watermark_path, 'w', encoding='utf-8') as f:
            json.dump({'accounts': {}}, f)
        return jsonify({'status': 'ok', 'message': '已清除全部水位线'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/collect/watermark/<name>', methods=['DELETE'])
def collect_watermark_clear_one(name):
    """清除单个公众号水位线"""
    watermark_path = os.path.join(ROOT, 'server', 'collector', 'watermark.json')
    try:
        with open(watermark_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {'accounts': {}}

    accounts = data.get('accounts', {})
    if name in accounts:
        del accounts[name]
        data['accounts'] = accounts
        with open(watermark_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return jsonify({'status': 'ok', 'message': f'已清除 {name} 的水位线'})
    else:
        return jsonify({'status': 'ok', 'message': f'{name} 无水位线记录'})


@app.route('/api/collect/accounts')
def collect_accounts():
    """获取已配置的公众号列表"""
    import yaml as _yaml
    channels_path = os.path.join(ROOT, 'server', 'config', 'wechat_channels.yaml')
    try:
        with open(channels_path, 'r', encoding='utf-8') as f:
            data = _yaml.safe_load(f)
        accounts = []
        for acc in data.get('official_accounts', []):
            accounts.append({
                'name': acc['name'],
                'id': acc.get('id', ''),
                'feed_id': acc.get('feed_id', ''),
                'dimensions': acc.get('dimensions', []),
            })
        return jsonify({'accounts': accounts})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/collect/feeds')
def collect_feeds():
    """获取 wewe-rss 订阅源状态"""
    import requests as req
    wewe_url = os.environ.get("WEWE_RSS_URL", "http://localhost:4000")
    try:
        resp = req.get(f"{wewe_url}/feeds", timeout=5)
        if resp.status_code == 200:
            return jsonify({'status': 'ok', 'feeds': resp.json(), 'url': wewe_url})
        return jsonify({'status': 'error', 'message': f'HTTP {resp.status_code}'}), 502
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 502


# ─── 情报速递 API ──────────────────────────────────────────────

@app.route('/api/feed/months')
def feed_months():
    """获取可用月份列表"""
    output_dir = os.path.join(ROOT, 'data', 'output')
    months = set()

    # 从输出目录扫描 *_digest.json
    if os.path.isdir(output_dir):
        for f in os.listdir(output_dir):
            if f.endswith('_digest.json'):
                month_label = f.replace('_digest.json', '')
                months.add(month_label)

    # 也从 results 目录扫描原始数据的月份
    results_dir = os.path.join(ROOT, 'data', 'cache', 'results')
    if os.path.isdir(results_dir):
        for f in os.listdir(results_dir):
            if f.endswith('_wechat.json'):
                # 文件名格式: 2026年3月_公众号名_wechat.json
                parts = f.split('_')
                if len(parts) >= 2:
                    month_label = parts[0]
                    if '年' in month_label:
                        months.add(month_label)

    return jsonify(sorted(months, reverse=True))


@app.route('/api/feed')
def feed_data():
    """获取情报速递数据，支持按公司和维度筛选"""
    month = request.args.get('month', '')
    company = request.args.get('company', '')
    dimension = request.args.get('dimension', '')
    output_dir = os.path.join(ROOT, 'data', 'output')

    if not month:
        # 默认取最新月份
        months_resp = feed_months()
        months = months_resp.get_json()
        if months:
            month = months[0]
        else:
            return jsonify({'entries': [], 'date_label': '', 'total': 0})

    json_path = os.path.join(output_dir, f"{month}_digest.json")
    if not os.path.exists(json_path):
        return jsonify({'entries': [], 'date_label': month, 'total': 0,
                        'message': f'{month} 的速递尚未生成，请先运行 Pipeline'})

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 按公司/维度筛选
        if company or dimension:
            filtered = []
            for entry in data.get('entries', []):
                canonical = entry.get('canonical', {})
                if company and company not in canonical.get('company', ''):
                    continue
                if dimension and canonical.get('dimension', '') != dimension:
                    continue
                filtered.append(entry)
            data['entries'] = filtered
            data['total_events'] = len(filtered)

        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/feed/generate', methods=['POST'])
def feed_generate():
    """触发 Feed Pipeline"""
    data = request.get_json() or {}
    month = data.get('month', '')
    no_dedup = data.get('no_dedup', False)
    no_split = data.get('no_split', False)

    try:
        from server.feed.pipeline import run_pipeline
        result = run_pipeline(month=month or None, no_dedup=no_dedup, no_split=no_split)

        entries = result.get('entries', [])
        return jsonify({
            'status': 'ok',
            'event_count': len(entries),
            'md_path': result.get('md_path'),
            'json_path': result.get('json_path'),
            'html_path': result.get('html_path'),
            'trend_report_path': result.get('trend_report_path'),
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─── 趋势报告 API ──────────────────────────────────────────────

@app.route('/api/report')
def report_data():
    """获取趋势报告数据（优先返回结构化JSON）"""
    month = request.args.get('month', '')
    output_dir = os.path.join(ROOT, 'data', 'output')

    if not month:
        months_resp = feed_months()
        months = months_resp.get_json()
        if months:
            month = months[0]
        else:
            return jsonify({'trends': [], 'stats': {}, 'date_label': ''})

    trend_json_path = os.path.join(output_dir, f"{month}_trend_report.json")
    trend_md_path = os.path.join(output_dir, f"{month}_trend_report.md")

    # 优先读取结构化JSON
    if os.path.exists(trend_json_path):
        try:
            with open(trend_json_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        except Exception:
            pass

    # 回退：读取markdown + digest统计
    result = {
        'date_label': month,
        'trends': [],
        'stats': {},
        'executive_summary': '',
        'unclassified': [],
        'trend_markdown': '',
    }

    digest_json_path = os.path.join(output_dir, f"{month}_digest.json")
    if os.path.exists(digest_json_path):
        try:
            with open(digest_json_path, 'r', encoding='utf-8') as f:
                digest_data = json.load(f)
            entries = digest_data.get('entries', [])
            dim_counts = {}
            companies = set()
            for e in entries:
                canonical = e.get('canonical', {})
                dim = canonical.get('dimension', '未分类')
                dim_counts[dim] = dim_counts.get(dim, 0) + 1
                company = canonical.get('company', '')
                if company:
                    companies.add(company)
            result['stats'] = {
                'total_events': len(entries),
                'dimensions': dim_counts,
                'company_count': len(companies),
            }
        except Exception:
            pass

    if os.path.exists(trend_md_path):
        try:
            with open(trend_md_path, 'r', encoding='utf-8') as f:
                result['trend_markdown'] = f.read()
        except Exception:
            pass
    else:
        result['message'] = f'{month} 的趋势报告尚未生成'

    return jsonify(result)


@app.route('/api/report/generate', methods=['POST'])
def report_generate():
    """按维度生成趋势报告（不重跑pipeline，从已有digest数据生成）"""
    data = request.get_json() or {}
    month = data.get('month', '')
    dimensions = data.get('dimensions', [])  # 可选维度过滤

    output_dir = os.path.join(ROOT, 'data', 'output')

    if not month:
        months_resp = feed_months()
        months = months_resp.get_json()
        if months:
            month = months[0]
        else:
            return jsonify({'status': 'error', 'message': '无可用月份'}), 400

    # 从 digest.json 加载 entries
    digest_json_path = os.path.join(output_dir, f"{month}_digest.json")
    if not os.path.exists(digest_json_path):
        return jsonify({'status': 'error', 'message': f'{month} 的速递数据不存在，请先生成速递'}), 400

    try:
        from server.feed.models import Event, DigestEntry
        from server.feed.trend_report import generate_trend_report, render_trend_markdown, render_trend_json

        with open(digest_json_path, 'r', encoding='utf-8') as f:
            digest_data = json.load(f)

        # 重建 DigestEntry 对象
        entries = []
        for e in digest_data.get('entries', []):
            c = e.get('canonical', {})
            ev = Event(
                company=c.get('company', ''),
                event_date=c.get('event_date', ''),
                dimension=c.get('dimension', ''),
                summary=c.get('summary', ''),
                detail=c.get('detail', ''),
                confidence=c.get('confidence', 0),
                source_url=c.get('source_url', ''),
                source_account=c.get('source_account', ''),
                source_title=c.get('source_title', ''),
                excerpts=c.get('excerpts', []),
            )
            entry = DigestEntry(
                canonical=ev,
                source_count=e.get('source_count', 1),
                all_sources=e.get('all_sources', []),
                all_urls=e.get('all_urls', []),
            )
            entries.append(entry)

        report = generate_trend_report(entries, month, dimensions=dimensions or None)
        render_trend_markdown(report, output_dir)
        render_trend_json(report, output_dir)

        return jsonify({
            'status': 'ok',
            'trend_count': report['stats']['trend_count'],
            'total_events': report['stats']['total_events'],
            'dimensions_used': dimensions or '全部',
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/report/export-markdown', methods=['GET'])
def report_export_markdown():
    """导出趋势报告为Markdown"""
    month = request.args.get('month', '')
    output_dir = os.path.join(ROOT, 'data', 'output')
    
    if not month:
        months_resp = feed_months()
        months = months_resp.get_json()
        if months:
            month = months[0]
        else:
            return jsonify({'status': 'error', 'message': '无可用月份'}), 400
    
    # 读取趋势报告Markdown文件
    md_filename = f"{month}_trend_report.md"
    trend_md_path = os.path.join(output_dir, md_filename)
    if not os.path.exists(trend_md_path):
        return jsonify({'status': 'error', 'message': f'{month} 的趋势报告不存在，请先生成报告'}), 400
    
    try:
        # 返回Markdown文件（下载时使用中文名）
        download_name = f"{month}_趋势报告.md"
        return send_from_directory(output_dir, md_filename, as_attachment=True, download_name=download_name)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Markdown导出失败: {str(e)}'}), 500


# ─── 静态文件服务（生产模式）──────────────────────────────────

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    """生产模式下服务 Vue 前端静态文件"""
    static_dir = os.path.join(ROOT, 'frontend', 'dist')
    if path and os.path.exists(os.path.join(static_dir, path)):
        return send_from_directory(static_dir, path)
    # SPA fallback
    index_path = os.path.join(static_dir, 'index.html')
    if os.path.exists(index_path):
        return send_from_directory(static_dir, 'index.html')
    return jsonify({'message': 'wechat-intel API is running. Frontend not built yet.'}), 200


# ─── 入口 ──────────────────────────────────────────────────────

if __name__ == '__main__':
    import yaml
    settings_path = os.path.join(ROOT, 'server', 'config', 'feed_settings.yaml')
    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = yaml.safe_load(f)
        web_cfg = settings.get('web', {})
    except Exception:
        web_cfg = {}

    host = web_cfg.get('host', '0.0.0.0')
    port = web_cfg.get('port', 5001)
    debug = web_cfg.get('debug', True)

    print(f"\n🚀 wechat-intel API 启动: http://{host}:{port}")
    print(f"   前端开发模式请访问: http://localhost:5173\n")

    app.run(host=host, port=port, debug=debug, threaded=True)
