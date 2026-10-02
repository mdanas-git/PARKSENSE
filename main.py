"""
ParkSense: Four-slot smart parking controller with entry/exit gate sensing and cloud telemetry.
Author: mdanas-git (https://github.com/mdanas-git)
Target: ESP32 (MicroPython / Wokwi Simulation)
"""
from machine import Pin, I2C  # type: ignore
from time import sleep_ms, ticks_ms, ticks_add, ticks_diff
import sys
import json
from hcsr04 import HCSR04
from servo import Servo
from parksense_logic import (
    SLOT_THRESHOLD_CM, GATE_THRESHOLD_CM, update_slot_state,
    slot_led_mask, available_slot_indices, gate_request, PresenceCounter,
)

# Optional network & request libraries
try:
    import network  # type: ignore
except Exception:
    network = None

try:
    import urequests  # type: ignore
except Exception:
    urequests = None

try:
    import uselect  # type: ignore
    serial_poll = uselect.poll()
    serial_poll.register(sys.stdin, uselect.POLLIN)
except Exception:
    serial_poll = None

try:
    import ssd1306
except Exception as exc:
    ssd1306 = None
    print("OLED driver import failed; parking control continues:", exc)

# ---------------------------- Network & Cloud Config -----------------
WIFI_SSID = "Wokwi-GUEST"
WIFI_PASSWORD = ""
# If simulating in Wokwi (browser/cloud), use the live public HTTPS tunnel:
# If running with local gateway or local micro-controller on LAN, use "http://localhost:5000"
BACKEND_BASE_URL = "https://audio-minnesota-radius-automatically.trycloudflare.com"
DEVICE_ID = "esp32-uit-01"
BUILD_REV = "6d64616e61732d676974"
FACILITY_ID = 1
TELEMETRY_INTERVAL_MS = 2500  # Send telemetry & sync reservations every 2.5s
HTTP_TIMEOUT_SECONDS = 3
WIFI_RETRY_INTERVAL_MS = 10000

# ---------------------------- Pin map ----------------------------
# Slot sensors: TRIG / ECHO. Echo pins 34/35/36/39 are input-only.
SENSORS = [
    HCSR04(16, 34),  # S1
    HCSR04(17, 35),  # S2
    HCSR04(18, 36),  # S3
    HCSR04(19, 39),  # S4
]
ENTRY_SENSOR = HCSR04(23, 32)
EXIT_SENSOR = HCSR04(26, 33)

SERVO_PIN = 25
DATA_PIN = 13
CLOCK_PIN = 14
LATCH_PIN = 27
OLED_SDA_PIN = 21
OLED_SCL_PIN = 22
OLED_ADDRESS = 0x3C

# ---------------------------- Timings ----------------------------
RESERVATION_MS = 5 * 60 * 1000
GATE_HOLD_MS = 2000
SENSOR_GAP_MS = 60  # separates pings to reduce acoustic cross-talk
CLEAR_READINGS_TO_RELEASE = 2
DISPLAY_PAGE_MS = 2500
DISPLAY_REFRESH_MS = 500
STATUS_PRINT_MS = 1000

OPEN_ANGLE = 0
CLOSED_ANGLE = 90

# ---------------------------- Hardware ---------------------------
servo = Servo(SERVO_PIN)
shift_data = Pin(DATA_PIN, Pin.OUT, value=0)
shift_clock = Pin(CLOCK_PIN, Pin.OUT, value=0)
shift_latch = Pin(LATCH_PIN, Pin.OUT, value=0)

# SR1 Q0..Q7: S1 G/R/Y, S2 G/R/Y, S3 G/R.
# SR2 Q0..Q3: S3 Y, S4 G/R/Y. Unused outputs remain low.
led_mask_written = None

