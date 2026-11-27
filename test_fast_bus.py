import unittest
from unittest.mock import Mock
from fast_bus import FastBus, packet


class FastBusTests(unittest.TestCase):
    def test_sync_write_matches_documented_example(self):
        bus = object.__new__(FastBus)
        bus.ser = Mock()
        expected = bytes.fromhex('FF FF FE 20 83 2A 06 01 00 08 00 00 E8 03 02 00 08 00 00 E8 03 03 00 08 00 00 E8 03 04 00 08 00 00 E8 03 58')
        bus.ser.write.return_value = len(expected)
        bus.sync_write(42, {s: bytes.fromhex('00 08 00 00 E8 03') for s in range(1, 5)})
        bus.ser.write.assert_called_once_with(expected)
        bus.ser.read.assert_not_called()

    def test_group_parser_handles_echo_noise_fragmentation_and_out_of_order(self):
        bus = object.__new__(FastBus)
        bus.ser = Mock()
        bus.ser.in_waiting = 1
        echo = packet(254, 0x82, bytes([56, 2, 1, 2]))
        data = b'garbage' + echo + packet(2, 0, b'\x02\x08') + packet(1, 0, b'\x01\x08')
        bus.ser.read.side_effect = [bytes([v]) for v in data]
        self.assertEqual(bus._receive([1, 2], 2), {1: (0, b'\x01\x08'), 2: (0, b'\x02\x08')})

    def test_invalid_checksum_and_wrong_id_are_not_used(self):
        bus = object.__new__(FastBus)
        bus.ser = Mock()
        bus.ser.in_waiting = 1
        corrupt = packet(1, 0, b'\x00\x00')[:-1] + b'\x00'
        data = corrupt + packet(9, 0, b'\x00\x00') + packet(1, 0, b'\x07\x08')
        bus.ser.read.side_effect = [bytes([v]) for v in data]
        self.assertEqual(bus._receive([1], 2), {1: (0, b'\x07\x08')})

    def test_partial_usb_write_is_failure(self):
        bus = object.__new__(FastBus)
        bus.ser = Mock()
        bus.ser.write.return_value = 1
        with self.assertRaises(OSError):
            bus.sync_write(42, {1: b'\0' * 6})


if __name__ == '__main__':
    unittest.main()
