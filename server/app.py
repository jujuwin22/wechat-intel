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

            _log(f"启动采集: {' '.join(cmd)}")

            proc = subprocess.Popen(
                cmd,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
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
    """获取情报速递数据"""
    month = request.args.get('month', '')
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
    """获取趋势报告数据"""
    month = request.args.get('month', '')
    output_dir = os.path.join(ROOT, 'data', 'output')

    if not month:
        months_resp = feed_months()
        months = months_resp.get_json()
        if months:
            month = months[0]
        else:
            return jsonify({'trends': [], 'stats': {}, 'date_label': ''})

    # 先检查是否有 digest.json（趋势数据嵌入其中）
    json_path = os.path.join(output_dir, f"{month}_digest.json")
    trend_md_path = os.path.join(output_dir, f"{month}_trend_report.md")

    result = {
        'date_label': month,
        'trends': [],
        'stats': {},
        'trend_markdown': '',
    }

    # 从 digest.json 读取事件数据用于统计
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                digest_data = json.load(f)

            entries = digest_data.get('entries', [])
            # 维度分布统计
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

    # 读取趋势报告 Markdown
    if os.path.exists(trend_md_path):
        try:
            with open(trend_md_path, 'r', encoding='utf-8') as f:
                result['trend_markdown'] = f.read()
        except Exception:
            pass
    else:
        result['message'] = f'{month} 的趋势报告尚未生成'

    return jsonify(result)


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