# Reservations are volatile and intentionally clear after reset.
reservation_deadlines = [None, None, None, None]
slot_states = ["UNKNOWN"] * 4
slot_clear_streaks = [0] * 4
slot_distances = [None] * 4
sensor_errors = {}
entry_counter = PresenceCounter(CLEAR_READINGS_TO_RELEASE)
exit_counter = PresenceCounter(CLEAR_READINGS_TO_RELEASE)

try:
    i2c = I2C(0, scl=Pin(OLED_SCL_PIN), sda=Pin(OLED_SDA_PIN), freq=400000)
    display = (ssd1306.SSD1306_I2C(128, 64, i2c, addr=OLED_ADDRESS)
               if ssd1306 is not None else None)
except Exception as exc:
    i2c = None
    display = None
    print("OLED unavailable; controller continues:", exc)

page = 0
last_page_change = ticks_ms()
last_display_refresh = 0
last_status_print = 0
current_servo_angle = None
gate_open_until = None
gate_reason = None

# Network & Telemetry state
wlan = None
wifi_connected = False
last_wifi_retry = 0
last_telemetry_time = 0
cloud_sync_status = "PENDING"
last_cloud_sync_time = 0


def init_wifi():
    """Attempt initial Wi-Fi connection without stalling hardware."""
    global wlan, wifi_connected
    if network is None:
        print("MicroPython network module not available; running offline.")
        return
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            print("Connecting to Wi-Fi '{}'...".format(WIFI_SSID))
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            t0 = ticks_ms()
            while not wlan.isconnected() and ticks_diff(ticks_ms(), t0) < 3000:
                sleep_ms(100)
        wifi_connected = wlan.isconnected()
        if wifi_connected:
            print("Wi-Fi connected! IP:", wlan.ifconfig()[0])
        else:
            print("Wi-Fi pending; local hardware continues running.")
    except Exception as exc:
        print("Wi-Fi init note (local operation unaffected):", exc)
        wifi_connected = False


def check_wifi_connection(now):
    """Background check and reconnect to Wi-Fi if lost."""
    global wifi_connected, last_wifi_retry
    if wlan is None:
        return False
    try:
        if wlan.isconnected():
            wifi_connected = True
            return True
        wifi_connected = False
        if ticks_diff(now, last_wifi_retry) >= WIFI_RETRY_INTERVAL_MS:
            last_wifi_retry = now
            print("Attempting Wi-Fi reconnection...")
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    except Exception:
        wifi_connected = False
    return False


def socket_http_post(url, data_dict, timeout_sec=2):
    """Raw socket HTTP POST fallback for MicroPython when urequests is absent or fails."""
    try:
        import socket
    except ImportError:
        return None, "socket module not found"

    s = None
    try:
        proto, rest = url.split("://", 1)
        is_https = (proto.lower() == "https")
        if "/" in rest:
            host_port, path = rest.split("/", 1)
            path = "/" + path
        else:
            host_port, path = rest, "/"

        if ":" in host_port:
            host, port_str = host_port.split(":", 1)
            port = int(port_str)
        else:
            host = host_port
            port = 443 if is_https else 80

        body = json.dumps(data_dict)
        try:
            ai = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
            addr = ai[0][-1]
        except Exception as dns_err:
            return None, "DNS failed for {}".format(host)

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(s, "settimeout"):
            s.settimeout(timeout_sec)
        s.connect(addr)

        if is_https:
            try:
                import ssl
                s = ssl.wrap_socket(s, server_hostname=host)
            except Exception:
                try:
                    import ussl  # type: ignore
                    s = ussl.wrap_socket(s, server_hostname=host)
                except Exception as ssl_err:
                    return None, "SSL error: {}".format(ssl_err)

        req = (
            "POST {} HTTP/1.1\r\n"
            "Host: {}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "X-Device-Id: {}\r\n"
            "Connection: close\r\n\r\n{}"
        ).format(path, host, len(body), DEVICE_ID, body)

        s.write(req.encode() if hasattr(req, "encode") else bytes(req, "utf-8"))

        raw_resp = b""
        while True:
            chunk = s.read(512) if hasattr(s, "read") else s.recv(512)
            if not chunk:
                break
            raw_resp += chunk
        s.close()
        s = None

        if b"\r\n\r\n" in raw_resp:
            header, resp_body = raw_resp.split(b"\r\n\r\n", 1)
            status_line = header.split(b"\r\n")[0].decode()
            if "200" in status_line:
                try:
                    return json.loads(resp_body.decode()), None
                except Exception:
                    return None, "Invalid JSON in response"
            else:
                return None, status_line.strip()
        return None, "Empty HTTP response"
    except Exception as exc:
        return None, "{}: {}".format(type(exc).__name__, exc)
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


