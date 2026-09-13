# -*- coding: utf-8 -*-
"""布光评估物理引擎。

模型假设（简化但可解释）：
- 灯具视为点光源，光通量 Φ = 功率 × 光效，光束角内光强按余弦平方衰减；
- 照度 E = I(θ)·cos(入射角) / r²（逆平方定律）；
- 遮挡：在平面图上对“灯→采样点”线段与设备矩形求交（Liang–Barsky），
  相交处射线高度低于设备高度即被遮挡；不透明设备完全阻挡，玻璃展柜按透过率衰减；
- 眩光：摄像机眼位处由可见灯具产生的垂直照度之和（简化指标）；
- 光损伤：年累积剂量 lx·h，并按色温做蓝光危害加权（色温越高权重越大）。
"""
import math

# 光敏度预设（参考 CIE 157 博物馆照明建议）
SENSITIVITY = {
    'paper':       {'label': '纸质/高敏', 'lux_limit': 50,  'annual_dose': 120000},
    'medium':      {'label': '中敏',      'lux_limit': 150, 'annual_dose': 360000},
    'insensitive': {'label': '低敏',      'lux_limit': 300, 'annual_dose': 10**12},
}

METRIC_KEYS = [
    ('E_avg', '平均照度 (lx)'), ('E_min', '最小照度 (lx)'), ('E_max', '最大照度 (lx)'),
    ('uniformity', '均匀度 U0'), ('shadow_rate', '阴影率'),
    ('dose_year', '年剂量 (lx·h)'), ('dose_eff', '年等效损伤剂量 (lx·h)'),
]


def _clamp(v, a, b):
    return a if v < a else b if v > b else v


def _rot(px, py, cx, cy, deg):
    """点绕中心旋转 deg 度（世界坐标，y 向上）。"""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    dx, dy = px - cx, py - cy
    return (cx + dx * c - dy * s, cy + dx * s + dy * c)


def _to_local(px, py, rect):
    """世界坐标 → 矩形局部坐标（原点为矩形中心，轴与矩形对齐）。"""
    r = math.radians(rect.get('rot', 0))
    c, s = math.cos(r), math.sin(r)
    dx, dy = px - rect['x'], py - rect['y']
    return (dx * c + dy * s, -dx * s + dy * c)


def _seg_rect_enter_t(p0, p1, rect):
    """线段与（可旋转）矩形求交，返回进入参数 t∈[0,1]，不相交返回 None。

    Liang–Barsky 裁剪：先把线段端点变换到矩形局部坐标（轴对齐）再求交。
    """
    x0, y0 = _to_local(p0[0], p0[1], rect)
    x1, y1 = _to_local(p1[0], p1[1], rect)
    hw = rect['w'] / 2.0
    hd = max(rect.get('d', 0.1), 0.02) / 2.0
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 + hw), (dx, hw - x0), (-dy, y0 + hd), (dy, hd - y0)):
        if abs(p) < 1e-12:
            if q < 0:
                return None
        else:
            r = q / p
            if p < 0:
                if r > t1:
                    return None
                t0 = max(t0, r)
            else:
                if r < t0:
                    return None
                t1 = min(t1, r)
    return t0


def transmission(lamp, pt, devices, owner_id):
    """灯到采样点的视线透过率：0 表示完全遮挡，玻璃设备按透过率连乘。"""
    z0, z1 = lamp.get('z', 3.0), pt['z']
    T = 1.0
    for d in devices:
        if d.get('type') == 'lamp' or d.get('id') == owner_id:
            continue
        h = d.get('h', 0)
        if h <= 0 or min(z0, z1) >= h:
            continue
        t = _seg_rect_enter_t((lamp['x'], lamp['y']), (pt['x'], pt['y']), d)
        if t is None:
            continue
        z_ray = z0 + t * (z1 - z0)
        if z_ray < h:
            if d.get('opaque', d.get('type') == 'background'):
                return 0.0
            T *= d.get('transmission', 0.9)
    return T


