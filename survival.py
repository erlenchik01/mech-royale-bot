"""Mech Royale survival v7: conservative zone positioning and quieter waiting.

Based on the verified v4 policy. Experiment changes zone destination / pacing;
combat remains independent. This is not proof of gameplay improvement.
"""
import math

_last_pos = None
_last_check_t = None
_last_tick = None
_escape_until_t = -1.0
_escape_direction = 1


def _unit(dx, dy):
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 1e-9 else (0.0, 0.0)


def _reset():
    global _last_pos, _last_check_t, _last_tick, _escape_until_t, _escape_direction
    _last_pos = None
    _last_check_t = None
    _last_tick = None
    _escape_until_t = -1.0
    _escape_direction = 1


def _projectile_avoidance(obs, x, y):
    best = (0.0, 0.0)
    best_risk = 0.0
    for p in obs.get('projectiles', ()):
        pos, vel = p.get('pos'), p.get('vel')
        if not pos or not vel:
            continue
        dx, dy = pos[0] - x, pos[1] - y
        vx, vy = vel[0], vel[1]
        speed2 = vx * vx + vy * vy
        if speed2 < 100.0 or dx * dx + dy * dy > 70.0 * 70.0:
            continue
        intercept_t = -(dx * vx + dy * vy) / speed2
        if not (0.0 < intercept_t < 0.45):
            continue
        miss = math.hypot(dx + vx * intercept_t, dy + vy * intercept_t)
        if miss > 8.0:
            continue
        risk = (1.0 - miss / 8.0) * (1.0 - intercept_t / 0.45)
        if risk > best_risk:
            px, py = dx + vx * intercept_t, dy + vy * intercept_t
            side_x, side_y = _unit(-vy, vx)
            if px * side_x + py * side_y > 0.0:
                side_x, side_y = -side_x, -side_y
            best, best_risk = (side_x, side_y), risk
    return best[0] * best_risk, best[1] * best_risk


def survival_action(obs):
    global _last_pos, _last_check_t, _last_tick, _escape_until_t, _escape_direction
    me = obs['self']
    x, y = me['pos'][:2]
    tick = obs['tick']
    t = float(obs.get('t', tick / 20.0))
    if _last_tick is not None and (tick <= _last_tick or tick - _last_tick > 200):
        _reset()
    _last_tick = tick

    zone = obs['zone']
    cx, cy = zone['next_center']
    radius = max(0.0, zone['next_radius'])
    dist = math.hypot(cx - x, cy - y)
    safe_radius = max(0.0, radius - min(25.0, radius * 0.20))
    outside_now = not me.get('in_zone', True)

    # Target the near side of the *next* ring, not the crowded center.
    # Pick the radial point on the current side, safely inside the boundary.
    dir_from_center = _unit(x - cx, y - cy)
    if dir_from_center == (0.0, 0.0):
        dir_from_center = (1.0, 0.0)
    target_r = 0.6 * safe_radius
    tx = cx + dir_from_center[0] * target_r
    ty = cy + dir_from_center[1] * target_r
    distance_to_target = math.hypot(tx - x, ty - y)
    target_ux, target_uy = _unit(tx - x, ty - y)
    center_ux, center_uy = _unit(cx - x, cy - y)

    # Travel time assumes normal walking, with 15s buffer for obstructions.
    # If already safely within the next ring, no need to go toward its center.
    speed = max(1.0, float(me.get('stats', {}).get('walk_speed', 11.7)))
    shrink_end = float(zone.get('shrink_end', t))
    time_left = max(0.0, shrink_end - t)
    need_to_depart = time_left <= distance_to_target / speed + 15.0
    urgency = outside_now or (dist > radius + 10.0 and need_to_depart)
    safely_inside_next = dist < max(0.0, safe_radius - 10.0)
    # If inside the next ring, remaining stationary is normally best, but
    # never stand still outside the *current* ring.
    move_for_zone = outside_now or (not safely_inside_next and need_to_depart)

    nearest = float('inf')
    health_ratio = me.get('hp', 1400.0) / max(1.0, me.get('max_hp', 1400.0))
    repulse_x, repulse_y = 0.0, 0.0
    for enemy in obs.get('mechs', ()):
        if enemy.get('kind') != 'mech' or enemy.get('id') == me.get('id'):
            continue
        ex, ey = enemy['pos'][:2]
        dx, dy = x - ex, y - ey
        distance = math.hypot(dx, dy)
        nearest = min(nearest, distance)
        if 1e-6 < distance < 75.0:
            strength = (75.0 - distance) / 75.0
            strength *= 2.0 if health_ratio < 0.5 else 1.2
            if urgency:
                strength *= 0.45
            repulse_x += strength * dx / distance
            repulse_y += strength * dy / distance

    dodge_x, dodge_y = _projectile_avoidance(obs, x, y)
    # A threat always overrides quiet waiting.
    immediate_threat = nearest < 75.0 or math.hypot(dodge_x, dodge_y) > 0.02

    if move_for_zone:
        zone_weight = 3.0 if outside_now else 2.0
        vx = target_ux * zone_weight + repulse_x
        vy = target_uy * zone_weight + repulse_y
    else:
        vx, vy = repulse_x, repulse_y
    if not urgency:
        vx += 1.3 * dodge_x
        vy += 1.3 * dodge_y

    if not move_for_zone and not immediate_threat:
        mx, my = 0.0, 0.0
    else:
        mx, my = _unit(vx, vy)
        # Avoid steering out of the next safe circle while fleeing a threat.
        if safely_inside_next and radius > 0.0 and (mx or my):
            if math.hypot(x + mx * 15.0 - cx, y + my * 15.0 - cy) > safe_radius:
                mx, my = center_ux, center_uy

    energy = float(me.get('energy', 0.0))
    grounded = bool(me.get('grounded', False))
    if _last_check_t is None:
        _last_check_t, _last_pos = t, (x, y)
    elif t - _last_check_t >= 1.3:
        actual_distance = math.hypot(x - _last_pos[0], y - _last_pos[1])
        wants_to_move = math.hypot(mx, my) > 0.5
        if grounded and wants_to_move and actual_distance < 1.8 and energy > 62.0:
            _escape_until_t = t + 1.4
            _escape_direction = -_escape_direction
        _last_check_t, _last_pos = t, (x, y)

    escaping = t < _escape_until_t and (mx != 0.0 or my != 0.0)
    if escaping:
        mx, my = _unit(mx - _escape_direction * my * 0.9,
                       my + _escape_direction * mx * 0.9)

    jump = bool(escaping and grounded and energy > 48.0)
    jet = bool(escaping and not grounded and energy > 24.0)
    emergency_boost = bool(grounded and energy > 25.0 and
                           (urgency or (nearest < 35.0 and health_ratio < 0.6)))
    boost = jet or emergency_boost
    return {'move': [mx, my], 'boost': bool(boost), 'jump': bool(jump)}
