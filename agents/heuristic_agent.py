from __future__ import annotations

from solitaire.engine import Action, ActionKind, RED_SUITS

from .base import Decision, Observation


class HeuristicAgent:
    """Small deterministic baseline, intentionally not a search player."""

    name = "heuristic"

    def reset(self, seed: int) -> None:
        pass

    @staticmethod
    def _rank(code: str) -> int:
        label = code[:-1]
        named = {"A": 1, "J": 11, "Q": 12, "K": 13}
        return named[label] if label in named else int(label)

    @staticmethod
    def _suit(code: str) -> str:
        return code[-1]

    def _safe_foundation(self, observation: Observation, action: Action) -> bool:
        state = observation.visible_state
        if action.kind is ActionKind.WASTE_TO_FOUNDATION:
            code = state["waste"]
        else:
            code = state["tableau"][int(action.source)][-1]
        rank = self._rank(code)
        suit = self._suit(code)
        if rank <= 2:
            return True
        opposite = ("S", "C") if suit in RED_SUITS else ("H", "D")
        return all(
            state["foundation"][other] != "-"
            and self._rank(state["foundation"][other]) >= rank - 1
            for other in opposite
        )

    def _reveals_hidden(self, observation: Observation, action: Action) -> bool:
        if action.kind not in {
            ActionKind.TABLEAU_TO_TABLEAU,
            ActionKind.TABLEAU_TO_FOUNDATION,
        }:
            return False
        pile = observation.visible_state["tableau"][int(action.source)]
        removed = action.count if action.kind is ActionKind.TABLEAU_TO_TABLEAU else 1
        return len(pile) > removed and pile[-removed - 1] == "XX"

    def _score(self, observation: Observation, action: Action) -> tuple[int, str]:
        score = 0
        if self._reveals_hidden(observation, action):
            score += 120
        if action.kind in {
            ActionKind.WASTE_TO_FOUNDATION,
            ActionKind.TABLEAU_TO_FOUNDATION,
        }:
            score += 65 if self._safe_foundation(observation, action) else -20
        elif action.kind is ActionKind.WASTE_TO_TABLEAU:
            score += 45
        elif action.kind is ActionKind.TABLEAU_TO_TABLEAU:
            score += 15
            if not observation.visible_state["tableau"][int(action.target)]:
                score += 10
                source = observation.visible_state["tableau"][int(action.source)]
                if len(source) == action.count:
                    # Moving the whole king stack between empty columns changes
                    # the hash but creates no new option.
                    score -= 350
        elif action.kind is ActionKind.FOUNDATION_TO_TABLEAU:
            # Legal under standard rules, but this tiny non-search baseline must
            # not manufacture thousands of novel states by dismantling progress.
            score -= 500
        elif action.kind is ActionKind.RECYCLE:
            score -= 5

        if observation.label(action) in observation.actions_tried_from_visible_state:
            score -= 200
        else:
            score += 20
        # The key makes tie-breaking explicit and reproducible.
        return score, action.key

    def choose(self, observation: Observation, actions: list[Action]) -> Decision:
        if not actions:
            raise ValueError("cannot choose without a legal action")
        scored = [(self._score(observation, action), action) for action in actions]
        selected_score, selected = max(scored, key=lambda item: item[0])
        return Decision(
            action=selected,
            metadata={"heuristic_score": selected_score[0]},
        )
