
import mechfight as mf
from survival import survival_action
from combat import CombatAI


class Bot:
    name = "survival-combat-v2"

    def __init__(self, hello: mf.Hello):
        self.combat = CombatAI(hello)

    def act(self, obs: mf.Observation) -> mf.Action:
        action: mf.Action = {"tick": obs["tick"]}

        # Erlen: Survival AI
        action.update(survival_action(obs))

        # Nazerke: Combat AI
        action.update(self.combat.act(obs))

        return action


mf.run(Bot)
