
import math

import mechfight as mf
from survival import survival_action
from combat import CombatAI


class Bot:
    name = "survival-combat-v5"

    def __init__(self, hello: mf.Hello):
        self.combat = CombatAI(hello)
        self.recovering = False

    def act(self, obs: mf.Observation) -> mf.Action:
        action: mf.Action = {"tick": obs["tick"]}

        # Erlen: Survival AI
        action.update(survival_action(obs))

        # Nazerke: Combat AI
        action.update(self.combat.act(obs))

        me = obs["self"]
        hp_ratio = me["hp"] / max(me["max_hp"], 1)

        # Enter recovery below 50% HP
        if hp_ratio < 0.50:
            self.recovering = True

        # Exit recovery after reaching 85% HP
        elif hp_ratio >= 0.85:
            self.recovering = False

        # Find the closest visible enemy mech
        nearest_enemy = float("inf")

        for enemy in obs.get("mechs", []):
            if enemy.get("kind") != "mech":
                continue

            if enemy.get("id") == me["id"]:
                continue

            distance = math.hypot(
                enemy["pos"][0] - me["pos"][0],
                enemy["pos"][1] - me["pos"][1]
            )

            nearest_enemy = min(nearest_enemy, distance)

        # Only stop attacking when recovery is relatively safe
        safe_to_recover = (
            self.recovering
            and me["in_zone"]
            and nearest_enemy > 80.0
        )

        if safe_to_recover:
            action["fire"] = [False, False]

        return action


mf.run(Bot)
