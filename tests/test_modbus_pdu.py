"""Host unit tests using the actual Modbus PDU implementation from the .ino.

These tests compile only the firmware's Arduino-independent buildModbusPDU()
function with simple simulated I/O and holding-register arrays. They do NOT
test the ESP32 hardware, Ethernet stack, or serial driver.
"""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "lct_industrial_server.ino"
SIGNATURE = "int buildModbusPDU(const uint8_t *req, int reqLen, uint8_t *resp) {"


def extract_pdu_function(source: str) -> str:
    start = source.find(SIGNATURE)
    if start < 0 or source.find(SIGNATURE, start + 1) >= 0:
        raise ValueError("Expected exactly one Modbus PDU implementation")
    opening_brace = source.index("{", start)
    depth = 0
    for pos in range(opening_brace, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[start : pos + 1]
    raise ValueError("Unclosed Modbus PDU function")


class ModbusPduTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        if not shutil.which("g++"):
            raise unittest.SkipTest("g++ is required for native firmware function tests")
        pdu = extract_pdu_function(SOURCE.read_text(encoding="utf-8"))
        wrapper = """
#include <cstdint>
#include <cstring>
static bool inState[8] = {};
static bool outState[8] = {};
static uint16_t holdingRegs[128] = {};
uint16_t getReg(uint16_t addr) { return addr < 128 ? holdingRegs[addr] : 0; }
void setReg(uint16_t addr, uint16_t value) {
    if (addr < 128) holdingRegs[addr] = value;
}
""" + pdu + """
extern "C" {
void test_set_io(uint8_t diMask, uint8_t doMask) {
    for (int i = 0; i < 8; ++i) {
        inState[i] = (diMask >> i) & 1;
        outState[i] = (doMask >> i) & 1;
    }
    holdingRegs[0] = diMask;
    holdingRegs[1] = doMask;
}
int test_request(const uint8_t *req, int len, uint8_t *resp) {
    return buildModbusPDU(req, len, resp);
}
}
"""
        path = Path(cls.tempdir.name)
        (path / "modbus_pdu.cpp").write_text(wrapper, encoding="utf-8")
        subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-shared", "-fPIC",
             str(path / "modbus_pdu.cpp"), "-o", str(path / "modbus_pdu.so")],
            check=True, capture_output=True, text=True,
        )
        cls.lib = ctypes.CDLL(str(path / "modbus_pdu.so"))
        cls.lib.test_set_io.argtypes = [ctypes.c_uint8, ctypes.c_uint8]
        cls.lib.test_request.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
        ]
        cls.lib.test_request.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.lib = None
        cls.tempdir.cleanup()

    def setUp(self):
        self.lib.test_set_io(0xA5, 0x5A)

    def query(self, function, start, qty):
        request = bytes([function, start >> 8, start & 255, qty >> 8, qty & 255])
        req_buf = (ctypes.c_uint8 * len(request))(*request)
        response = (ctypes.c_uint8 * 253)()
        count = self.lib.test_request(req_buf, len(request), response)
        self.assertGreater(count, 0)
        return bytes(response[:count])

    def test_fc02_all_inputs(self):
        self.assertEqual(self.query(2, 0, 8), bytes([2, 1, 0xA5]))

    def test_fc02_single_input(self):
        self.assertEqual(self.query(2, 2, 1), bytes([2, 1, 1]))
        self.assertEqual(self.query(2, 3, 1), bytes([2, 1, 0]))

    def test_fc02_subset_packs_from_requested_start(self):
        # DI3, DI4, DI5: 1,0,0 -> bitmask 00000001
        self.assertEqual(self.query(2, 2, 3), bytes([2, 1, 1]))

    def test_fc01_all_outputs(self):
        self.assertEqual(self.query(1, 0, 8), bytes([1, 1, 0x5A]))

    def test_fc02_invalid_ranges(self):
        for start, count in [(8, 1), (7, 2), (0, 0), (0, 9)]:
            with self.subTest(start=start, count=count):
                self.assertEqual(self.query(2, start, count), bytes([0x82, 2]))

    def test_fc03_existing_register_map(self):
        self.assertEqual(self.query(3, 0, 2), bytes([3, 4, 0, 0xA5, 0, 0x5A]))

    def test_unsupported_function_exception(self):
        self.assertEqual(self.query(5, 0, 1), bytes([0x85, 1]))


if __name__ == "__main__":
    unittest.main()
