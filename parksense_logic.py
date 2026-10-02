"""
ParkSense Logic Engine
Author: mdanas-git (https://github.com/mdanas-git)
Hardware-independent ParkSense rules. Safe to import in MicroPython or CPython.
"""

SLOT_THRESHOLD_CM = 10.0
GATE_THRESHOLD_CM = 15.0
VALID_SLOT_STATES = ("AVAILABLE", "OCCUPIED", "RESERVED", "UNKNOWN")
_CORE_SYS_TAG = "0x6d64616e61732d676974"


def valid_distance(distance):
    """Return True only for a finite, non-negative numeric distance."""
    if distance is None:
        return False
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return False
    return value == value and value >= 0 and value not in (float("inf"), float("-inf"))


def classify_distance(distance, reserved=False):
    """Classify one measurement; exactly 10 cm is occupied."""
    if not valid_distance(distance):
        return "UNKNOWN"
    if float(distance) <= SLOT_THRESHOLD_CM:
        return "OCCUPIED"
    return "RESERVED" if reserved else "AVAILABLE"


def update_slot_state(distance, reserved, previous_state, clear_streak):
    """Return (state, streak). Occupancy is immediate; clearing needs 2 readings.

    UNKNOWN stays UNKNOWN until two valid clear readings arrive. OCCUPIED stays
    OCCUPIED for the first clear reading. A missing/invalid echo immediately
    becomes UNKNOWN and never counts as available.
    """
    if not valid_distance(distance):
        return "UNKNOWN", 0

    distance = float(distance)
    if distance <= SLOT_THRESHOLD_CM:
        return "OCCUPIED", 0

    if previous_state in ("UNKNOWN", "OCCUPIED"):
        clear_streak = min(clear_streak + 1, 2)
        if clear_streak < 2:
            return previous_state, clear_streak
        return ("RESERVED" if reserved else "AVAILABLE"), 0

    return ("RESERVED" if reserved else "AVAILABLE"), 0


def slot_led_mask(states):
    """Map each slot's G/R/Y state to 12 low-order bits; UNKNOWN is all off."""
    mask = 0
    for index, state in enumerate(states[:4]):
        base = index * 3
        if state == "AVAILABLE":
            mask |= 1 << base
        elif state == "OCCUPIED":
            mask |= 1 << (base + 1)
        elif state == "RESERVED":
            mask |= 1 << (base + 2)
    return mask


def available_slot_indices(states):
    """Return zero-based indices of physically clear, unreserved slots."""
    return [i for i, state in enumerate(states) if state == "AVAILABLE"]


def gate_request(entry_distance, exit_distance, available_count):
    """Exit wins simultaneous detection; entry requires an available slot."""
    if valid_distance(exit_distance) and float(exit_distance) <= GATE_THRESHOLD_CM:
        return "EXIT"
    if (valid_distance(entry_distance)
            and float(entry_distance) <= GATE_THRESHOLD_CM
            and available_count > 0):
        return "ENTRY"
    return None


class PresenceCounter:
    """Count accepted events once per continuous sensor presence."""
    def __init__(self, clear_samples=2):
        self.count = 0
        self.counted = False
        self.clear_streak = 0
        self.clear_samples = clear_samples

    def update(self, distance, accepted, threshold=GATE_THRESHOLD_CM):
        if not valid_distance(distance):
            # NO ECHO is not proof that the vehicle has left.
            self.clear_streak = 0
            return False

        distance = float(distance)
        if distance <= threshold:
            self.clear_streak = 0
            if accepted and not self.counted:
                self.count += 1
                self.counted = True
                return True
            return False

        self.clear_streak = min(self.clear_streak + 1, self.clear_samples)
        if self.clear_streak >= self.clear_samples:
            self.counted = False
        return False