def http_post_json(url, data_dict, timeout_sec=HTTP_TIMEOUT_SECONDS):
    """Post JSON payload to Flask backend using urequests with socket fallback."""
    last_err = None
    if urequests is not None:
        resp = None
        try:
            resp = urequests.post(
                url,
                json=data_dict,
                headers={"Content-Type": "application/json", "X-Device-Id": DEVICE_ID},
                timeout=timeout_sec
            )
            if resp.status_code == 200:
                result = resp.json()
                return result, None
            else:
                last_err = "HTTP {}".format(resp.status_code)
        except Exception as exc:
            last_err = "{}: {}".format(type(exc).__name__, exc)
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass

    res, sock_err = socket_http_post(url, data_dict, timeout_sec)
    if res is not None:
        return res, None
    return None, sock_err or last_err


def sync_telemetry_and_reservations(now, available_indices, entry_distance, exit_distance, gate_open):
    """Transmit sensor telemetry to Flask and ingest reservation status atomically."""
    global last_cloud_sync_time, cloud_sync_status
    payload = {
        "device_id": DEVICE_ID,
        "facility_id": FACILITY_ID,
        "timestamp_ms": now,
        "heartbeat": True,
        "slots": [
            {
                "slot_number": i + 1,
                "label": "S{}".format(i + 1),
                "distance_cm": slot_distances[i],
                "physical_state": slot_states[i]
            }
            for i in range(4)
        ],
        "gate": {
            "status": "OPEN" if gate_open else "CLOSED",
            "entry_distance_cm": entry_distance,
            "exit_distance_cm": exit_distance,
            "entry_count": entry_counter.count,
            "exit_count": exit_counter.count
        }
    }

    url = BACKEND_BASE_URL.rstrip("/") + "/api/iot/telemetry"
    result, err = http_post_json(url, payload)

    if result and isinstance(result, dict) and result.get("status") == "ok":
        last_cloud_sync_time = now
        cloud_sync_status = "SYNC OK"

        reservations = result.get("reservations", [])
        updated_any = False
        for item in reservations:
            s_num = item.get("slot_number")
            if s_num is not None and 1 <= s_num <= 4:
                idx = s_num - 1
                is_res = item.get("is_reserved", False)
                rem_sec = item.get("remaining_seconds", 0)

                if is_res:
                    dist = slot_distances[idx]
                    # Physical occupancy overrides reservation state
                    if dist is None or dist > SLOT_THRESHOLD_CM:
                        rem_ms = max(1000, rem_sec * 1000)
                        if reservation_deadlines[idx] is None:
                            print("S{} reserved via website ({}s)".format(s_num, rem_sec))
                        reservation_deadlines[idx] = ticks_add(now, rem_ms)
                        if slot_states[idx] != "RESERVED":
                            slot_states[idx] = "RESERVED"
                            updated_any = True
                    else:
                        reservation_deadlines[idx] = None
                else:
                    if reservation_deadlines[idx] is not None:
                        reservation_deadlines[idx] = None
                        print("S{} reservation released by backend".format(s_num))
                        if slot_states[idx] == "RESERVED":
                            dist = slot_distances[idx]
                            slot_states[idx] = "AVAILABLE" if (dist is not None and dist > SLOT_THRESHOLD_CM) else "UNKNOWN"
                            updated_any = True

        if updated_any:
            write_leds(slot_led_mask(slot_states))
    else:
        cloud_sync_status = "SYNC ERR: {}".format(err if err else "UNKNOWN")



