import os
import unittest

import habit_sounds as hs

SOFLE_ROWS = 10


class TestClassify(unittest.TestCase):
    def classify(self, row, col, layer, keycode):
        return hs.classify(row, col, layer, keycode, SOFLE_ROWS, (0, 2, 3))

    def test_old_pinky_keys(self):
        self.assertEqual(self.classify(1, 0, 0, hs.QK_GESC), hs.OLD_KEY)    # base Esc/~
        self.assertEqual(self.classify(1, 0, 3, hs.KC_ESC), hs.OLD_KEY)     # raise Esc
        self.assertEqual(self.classify(1, 0, 2, hs.KC_GRV), hs.OLD_KEY)     # lower: grave where Esc/~ used to be
        self.assertEqual(self.classify(7, 0, 3, hs.KC_BSPC), hs.OLD_KEY)    # raise Backspace, right pinky
        self.assertEqual(self.classify(7, 1, 3, hs.KC_DEL), hs.OLD_KEY)     # raise Delete, right ring/pinky column

    def test_same_key_elsewhere_is_fine(self):
        self.assertIsNone(self.classify(7, 3, 3, hs.KC_BSPC))               # not a pinky column
        self.assertIsNone(self.classify(4, 2, 0, hs.QK_GESC))               # thumb row
        self.assertIsNone(self.classify(9, 2, 3, hs.KC_BSPC))               # right thumb
        self.assertIsNone(self.classify(4, 2, 2, hs.KC_GRV))                # thumb grave
        self.assertIsNone(self.classify(7, 0, 0, 0x0034))                   # base apostrophe

    def test_top_row(self):
        self.assertEqual(self.classify(0, 3, 0, 0x001E), hs.TOP_ROW)        # left, base
        self.assertEqual(self.classify(5, 2, 2, 0x001F), hs.TOP_ROW)        # right half stored from row 5, lower
        self.assertEqual(self.classify(0, 4, 3, 0x0001), hs.TOP_ROW)        # raise, transparent falls through
        self.assertIsNone(self.classify(0, 3, 1, 0x001E))                   # game layer
        self.assertIsNone(self.classify(0, 3, 4, 0x001E))                   # adjust layer
        self.assertIsNone(self.classify(0, 3, 2, 0x0000))                   # KC_NO

    def test_old_key_beats_top_row(self):
        self.assertEqual(self.classify(0, 0, 0, hs.KC_ESC), hs.OLD_KEY)

    def test_corne_thumb_row(self):
        self.assertIsNone(hs.classify(3, 0, 0, hs.KC_ESC, 8, (0, 2, 3)))
        self.assertEqual(hs.classify(0, 1, 0, 0x001E, 8, (0, 2, 3)), hs.TOP_ROW)


class TestCoach(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.played = []
        self.coach = hs.HabitCoach(SOFLE_ROWS, cooldown=5.0, player=self.played.append, clock=lambda: self.now)

    def tearDown(self):
        self.coach.close()

    def test_sound_files_exist(self):
        for path in self.coach.files.values():
            self.assertGreater(os.path.getsize(path), 1000)

    def test_cooldown_per_kind(self):
        self.assertEqual(self.coach.on_press(7, 0, 3, hs.KC_BSPC), hs.OLD_KEY)
        self.now += 4.9
        self.assertIsNone(self.coach.on_press(7, 0, 3, hs.KC_BSPC))
        self.assertEqual(self.coach.on_press(0, 3, 0, 0x001E), hs.TOP_ROW)  # other kind is independent
        self.now += 0.2
        self.assertEqual(self.coach.on_press(7, 0, 3, hs.KC_BSPC), hs.OLD_KEY)
        self.assertEqual(len(self.played), 3)

    def test_ignored_presses_do_not_start_cooldown(self):
        self.assertIsNone(self.coach.on_press(2, 3, 0, 0x0004))
        self.assertEqual(self.coach.on_press(1, 0, 0, hs.QK_GESC), hs.OLD_KEY)


class TestPlayerAttempts(unittest.TestCase):
    def test_user_process_plays_directly(self):
        attempts = hs.player_attempts("/x.wav", environ={}, euid=1000)
        self.assertEqual([a[0] for a in attempts], ["direct"])
        self.assertEqual(attempts[0][1][-1], "/x.wav")

    def test_root_under_sudo_targets_the_users_session(self):
        attempts = hs.player_attempts("/x.wav", environ={"SUDO_UID": "1000"}, euid=0)
        direct, via_sudo = attempts
        self.assertEqual(direct[2]["PULSE_SERVER"], "unix:/run/user/1000/pulse/native")
        self.assertEqual(direct[2]["XDG_RUNTIME_DIR"], "/run/user/1000")
        self.assertEqual(via_sudo[1][:4], ["sudo", "-n", "-u", "#1000"])
        self.assertEqual(via_sudo[1][-1], "/x.wav")

    def test_root_without_sudo_uid_plays_directly(self):
        self.assertEqual([a[0] for a in hs.player_attempts("/x.wav", environ={}, euid=0)], ["direct"])


if __name__ == "__main__":
    unittest.main()
