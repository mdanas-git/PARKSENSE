"""Minimal SSD1306 128x64 I2C driver using MicroPython framebuf."""
from micropython import const  # type: ignore
import framebuf  # type: ignore

_SET_CONTRAST = const(0x81)
_SET_ENTIRE_ON = const(0xA4)
_SET_NORMAL = const(0xA6)
_SET_DISPLAY = const(0xAE)
_SET_MEM_ADDR = const(0x20)
_SET_START_LINE = const(0x40)
_SET_SEG_REMAP = const(0xA1)
_SET_MUX_RATIO = const(0xA8)
_SET_COM_SCAN = const(0xC8)
_SET_DISPLAY_OFFSET = const(0xD3)
_SET_COM_PINS = const(0xDA)
_SET_CLOCK = const(0xD5)
_SET_PRECHARGE = const(0xD9)
_SET_VCOM = const(0xDB)
_SET_CHARGE_PUMP = const(0x8D)
_SET_COLUMN = const(0x21)
_SET_PAGE = const(0x22)


class SSD1306_I2C:
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.addr = addr
        self.external_vcc = external_vcc
        self.pages = height // 8
        self.buffer = bytearray(self.width * self.pages)
        self.framebuf = framebuf.FrameBuffer(
            self.buffer, self.width, self.height, framebuf.MONO_VLSB)
        self._cmd_buf = bytearray(2)
        self._data_prefix = b"\x40"
        self.init_display()

    def write_cmd(self, command):
        self._cmd_buf[0] = 0x80
        self._cmd_buf[1] = command
        self.i2c.writeto(self.addr, self._cmd_buf)

    def init_display(self):
        self.write_cmd(_SET_DISPLAY | 0x00)
        self.write_cmd(_SET_MEM_ADDR)
        self.write_cmd(0x00)
        self.write_cmd(_SET_START_LINE | 0x00)
        self.write_cmd(_SET_SEG_REMAP)
        self.write_cmd(_SET_MUX_RATIO)
        self.write_cmd(self.height - 1)
        self.write_cmd(_SET_COM_SCAN)
        self.write_cmd(_SET_DISPLAY_OFFSET)
        self.write_cmd(0x00)
        self.write_cmd(_SET_COM_PINS)
        self.write_cmd(0x12 if self.height == 64 else 0x02)
        self.write_cmd(_SET_CLOCK)
        self.write_cmd(0x80)
        self.write_cmd(_SET_PRECHARGE)
        self.write_cmd(0x22 if self.external_vcc else 0xF1)
        self.write_cmd(_SET_VCOM)
        self.write_cmd(0x30)
        self.write_cmd(_SET_CONTRAST)
        self.write_cmd(0xCF)
        self.write_cmd(_SET_ENTIRE_ON)
        self.write_cmd(_SET_NORMAL)
        self.write_cmd(_SET_CHARGE_PUMP)
        self.write_cmd(0x10 if self.external_vcc else 0x14)
        self.write_cmd(_SET_DISPLAY | 0x01)
        self.fill(0)
        self.show()

    def show(self):
        self.write_cmd(_SET_COLUMN)
        self.write_cmd(0)
        self.write_cmd(self.width - 1)
        self.write_cmd(_SET_PAGE)
        self.write_cmd(0)
        self.write_cmd(self.pages - 1)
        # I2C write length is small enough for Wokwi; prefix is SSD1306 data mode.
        self.i2c.writeto(self.addr, self._data_prefix + self.buffer)

    def fill(self, color):
        self.framebuf.fill(color)

    def pixel(self, x, y, color):
        self.framebuf.pixel(x, y, color)

    def text(self, string, x, y, color=1):
        self.framebuf.text(string, x, y, color)

    def line(self, x1, y1, x2, y2, color):
        self.framebuf.line(x1, y1, x2, y2, color)
