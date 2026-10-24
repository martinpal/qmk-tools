import unittest

import rgb_matrix_info as info


class TestRgbMatrixInfo(unittest.TestCase):
    def setUp(self):
        self.max_v = info.load_max_brightness()
        self.names = {18: "Cycle Pinwheel", 51: "Game of Life"}

    def test_max_brightness_loaded(self):
        self.assertEqual(self.max_v, 120)

    def test_default_effect(self):
        state = {"effect": 18, "speed": 128, "hue": 200, "sat": 255, "brightness": 255}
        self.assertEqual(info.format_state(state, self.max_v, self.names),
                         "Cycle Pinwheel · speed 128 · H 200 S 255 V 120")

    def test_off(self):
        state = {"effect": 0, "speed": 1, "hue": 0, "sat": 0, "brightness": 0}
        self.assertEqual(info.format_state(state, self.max_v, self.names), "RGB off")

    def test_dimmed(self):
        state = {"effect": 1, "speed": 1, "hue": 10, "sat": 20, "brightness": 0}
        self.assertTrue(info.format_state(state, self.max_v, self.names).endswith("V 0 (dimmed)"))

    def test_unknown_effect(self):
        state = {"effect": 99, "speed": 1, "hue": 1, "sat": 2, "brightness": 255}
        self.assertTrue(info.format_state(state, self.max_v, self.names).startswith("effect 99 "))

    def test_no_names_from_firmware(self):
        state = {"effect": 18, "speed": 1, "hue": 1, "sat": 2, "brightness": 255}
        self.assertTrue(info.format_state(state, self.max_v, {}).startswith("effect 18 "))

    def test_no_answer(self):
        self.assertEqual(info.format_state(None, self.max_v, self.names), "")

    def test_real_value_scaling(self):
        self.assertEqual(info.real_value(255, 120), 120)
        self.assertEqual(info.real_value(0, 120), 0)
        self.assertEqual(info.real_value(128, 120), 60)

    def test_key_labels_rgb_matrix_and_underglow(self):
        # layer 4 keys of the RGB matrix firmware: RM_TOGG, RM_NEXT, RM_PREV, RM_HUEU, ...
        expected = {"RGB(0x42)": "RGB\u23fb", "RGB(0x43)": "RGB\u25b6", "RGB(0x44)": "RGB\u25c0",
                    "RGB(0x45)": "H+", "RGB(0x46)": "H-", "RGB(0x47)": "S+", "RGB(0x48)": "S-",
                    "RGB(0x49)": "V+", "RGB(0x4A)": "V-",
                    "RGB(0x22)": "RGB\u25c0", "RGB(0x29)": "SPD+"}  # old underglow keys still work
        for name, label in expected.items():
            self.assertEqual(info.rgb_key_label(name), label, name)

    def test_key_label_ignores_other_names(self):
        self.assertIsNone(info.rgb_key_label("RGB(0xFF)"))
        self.assertIsNone(info.rgb_key_label("RGB(0xZZ)"))
        self.assertIsNone(info.rgb_key_label("KC_A"))


if __name__ == "__main__":
    unittest.main()
