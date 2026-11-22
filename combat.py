"""Mech Royale Combat AI. No external dependencies; does not control movement.

Usage from the controller:
    from combat import CombatAI
    self.combat = CombatAI(hello)
    ...
    action.update(self.combat.act(obs))  # after survival/movement decisions

The returned dict contains only combat-related action fields (never tick/move/boost/jump).
"""
import math


def _angle_delta(a, b):
    return (a - b + math.pi) % (2.0 * math.pi) - math.pi


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _intercept(me, target, speed, height):
    """Constant-velocity intercept; return (yaw, pitch, flight_seconds, horizontal_range)."""
    src = me['pos']
    pos = target['pos']
    velocity = target.get('vel', [0.0, 0.0, 0.0])
    own_vel = me.get('vel', [0.0, 0.0, 0.0])
    # Projectiles inherit no mech velocity in the game. Source is the muzzle.
    dx = pos[0] - src[0]
    dy = pos[1] - src[1]
    dz = pos[2] + height - (src[2] + me.get('stats', {}).get('muzzle_height', 7.0))
    vx, vy, vz = velocity
    aa = vx * vx + vy * vy + vz * vz - speed * speed
    bb = 2.0 * (dx * vx + dy * vy + dz * vz)
    cc = dx * dx + dy * dy + dz * dz
    t = math.sqrt(cc) / max(speed, 1.0)
    if abs(aa) > 1e-9:
        disc = bb * bb - 4.0 * aa * cc
        if disc >= 0:
            root = math.sqrt(disc)
            times = [q for q in ((-bb - root) / (2 * aa), (-bb + root) / (2 * aa)) if q > 0]
            if times:
                t = min(times)
    elif abs(bb) > 1e-9:
        candidate = -cc / bb
        if candidate > 0:
            t = candidate
    t = min(t, 3.0)  # avoid huge extrapolation
    px, py, pz = dx + vx * t, dy + vy * t, dz + vz * t
    return math.atan2(py, px), math.atan2(pz, math.hypot(px, py)), t, math.hypot(px, py)


def _mortar_aim(me, target, speed, gravity, target_height):
    """Approximate low-arc ballistic trajectory, updating target lead twice."""
    src = me['pos']
    muzzle = src[2] + me.get('stats', {}).get('muzzle_height', 7.0) + 2.5
    target_pos = target['pos']
    vel = target.get('vel', [0, 0, 0])
    t = _distance(src, target_pos) / max(speed * 0.7, 1.0)
    for _ in range(3):
        dx = target_pos[0] + vel[0] * t - src[0]
        dy = target_pos[1] + vel[1] * t - src[1]
        dz = target_pos[2] + target_height + vel[2] * t - muzzle
        r = math.hypot(dx, dy)
        if r < 1.0:
            return None
        disc = speed ** 4 - gravity * (gravity * r * r + 2 * dz * speed * speed)
        if disc < 0:
            return None
        pitch = math.atan((speed * speed - math.sqrt(disc)) / (gravity * r))
        if not (-0.7 <= pitch <= 1.45):
            return None
        t = min(r / max(speed * math.cos(pitch), 1.0), 4.5)
    return math.atan2(dy, dx), pitch, t, r


