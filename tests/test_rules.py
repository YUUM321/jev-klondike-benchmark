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
        engine.step(Action(ActionKind.DRAW))
        self.assertEqual(engine.waste[-1].code, draw_order[0])

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
