"""HC-SR04 driver for ESP32 MicroPython (Wokwi MicroPython v1.22)."""
from machine import Pin, time_pulse_us
from time import sleep_us, sleep_ms


class HCSR04:
    def __init__(self, trigger_pin, echo_pin, timeout_us=30000):
        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin
        self.trigger = Pin(trigger_pin, Pin.OUT)
        self.echo = Pin(echo_pin, Pin.IN)
        self.timeout_us = timeout_us
        self.trigger.value(0)
        sleep_ms(2)

    def distance_cm(self):
        # HC-SR04 requires a low pre-pulse, then a >=10 us trigger pulse.
        self.trigger.value(0)
        sleep_us(2)
        self.trigger.value(1)
        sleep_us(10)
        self.trigger.value(0)

        duration_us = time_pulse_us(self.echo, 1, self.timeout_us)
        # MicroPython returns a negative duration on either timeout condition.
        # Zero is not a physically useful echo and must not mean 0 cm.
        if duration_us <= 0:
            raise OSError("HC-SR04 echo timeout on TRIG GPIO{} / ECHO GPIO{}".format(
                self.trigger_pin, self.echo_pin))

        distance = duration_us / 58.0
        if distance <= 0 or distance > 500:
            raise OSError("HC-SR04 returned out-of-range distance")
        return distance
