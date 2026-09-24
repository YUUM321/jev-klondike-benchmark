import random
import unittest

from solitaire import Action, ActionKind, Card, KlondikeEngine
from solitaire.engine import SUITS


class RulesTests(unittest.TestCase):
    def test_initial_deal_shape(self) -> None:
        engine = KlondikeEngine()
        engine.reset(0)
        self.assertEqual([len(pile) for pile in engine.tableau], list(range(1, 8)))
        self.assertEqual(len(engine.stock), 24)
        self.assertEqual(engine.hidden_cards, 21)
        self.assertTrue(all(pile[-1].face_up for pile in engine.tableau))

    def test_every_generated_action_applies_and_preserves_invariants(self) -> None:
        rng = random.Random(123)
        engine = KlondikeEngine()
        engine.reset(19)
        for _ in range(250):
            actions = engine.get_legal_actions()
            self.assertTrue(actions)
            for action in actions:
                preview = engine.clone()
                preview.step(action)
                preview.assert_invariants()
            engine.step(rng.choice(actions))

    def test_illegal_action_is_rejected(self) -> None:
        engine = KlondikeEngine()
        engine.reset(0)
        with self.assertRaises(ValueError):
            engine.step(Action(ActionKind.TABLEAU_TO_TABLEAU, 0, 0))

    def test_stock_recycle_restores_draw_order(self) -> None:
        engine = KlondikeEngine()
        engine.reset(7)
        draw_order = []
        for _ in range(24):
            engine.step(Action(ActionKind.DRAW))
            draw_order.append(engine.waste[-1].code)
        self.assertFalse(engine.stock)
        engine.step(Action(ActionKind.RECYCLE))
        second_draw_order = []
        for _ in range(24):
            engine.step(Action(ActionKind.DRAW))
            second_draw_order.append(engine.waste[-1].code)
        self.assertEqual(second_draw_order, draw_order)

    def test_draw_three_reveals_packet_with_only_last_card_on_top(self) -> None:
        engine = KlondikeEngine(draw_count=3)
        engine.reset(7)
        expected = [engine.stock[-offset].code for offset in (1, 2, 3)]

        engine.step(Action(ActionKind.DRAW))

        visible = engine.get_visible_state()
        self.assertEqual(visible["draw_count"], 3)
        self.assertEqual(visible["waste_visible"], expected)
        self.assertEqual(visible["waste"], expected[-1])
        self.assertEqual(len(engine.stock), 21)
        waste_actions = [
            action
            for action in engine.get_legal_actions()
            if action.kind in {
                ActionKind.WASTE_TO_FOUNDATION,
                ActionKind.WASTE_TO_TABLEAU,
            }
        ]
        self.assertTrue(
            all(engine.action_label(action).startswith(expected[-1]) for action in waste_actions)
        )

    def test_draw_three_recycle_keeps_order_and_reforms_packets(self) -> None:
        engine = KlondikeEngine(draw_count=3)
        engine.reset(12)
        first_pass = []
        while engine.stock:
            engine.step(Action(ActionKind.DRAW))
            first_pass.append(tuple(engine.get_visible_state()["waste_visible"]))
        engine.step(Action(ActionKind.RECYCLE))
        second_pass = []
        while engine.stock:
            engine.step(Action(ActionKind.DRAW))
            second_pass.append(tuple(engine.get_visible_state()["waste_visible"]))
        self.assertEqual(second_pass, first_pass)
        self.assertEqual([len(packet) for packet in second_pass], [3] * 8)

    def test_state_hash_distinguishes_hidden_stock_order(self) -> None:
        first = KlondikeEngine()
        first.reset(8)
        second = first.clone()
        second.stock[0], second.stock[1] = second.stock[1], second.stock[0]
        self.assertEqual(first.get_visible_state(), second.get_visible_state())
        self.assertEqual(first.visible_state_hash(), second.visible_state_hash())
        self.assertNotEqual(first.state_hash(), second.state_hash())

    def test_draw_three_state_hash_includes_waste_packet_boundaries(self) -> None:
        first = KlondikeEngine(draw_count=3)
        first.reset(8)
        first.step(Action(ActionKind.DRAW))
        first.step(Action(ActionKind.DRAW))
        second = first.clone()
        second.waste_packets = [1, 2, 3]

        self.assertEqual(first.get_visible_state(), second.get_visible_state())
        self.assertEqual(first.visible_state_hash(), second.visible_state_hash())
        self.assertNotEqual(first.state_hash(), second.state_hash())

    def test_tableau_generates_each_legal_face_up_suffix(self) -> None:
        engine = KlondikeEngine()
        engine.tableau = [
            [
                Card("C", 10, True),
                Card("H", 9, True),
                Card("S", 8, True),
                Card("D", 7, True),
            ],
            [Card("S", 10, True)],
            [Card("D", 9, True)],
            [],
            [],
            [],
            [],
        ]
        engine.stock = []
        engine.waste = []
        engine.foundations = {suit: [] for suit in SUITS}
        actions = engine.get_legal_actions()
        self.assertIn(Action(ActionKind.TABLEAU_TO_TABLEAU, 0, 1, 3), actions)
        self.assertIn(Action(ActionKind.TABLEAU_TO_TABLEAU, 0, 2, 2), actions)

    def test_action_sources_are_restricted_to_exposed_top_cards(self) -> None:
        engine = KlondikeEngine()
        engine.tableau = [
            [Card("H", 7, True), Card("C", 6, True)],
            [],
            [],
            [],
            [],
            [],
            [],
        ]
        engine.stock = []
        engine.waste = [Card("D", 3, True), Card("S", 2, True)]
        engine.foundations = {
            "S": [Card("S", 1, True)],
            "H": [Card("H", rank, True) for rank in range(1, 7)],
            "D": [],
            "C": [Card("C", rank, True) for rank in range(1, 6)],
        }
        actions = engine.get_legal_actions()
        self.assertNotIn(Action(ActionKind.TABLEAU_TO_FOUNDATION, 0, "H"), actions)
        self.assertIn(Action(ActionKind.TABLEAU_TO_FOUNDATION, 0, "C"), actions)
        self.assertIn(Action(ActionKind.WASTE_TO_FOUNDATION, "waste", "S"), actions)
        self.assertNotIn(Action(ActionKind.WASTE_TO_FOUNDATION, "waste", "D"), actions)
        self.assertTrue(
            all(action.kind is not ActionKind.DRAW for action in actions)
        )

    def test_only_foundation_top_can_return_to_tableau(self) -> None:
        engine = KlondikeEngine()
        engine.tableau = [
            [Card("C", 4, True)],
            [Card("S", 5, True)],
            [],
            [],
            [],
            [],
            [],
        ]
        engine.stock = []
        engine.waste = []
        engine.foundations = {
            "H": [Card("H", rank, True) for rank in range(1, 5)],
            "D": [],
            "S": [],
            "C": [],
        }
        actions = engine.get_legal_actions()
        self.assertIn(Action(ActionKind.FOUNDATION_TO_TABLEAU, "H", 1), actions)
        self.assertNotIn(Action(ActionKind.FOUNDATION_TO_TABLEAU, "H", 0), actions)

    def test_exposed_hidden_card_flips_in_same_transition(self) -> None:
        engine = KlondikeEngine()
        revealing_action = None
        source = None
        for seed in range(100):
            engine.reset(seed)
            for action in engine.get_legal_actions():
                if action.kind not in {
                    ActionKind.TABLEAU_TO_TABLEAU,
                    ActionKind.TABLEAU_TO_FOUNDATION,
                }:
                    continue
                pile = engine.tableau[int(action.source)]
                removed = action.count if action.kind is ActionKind.TABLEAU_TO_TABLEAU else 1
                if len(pile) > removed and not pile[-removed - 1].face_up:
                    revealing_action = action
                    source = int(action.source)
                    break
            if revealing_action:
                break
        self.assertIsNotNone(revealing_action)
        hidden_before = engine.hidden_cards
        result = engine.step(revealing_action)
        self.assertEqual(engine.steps, 1)
        self.assertEqual(result.hidden_cards_revealed, 1)
        self.assertEqual(engine.hidden_cards, hidden_before - 1)
        self.assertTrue(engine.tableau[source][-1].face_up)

    def test_state_hash_is_stable_and_changes_after_move(self) -> None:
        engine = KlondikeEngine()
        engine.reset(8)
        before = engine.state_hash()
        self.assertEqual(before, engine.clone().state_hash())
        engine.step(engine.get_legal_actions()[0])
        self.assertNotEqual(before, engine.state_hash())

    def test_win_requires_all_foundations(self) -> None:
        engine = KlondikeEngine()
        engine.reset(1)
        self.assertFalse(engine.is_win())
        engine.tableau = [[] for _ in range(7)]
        engine.stock = []
        engine.waste = []
        engine.foundations = {
            suit: [Card(suit, rank, True) for rank in range(1, 14)] for suit in SUITS
        }
        engine.assert_invariants()
        self.assertTrue(engine.is_win())


if __name__ == "__main__":
    unittest.main()