def _lamp_dir(lamp):
    a = lamp.get('aim') or {}
    dx = a.get('x', lamp['x']) - lamp['x']
    dy = a.get('y', lamp['y']) - lamp['y']
    dz = a.get('z', 0.0) - lamp.get('z', 3.0)
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    if n < 1e-9:
        return (0.0, 0.0, -1.0)  # 默认垂直向下
    return (dx / n, dy / n, dz / n)


def lamp_intensity(lamp, target):
    """灯具朝 target 方向的光强 I(θ) 与距离 r。光束角外为 0。"""
    dx = target['x'] - lamp['x']
    dy = target['y'] - lamp['y']
    dz = target['z'] - lamp.get('z', 3.0)
    r2 = dx * dx + dy * dy + dz * dz
    if r2 < 1e-9:
        return 0.0, 0.0
    r = math.sqrt(r2)
    half = math.radians(lamp.get('beam', 36)) / 2.0
    flux = lamp.get('power', 0) * lamp.get('efficacy', 90)
    if flux <= 0 or half <= 0:
        return 0.0, r
    omega = 2 * math.pi * (1 - math.cos(half))  # 光束立体角
    I0 = flux / omega
    ax, ay, az = _lamp_dir(lamp)
    cosang = _clamp((dx * ax + dy * ay + dz * az) / r, -1.0, 1.0)
    ang = math.acos(cosang)
    if ang >= half:
        return 0.0, r
    I = I0 * (math.cos(ang / half * math.pi / 2) ** 2)  # 束内余弦平方衰减
    return I, r


def lamp_point_E(lamp, pt, normal):
    """单灯对表面采样点的照度贡献（含入射角余弦）。"""
    I, r = lamp_intensity(lamp, pt)
    if I <= 0 or r <= 0:
        return 0.0
    dx = pt['x'] - lamp['x']
    dy = pt['y'] - lamp['y']
    dz = pt['z'] - lamp.get('z', 3.0)
    cosi = _clamp(-(dx * normal[0] + dy * normal[1] + dz * normal[2]) / r, 0.0, 1.0)
    return I * cosi / (r * r)


def cct_damage_factor(cct):
    """蓝光危害简化权重：2700K≈0.6，6500K≈1.2，用于等效损伤剂量修正。"""
    return _clamp(0.6 + (cct - 2700) / 6500.0, 0.5, 1.6)


def build_surfaces(config):
    """为每个展柜生成拍摄面网格：展台面（水平）与背板（竖直）。"""
    settings = config.get('settings') or {}
    grid = float(settings.get('grid') or 0.25)
    grid = max(grid, 0.05)
    surfaces = []
    for d in config.get('devices', []):
        if d.get('type') != 'case':
            continue
        rot = d.get('rot', 0)
        name = d.get('name', d['id'])
        # 展台面：z=0.1 水平面，法线向上
        pts = []
        nx = max(1, int(round(d['w'] / grid)))
        ny = max(1, int(round(d.get('d', 1) / grid)))
        for i in range(nx):
            for j in range(ny):
                lx = -d['w'] / 2 + (i + 0.5) * d['w'] / nx
                ly = -d.get('d', 1) / 2 + (j + 0.5) * d.get('d', 1) / ny
                wx, wy = _rot(lx, ly, 0, 0, rot)
                pts.append({'x': d['x'] + wx, 'y': d['y'] + wy, 'z': 0.1})
        surfaces.append({'id': d['id'] + ':bottom', 'owner': d['id'], 'plane': 'bottom',
                         'name': name + ' · 展台面', 'normal': (0, 0, 1), 'points': pts})
        # 背板：局部 +y 边竖直面，法线朝展柜前方
        pts = []
        nx = max(1, int(round(d['w'] / grid)))
        nz = max(1, int(round(d.get('h', 2) / grid)))
        bx, by = _rot(0, 1, 0, 0, rot)
        for i in range(nx):
            for k in range(nz):
                lx = -d['w'] / 2 + (i + 0.5) * d['w'] / nx
                wx, wy = _rot(lx, d.get('d', 1) / 2, 0, 0, rot)
                pts.append({'x': d['x'] + wx, 'y': d['y'] + wy,
                            'z': (k + 0.5) * d.get('h', 2) / nz})
        surfaces.append({'id': d['id'] + ':back', 'owner': d['id'], 'plane': 'back',
                         'name': name + ' · 背板', 'normal': (-bx, -by, 0), 'points': pts})
    return surfaces