class CombatAI:
    """A lightweight, placement-aware combat advisor (does not issue movement)."""

    def __init__(self, hello):
        self.config = hello.get('config', {})
        self.last_target_id = None
        self.last_laser_trigger = [False, False]

    def find_enemies(self, obs):
        me = obs['self']
        return sorted((m for m in obs.get('mechs', []) if m.get('kind') == 'mech'
                       and m.get('id') != me['id']),
                      key=lambda m: _distance(m['pos'], me['pos']))

    def select_target(self, obs):
        """Prefer nearby mechs, or opportunistic NPCs when fighting is safe."""
        me = obs['self']
        enemies = self.find_enemies(obs)
        hp_ratio = me.get('hp', 1) / max(me.get('max_hp', 1), 1)
        max_range = 95.0 if hp_ratio < 0.35 else 185.0
        eligible = [m for m in enemies if _distance(m['pos'], me['pos']) <= max_range]

        # Mechs remain the priority. Never farm NPCs while exposed to nearby mechs.
        def priority(m):
            d = _distance(m['pos'], me['pos'])
            hp = m.get('hp')
            weakness = (1.0 - hp / max(m.get('max_hp', 1), 1)) if hp is not None else 0.0
            continuity = 0.25 if m.get('id') == self.last_target_id else 0.0
            return (1.8 / (1.0 + d / 60.0)) + 0.6 * weakness + continuity

        if eligible:
            return max(eligible, key=priority)

        # NPC farming v7: only while healthy, in-zone, with energy, and
        # with no known mech in close proximity. This is not NPC chasing:
        # survival_action() still owns movement.
        if (hp_ratio < 0.75 or not me.get('in_zone', True)
                or me.get('energy', 0) < 20):
            return None
        if any(_distance(m['pos'], me['pos']) < 110.0 for m in enemies):
            return None
        weapon_ready = any(w and w.get('kind') == 'gun'
                           and w.get('reload', 0) <= 0
                           and w.get('ammo', 0) >= 4 for w in me.get('weapons', []))
        if not weapon_ready:
            return None
        npcs = [m for m in obs.get('mechs', [])
                if m.get('kind') == 'npc'
                and _distance(m['pos'], me['pos']) <= 65.0]
        if not npcs:
            return None
        return min(npcs, key=lambda m: (
            _distance(m['pos'], me['pos'])
            - (8.0 if m.get('id') == self.last_target_id else 0.0)))

    def choose_upgrade(self, offer):
        if not offer:
            return None
        scores = {
            'armor': 12, 'regen': 11, 'hp': 11, 'health': 11,
            'speed': 10, 'energy': 9, 'mobility': 9, 'boost': 9,
            'gun_rate': 7, 'gun_damage': 7, 'laser_damage': 8,
            'lightning': 7, 'mortar': 6, 'sensors': 5,
        }
        choices = offer.get('choices', [])
        if not choices:
            return None
        def score(choice):
            key = choice.get('id', '').lower()
            return max((v for k, v in scores.items() if k in key), default=4)
        return max(range(len(choices)), key=lambda i: score(choices[i]))

    def choose_pickup(self, obs):
        me = obs['self']
        pickup_radius = self.config.get('loot', {}).get('pickup_radius', 4.0)
        weapons = me.get('weapons', [])
        owned = {w['kind'] for w in weapons if w}
        desirability = {'laser': 4, 'lightning': 3, 'mortar': 2, 'gun': 1}
        options = []
        for p in obs.get('pickups', []):
            if p['kind'] in owned or p['kind'] == 'gun':
                continue
            if _distance(me['pos'], p['pos']) > pickup_radius:
                continue
            if abs(me['pos'][2] - p['pos'][2]) > 4.0:
                continue
            options.append(p)
        if not options:
            return {}
        pickup = max(options, key=lambda p: desirability.get(p['kind'], 0))
        result = {'take': pickup['id']}
        if not any(w is None for w in weapons):
            candidates = [(i, desirability.get(w['kind'], 0)) for i, w in enumerate(weapons)
                          if w and not (w['kind'] == 'laser' and w.get('charge', 0) > 0)]
            if not candidates:
                return {}
            drop_index, drop_value = min(candidates, key=lambda x: x[1])
            if desirability.get(pickup['kind'], 0) <= drop_value:
                return {}
            result['drop'] = drop_index
        return result

    def _options(self, me, target):
        d = _distance(me['pos'], target['pos'])
        enemy_h = 1.8 if target.get('kind') == 'npc' else 4.5
        choices = []
        for i, w in enumerate(me.get('weapons', [])):
            if not w:
                continue
            kind = w.get('kind')
            stats = w.get('stats', {})
            cooldown = w.get('cooldown', 0)
            if kind == 'gun':
                if w.get('reload', 0) > 0 or w.get('ammo', 1) <= 0:
                    continue
                rng = stats.get('range', 230)
                if d > rng * 0.95:
                    continue
                aim = _intercept(me, target, stats.get('speed', 252), enemy_h)
                choices.append((2.0 + 45.0 / (d + 15), i, kind, aim))
            elif kind == 'lightning':
                cost = stats.get('energy', 3)
                if d > stats.get('range', 45) * 0.87 or me.get('energy', 0) < cost + 3:
                    continue
                aim = _intercept(me, target, 5000, enemy_h)
                choices.append((6.0, i, kind, aim))
            elif kind == 'laser':
                if d > stats.get('range', 280) * 0.95:
                    continue
                aim = _intercept(me, target, 5000, enemy_h)
                choices.append((5.0 if w.get('charge', 0) > 0 else 4.0, i, kind, aim))
            elif kind == 'mortar':
                if d < 22 or d > 205:
                    continue  # avoid self splash and excessive range
                aim = _mortar_aim(me, target, stats.get('speed', 72),
                                  stats.get('gravity', self.config.get('weapons', {}).get('mortar', {}).get('gravity', 22)), enemy_h)
                if aim:
                    choices.append((3.0 if d > 45 else 1.0, i, kind, aim))
        return sorted(choices, reverse=True, key=lambda x: x[0])

    def act(self, obs):
        """Return partial action: aim, fire, reload, pick, take/drop only."""
        me = obs['self']
        result = {'fire': [False, False]}
        upgrade = self.choose_upgrade(obs.get('offer'))
        if upgrade is not None:
            result['pick'] = upgrade
        result.update(self.choose_pickup(obs))
        for w in me.get('weapons', []):
            if w and w['kind'] == 'gun' and w.get('ammo', 1) <= 0 and w.get('reload', 0) <= 0:
                result['reload'] = True
        target = self.select_target(obs)
        if target is None:
            self.last_target_id = None
            return result
        options = self._options(me, target)
        if not options:
            return result
        self.last_target_id = target['id']
        _, idx, kind, solution = options[0]
        yaw, pitch, _, horizontal_range = solution
        result['aim'] = [yaw, pitch]
        actual_yaw, actual_pitch = me.get('aim', [yaw, pitch])
        # Shots use CURRENT torso aim, not the commanded aim. Estimate next 0.1s rotation.
        stats = me.get('stats', {})
        rate_yaw = stats.get('turn_rate', 4.0)
        rate_pitch = stats.get('pitch_rate', 3.0)
        error_yaw = max(0.0, abs(_angle_delta(yaw, actual_yaw)) - rate_yaw * 0.06)
        error_pitch = max(0.0, abs(pitch - actual_pitch) - rate_pitch * 0.06)
        radius = 1.8 if target.get('kind') == 'npc' else 2.5
        tolerance = min(0.14, max(0.018, math.atan2(radius * 0.80, max(horizontal_range, 1.0))))
        aligned = error_yaw < tolerance and error_pitch < max(tolerance, 0.045)
        weapon = me['weapons'][idx]
        if kind == 'laser':
            charge = weapon.get('charge', 0)
            desired = weapon.get('stats', {}).get('charge', 0.75)
            # Stay on target while charging. Releasing emits the beam.
            result['fire'][idx] = charge < desired or not aligned
        elif kind == 'lightning':
            cone = math.radians(weapon.get('stats', {}).get('cone_deg', 30) / 2)
            result['fire'][idx] = (error_yaw < cone * 0.65 and aligned and
                                   weapon.get('cooldown', 0) <= 0.1)
        else:
            result['fire'][idx] = aligned and weapon.get('cooldown', 0) <= 0.1
        # Gun can fire concurrently with a non-gun main weapon if aim also lines up.
        for j, w in enumerate(me.get('weapons', [])):
            if j == idx or not w or w['kind'] != 'gun' or w.get('reload', 0) > 0 or w.get('ammo', 0) <= 0:
                continue
            gun_aim = _intercept(me, target, w.get('stats', {}).get('speed', 252), 4.5)
            if (_distance(me['pos'], target['pos']) < w.get('stats', {}).get('range', 230) and
                abs(_angle_delta(gun_aim[0], yaw)) < tolerance and
                abs(gun_aim[1] - pitch) < max(tolerance, 0.045) and aligned):
                result['fire'][j] = True
        return result
