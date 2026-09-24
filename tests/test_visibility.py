import json
import unittest

from solitaire import KlondikeEngine


class VisibilityTests(unittest.TestCase):
    def test_hidden_identities_are_redacted(self) -> None:
        engine = KlondikeEngine()
        engine.reset(37)
        hidden_codes = {
            card.code
            for pile in engine.tableau
            for card in pile
            if not card.face_up
        }
        visible = json.dumps(engine.get_visible_state(), sort_keys=True)
        for code in hidden_codes:
            self.assertNotIn(code, visible)
        self.assertEqual(visible.count("XX"), engine.hidden_cards)

    def test_visible_state_exposes_only_waste_top(self) -> None:
        engine = KlondikeEngine()
        engine.reset(4)
        draw = engine.get_legal_actions()[0]
        engine.step(draw)
        first_waste = engine.waste[-1].code
        engine.step(next(a for a in engine.get_legal_actions() if a.kind.value == "draw"))
        visible = json.dumps(engine.get_visible_state())
        self.assertNotIn(first_waste, visible)
        self.assertEqual(engine.get_visible_state()["waste"], engine.waste[-1].code)

    def test_draw_three_exposes_current_packet_but_not_older_packet(self) -> None:
        engine = KlondikeEngine(draw_count=3)
        engine.reset(4)
        engine.step(next(a for a in engine.get_legal_actions() if a.kind.value == "draw"))
        old_packet = set(engine.get_visible_state()["waste_visible"])
        engine.step(next(a for a in engine.get_legal_actions() if a.kind.value == "draw"))
        visible = engine.get_visible_state()
        self.assertEqual(len(visible["waste_visible"]), 3)
        self.assertTrue(old_packet.isdisjoint(visible["waste_visible"]))
        self.assertEqual(visible["waste"], visible["waste_visible"][-1])


if __name__ == "__main__":
    unittest.main()
