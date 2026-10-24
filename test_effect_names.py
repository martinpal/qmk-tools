import unittest

import list_via_keyboards_usb as via

NAMES = {0: "Off", 1: "Solid Color", 18: "Cycle Pinwheel", 51: "Game of Life", 52: "PDP-11"}


class StubKeyboard(via.ViaKeyboard):
    """ViaKeyboard whose send_command answers like the firmware's 0x51 command."""

    def __init__(self, handler):
        self.handler = handler

    def send_command(self, command_id, params=None, verbose=False, allow_unhandled=False):
        packet = bytearray(32)
        packet[0] = command_id
        for i, p in enumerate(params or []):
            packet[i + 1] = p
        return self.handler(packet)


def firmware(packet):
    if packet[1] == 0:
        packet[2] = 52
    elif packet[1] == 2:
        name = NAMES.get(packet[2], "").encode()
        packet[3:3 + len(name)] = name
    return packet


class TestEffectNames(unittest.TestCase):
    def test_names_from_firmware(self):
        self.assertEqual(StubKeyboard(firmware).get_effect_names(), NAMES)

    def test_unsupported_firmware(self):
        def unhandled(packet):
            packet[0] = 0xFF
            return packet
        self.assertEqual(StubKeyboard(unhandled).get_effect_names(), {})

    def test_no_answer(self):
        self.assertEqual(StubKeyboard(lambda p: None).get_effect_names(), {})

    def test_mismatched_reply_skipped(self):
        def wrong_number(packet):
            packet = firmware(packet)
            if packet[1] == 2 and packet[2] == 18:
                packet[2] = 19
            return packet
        names = StubKeyboard(wrong_number).get_effect_names()
        self.assertNotIn(18, names)
        self.assertEqual(names[51], "Game of Life")


if __name__ == "__main__":
    unittest.main()
