from __future__ import annotations

from solitaire.engine import Action, ActionKind, KlondikeEngine, RED_SUITS

from .base import Decision


class HeuristicAgent:
    """Small deterministic baseline, intentionally not a search player."""

    name = "heuristic"

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def reset(self, seed: int) -> None:
        self._seen.clear()

    def _safe_foundation(self, engine: KlondikeEngine, action: Action) -> bool:
        if action.kind is ActionKind.WASTE_TO_FOUNDATION:
            card = engine.waste[-1]
        else:
            card = engine.tableau[int(action.source)][-1]
        if card.rank <= 2:
            return True
        opposite = ("S", "C") if card.suit in RED_SUITS else ("H", "D")
        return all(len(engine.foundations[suit]) >= card.rank - 1 for suit in opposite)

    def _reveals_hidden(self, engine: KlondikeEngine, action: Action) -> bool:
        if action.kind not in {
            ActionKind.TABLEAU_TO_TABLEAU,
            ActionKind.TABLEAU_TO_FOUNDATION,
        }:
            return False
        pile = engine.tableau[int(action.source)]
        removed = action.count if action.kind is ActionKind.TABLEAU_TO_TABLEAU else 1
        return len(pile) > removed and not pile[-removed - 1].face_up

    def _score(self, engine: KlondikeEngine, action: Action) -> tuple[int, str]:
        score = 0
        if self._reveals_hidden(engine, action):
            score += 120
        if action.kind in {
            ActionKind.WASTE_TO_FOUNDATION,
            ActionKind.TABLEAU_TO_FOUNDATION,
        }:
            score += 65 if self._safe_foundation(engine, action) else -20
        elif action.kind is ActionKind.WASTE_TO_TABLEAU:
            score += 45
        elif action.kind is ActionKind.TABLEAU_TO_TABLEAU:
            score += 15
            if not engine.tableau[int(action.target)]:
                score += 10
                source = engine.tableau[int(action.source)]
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

        if engine.preview_state_hash(action) in self._seen:
            score -= 200
        else:
            score += 20
        # The key makes tie-breaking explicit and reproducible.
        return score, action.key

    def choose(self, engine: KlondikeEngine, actions: list[Action]) -> Decision:
        if not actions:
            raise ValueError("cannot choose without a legal action")
        self._seen.add(engine.state_hash())
        scored = [(self._score(engine, action), action) for action in actions]
        selected_score, selected = max(scored, key=lambda item: item[0])
        return Decision(
            action=selected,
            metadata={"heuristic_score": selected_score[0]},
        )
