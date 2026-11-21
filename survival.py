"""Mech Royale Survival AI v4 (protocol mechfight/1).

Conservative evolution of the better-scoring v2 policy. Controls only
move/boost/jump, and can be combined with the team's unchanged CombatAI.

Important: The official check/check.py replays observations; it cannot measure
real survival, obstacle avoidance effectiveness, or match score.
"""
import math

# Per-match observation state. The process controls only one mech.
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
    """Bounded sideways steering for nearby approaching projectiles.

    Uses horizontal constant-velocity closest approach (short horizon only).
    Does not attempt prediction of terrain collisions or mortar explosions.
    """
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
        # Time until projectile is closest to our current horizontal position.
        t = - (dx * vx + dy * vy) / speed2
        if not (0.0 < t < 0.45):
            continue
        miss = math.hypot(dx + vx * t, dy + vy * t)
        if miss > 8.0:
            continue
        risk = (1.0 - miss / 8.0) * (1.0 - t / 0.45)
        if risk > best_risk:
            # Pick the side that moves away from the projected impact position.
            px, py = dx + vx * t, dy + vy * t
            side_x, side_y = _unit(-vy, vx)
            if px * side_x + py * side_y > 0.0:
                side_x, side_y = -side_x, -side_y
            best, best_risk = (side_x, side_y), risk
    return best[0] * best_risk, best[1] * best_risk


def survival_action(obs):
    """Return protocol-compliant movement controls for a single observation."""
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
    outside_next = dist > safe_radius
    urgency = outside_now or dist > radius + 10.0

    # Preserve v2's steady inward pressure. Do not stop just because enemies
    # are temporarily outside vision: health regen does not require idling.
    weight = 3.0 if outside_now else (2.0 if outside_next else 0.15)
    ux, uy = _unit(cx - x, cy - y)
    vx, vy = weight * ux, weight * uy

    nearest = float('inf')
    health_ratio = me.get('hp', 1400.0) / max(1.0, me.get('max_hp', 1400.0))
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
            if outside_now or outside_next:
                strength *= 0.45
            vx += strength * dx / distance
            vy += strength * dy / distance

    # Optional, cautious bullet dodge. Zone takes precedence when in danger.
    dodge_x, dodge_y = _projectile_avoidance(obs, x, y)
    if not urgency:
        vx += 1.3 * dodge_x
        vy += 1.3 * dodge_y

    if not outside_now and not outside_next and radius > 0.0:
        mx, my = _unit(vx, vy)
        if math.hypot(x + mx * 15.0 - cx, y + my * 15.0 - cy) > safe_radius:
            vx, vy = ux, uy

    mx, my = _unit(vx, vy)
    energy = float(me.get('energy', 0.0))
    grounded = bool(me.get('grounded', False))

    # Detect a real movement stall by comparing observed positions over time.
    # Do not activate from a single frame. A recorded replay is not suitable
    # for evaluating this trigger because actions do not affect positions.
    if _last_check_t is None:
        _last_check_t, _last_pos = t, (x, y)
    elif t - _last_check_t >= 1.3:
        actual_distance = math.hypot(x - _last_pos[0], y - _last_pos[1])
        wants_to_move = math.hypot(mx, my) > 0.5
        if grounded and wants_to_move and actual_distance < 1.8 and energy > 62.0:
            _escape_until_t = t + 1.4
            _escape_direction = -_escape_direction
        _last_check_t, _last_pos = t, (x, y)

    escaping = t < _escape_until_t
    # When blocked, steer diagonally along the wall while jumping over it.
    # The jet works only while airborne per mechfight/1, not on the ground.
    if escaping:
        mx, my = _unit(mx - _escape_direction * my * 0.9,
                       my + _escape_direction * mx * 0.9)

    jump = bool(escaping and grounded and energy > 48.0)
    jet = bool(escaping and not grounded and energy > 24.0)
    emergency_boost = bool(grounded and energy > 25.0 and
                           (urgency or (nearest < 35.0 and health_ratio < 0.6)))
    boost = jet or emergency_boost
    return {'move': [mx, my], 'boost': bool(boost), 'jump': bool(jump)}
