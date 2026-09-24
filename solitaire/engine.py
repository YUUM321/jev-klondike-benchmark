from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any


SUITS = ("S", "H", "D", "C")
RED_SUITS = frozenset(("H", "D"))
RANK_LABELS = {1: "A", 11: "J", 12: "Q", 13: "K"}


@dataclass(frozen=True, slots=True)
class Card:
    suit: str
    rank: int
    face_up: bool = False

    def __post_init__(self) -> None:
        if self.suit not in SUITS or not 1 <= self.rank <= 13:
            raise ValueError(f"invalid card: {self.suit}{self.rank}")

    @property
    def code(self) -> str:
        return f"{RANK_LABELS.get(self.rank, self.rank)}{self.suit}"

    @property
    def color(self) -> str:
        return "red" if self.suit in RED_SUITS else "black"


class ActionKind(str, Enum):
    DRAW = "draw"
    RECYCLE = "recycle"
    WASTE_TO_TABLEAU = "waste_to_tableau"
    WASTE_TO_FOUNDATION = "waste_to_foundation"
    TABLEAU_TO_TABLEAU = "tableau_to_tableau"
    TABLEAU_TO_FOUNDATION = "tableau_to_foundation"
    FOUNDATION_TO_TABLEAU = "foundation_to_tableau"


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionKind
    source: int | str | None = None
    target: int | str | None = None
    count: int = 1

    @property
    def key(self) -> str:
        parts = [self.kind.value]
        if self.source is not None:
            parts.append(str(self.source))
        if self.target is not None:
            parts.append(str(self.target))
        if self.count != 1:
            parts.append(str(self.count))
        return ":".join(parts)


@dataclass(frozen=True, slots=True)
class StepResult:
    hidden_cards_revealed: int
    foundation_delta: int
    state_hash: str


