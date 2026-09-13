# -*- coding: utf-8 -*-
"""把方案与评估结果渲染为带尺寸标注和告警的 SVG 图。"""
import math
from xml.sax.saxutils import escape

S = 70  # 像素/米


def _dim_h(x1, x2, y, label):
    mx = (x1 + x2) / 2
    return ('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#555"/>'
            '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#555"/>'
            '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#555"/>'
            '<text x="%s" y="%s" font-size="11" text-anchor="middle" fill="#333">%s</text>'
            % (x1, y, x2, y, x1, y - 4, x1, y + 4, x2, y - 4, x2, y + 4,
               mx, y + 15, escape(label)))


def _dim_v(y1, y2, x, label):
    my = (y1 + y2) / 2
    return ('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#555"/>'
            '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#555"/>'
            '<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="#555"/>'
            '<text x="%s" y="%s" font-size="11" text-anchor="end" fill="#333">%s</text>'
            % (x, y1, x, y2, x - 4, y1, x + 4, y1, x - 4, y2, x + 4, y2,
               x - 6, my, escape(label)))


def render_svg(config, m):
    room = config.get('room', {'w': 10, 'h': 7})
    rw, rh = float(room.get('w', 10)), float(room.get('h', 7))
    ox, oy = 90.0, 70.0
    W = ox * 2 + rw * S

    warn_lines = []
    for s in m['surfaces']:
        for w in s['warnings']:
            warn_lines.append(s['name'] + '：' + w)
    if m['glare']['warning']:
        warn_lines.append('眩光：摄像机处垂直照度 %.1f lx 超过限值 %.0f lx'
                          % (m['glare']['total'], m['glare']['limit']))
    refl = m.get('reflections') or {}
    for w in refl.get('warnings') or []:
        warn_lines.append(w)
    H = oy * 2 + rh * S + 40 + 18 * (len(warn_lines) + 1)

    def X(x):
        return ox + x * S

    def Y(y):
        return oy + (rh - y) * S

    P = ['<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" '
         'viewBox="0 0 %.0f %.0f" font-family="sans-serif">' % (W, H, W, H)]
    P.append('<rect width="%.0f" height="%.0f" fill="#fafafa"/>' % (W, H))
    P.append('<text x="20" y="30" font-size="16" font-weight="bold" fill="#111">'
             '文物摄影布光评估图</text>')
    lim = m['summary']['limits']
    P.append('<text x="20" y="50" font-size="11" fill="#555">目标 %.0f–%.0f lx · '
             '均匀度≥%.2f · %.0f h/天 · 光敏阈值 %.0f lx / %.0f lx·h·年</text>'
             % (lim['tmin'], lim['tmax'], lim['umin'], lim['hours'],
                lim['lux_limit'], lim['annual_limit']))
    # 房间与 1m 网格
    P.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#fff" '
             'stroke="#333" stroke-width="2"/>' % (X(0), Y(rh), rw * S, rh * S))
    i = 1
    while i < rw:
        P.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#eee"/>'
                 % (X(i), Y(0), X(i), Y(rh)))
        i += 1
    j = 1
    while j < rh:
        P.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#eee"/>'
                 % (X(0), Y(j), X(rw), Y(j)))
        j += 1
    # 房间尺寸标注
    P.append(_dim_h(X(0), X(rw), Y(0) + 28, '%gm' % rw))
    P.append(_dim_v(Y(0), Y(rh), X(0) - 28, '%gm' % rh))

    # 设备
    for d in config.get('devices', []):
        t = d.get('type')
        cx, cy = X(d['x']), Y(d['y'])
        rot = -d.get('rot', 0)
        if t == 'case':
            w, dd = d['w'] * S, max(d.get('d', 1), 0.05) * S
            P.append('<g transform="rotate(%.1f %.1f %.1f)">'
                     '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                     'fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/></g>'
                     % (rot, cx, cy, cx - w / 2, cy - dd / 2, w, dd))
            P.append('<text x="%.1f" y="%.1f" font-size="11" text-anchor="middle" '
                     'fill="#1e3a8a">%s %g×%g×h%gm</text>'
                     % (cx, cy + 4, escape(d.get('name', d['id'])),
                        d['w'], d.get('d', 1), d.get('h', 0)))
            # 展柜尺寸标注（底部）
            P.append(_dim_h(cx - w / 2, cx + w / 2, cy + dd / 2 + 16, '%gm' % d['w']))
        elif t == 'background':
            w = d['w'] * S
            dd = max(d.get('d', 0.1), 0.08) * S
            P.append('<g transform="rotate(%.1f %.1f %.1f)">'
                     '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                     'fill="#d1d5db" stroke="#4b5563"/></g>'
                     % (rot, cx, cy, cx - w / 2, cy - dd / 2, w, dd))
            P.append('<text x="%.1f" y="%.1f" font-size="10" text-anchor="middle" '
                     'fill="#374151">%s h%gm%s</text>'
                     % (cx, cy - 8, escape(d.get('name', d['id'])), d.get('h', 0),
                        '' if d.get('opaque', True) else '（透光）'))
        elif t == 'lamp':
            a = d.get('aim') or {'x': d['x'], 'y': d['y']}
            ax, ay = X(a.get('x', d['x'])), Y(a.get('y', d['y']))
            P.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#f59e0b" '
                     'stroke-dasharray="4 3"/>' % (cx, cy, ax, ay))
            P.append('<circle cx="%.1f" cy="%.1f" r="7" fill="#fbbf24" stroke="#b45309"/>'
                     % (cx, cy))
            P.append('<circle cx="%.1f" cy="%.1f" r="3" fill="none" stroke="#b45309" '
                     'stroke-dasharray="2 2"/>' % (ax, ay))
            lock = ' [锁定]' if d.get('locked') else ''
            P.append('<text x="%.1f" y="%.1f" font-size="10" fill="#92400e">%s %gW/%gK/%g°%s</text>'
                     % (cx + 10, cy - 8, escape(d.get('name', d['id'])),
                        d.get('power', 0), d.get('cct', 0), d.get('beam', 0), lock))
    cam = config.get('camera')
    if cam:
        cx, cy = X(cam['x']), Y(cam['y'])
        # 镜头视场（水平张角，裁剪到房间边界）
        yaw = math.radians(cam.get('yaw', 90))
        focal = max(float(cam.get('focal', 35)), 1.0)
        sw = max(float(cam.get('sensor_w', 36)), 1.0)
        half = math.atan(sw / (2 * focal))
        fov_pts = []
        for sgn in (-1, 1):
            a = yaw + sgn * half
            dx, dy = math.cos(a), math.sin(a)
            t = 1e9
            if dx > 1e-9:
                t = min(t, (rw - cam['x']) / dx)
            elif dx < -1e-9:
                t = min(t, -cam['x'] / dx)
            if dy > 1e-9:
                t = min(t, (rh - cam['y']) / dy)
            elif dy < -1e-9:
                t = min(t, -cam['y'] / dy)
            t = max(t, 0.0)
            fov_pts.append((X(cam['x'] + dx * t), Y(cam['y'] + dy * t)))
        P.append('<path d="M %.1f %.1f L %.1f %.1f L %.1f %.1f Z" '
                 'fill="rgba(16,185,129,0.08)" stroke="#059669" stroke-width="1" '
                 'stroke-dasharray="5 4"/>'
                 % (cx, cy, fov_pts[0][0], fov_pts[0][1], fov_pts[1][0], fov_pts[1][1]))
        P.append('<path d="M %.1f %.1f L %.1f %.1f L %.1f %.1f Z" fill="#10b981"/>'
                 % (cx, cy - 8, cx + 8, cy + 6, cx - 8, cy + 6))
        P.append('<text x="%.1f" y="%.1f" font-size="10" fill="#065f46">相机 %gmm</text>'
                 % (cx + 10, cy + 4, focal))

    # 反射光路（红=入画，灰虚线=视场外）与光斑范围
    for sp in refl.get('spots') or []:
        p = sp['path']
        col = '#dc2626' if sp['in_frame'] else '#94a3b8'
        dash = '' if sp['in_frame'] else ' stroke-dasharray="5 4"'
        P.append('<polyline points="%.1f,%.1f %.1f,%.1f %.1f,%.1f" fill="none" '
                 'stroke="%s" stroke-width="1.2"%s/>'
                 % (X(p['lamp']['x']), Y(p['lamp']['y']),
                    X(p['hit']['x']), Y(p['hit']['y']),
                    X(p['cam']['x']), Y(p['cam']['y']), col, dash))
        n = sp.get('normal') or [0, 0, 0]
        off = 0 if sp['plane'] == 'bottom' else 8
        px, py = X(sp['hit']['x']) + n[0] * off, Y(sp['hit']['y']) - n[1] * off
        r = max(3.0, min(24.0, (sp['spot']['ry'] or 0) * S))
        P.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" fill-opacity="0.3" '
                 'stroke="%s"/>' % (px, py, r, col, col))

    # 热区标记（红=超上限/光敏阈值，橙=低于目标下限）
    for s in m['surfaces']:
        nx, ny = (s.get('normal') or [0, 0, 0])[0], (s.get('normal') or [0, 0, 0])[1]
        for p in s['points']:
            if p['flag'] == 'ok':
                continue
            color = '#dc2626' if p['flag'] == 'over' else '#f59e0b'
            px = X(p['x']) + (nx * 8 if s['plane'] == 'back' else 0)
            py = Y(p['y']) - (ny * 8 if s['plane'] == 'back' else 0)
            P.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s" fill-opacity="0.85"/>'
                     % (px, py, color))

    # 图例与告警
    ly = oy + rh * S + 46
    P.append('<rect x="20" y="%.1f" width="12" height="12" fill="#dc2626"/>'
             '<text x="38" y="%.1f" font-size="11" fill="#333">超上限/光敏阈值</text>'
             % (ly - 11, ly))
    P.append('<rect x="180" y="%.1f" width="12" height="12" fill="#f59e0b"/>'
             '<text x="198" y="%.1f" font-size="11" fill="#333">低于目标下限</text>'
             % (ly - 11, ly))
    P.append('<line x1="330" y1="%.1f" x2="356" y2="%.1f" stroke="#dc2626" stroke-width="2"/>'
             '<text x="362" y="%.1f" font-size="11" fill="#333">反射光路（入画）</text>'
             % (ly - 5, ly - 5, ly))
    P.append('<line x1="480" y1="%.1f" x2="506" y2="%.1f" stroke="#94a3b8" stroke-width="2" '
             'stroke-dasharray="5 4"/>'
             '<text x="512" y="%.1f" font-size="11" fill="#333">视场外光路</text>'
             % (ly - 5, ly - 5, ly))
    ty = ly + 24
    P.append('<text x="20" y="%.1f" font-size="13" font-weight="bold" fill="#b91c1c">'
             '告警（%d）</text>' % (ty, len(warn_lines)))
    for w in warn_lines:
        ty += 18
        P.append('<text x="20" y="%.1f" font-size="11" fill="#7f1d1d">• %s</text>'
                 % (ty, escape(w)))
    P.append('</svg>')
    return ''.join(P)
