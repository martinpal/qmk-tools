import unittest

import key_labels


class TestKeyLabels(unittest.TestCase):
    def test_qk_labels(self):
        self.assertEqual(key_labels.short_label("QK_BOOT"), "BOOTLDR")
        self.assertEqual(key_labels.short_label("QK_REBOOT"), "REBOOT")
        self.assertEqual(key_labels.short_label("QK_CLEAR_EEPROM"), "EE CLR")
        self.assertEqual(key_labels.short_label("QK_GESC"), "ESC~")

    def test_danger_borders(self):
        self.assertEqual(key_labels.danger_border(0x7C03), (255, 0, 0))      # QK_CLEAR_EEPROM
        self.assertEqual(key_labels.danger_border(0x7C00), (255, 190, 0))    # QK_BOOT
        self.assertEqual(key_labels.danger_border(0x7C01), (255, 190, 0))    # QK_REBOOT
        self.assertIsNone(key_labels.danger_border(0x7C16))                  # QK_GESC
        self.assertIsNone(key_labels.danger_border(0x0004))                  # KC_A

    def test_unknown_unchanged(self):
        self.assertEqual(key_labels.short_label("KC_A"), "KC_A")

    def test_labels_fit_the_key(self):
        # the overlay truncates names longer than 8 characters
        for label in key_labels.QK_LABELS.values():
            self.assertLessEqual(len(label), 8, label)


if __name__ == "__main__":
    unittest.main()
