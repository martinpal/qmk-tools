import unittest

import layer_tap as lt

LOWER_SPC = 0x4000 | (2 << 8) | 0x2C   # LT(2, KC_SPC)
RAISE_ENT = 0x4000 | (3 << 8) | 0x28   # LT(3, KC_ENT)


class TestLayerTap(unittest.TestCase):
    def setUp(self):
        self.t = lt.LayerTapTracker(term=0.2)

    def test_keycode_decoding(self):
        self.assertTrue(lt.is_layer_tap(LOWER_SPC))
        self.assertFalse(lt.is_layer_tap(0x5222))   # MO(2)
        self.assertFalse(lt.is_layer_tap(0x002C))
        self.assertEqual(lt.layer_of(LOWER_SPC), 2)
        self.assertEqual(lt.layer_of(RAISE_ENT), 3)

    def test_quick_tap_never_changes_layer(self):
        self.t.press((4, 3), LOWER_SPC, 10.0)
        self.assertEqual(self.t.tick(10.1), [])
        self.assertIsNone(self.t.release((4, 3)))
        self.assertEqual(self.t.tick(11.0), [])

    def test_hold_after_tapping_term(self):
        self.t.press((4, 3), LOWER_SPC, 10.0)
        self.assertEqual(self.t.tick(10.19), [])
        self.assertEqual(self.t.tick(10.25), [2])
        self.assertEqual(self.t.tick(10.5), [])      # reported once
        self.assertEqual(self.t.release((4, 3)), 2)

    def test_other_key_makes_it_a_hold(self):
        self.t.press((4, 3), LOWER_SPC, 10.0)
        self.assertEqual(self.t.before_press(), [2])
        self.assertEqual(self.t.release((4, 3)), 2)

    def test_release_of_other_key_does_nothing(self):
        self.t.press((4, 3), LOWER_SPC, 10.0)
        self.assertIsNone(self.t.release((1, 1)))
        self.assertIn((4, 3), self.t.pending)

    def test_two_layer_taps(self):
        self.t.press((4, 3), LOWER_SPC, 10.0)
        self.assertEqual(self.t.before_press(), [2])
        self.t.press((9, 3), RAISE_ENT, 10.1)
        self.assertEqual(self.t.tick(10.4), [3])
        self.assertEqual(self.t.release((9, 3)), 3)
        self.assertEqual(self.t.release((4, 3)), 2)

    def test_reset(self):
        self.t.press((4, 3), LOWER_SPC, 10.0)
        self.t.before_press()
        self.t.reset()
        self.assertIsNone(self.t.release((4, 3)))


if __name__ == "__main__":
    unittest.main()
