# -*- coding: utf-8 -*-
"""文物摄影布光评估 —— Flask 后端。

接口：
  GET  /                        页面
  POST /api/evaluate            评估当前配置
  POST /api/trace               追溯单个采样点的灯具贡献
  GET/POST /api/schemes         方案列表 / 保存
  GET/DELETE /api/schemes/<id>  读取 / 删除
  POST /api/compare             两方案指标对比
  POST /api/export.svg          导出带尺寸与告警的 SVG
"""
import json
import os
import sqlite3

from flask import Flask, Response, g, jsonify, render_template, request

from physics import diff_metrics, evaluate, trace_point
from svg_export import render_svg

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'lighting.db')

app = Flask(__name__)


def get_db():
    db = getattr(g, '_db', None)
    if db is None:
        db = g._db = sqlite3.connect(DB)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, '_db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB)
    db.execute('''CREATE TABLE IF NOT EXISTS schemes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        config TEXT NOT NULL,
        metrics TEXT)''')
    db.commit()
    db.close()


@app.route('/')
def index():
    return render_template('index.html')


@app.post('/api/evaluate')
def api_evaluate():
    cfg = request.get_json(force=True)
    return jsonify(evaluate(cfg))


@app.post('/api/trace')
def api_trace():
    data = request.get_json(force=True)
    return jsonify(trace_point(data.get('config', {}),
                               data.get('surface', ''),
                               int(data.get('index', 0))))


@app.get('/api/schemes')
def list_schemes():
    rows = get_db().execute(
        'SELECT id, name, created_at FROM schemes ORDER BY id DESC').fetchall()
    return jsonify([dict(r) for r in rows])


@app.post('/api/schemes')
def save_scheme():
    data = request.get_json(force=True)
    name = (data.get('name') or '未命名方案').strip()
    config = data.get('config') or {}
    metrics = evaluate(config)
    cur = get_db().execute(
        'INSERT INTO schemes(name, config, metrics) VALUES (?,?,?)',
        (name, json.dumps(config, ensure_ascii=False),
         json.dumps(metrics, ensure_ascii=False)))
    get_db().commit()
    return jsonify({'id': cur.lastrowid, 'name': name})


def _load_scheme(sid):
    row = get_db().execute('SELECT * FROM schemes WHERE id=?', (sid,)).fetchone()
    return dict(row) if row else None


@app.get('/api/schemes/<int:sid>')
def get_scheme(sid):
    s = _load_scheme(sid)
    if not s:
        return jsonify({'error': '方案不存在'}), 404
    s['config'] = json.loads(s['config'])
    s['metrics'] = json.loads(s['metrics']) if s.get('metrics') else None
    return jsonify(s)


@app.delete('/api/schemes/<int:sid>')
def delete_scheme(sid):
    get_db().execute('DELETE FROM schemes WHERE id=?', (sid,))
    get_db().commit()
    return jsonify({'ok': True})


@app.post('/api/compare')
def api_compare():
    data = request.get_json(force=True)
    a = _load_scheme(int(data.get('a', 0)))
    b = _load_scheme(int(data.get('b', 0)))
    if not a or not b:
        return jsonify({'error': '方案不存在'}), 404
    # 重新计算，保证指标与当前引擎一致
    ma = evaluate(json.loads(a['config']))
    mb = evaluate(json.loads(b['config']))
    return jsonify({
        'a': {'id': a['id'], 'name': a['name'], 'metrics': ma},
        'b': {'id': b['id'], 'name': b['name'], 'metrics': mb},
        'diff': diff_metrics(ma, mb),
    })


@app.post('/api/export.svg')
def export_svg():
    cfg = request.get_json(force=True)
    svg = render_svg(cfg, evaluate(cfg))
    return Response(svg, mimetype='image/svg+xml',
                    headers={'Content-Disposition': 'attachment; filename=lighting.svg'})


init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
