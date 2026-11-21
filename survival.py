"""Mech Royale: experimental survival policy v3.

Drop-in replacement for survival.py. Provides survival_action(obs) and never
writes combat action fields, so CombatAI can remain independent.
"""
import math

# These values persist only during one bot process / match.
_last_position = None
_last_sample_tick = None
_escape_until = -1
_escape_side = 1
_escape_target = None


def _norm(x, y):
    d = math.hypot(x, y)
    return (x / d, y / d) if d > 1e-8 else (0.0, 0.0)


def survival_action(obs):
    global _last_position, _last_sample_tick, _escape_until, _escape_side, _escape_target

    me = obs['self']
    x, y = me['pos'][:2]
    tick = obs['tick']
    hp_ratio = me['hp'] / max(me['max_hp'], 1.0)
    energy = me.get('energy', 0.0)
    grounded = me.get('grounded', False)
    zone = obs['zone']
    cx, cy = zone['next_center']
    r = zone['next_radius']
    current_cx, current_cy = zone['center']
    current_r = zone['radius']
    d_next = math.hypot(x-cx, y-cy)
    d_current = math.hypot(x-current_cx, y-current_cy)
    inside_current = bool(me.get('in_zone', d_current < current_r))

    # Stay sufficiently deep in the next ring without insisting on its center.
    margin = min(24.0, max(3.0, r * 0.16))
    safe_r = max(0.0, r - margin)
    urgently_outside = not inside_current or d_next > r
    toward_x, toward_y = _norm(cx-x, cy-y)

    # Fight for zone safety when necessary; otherwise preserve distance from enemies.
    if not inside_current:
        zx, zy = toward_x * 5.0, toward_y * 5.0
    elif d_next > safe_r:
        zx, zy = toward_x * 3.0, toward_y * 3.0
    else:
        zx, zy = 0.0, 0.0

    ax, ay = zx, zy
    closest = float('inf')
    enemies = [m for m in obs.get('mechs', ()) if m.get('kind') == 'mech' and m.get('id') != me.get('id')]
    for enemy in enemies:
        ex, ey = enemy['pos'][:2]
        dx, dy = x-ex, y-ey
        d = math.hypot(dx, dy)
        closest = min(closest, d)
        if d < 1e-5 or d > 95.0:
            continue
        # Avoid close engagements more strongly when weak.
        threat = ((95.0-d)/95.0)**1.4
        threat *= (3.2 if hp_ratio < 0.4 else 2.1 if hp_ratio < 0.75 else 1.2)
        if urgently_outside:
            threat *= 0.38
        ax += threat * dx/d
        ay += threat * dy/d

    # If taking fire from an unseen enemy, move away from the attack bearing.
    for event in obs.get('events', ()):
        if event.get('type') == 'damaged' and event.get('bearing') is not None:
            bearing = event['bearing']
            weight = min(1.8, 0.7 + event.get('amount', 0.0) / 160.0)
            if urgently_outside:
                weight *= 0.4
            ax -= weight * math.cos(bearing)
            ay -= weight * math.sin(bearing)

    # Detect stalled motion only when our earlier command was to move.
    if _last_sample_tick is None or tick < _last_sample_tick:
        _last_position = (x, y)
        _last_sample_tick = tick
        _escape_until = -1
    elif tick - _last_sample_tick >= 24:
        moved = math.hypot(x-_last_position[0], y-_last_position[1])
        trying_to_move = math.hypot(ax, ay) > 0.5
        if trying_to_move and moved < 3.0 and grounded:
            _escape_side *= -1
            _escape_until = tick + 35
            _escape_target = (ax, ay)
        _last_position = (x, y)
        _last_sample_tick = tick

    # Attempt a lateral detour around an obstruction; keep zone priority.
    escaping = tick < _escape_until and _escape_target is not None
    if escaping and not urgently_outside:
        ux, uy = _norm(*_escape_target)
        ax += 3.0 * (-uy) * _escape_side
        ay += 3.0 * ux * _escape_side

    # Prevent hazard avoidance from steering us outside a circle we already occupy.
    mx, my = _norm(ax, ay)
    if inside_current and d_next < safe_r and r > 2.0:
        projected = math.hypot(x + mx * 12.0 - cx, y + my * 12.0 - cy)
        if projected > safe_r:
            mx, my = toward_x, toward_y

    # If safe and alone, remain quiet and allow health / energy regeneration.
    if d_next < safe_r - 8.0 and closest > 95.0 and not urgently_outside:
        mx, my = 0.0, 0.0

    urgent_escape = closest < 24.0 and hp_ratio < 0.65
    boost = bool(grounded and energy > (32.0 if urgent_escape else 45.0)
                 and (urgently_outside or urgent_escape or (d_next > safe_r + 75.0)))
    # Jump only if repeatedly stalled and we can spare energy; in air boost jets upward.
    jump = bool(escaping and grounded and energy > 50.0 and tick % 12 < 2)
    return {'move': [mx, my], 'boost': boost, 'jump': jump}