def _limits(config):
    settings = config.get('settings') or {}
    sens = SENSITIVITY.get(settings.get('sensitivity', 'paper'), SENSITIVITY['paper'])
    lux_limit = float(settings.get('lux_limit') or sens['lux_limit'])
    tmax = float(settings.get('target_max') or lux_limit)
    return {
        'tmin': float(settings.get('target_min') or 0),
        'tmax': tmax,
        'over_lim': min(tmax, lux_limit),
        'lux_limit': lux_limit,
        'annual_limit': float(settings.get('dose_limit') or sens['annual_dose']),
        'umin': float(settings.get('uniformity_min') or 0),
        'hours': float(settings.get('hours_per_day') or 0),
        'glare_limit': float(settings.get('glare_limit') or 25),
    }


def _flag(E, lim):
    if E < lim['tmin']:
        return 'under'
    if E > lim['over_lim']:
        return 'over'
    return 'ok'


def evaluate(config):
    """整体评估：逐拍摄面计算照度分布与指标，并计算摄像机处眩光。"""
    lim = _limits(config)
    devices = config.get('devices', [])
    lamps = [d for d in devices if d.get('type') == 'lamp']
    tot_p = sum(l.get('power', 0) for l in lamps) or 1.0
    avg_cct = sum(l.get('power', 0) * l.get('cct', 3000) for l in lamps) / tot_p
    dmg = cct_damage_factor(avg_cct)

    out_surfaces = []
    for s in build_surfaces(config):
        pts, Es = [], []
        for p in s['points']:
            E = 0.0
            for lamp in lamps:
                T = transmission(lamp, p, devices, s['owner'])
                if T > 0:
                    E += lamp_point_E(lamp, p, s['normal']) * T
            E = round(E, 2)
            Es.append(E)
            pts.append({'x': round(p['x'], 3), 'y': round(p['y'], 3), 'z': round(p['z'], 3),
                        'E': E, 'flag': _flag(E, lim)})
        n = len(Es) or 1
        Eavg = sum(Es) / n
        Emin = min(Es) if Es else 0.0
        Emax = max(Es) if Es else 0.0
        u = Emin / Eavg if Eavg > 0 else 0.0
        shadow = sum(1 for e in Es if e < 0.5 * lim['tmin']) / n if lim['tmin'] > 0 else 0.0
        dose_day = Eavg * lim['hours']
        dose_year = dose_day * 365
        dose_eff = dose_year * dmg
        warnings = []
        if Eavg < lim['tmin']:
            warnings.append('平均照度 %.1f lx 低于目标下限 %.0f lx' % (Eavg, lim['tmin']))
        if Emax > lim['over_lim']:
            warnings.append('存在热点：Emax %.1f lx 超过上限 %.0f lx' % (Emax, lim['over_lim']))
        if u < lim['umin']:
            warnings.append('均匀度 %.2f 低于下限 %.2f' % (u, lim['umin']))
        if shadow > 0.1:
            warnings.append('阴影率 %.0f%% 偏高（低于目标下限 50%% 的采样点）' % (shadow * 100))
        if dose_eff > lim['annual_limit']:
            warnings.append('年等效光剂量 %.0f lx·h 超过光敏阈值 %.0f lx·h' % (dose_eff, lim['annual_limit']))
        out_surfaces.append({
            'id': s['id'], 'owner': s['owner'], 'name': s['name'], 'plane': s['plane'],
            'normal': list(s['normal']),
            'E_avg': round(Eavg, 2), 'E_min': round(Emin, 2), 'E_max': round(Emax, 2),
            'uniformity': round(u, 3), 'shadow_rate': round(shadow, 3),
            'dose_day': round(dose_day, 1), 'dose_year': round(dose_year, 0),
            'dose_eff': round(dose_eff, 0),
            'warnings': warnings, 'points': pts,
        })

    # 眩光：眼位处可见灯具的垂直照度之和
    glare = {'total': 0.0, 'lamps': [], 'limit': lim['glare_limit'], 'warning': False}
    cam = config.get('camera')
    if cam:
        pt = {'x': cam['x'], 'y': cam['y'], 'z': cam.get('z', 1.6)}
        for lamp in lamps:
            T = transmission(lamp, pt, devices, None)
            if T <= 0:
                continue
            I, r = lamp_intensity(lamp, pt)
            if I <= 0 or r <= 0:
                continue
            ev = I / (r * r) * T
            glare['lamps'].append({'id': lamp['id'], 'name': lamp.get('name', lamp['id']),
                                   'ev': round(ev, 2)})
            glare['total'] += ev
        glare['total'] = round(glare['total'], 2)
        glare['lamps'].sort(key=lambda x: -x['ev'])
        glare['warning'] = glare['total'] > lim['glare_limit']

    summary = {
        'surfaces': len(out_surfaces),
        'warnings': sum(len(s['warnings']) for s in out_surfaces) + (1 if glare['warning'] else 0),
        'avg_cct': round(avg_cct), 'damage_factor': round(dmg, 3),
        'limits': lim,
    }
    return {'surfaces': out_surfaces, 'glare': glare, 'summary': summary}