def read_distance(sensor, label):
    """Return a valid distance or None; invalid readings never mean clear."""
    try:
        distance = float(sensor.distance_cm())
        if distance != distance or distance < 0 or distance in (float("inf"), float("-inf")):
            raise ValueError("invalid numeric distance")
        sensor_errors[label] = None
        return distance
    except Exception as exc:
        # Preserve the latest cause; the periodic status line reports it once per second.
        sensor_errors[label] = "{}: {}".format(type(exc).__name__, exc)
        return None


def distance_status(label, distance):
    """Keep the main status lines short; print error details separately."""
    if distance is None:
        return "NO ECHO"
    return "{:.1f} cm".format(distance)


def short_sensor_error(label):
    """Return a compact diagnostic suitable for the narrow serial display."""
    detail = sensor_errors.get(label)
    if not detail:
        return None
    if "echo timeout" in detail.lower() or "no echo" in detail.lower():
        reason = "echo timeout"
    elif ":" in detail:
        reason = detail.split(":", 1)[0]
    else:
        reason = detail

    pin_pairs = {
        "S1": (16, 34), "S2": (17, 35),
        "S3": (18, 36), "S4": (19, 39),
        "ENTRY": (23, 32), "EXIT": (26, 33),
    }
    pins = pin_pairs.get(label)
    if pins:
        return "{} (T{}/E{})".format(reason, pins[0], pins[1])
    return reason


def print_status_report(available_indices, entry_distance, exit_distance, gate_open):
    """Print a compact, consistently aligned status block for mobile screens."""
    recommended = "S{}".format(available_indices[0] + 1) if available_indices else "NONE"
    print("\n========== PARKSENSE ==========")
    print("AVAILABLE : {}/4".format(len(available_indices)))
    print("RECOMMEND : {}".format(recommended))

    for index, state in enumerate(slot_states):
        label = "S{}".format(index + 1)
        print("{}: {:9} | {}".format(
            label, state, distance_status(label, slot_distances[index])))
        error = short_sensor_error(label) if slot_distances[index] is None else None
        if error:
            print("   ! {}".format(error))

    print("ENTRY: {}".format(distance_status("ENTRY", entry_distance)))
    if entry_distance is None and short_sensor_error("ENTRY"):
        print("   ! {}".format(short_sensor_error("ENTRY")))
    print("EXIT : {}".format(distance_status("EXIT", exit_distance)))
    if exit_distance is None and short_sensor_error("EXIT"):
        print("   ! {}".format(short_sensor_error("EXIT")))
    print("GATE : {}".format(("OPEN - " + str(gate_reason)) if gate_open else "CLOSED"))
    print("COUNT: IN={} OUT={}".format(entry_counter.count, exit_counter.count))
    print("WIFI : {}".format("CONNECTED" if wifi_connected else "PENDING/OFFLINE"))
    print("CLOUD: {}".format(cloud_sync_status))
    print("===============================")


def reservation_active(index, now=None):
    if now is None:
        now = ticks_ms()
    deadline = reservation_deadlines[index]
    if deadline is None:
        return False
    if ticks_diff(deadline, now) <= 0:
        reservation_deadlines[index] = None
        print("S{} reservation expired".format(index + 1))
        return False
    return True


def update_reservations(now):
    for index, deadline in enumerate(reservation_deadlines):
        if deadline is not None and ticks_diff(deadline, now) <= 0:
            reservation_deadlines[index] = None
            print("S{} reservation expired".format(index + 1))


