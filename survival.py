
"""Mech Royale Survival AI v7b (protocol mechfight/1).

Based on Survival v4.
Experimental change: quiet patrol while safely inside the next zone.
Controls only move, boost, and jump.
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
    global _last_pos, _last_check_t, _last_tick
    global _escape_until_t, _escape_direction

    _last_pos = None
    _last_check_t = None
    _last_tick = None
    _escape_until_t = -1.0
    _escape_direction = 1


def _projectile_avoidance(obs, x, y):
    """Bounded sideways steering for nearby approaching projectiles."""
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

        t = -(dx * vx + dy * vy) / speed2

        if not (0.0 < t < 0.45):
            continue

        miss = math.hypot(dx + vx * t, dy + vy * t)

        if miss > 8.0:
            continue

        risk = (1.0 - miss / 8.0) * (1.0 - t / 0.45)

        if risk > best_risk:
            px, py = dx + vx * t, dy + vy * t
            side_x, side_y = _unit(-vy, vx)

            if px * side_x + py * side_y > 0.0:
                side_x, side_y = -side_x, -side_y

            best = (side_x, side_y)
            best_risk = risk

    return best[0] * best_risk, best[1] * best_risk


def survival_action(obs):
    """Return movement controls for a single observation."""
    global _last_pos, _last_check_t, _last_tick
    global _escape_until_t, _escape_direction

    me = obs['self']
    x, y = me['pos'][:2]

    tick = obs['tick']
    t = float(obs.get('t', tick / 20.0))

    if _last_tick is not None and (
        tick <= _last_tick or tick - _last_tick > 200
    ):
        _reset()

    _last_tick = tick

    # Zone information
    zone = obs['zone']
    cx, cy = zone['next_center']
    radius = max(0.0, zone['next_radius'])

    dist = math.hypot(cx - x, cy - y)
    safe_radius = max(
        0.0,
        radius - min(25.0, radius * 0.20)
    )

    outside_now = not me.get('in_zone', True)
    outside_next = dist > safe_radius

    urgency = outside_now or dist > radius + 10.0

    # Original Survival v4 zone steering
    weight = (
        3.0 if outside_now
        else (2.0 if outside_next else 0.15)
    )

    ux, uy = _unit(cx - x, cy - y)
    vx, vy = weight * ux, weight * uy

    nearest = float('inf')
    health_ratio = (
        me.get('hp', 1400.0)
        / max(1.0, me.get('max_hp', 1400.0))
    )

    # Avoid nearby enemy mechs
    for enemy in obs.get('mechs', ()):
        if (
            enemy.get('kind') != 'mech'
            or enemy.get('id') == me.get('id')
        ):
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

    # Projectile avoidance
    dodge_x, dodge_y = _projectile_avoidance(obs, x, y)

    if not urgency:
        vx += 1.3 * dodge_x
        vy += 1.3 * dodge_y

    # Original zone boundary protection
    if not outside_now and not outside_next and radius > 0.0:
        mx, my = _unit(vx, vy)

        if math.hypot(
            x + mx * 15.0 - cx,
            y + my * 15.0 - cy
        ) > safe_radius:
            vx, vy = ux, uy

    # Final movement direction
    mx, my = _unit(vx, vy)

    # NEW v7b: quiet patrol
    calm = (
        not outside_now
        and not outside_next
        and radius > 0.0
        and nearest >= 90.0
        and abs(dodge_x) + abs(dodge_y) < 0.05
        and t >= _escape_until_t
    )

    if calm:
        rx, ry = _unit(x - cx, y - cy)

        # Aim for movement speed <= 4.5 m/s.
        walk_speed = max(
            1.0,
            float(me.get('stats', {}).get('walk_speed', 11.7))
        )
        k = min(1.0, 4.5 / walk_speed)

        if abs(rx) + abs(ry) > 0.001:
            patrol_x = -ry * k
            patrol_y = rx * k

            # Avoid moving beyond the safe boundary.
            patrol_horizon = 3.0
            predicted_x = x + patrol_x * walk_speed * patrol_horizon
            predicted_y = y + patrol_y * walk_speed * patrol_horizon

            predicted_dist = math.hypot(
                predicted_x - cx,
                predicted_y - cy
            )

            if predicted_dist <= safe_radius:
                mx, my = patrol_x, patrol_y
            else:
                # Move inward at quiet speed.
                mx, my = -rx * k, -ry * k
        else:
            mx, my = 0.0, 0.0

    energy = float(me.get('energy', 0.0))
    grounded = bool(me.get('grounded', False))

    # Original v4 stuck detection
    if _last_check_t is None:
        _last_check_t = t
        _last_pos = (x, y)

    elif t - _last_check_t >= 1.3:
        actual_distance = math.hypot(
            x - _last_pos[0],
            y - _last_pos[1]
        )

        wants_to_move = math.hypot(mx, my) > 0.5

        if (
            grounded
            and wants_to_move
            and actual_distance < 1.8
            and energy > 62.0
        ):
            _escape_until_t = t + 1.4
            _escape_direction = -_escape_direction

        _last_check_t = t
        _last_pos = (x, y)

    escaping = t < _escape_until_t

    # Original escape maneuver
    if escaping:
        mx, my = _unit(
            mx - _escape_direction * my * 0.9,
            my + _escape_direction * mx * 0.9
        )

    jump = bool(
        escaping and grounded and energy > 48.0
    )

    jet = bool(
        escaping and not grounded and energy > 24.0
    )

    emergency_boost = bool(
        grounded
        and energy > 25.0
        and (
            urgency
            or (nearest < 35.0 and health_ratio < 0.6)
        )
    )

    boost = jet or emergency_boost

    return {
        'move': [mx, my],
        'boost': bool(boost),
        'jump': bool(jump)
    }
