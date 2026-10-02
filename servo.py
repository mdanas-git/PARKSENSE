"""50 Hz hobby-servo driver for ESP32 MicroPython's 10-bit PWM API."""
from machine import Pin, PWM  # type: ignore


class Servo:
    def __init__(self, pin, min_us=500, max_us=2500, frequency=50):
        self.pin_number = pin
        self.min_us = min_us
        self.max_us = max_us
        self.frequency = frequency
        self.period_us = 1000000 // frequency
        self.pwm = PWM(Pin(pin), freq=frequency, duty=0)
        self.angle = None

    def move(self, angle):
        angle = max(0, min(180, int(angle)))
        pulse_us = self.min_us + ((self.max_us - self.min_us) * angle // 180)
        duty = int((pulse_us * 1023) / self.period_us)
        self.pwm.duty(duty)
        self.angle = angle

    def deinit(self):
        self.pwm.duty(0)
        self.pwm.deinit()
