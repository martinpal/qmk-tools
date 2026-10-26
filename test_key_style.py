import unittest

import key_style as ks


class TestDecode(unittest.TestCase):
    def test_layer_keys(self):
        self.assertEqual(ks.decode_layer_key(0x5222), ("MO", 2, None))
        self.assertEqual(ks.decode_layer_key(0x5241), ("DF", 1, None))
        self.assertEqual(ks.decode_layer_key(0x5263), ("TG", 3, None))
        self.assertEqual(ks.decode_layer_key(0x4000 | (3 << 8) | 0x28), ("LT", 3, 0x28))

    def test_other_keys(self):
        for kc in (0x0004, 0x2204, 0x7C03, 0x521F, 0x5280, 0x0000):
            self.assertIsNone(ks.decode_layer_key(kc), hex(kc))

    def test_every_kind_has_a_border_style(self):
        for kind in ("MO", "LT", "TG", "DF"):
            self.assertIn(kind, ks.BORDER_STYLES)


if __name__ == "__main__":
    unittest.main()
