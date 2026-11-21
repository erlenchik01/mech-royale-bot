"""Survival movement policy for Mech Royale (mechfight/1).

Returns only movement-related action fields; combat decisions remain separate.
This is an experimental baseline, not a guaranteed score improvement.
"""
import math


def _unit(dx, dy):
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 1e-8 else (0.0, 0.0)


def survival_action(obs):
    """Return movement commands using the current observation."""
    me = obs["self"]
    x, y = me["pos"][:2]
    zone = obs["zone"]
    cx, cy = zone["next_center"]
    next_radius = zone["next_radius"]

    dist_to_next = math.hypot(cx - x, cy - y)
    # Stay comfortably inside the NEXT safe circle, but don't hug its center
    # when doing so would run directly into nearby enemies.
    safe_radius = max(0.0, next_radius - min(25.0, next_radius * 0.20))
    outside_next = dist_to_next > safe_radius
    outside_now = not me["in_zone"]

    # Weak pressure toward the next center while safely inside the next circle.
    zone_weight = 3.0 if outside_now else (2.0 if outside_next else 0.15)
    ux, uy = _unit(cx - x, cy - y)
    vx, vy = zone_weight * ux, zone_weight * uy

    nearest = float("inf")
    for enemy in obs.get("mechs", []):
        if enemy.get("kind") != "mech":
            continue
        ex, ey = enemy["pos"][:2]
        dx, dy = x - ex, y - ey
        distance = math.hypot(dx, dy)
        nearest = min(nearest, distance)
        if 1e-6 < distance < 75.0:
            # Stronger repulsion near enemies. Out-of-zone mechs prioritize safety.
            strength = (75.0 - distance) / 75.0
            strength *= 2.0 if me["hp"] < 0.5 * me["max_hp"] else 1.2
            if outside_now or outside_next:
                strength *= 0.45
            vx += strength * dx / distance
            vy += strength * dy / distance

    # If the proposed move would leave the next circle, steer back toward it.
    if not outside_now and not outside_next and next_radius > 0:
        step = 15.0
        px, py = x + vx * step, y + vy * step
        if math.hypot(px - cx, py - cy) > safe_radius:
            vx, vy = _unit(cx - x, cy - y)

    mx, my = _unit(vx, vy)
    # Boost strategically; energy is needed for later escapes and jumps.
    emergency = outside_now or (outside_next and dist_to_next > next_radius + 10.0)
    threatened = nearest < 35.0 and me["hp"] < me["max_hp"] * 0.6
    boost = bool(me["grounded"] and me["energy"] > 25 and (emergency or threatened))

    return {"move": [mx, my], "boost": boost, "jump": False}