class KlondikeEngine:
    """Klondike Draw-1 or Draw-3 with unlimited stock recycling.

    The engine owns the full deal. Public observation methods redact every
    face-down identity. Exposed face-down tableau cards flip automatically.
    """

    def __init__(self, *, draw_count: int = 1) -> None:
        if draw_count not in {1, 3}:
            raise ValueError("draw_count must be 1 or 3")
        self.draw_count = draw_count
        self.seed: int | None = None
        self.tableau: list[list[Card]] = [[] for _ in range(7)]
        self.foundations: dict[str, list[Card]] = {suit: [] for suit in SUITS}
        self.stock: list[Card] = []
        self.waste: list[Card] = []
        self.waste_packets: list[int] = []
        self.steps = 0

    def reset(self, seed: int) -> dict[str, Any]:
        rng = random.Random(seed)
        deck = [Card(suit, rank) for suit in SUITS for rank in range(1, 14)]
        rng.shuffle(deck)

        self.seed = seed
        self.tableau = [[] for _ in range(7)]
        self.foundations = {suit: [] for suit in SUITS}
        self.waste = []
        self.waste_packets = []
        self.steps = 0

        cursor = 0
        for column in range(7):
            for row in range(column + 1):
                card = deck[cursor]
                cursor += 1
                self.tableau[column].append(
                    replace(card, face_up=(row == column))
                )
        self.stock = [replace(card, face_up=False) for card in deck[cursor:]]
        self.assert_invariants()
        return self.get_visible_state()

    @property
    def foundation_cards(self) -> int:
        return sum(len(pile) for pile in self.foundations.values())

    @property
    def hidden_cards(self) -> int:
        return sum(not card.face_up for pile in self.tableau for card in pile)

    def get_visible_state(self) -> dict[str, Any]:
        packet_size = self._visible_waste_packet_size()
        waste_visible = [card.code for card in self.waste[-packet_size:]]
        return {
            "draw_count": self.draw_count,
            "foundation": {
                suit: (pile[-1].code if pile else "-")
                for suit, pile in self.foundations.items()
            },
            "tableau": [
                [card.code if card.face_up else "XX" for card in pile]
                for pile in self.tableau
            ],
            "waste": self.waste[-1].code if self.waste else "-",
            "waste_visible": waste_visible,
            "stock_count": len(self.stock),
        }

    def _visible_waste_packet_size(self) -> int:
        if not self.waste:
            return 0
        if self.waste_packets and sum(self.waste_packets) == len(self.waste):
            return self.waste_packets[-1]
        # Compatibility for tests or callers that construct a state directly.
        return min(self.draw_count, len(self.waste))

    def _normalize_waste_packets(self) -> None:
        if sum(self.waste_packets) != len(self.waste):
            self.waste_packets = [len(self.waste)] if self.waste else []

    def _pop_waste(self) -> Card:
        self._normalize_waste_packets()
        card = self.waste.pop()
        self.waste_packets[-1] -= 1
        if self.waste_packets[-1] == 0:
            self.waste_packets.pop()
        return card

    def visible_text(self) -> str:
        state = self.get_visible_state()
        foundation = " ".join(
            f"{suit}:{state['foundation'][suit]}" for suit in SUITS
        )
        tableau = "\n".join(
            f"{index}: {' '.join(pile) if pile else '-'}"
            for index, pile in enumerate(state["tableau"])
        )
        waste_line = (
            f"Waste: {state['waste']}"
            if self.draw_count == 1
            else "Waste visible: "
            + (" ".join(state["waste_visible"]) or "-")
            + f" (playable: {state['waste']})"
        )
        return (
            f"Foundation:\n{foundation}\n\nTableau:\n{tableau}\n\n"
            f"{waste_line}\nStock: {state['stock_count']}"
        )

    def visible_state_hash(self) -> str:
        """Hash only what a player can observe; safe for agent-side memory."""

        raw = json.dumps(
            self.get_visible_state(), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _can_stack_on_tableau(self, card: Card, target: list[Card]) -> bool:
        if not target:
            return card.rank == 13
        top = target[-1]
        return top.face_up and top.color != card.color and top.rank == card.rank + 1

    def _can_move_to_foundation(self, card: Card) -> bool:
        pile = self.foundations[card.suit]
        return card.rank == (pile[-1].rank + 1 if pile else 1)

    @staticmethod
    def _valid_face_up_sequence(cards: list[Card]) -> bool:
        if not cards or not all(card.face_up for card in cards):
            return False
        return all(
            upper.rank == lower.rank + 1 and upper.color != lower.color
            for upper, lower in zip(cards, cards[1:])
        )

    def get_legal_actions(self) -> list[Action]:
        actions: list[Action] = []

        if self.stock:
            actions.append(Action(ActionKind.DRAW))
        elif self.waste:
            actions.append(Action(ActionKind.RECYCLE))

        if self.waste:
            card = self.waste[-1]
            if self._can_move_to_foundation(card):
                actions.append(
                    Action(ActionKind.WASTE_TO_FOUNDATION, source="waste", target=card.suit)
                )
            for target in range(7):
                if self._can_stack_on_tableau(card, self.tableau[target]):
                    actions.append(
                        Action(ActionKind.WASTE_TO_TABLEAU, source="waste", target=target)
                    )

        for source, pile in enumerate(self.tableau):
            if not pile or not pile[-1].face_up:
                continue
            top = pile[-1]
            if self._can_move_to_foundation(top):
                actions.append(
                    Action(ActionKind.TABLEAU_TO_FOUNDATION, source=source, target=top.suit)
                )

            first_face_up = next(
                (index for index, card in enumerate(pile) if card.face_up), len(pile)
            )
            for start in range(first_face_up, len(pile)):
                sequence = pile[start:]
                if not self._valid_face_up_sequence(sequence):
                    continue
                for target in range(7):
                    if target == source:
                        continue
                    if self._can_stack_on_tableau(sequence[0], self.tableau[target]):
                        actions.append(
                            Action(
                                ActionKind.TABLEAU_TO_TABLEAU,
                                source=source,
                                target=target,
                                count=len(sequence),
                            )
                        )

        for suit in SUITS:
            pile = self.foundations[suit]
            if not pile:
                continue
            card = pile[-1]
            for target in range(7):
                if self._can_stack_on_tableau(card, self.tableau[target]):
                    actions.append(
                        Action(ActionKind.FOUNDATION_TO_TABLEAU, source=suit, target=target)
                    )

        # Stable ordering is part of the benchmark input contract.
        return actions

    def action_label(self, action: Action) -> str:
        if action.kind is ActionKind.DRAW:
            return (
                "draw one card from stock"
                if self.draw_count == 1
                else "draw up to 3 cards from stock"
            )
        if action.kind is ActionKind.RECYCLE:
            return "recycle waste into stock"
        if action.kind is ActionKind.WASTE_TO_TABLEAU:
            return f"{self.waste[-1].code}: waste -> tableau {action.target}"
        if action.kind is ActionKind.WASTE_TO_FOUNDATION:
            return f"{self.waste[-1].code}: waste -> foundation {action.target}"
        if action.kind is ActionKind.TABLEAU_TO_FOUNDATION:
            card = self.tableau[int(action.source)][-1]
            return f"{card.code}: tableau {action.source} -> foundation {action.target}"
        if action.kind is ActionKind.FOUNDATION_TO_TABLEAU:
            card = self.foundations[str(action.source)][-1]
            return f"{card.code}: foundation {action.source} -> tableau {action.target}"
        if action.kind is ActionKind.TABLEAU_TO_TABLEAU:
            pile = self.tableau[int(action.source)]
            moved = pile[-action.count :]
            cards = " ".join(card.code for card in moved)
            return (
                f"{cards}: tableau {action.source} -> tableau {action.target} "
                f"({action.count} card{'s' if action.count != 1 else ''})"
            )
        raise ValueError(f"unknown action: {action}")

    def is_legal(self, action: Action) -> bool:
        return action in self.get_legal_actions()

    def step(self, action: Action) -> StepResult:
        if not self.is_legal(action):
            raise ValueError(f"illegal action: {action.key}")

        hidden_before = self.hidden_cards
        foundation_before = self.foundation_cards

        self._apply_action(action)
        self.steps += 1
        self.assert_invariants()
        return StepResult(
            hidden_cards_revealed=hidden_before - self.hidden_cards,
            foundation_delta=self.foundation_cards - foundation_before,
            state_hash=self.state_hash(),
        )

    def _apply_action(self, action: Action) -> None:
        """Apply a known-legal action; caller owns validation and invariants."""

        if action.kind is ActionKind.DRAW:
            self._normalize_waste_packets()
            drawn = min(self.draw_count, len(self.stock))
            for _ in range(drawn):
                self.waste.append(replace(self.stock.pop(), face_up=True))
            self.waste_packets.append(drawn)
        elif action.kind is ActionKind.RECYCLE:
            self.stock = [
                replace(card, face_up=False) for card in reversed(self.waste)
            ]
            self.waste.clear()
            self.waste_packets.clear()
        elif action.kind is ActionKind.WASTE_TO_TABLEAU:
            self.tableau[int(action.target)].append(self._pop_waste())
        elif action.kind is ActionKind.WASTE_TO_FOUNDATION:
            card = self._pop_waste()
            self.foundations[card.suit].append(card)
        elif action.kind is ActionKind.TABLEAU_TO_FOUNDATION:
            source = int(action.source)
            card = self.tableau[source].pop()
            self.foundations[card.suit].append(card)
            self._flip_exposed(source)
        elif action.kind is ActionKind.FOUNDATION_TO_TABLEAU:
            card = self.foundations[str(action.source)].pop()
            self.tableau[int(action.target)].append(card)
        elif action.kind is ActionKind.TABLEAU_TO_TABLEAU:
            source = int(action.source)
            moved = self.tableau[source][-action.count :]
            del self.tableau[source][-action.count :]
            self.tableau[int(action.target)].extend(moved)
            self._flip_exposed(source)
        else:  # pragma: no cover - Enum keeps this unreachable.
            raise ValueError(f"unknown action: {action.kind}")

    def _flip_exposed(self, column: int) -> None:
        pile = self.tableau[column]
        if pile and not pile[-1].face_up:
            pile[-1] = replace(pile[-1], face_up=True)

    def is_win(self) -> bool:
        return self.foundation_cards == 52

    def is_dead_end(self) -> bool:
        """Return True only for a hard dead end with no legal action.

        Unlimited recycling makes strategic dead ends history-dependent. The
        benchmark runner detects those with a documented stagnation rule.
        """

        return not self.is_win() and not self.get_legal_actions()

    def state_hash(self) -> str:
        def encoded(card: Card) -> tuple[str, int, bool]:
            return card.suit, card.rank, card.face_up

        state = {
            "draw_count": self.draw_count,
            "tableau": [[encoded(card) for card in pile] for pile in self.tableau],
            "foundation": {
                suit: [encoded(card) for card in self.foundations[suit]] for suit in SUITS
            },
            "stock": [encoded(card) for card in self.stock],
            "waste": [encoded(card) for card in self.waste],
            "waste_packets": self.waste_packets,
        }
        raw = json.dumps(state, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def clone(self) -> "KlondikeEngine":
        return copy.deepcopy(self)

    def assert_invariants(self) -> None:
        cards = [
            *self.stock,
            *self.waste,
            *(card for pile in self.tableau for card in pile),
            *(card for pile in self.foundations.values() for card in pile),
        ]
        identities = [(card.suit, card.rank) for card in cards]
        if len(cards) != 52 or len(set(identities)) != 52:
            raise AssertionError("the state must contain each of the 52 cards exactly once")
        if any(card.face_up for card in self.stock):
            raise AssertionError("stock cards must be face down")
        if any(not card.face_up for card in self.waste):
            raise AssertionError("waste cards must be face up")
        if sum(self.waste_packets) != len(self.waste):
            raise AssertionError("waste packet sizes must cover the waste pile")
        if any(not 1 <= size <= self.draw_count for size in self.waste_packets):
            raise AssertionError("invalid waste packet size")
        for suit, pile in self.foundations.items():
            if any(not card.face_up or card.suit != suit for card in pile):
                raise AssertionError("invalid foundation identity or visibility")
            if [card.rank for card in pile] != list(range(1, len(pile) + 1)):
                raise AssertionError("foundation must be ascending from ace")
        for pile in self.tableau:
            seen_face_up = False
            for card in pile:
                if card.face_up:
                    seen_face_up = True
                elif seen_face_up:
                    raise AssertionError("a face-down card cannot cover a face-up card")
            visible = [card for card in pile if card.face_up]
            if visible and not self._valid_face_up_sequence(visible):
                raise AssertionError("face-up tableau cards must descend and alternate colors")