def trace_point(config, surface_id, index):
    """追溯单个采样点：列出每盏灯的贡献照度、占比与参数。"""
    lim = _limits(config)
    surfaces = build_surfaces(config)
    s = next((x for x in surfaces if x['id'] == surface_id), None)
    if not s or index < 0 or index >= len(s['points']):
        return {'error': '采样点不存在'}
    p = s['points'][index]
    devices = config.get('devices', [])
    lamps = [d for d in devices if d.get('type') == 'lamp']
    rows, total = [], 0.0
    for lamp in lamps:
        T = transmission(lamp, p, devices, s['owner'])
        e = lamp_point_E(lamp, p, s['normal']) * T if T > 0 else 0.0
        total += e
        rows.append({
            'id': lamp['id'], 'name': lamp.get('name', lamp['id']),
            'E': round(e, 2), 'T': round(T, 3),
            'power': lamp.get('power'), 'cct': lamp.get('cct'), 'beam': lamp.get('beam'),
            'efficacy': lamp.get('efficacy'), 'z': lamp.get('z'),
            'aim': lamp.get('aim'), 'locked': bool(lamp.get('locked')),
        })
    for r in rows:
        r['share'] = round(r['E'] / total * 100, 1) if total > 0 else 0.0
    rows.sort(key=lambda r: -r['E'])
    return {
        'surface': surface_id, 'name': s['name'], 'index': index,
        'point': {'x': round(p['x'], 3), 'y': round(p['y'], 3), 'z': round(p['z'], 3)},
        'total': round(total, 2), 'flag': _flag(total, lim), 'lamps': rows,
    }


def diff_metrics(ma, mb):
    """两套方案指标差异（B 相对 A）。"""
    rows = []
    for sa in ma['surfaces']:
        sb = next((s for s in mb['surfaces'] if s['id'] == sa['id']), None)
        if not sb:
            rows.append({'surface': sa['name'], 'missing': True})
            continue
        mrows = []
        for k, label in METRIC_KEYS:
            mrows.append({'key': k, 'label': label, 'a': sa[k], 'b': sb[k],
                          'd': round(sb[k] - sa[k], 3)})
        rows.append({'surface': sa['name'], 'metrics': mrows})
    return {
        'surfaces': rows,
        'glare': {'a': ma['glare']['total'], 'b': mb['glare']['total'],
                  'd': round(mb['glare']['total'] - ma['glare']['total'], 2)},
    }