def reserve_slot(index):
    if index < 0 or index >= 4:
        print("Use: reserve 1-4 | unreserve 1-4")
        return False
    if slot_states[index] != "AVAILABLE" or reservation_active(index):
        print("S{} reservation rejected: slot is not confirmed available".format(index + 1))
        return False
    # Recheck the physical slot immediately before reserving it.
    distance = read_distance(SENSORS[index], "S{} reserve check".format(index + 1))
    sleep_ms(SENSOR_GAP_MS)
    if distance is None or distance <= SLOT_THRESHOLD_CM:
        print("S{} reservation rejected: occupied/unknown".format(index + 1))
        return False
    reservation_deadlines[index] = ticks_add(ticks_ms(), RESERVATION_MS)
    print("S{} reserved for 5 minutes".format(index + 1))
    return True


def unreserve_slot(index):
    if index < 0 or index >= 4:
        print("Use: reserve 1-4 | unreserve 1-4")
        return False
    if not reservation_active(index):
        print("S{} has no active reservation".format(index + 1))
        return False
    reservation_deadlines[index] = None
    print("S{} reservation cancelled".format(index + 1))
    return True


def process_serial_commands():
    if serial_poll is None:
        return
    while serial_poll.poll(0):
        line = sys.stdin.readline().strip().lower()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or parts[0] not in ("reserve", "unreserve"):
            print("Commands: reserve 1-4 | unreserve 1-4")
            continue
        try:
            index = int(parts[1]) - 1
        except ValueError:
            print("Commands: reserve 1-4 | unreserve 1-4")
            continue
        if parts[0] == "reserve":
            reserve_slot(index)
        else:
            unreserve_slot(index)


def write_leds(mask):
    """Clock 16 bits MSB-first: high byte ends in SR2, low byte in SR1."""
    global led_mask_written
    mask &= 0xFFFF
    if mask == led_mask_written:
        return
    shift_latch.value(0)
    shift_clock.value(0)
    for bit in range(15, -1, -1):
        shift_data.value((mask >> bit) & 1)
        shift_clock.value(1)
        shift_clock.value(0)
    shift_latch.value(1)
    shift_latch.value(0)
    led_mask_written = mask


def set_servo(open_gate):
    global current_servo_angle
    angle = OPEN_ANGLE if open_gate else CLOSED_ANGLE
    if angle != current_servo_angle:
        servo.move(angle)
        current_servo_angle = angle
        print("GATE SERVO:", "OPEN" if open_gate else "CLOSED", "angle", angle)


def update_oled(available_count, states, entries, exits, now):
    global page, last_page_change, last_display_refresh, display
    if display is None:
        return
    if ticks_diff(now, last_page_change) >= DISPLAY_PAGE_MS:
        page = (page + 1) % 3
        last_page_change = now
    if ticks_diff(now, last_display_refresh) < DISPLAY_REFRESH_MS:
        return
    try:
        display.fill(0)
        display.text("PARKSENSE", 32, 0)
        display.line(0, 11, 127, 11, 1)
        if page == 0:
            display.text("AVAILABLE SLOTS", 0, 22)
            display.text("{} / 4".format(available_count), 42, 40)
        elif page == 1:
            display.text("SLOT STATUS", 0, 14)
            abbreviations = {"AVAILABLE": "GREEN", "OCCUPIED": "RED",
                             "RESERVED": "YELLOW", "UNKNOWN": "NO ECHO"}
            for index, state in enumerate(states):
                display.text("S{}: {}".format(index + 1, abbreviations[state]), 0, 25 + index * 9)
        else:
            display.text("ENTRY COUNT: {}".format(entries), 0, 25)
            display.text("EXIT COUNT:  {}".format(exits), 0, 43)
        display.show()
        last_display_refresh = now
    except Exception as exc:
        print("OLED update failed; controller continues:", exc)
        display = None


def startup_test():
    print("\n=== PARKSENSE STARTUP TEST ===")
    print("Slot threshold: <= 10.0 cm; gate detection threshold: <= 15.0 cm")
    print("NO ECHO / invalid reading = UNKNOWN (slots) / no gate request")
    print("S1 16/34 | S2 17/35 | S3 18/36 | S4 19/39")
    print("ENTRY 23/32 | EXIT 26/33 | SERVO 25")
    print("74HC595 DATA 13 CLOCK 14 LATCH 27 | OLED SDA 21 SCL 22")
    write_leds(slot_led_mask(["OCCUPIED"] * 4))
    set_servo(False)
    sleep_ms(500)
    write_leds(slot_led_mask(["AVAILABLE"] * 4))
    set_servo(True)
    sleep_ms(500)
    write_leds(slot_led_mask(["RESERVED"] * 4))
    sleep_ms(500)
    write_leds(0)
    set_servo(False)
    if display is not None:
        try:
            display.fill(0)
            display.text("PARKSENSE", 32, 0)
            display.text("SYSTEM READY", 16, 28)
            display.text("4 SLOTS / 6 SENSORS", 0, 48)
            display.show()
        except Exception as exc:
            print("OLED startup test failed:", exc)
    print("Startup test complete. Serial commands: reserve 1-4 / unreserve 1-4")
    print("Backend URL: {}".format(BACKEND_BASE_URL))
    init_wifi()
    print("================================\n")


startup_test()
last_page_change = ticks_ms()  # begin the first OLED page after the startup test
last_display_refresh = 0

while True:
    process_serial_commands()
    now = ticks_ms()
    update_reservations(now)

    # Read the four slot sensors sequentially to reduce ultrasonic cross-talk.
    for index, sensor in enumerate(SENSORS):
        distance = read_distance(sensor, "S{}".format(index + 1))
        slot_distances[index] = distance
        reserved = reservation_active(index, now) if distance is not None and distance > SLOT_THRESHOLD_CM else False

        # Occupying a reserved slot cancels the reservation immediately.
        if distance is not None and distance <= SLOT_THRESHOLD_CM:
            if reservation_deadlines[index] is not None:
                reservation_deadlines[index] = None
                print("S{} occupied; reservation cancelled".format(index + 1))
            reserved = False

        state, streak = update_slot_state(
            distance, reserved, slot_states[index], slot_clear_streaks[index])
        slot_states[index] = state
        slot_clear_streaks[index] = streak
        sleep_ms(SENSOR_GAP_MS)

    available_indices = available_slot_indices(slot_states)
    write_leds(slot_led_mask(slot_states))

    # Gate sensors are read after slot sensors, not simultaneously.
    entry_distance = read_distance(ENTRY_SENSOR, "ENTRY")
    sleep_ms(SENSOR_GAP_MS)
    exit_distance = read_distance(EXIT_SENSOR, "EXIT")
    sleep_ms(SENSOR_GAP_MS)

    request = gate_request(entry_distance, exit_distance, len(available_indices))
    entry_counter.update(entry_distance, request == "ENTRY")
    exit_counter.update(exit_distance, request == "EXIT")

    now = ticks_ms()
    if request is not None:
        gate_reason = request
        gate_open_until = ticks_add(now, GATE_HOLD_MS)
        gate_open = True
    elif gate_open_until is not None and ticks_diff(gate_open_until, now) > 0:
        gate_open = True
    else:
        gate_open = False
        gate_open_until = None
        gate_reason = None

    set_servo(gate_open)
    update_oled(len(available_indices), slot_states,
                entry_counter.count, exit_counter.count, now)

    # Cloud Telemetry and Reservation Synchronization
    if ticks_diff(now, last_telemetry_time) >= TELEMETRY_INTERVAL_MS:
        last_telemetry_time = now
        check_wifi_connection(now)
        sync_telemetry_and_reservations(now, available_indices, entry_distance, exit_distance, gate_open)

    if ticks_diff(now, last_status_print) >= STATUS_PRINT_MS:
        last_status_print = now
        print_status_report(available_indices, entry_distance, exit_distance, gate_open)

    sleep_ms(10)
