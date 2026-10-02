"""
ParkSense Assistant Engine
==========================
Author: mdanas-git (https://github.com/mdanas-git)
An intelligence engine designed for smart parking facilities.
Operates without external cloud APIs or API keys.

Features:
1. Real-time Database RAG (Retrieval-Augmented Generation):
   Extracts live slot telemetry, connection state, user reservations,
   and vehicle profiles directly from SQLite (`parksense.db`).
2. Deterministic Local Rule & Intent Classifier:
   High-speed (<5ms), zero-RAM overhead, deterministic natural language matching.
3. Optional Local SLM Bridge (Ollama / llama.cpp):
   Auto-detects if a local inference server (e.g. Ollama with Qwen/Llama)
   is running on http://127.0.0.1:11434. If unavailable, seamlessly falls back
   to the built-in local engine with 0 errors.
"""

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime

# Engine Diagnostic Fingerprint: 6d64616e61732d676974
_ENGINE_CORE_REF = "0x6d64616e61732d676974"

DB_PATH = os.environ.get("PARKSENSE_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "parksense.db"))
OLLAMA_API_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_TIMEOUT_SECONDS = 1.5

_ollama_status_cache = {"available": None, "last_checked": 0.0}


def is_ollama_available():
    """Fast non-blocking check to determine if local Ollama daemon is active."""
    now = time.time()
    if _ollama_status_cache["available"] is not None and (now - _ollama_status_cache["last_checked"]) < 60.0:
        return _ollama_status_cache["available"]

    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=0.15) as resp:
            is_avail = (resp.status == 200)
    except Exception:
        is_avail = False

    _ollama_status_cache["available"] = is_avail
    _ollama_status_cache["last_checked"] = now
    return is_avail


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def is_sensor_fresh(last_sensor_update):
    if not last_sensor_update:
        return False
    try:
        dt = datetime.strptime(last_sensor_update, "%Y-%m-%d %H:%M:%S")
        return (datetime.utcnow() - dt).total_seconds() <= 30
    except Exception:
        return False


def get_system_context(user_id=None):
    """Gathers real-time context from the local SQLite database."""
    conn = get_db_connection()
    c = conn.cursor()

    # Expire stale reservations first
    c.execute("""
        UPDATE reservations
        SET status = 'EXPIRED'
        WHERE status = 'ACTIVE' AND datetime(expires_at) <= datetime('now')
    """)
    conn.commit()

    # Location UIT
    loc = c.execute("SELECT * FROM locations WHERE name = ?", ("UIT Parking",)).fetchone()
    loc_dict = dict(loc) if loc else {}

    # Slots
    slots = []
    if loc:
        rows = c.execute("""
            SELECT * FROM parking_slots
            WHERE location_id = ?
            ORDER BY slot_number ASC
        """, (loc["id"],)).fetchall()
        slots = [dict(r) for r in rows]

    # Active reservations count
    active_res = []
    if loc:
        rows = c.execute("""
            SELECT r.*, u.name as user_name
            FROM reservations r
            JOIN users u ON r.user_id = u.id
            WHERE r.location_id = ? AND r.status = 'ACTIVE'
        """, (loc["id"],)).fetchall()
        active_res = [dict(r) for r in rows]

    # Current caller's active reservation
    user_res = None
    if user_id:
        row = c.execute("""
            SELECT r.*, p.slot_number, p.label as slot_label, l.name as loc_name, l.address as loc_address
            FROM reservations r
            JOIN parking_slots p ON r.slot_id = p.id
            JOIN locations l ON r.location_id = l.id
            WHERE r.user_id = ? AND r.status = 'ACTIVE'
        """, (user_id,)).fetchone()
        if row:
            res_dict = dict(row)
            try:
                exp_dt = datetime.strptime(res_dict["expires_at"], "%Y-%m-%d %H:%M:%S")
                rem = max(0, int((exp_dt - datetime.utcnow()).total_seconds()))
                res_dict["remaining_seconds"] = rem
                res_dict["remaining_formatted"] = f"{rem // 60:02d}:{rem % 60:02d}"
            except Exception:
                res_dict["remaining_seconds"] = 0
                res_dict["remaining_formatted"] = "00:00"
            user_res = res_dict

    # Current caller user info
    user_info = None
    if user_id:
        row = c.execute("SELECT id, name, email, role, vehicle_name, vehicle_reg_number FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            user_info = dict(row)

    conn.close()

    # Slot state evaluation
    is_online = loc_dict.get("status") == "ONLINE" and is_sensor_fresh(loc_dict.get("last_sensor_update"))

    evaluated_slots = []
    avail_count = 0
    occ_count = 0
    res_count = 0
    unk_count = 0
    recommended_slot = None

    reserved_slot_ids = {r["slot_id"] for r in active_res}

    for s in slots:
        slot_label = s["label"]
        phys = s["physical_state"]

        if not is_online:
            st = "UNKNOWN"
            desc = "Sensor status not connected (device offline)"
            unk_count += 1
        elif phys == "OCCUPIED":
            st = "OCCUPIED"
            dist = s.get("distance_cm")
            desc = f"Vehicle detected ({dist:.1f} cm)" if dist is not None else "Vehicle detected"
            occ_count += 1
        elif s["id"] in reserved_slot_ids:
            st = "RESERVED"
            desc = "Slot held under active 5-minute reservation"
            res_count += 1
        elif phys == "AVAILABLE":
            st = "AVAILABLE"
            desc = "Clear and ready for parking"
            avail_count += 1
            if recommended_slot is None:
                recommended_slot = slot_label
        else:
            st = "UNKNOWN"
            desc = "Sensor reading unavailable or invalid"
            unk_count += 1

        evaluated_slots.append({
            "slot_number": s["slot_number"],
            "label": slot_label,
            "status": st,
            "description": desc,
            "distance_cm": s.get("distance_cm"),
        })

    return {
        "location": loc_dict,
        "is_online": is_online,
        "total_slots": len(slots),
        "available_count": avail_count if is_online else None,
        "occupied_count": occ_count if is_online else None,
        "reserved_count": res_count if is_online else None,
        "unknown_count": unk_count if is_online else len(slots),
        "recommended_slot": recommended_slot if is_online else None,
        "evaluated_slots": evaluated_slots,
        "user_reservation": user_res,
        "user_info": user_info,
        "last_sensor_update": loc_dict.get("last_sensor_update"),
    }


def query_local_ollama(prompt, system_prompt, model="llama3.2:1b"):
    """Attempts to query a local Ollama instance if available. Returns None if unreachable."""
    if not is_ollama_available():
        return None

    payload = {
        "model": model,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 200,
        },
    }
    try:
        req = urllib.request.Request(
            OLLAMA_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("response", "").strip()
    except Exception:
        # Offline or Ollama not running; fallback gracefully
        return None


def match_intent_and_respond(msg, context):
    """
    Deterministic Natural Language Rule & Intent Engine.
    Evaluates queries against real-time database context.
    """
    text = msg.lower().strip()
    clean = re.sub(r"[^\w\s]", "", text)

    is_online = context["is_online"]
    loc_name = context["location"].get("name", "UIT Parking")
    loc_addr = context["location"].get("address", "United Institute of Technology, Prayagraj")
    total = context["total_slots"]
    avail = context["available_count"]
    occ = context["occupied_count"]
    res = context["reserved_count"]
    unk = context["unknown_count"]
    recommended = context["recommended_slot"]
    user_res = context["user_reservation"]
    user_info = context["user_info"] or {}
    user_name = user_info.get("name") or "Driver"
    first_name = user_name.split()[0] if user_name else "Driver"
    user_email = user_info.get("email") or "Not provided"
    v_name = user_info.get("vehicle_name") or ""
    v_reg = user_info.get("vehicle_reg_number") or ""

    # 1. Admin & Editor Questions (Strict Filter: Do NOT share internal administrative data)
    is_admin_editor_query = any(k in clean for k in [
        "admin", "administrator", "editor", "admin settings", "password list", "passwords list",
        "show passwords", "all passwords", "suspend user", "delete location", "delete facility",
        "admin log", "admin logs", "user management", "manage users", "change role", "assign role"
    ])
    if is_admin_editor_query:
        return (
            f"**Notice: Driver & Parking Services Only**\n\n"
            f"ParkSense Assistant is dedicated strictly to driver parking operations. "
            f"Administrative configuration, user credentials, and editorial controls are restricted internal tools.\n\n"
            f"I can gladly assist you with live parking spot availability, 5-minute reservations, recommended spots, saved locations, and data privacy.",
            ["Check live UIT status", "Which slot is recommended?", "My active reservation", "Data & privacy"]
        )

    # 2. Reservation Cancellation Inquiries
    is_cancel_query = any(k in clean for k in [
        "cancel", "cancelling", "cancellation", "how to cancel", "how do i cancel",
        "can i cancel", "where to cancel", "abort reservation", "drop reservation",
        "release slot", "release my slot", "unreserve", "stop reservation", "delete reservation"
    ])
    if is_cancel_query:
        if user_res and user_res.get("remaining_seconds", 0) > 0:
            slot = user_res["slot_label"]
            loc = user_res["loc_name"]
            rem_fmt = user_res["remaining_formatted"]
            return (
                f"**How to Cancel Your Active Reservation:**\n\n"
                f"You currently hold an active reservation for **Slot {slot}** at **{loc}** (Time remaining: `{rem_fmt}`).\n\n"
                f"**To cancel:**\n"
                f"1. **From Any Screen:** Click the red **Cancel** button on the blue reservation banner at the top of the screen, or\n"
                f"2. **From the Dashboard:** Open **{loc}** and click **Cancel Reservation** inside your active booking card.\n\n"
                f"*Once cancelled, Slot {slot} is immediately released for other drivers, and the physical Yellow LED on the ESP32 turns off.*",
                ["My active reservation", "How do reservations work?", "Check live UIT status"]
            )
        else:
            return (
                f"**No Active Reservation to Cancel**\n\n"
                f"You currently do not have any active reservations on your account.\n\n"
                f"**Cancellation Policy:**\n"
                f"- Whenever you book an open slot, it is held exclusively for you for **5 minutes**.\n"
                f"- If your journey or plans change, you can cancel at any time to immediately release the spot for fellow drivers.\n"
                f"- If you do not arrive within 5 minutes, the spot releases automatically.",
                ["How do reservations work?", "Which slot is recommended?", "Check live UIT status"]
            )

    # 3. Active Reservation & Countdown Inquiries
    if any(k in clean for k in ["my reservation", "active reservation", "reservation status", "time left", "countdown", "expire", "did i reserve", "booked slot", "check reservation", "my slot"]):
        if user_res:
            slot = user_res["slot_label"]
            rem_fmt = user_res["remaining_formatted"]
            rem_sec = user_res["remaining_seconds"]
            loc = user_res["loc_name"]

            if rem_sec > 0:
                return (
                    f"**Active Reservation Found!**\n\n"
                    f"- **Slot:** `{slot}` at **{loc}**\n"
                    f"- **Time Remaining:** `{rem_fmt}` ({rem_sec} seconds)\n"
                    f"- **Expires At:** `{user_res['expires_at']}`\n\n"
                    f"Proceed to slot `{slot}` and park your vehicle. Once the ultrasonic sensor detects your car (distance <= 10 cm), your reservation completes automatically!",
                    ["How do reservations work?", "Check live UIT status", "Saved locations"]
                )
            else:
                return (
                    f"Your reservation for **Slot {slot}** has expired. You can reserve a new spot from the dashboard when slots are available.",
                    ["Which slot is recommended?", "Check live UIT status", "How do reservations work?"]
                )
        else:
            return (
                f"You currently have **no active reservations**.\n\n"
                f"**To reserve a spot:**\n"
                f"1. Open **UIT Parking** from the Locations view.\n"
                f"2. Click on any clear green slot and select **Reserve Slot**.\n"
                f"3. You will have **5 minutes** to arrive and park.",
                ["Which slot is recommended?", "How do reservations work?", "Check live UIT status"]
            )

    # 4. How Reservations Work & 5-Minute Timer Rules
    if any(k in clean for k in ["how do reservations work", "how to reserve", "how do i reserve", "reserve slot", "5 min", "five min", "reservation rules", "reservation rule", "reservation policy", "booking rules", "booking duration", "how long is reservation", "hold duration", "fair use"]):
        return (
            f"**How ParkSense 5-Minute Reservations Work:**\n\n"
            f"1. **Strict 5-Minute Window:** Each reservation holds the slot exclusively for **300 seconds (5 minutes)**.\n"
            f"2. **Physical Occupancy Auto-Complete:** When you drive into the parking bay, the ultrasonic sensor detects your vehicle and automatically marks your reservation completed.\n"
            f"3. **Automatic Release:** If you don't arrive within 5 minutes, the reservation expires and the spot is released to other drivers.\n"
            f"4. **Easy Cancellation:** You can cancel at any time before arriving with one click.\n"
            f"5. **Fair Use:** Each driver account may hold at most one active reservation at a time.",
            ["My active reservation", "Which slot is recommended?", "Check live UIT status"]
        )

    # 5. User Identity: "Who am I?"
    if any(k in clean for k in ["who am i", "my account", "my profile", "my vehicle", "my car", "who is logged in", "user info", "my details"]):
        veh_str = f"{v_name} ({v_reg})" if v_name and v_reg else (v_name or v_reg or "No vehicle registered yet")
        return (
            f"**Your ParkSense Driver Profile:**\n\n"
            f"- **Driver Name:** {user_name}\n"
            f"- **Email Address:** `{user_email}`\n"
            f"- **Vehicle Profile:** {veh_str}\n\n"
            f"You can update your vehicle details or change your password anytime under the **Profile** tab.",
            ["Data & privacy", "My active reservation", "Which slot is recommended?"]
        )

    # 6. Specific Slot Inquiries (S1, S2, S3, S4)
    slot_match = re.search(r"\b(s[1-4]|slot\s*[1-4])\b", clean)
    if slot_match:
        target_str = slot_match.group(1).replace("slot", "").strip()
        target_num = int(target_str.replace("s", ""))
        matched_slot = next((s for s in context["evaluated_slots"] if s["slot_number"] == target_num), None)

        if matched_slot:
            status = matched_slot["status"]
            desc = matched_slot["description"]
            badge_icon = {
                "AVAILABLE": "[AVAILABLE]",
                "OCCUPIED": "[OCCUPIED]",
                "RESERVED": "[RESERVED]",
                "UNKNOWN": "[UNKNOWN / OFFLINE]",
            }.get(status, status)

            resp = (
                f"**Status for Slot {matched_slot['label']}:**\n\n"
                f"- **Condition:** **{badge_icon}**\n"
                f"- **Sensor ID:** `S{target_num}`\n"
                f"- **Details:** {desc}\n"
            )
            if not is_online:
                resp += "\n*Note: Device is currently offline or sensor readings are pending fresh telemetry.*"
            elif status == "AVAILABLE":
                resp += "\n*This slot is clear and ready to be reserved for 5 minutes!*"
            return resp, ["Which slot is recommended?", "Check live UIT status", "How do reservations work?"]

    # 7. Recommended Slot Inquiries
    if any(k in clean for k in ["recommended", "best slot", "where should i park", "where to park", "which slot", "find slot", "suggest slot"]):
        if not is_online:
            return (
                f"**Recommended Slot: Not Available**\n\n"
                f"The ESP32 parking sensors at **{loc_name}** are currently offline or connection is pending.\n"
                f"ParkSense never recommends unverified slots.",
                ["Check live UIT status", "What is ParkSense?", "Data & privacy"]
            )
        elif recommended:
            return (
                f"**Recommended Slot: {recommended}**\n\n"
                f"Slot **{recommended}** is physically clear with no active reservations and confirmed fresh ultrasonic telemetry.\n"
                f"You can reserve it directly from the UIT Parking Dashboard for 5 minutes.",
                ["Check live UIT status", "How do reservations work?", "My active reservation"]
            )
        else:
            return (
                f"**Recommended Slot: None Available**\n\n"
                f"All slots at **{loc_name}** are currently occupied or reserved. Please check back shortly as reservations expire within 5 minutes.",
                ["Check live UIT status", "How do reservations work?", "Saved locations"]
            )

    # 8. Live Availability & Facility Status
    if any(k in clean for k in ["available", "free spot", "free slot", "how many", "status", "spots left", "vacancy", "uit parking", "check status", "overview", "check all slots", "all slots", "show slots", "list slots"]):
        if not is_online:
            return (
                f"**{loc_name} -- System Offline**\n\n"
                f"- **Location:** {loc_addr}\n"
                f"- **Device Connection:** `OFFLINE / PENDING`\n"
                f"- **Total Slots:** `{total}`\n"
                f"- **Available:** `-- (Unavailable)`\n"
                f"- **Occupied:** `-- (Unavailable)`\n"
                f"- **Reserved:** `-- (Unavailable)`\n"
                f"- **Unknown:** `{unk}`\n\n"
                f"Live sensor readings will display automatically once the ESP32 hardware or Wokwi simulator streams fresh telemetry to `/api/iot/telemetry`.",
                ["Check live UIT status", "What is ParkSense?", "Data & privacy"]
            )
        else:
            slots_summary = "\n".join([f"- **{s['label']}:** [{s['status']}] ({s['description']})" for s in context["evaluated_slots"]])
            return (
                f"**Live Status for {loc_name}:**\n\n"
                f"- **System Status:** `ONLINE (Telemetry Fresh)`\n"
                f"- **Total Slots:** `{total}`\n"
                f"- **Available:** `[AVAILABLE] {avail}`\n"
                f"- **Occupied:** `[OCCUPIED] {occ}`\n"
                f"- **Reserved:** `[RESERVED] {res}`\n"
                f"- **Recommended Slot:** `{recommended or 'None'}`\n\n"
                f"**Slot Breakdown:**\n{slots_summary}",
                ["Which slot is recommended?", "My active reservation", "How do reservations work?"]
            )

    # 9. Locations & Saved Locations (Favorites)
    if any(k in clean for k in ["location", "locations", "saved locations", "facility", "facilities", "favorite", "favorites", "bookmark", "how to save", "save location", "directory", "propose location"]):
        return (
            f"**ParkSense Parking Locations & Favorites:**\n\n"
            f"- **Browsing Facilities:** Open the **Locations** directory to view all monitored facilities (like **UIT Parking** at United Institute of Technology, featuring live IoT sensors and 4 monitored slots).\n"
            f"- **Saved Locations:** Click the bookmark icon on any facility card to save it under your **Saved Locations** view for instant 1-click access.\n"
            f"- **Propose a Location:** Need a new parking area monitored? Click **Add New Location** and submit a facility proposal for operator review.",
            ["Saved locations", "Check live UIT status", "Which slot is recommended?"]
        )

    # 10. Data & Privacy / Security
    if any(k in clean for k in ["data", "privacy", "security", "is my data safe", "what data", "protect", "safe", "gdpr", "private"]):
        return (
            f"**ParkSense Data & Privacy Commitment:**\n\n"
            f"Your privacy and account safety are built into ParkSense:\n\n"
            f"1. **Minimal Account Data:** We store only essential driver details (name, email, and optional vehicle profile) to enable your parking reservations.\n"
            f"2. **Encrypted Passwords:** Passwords are protected using strong cryptographic one-way hashing algorithms.\n"
            f"3. **Secure Sessions:** All communication is secured using cryptographically signed, expiring JWT authentication tokens.\n"
            f"4. **Distance Telemetry Only:** IoT sensors transmit only physical vehicle distance readings (cm)—no cameras, facial recognition, or license-plate tracking are used.\n"
            f"5. **Zero Third-Party Sharing:** Your data is kept securely on the local ParkSense platform and is never shared, tracked, or sold.",
            ["Who am I?", "What is ParkSense?", "Check live UIT status"]
        )

    # 11. What is ParkSense?
    if any(k in clean for k in ["what is parksense", "what does parksense do", "about parksense", "tell me about parksense", "explain parksense"]):
        return (
            f"**What is ParkSense?**\n\n"
            f"**ParkSense** is an intelligent IoT smart parking management system designed to make finding and holding parking effortless.\n\n"
            f"**Key Driver Features:**\n"
            f"- **Live Space Availability:** Ultrasonic sensors continuously monitor each parking bay (`S1`–`S4`) in real time.\n"
            f"- **5-Minute Cloud Reservations:** Reserve a confirmed clear spot online before arriving; it is held for you for 300 seconds.\n"
            f"- **Automatic Arrival Completion:** When you park in your bay, the sensor detects your vehicle and automatically marks the reservation completed.\n"
            f"- **Automated Servo Barrier:** An SG90 servo motor automatically manages entry and exit traffic with lot-full lockout.\n"
            f"- **LED Status Indicators:** Green (Available), Red (Occupied), and Yellow (Reserved) lights at each parking bay.",
            ["Check live UIT status", "Which slot is recommended?", "How do reservations work?"]
        )

    # 12. Assistant Identity / Name
    if any(k in clean for k in ["your name", "who are you", "what are you called", "whats your name", "what is your name"]):
        return (
            f"My name is **ParkSense** (ParkSense Assistant)!\n\n"
            f"I am your dedicated smart parking assistant. I can help you monitor live parking spots, track your 5-minute reservations, find recommended clear spaces, and navigate facility features.",
            ["What is ParkSense?", "Who am I?", "Check live UIT status"]
        )

    # 13. LED Indicator Colors & Meanings
    led_keywords = ["led", "leds", "color", "colors", "light", "lights", "green", "red", "yellow", "amber", "indicator"]
    if any(re.search(rf"\b{re.escape(w)}\b", clean) for w in led_keywords):
        return (
            f"**ParkSense Hardware LED Color Legend:**\n\n"
            f"- **GREEN LED:** Slot is physically **AVAILABLE** (clear and unreserved).\n"
            f"- **RED LED:** Slot is **OCCUPIED** (ultrasonic sensor detected a vehicle within 10 cm).\n"
            f"- **YELLOW / AMBER LED:** Slot is **RESERVED** (a user booked it for 5 minutes).\n"
            f"- **OFF / SLATE:** Slot is **UNKNOWN / OFFLINE** (device disconnected or stale readings).\n\n"
            f"These LEDs are driven directly by ESP32 shift registers on the parking prototype.",
            ["Check live UIT status", "Which slot is recommended?", "How do reservations work?"]
        )

    # 14. Entrance Gate & Servo Mechanics
    if any(k in clean for k in ["gate", "servo", "barrier", "entry", "entrance", "exit", "door", "arm"]):
        return (
            f"**Automated Gate Barrier Operation:**\n\n"
            f"The entrance/exit barrier is powered by a MicroPython servo motor:\n"
            f"1. **Entry Rule:** When a car arrives at the entry sensor (distance < 15 cm), the barrier opens to 90 degrees **only if** at least one slot is AVAILABLE.\n"
            f"2. **Exit Priority:** If an exiting vehicle is detected, exit traffic takes immediate priority.\n"
            f"3. **Lot Full Lockout:** If all slots are occupied or reserved, the barrier remains closed (0 degrees) and displays `LOT FULL`.",
            ["Check live UIT status", "What is ParkSense?", "How do reservations work?"]
        )

    # 15. Ultrasonic Sensors & Detection
    if any(k in clean for k in ["sensor", "sensors", "ultrasonic", "hcsr04", "hardware", "esp32", "distance", "detect"]):
        return (
            f"**ESP32 Sensor & Detection Specifications:**\n\n"
            f"- **Ultrasonic Sensors:** HC-SR04 sensors measure the distance to vehicles in centimeters.\n"
            f"- **Occupancy Threshold:** Distance `<= 10.0 cm` = OCCUPIED; `> 10.0 cm` = CLEAR.\n"
            f"- **Noise Filter:** Requires 2 consecutive matching readings before changing state to prevent flickering.\n"
            f"- **OLED Display:** Shows live free-slot counts on-site at the facility entrance.",
            ["Check live UIT status", "Which slot is recommended?", "What is ParkSense?"]
        )

    # 16. Profile & Account Settings
    if any(k in clean for k in ["profile", "change password", "update vehicle", "license plate", "car"]):
        return (
            f"**Driver Profile & Vehicle Management:**\n\n"
            f"You can manage your account under the **Profile** tab:\n"
            f"- **Vehicle Details:** Save your vehicle model and registration number for streamlined parking records.\n"
            f"- **Security:** Change your login password anytime under the Change Password section.",
            ["Who am I?", "Data & privacy", "Check live UIT status"]
        )

    # 17. Greetings (Hi, Hello, Hey)
    if any(re.search(rf"\b{re.escape(w)}\b", clean) for w in ["hi", "hello", "hey", "greetings", "good morning", "good afternoon", "good evening"]):
        return (
            f"**Hello {first_name}! Welcome to ParkSense.**\n\n"
            f"I am your **ParkSense Assistant**. How can I help you find or reserve a parking spot today?\n\n"
            f"Feel free to ask about live slot availability, your reservations, saved locations, or data privacy.",
            ["Check live UIT status", "Which slot is recommended?", "My active reservation", "Data & privacy"]
        )

    # 18. Farewell / Signing Off Messages
    if any(re.search(rf"\b{re.escape(w)}\b", clean) for w in ["bye", "goodbye", "see you", "cya", "exit", "quit", "good night", "take care", "have a good day"]):
        return (
            f"**Goodbye {first_name}!** Have a safe and pleasant drive. Feel free to ask anytime you need parking updates.",
            ["Check live UIT status", "My active reservation"]
        )

    # 19. Politeness / Gratitude
    if any(re.search(rf"\b{re.escape(w)}\b", clean) for w in ["thank you", "thanks", "thx", "appreciate"]):
        return (
            f"You're very welcome, {first_name}! Let me know if you need help finding or reserving a spot.",
            ["Which slot is recommended?", "Check live UIT status"]
        )

    # 20. Offline / System Connection Status
    if any(k in clean for k in ["why offline", "offline", "online", "connected", "connection", "sensor update", "stale"]):
        if not is_online:
            return (
                f"**Why is the system currently showing Offline?**\n\n"
                f"ParkSense enforces a strict 30-second data freshness guarantee:\n"
                f"1. Telemetry is considered fresh only if an update occurred within the last **30 seconds**.\n"
                f"2. UIT Parking will automatically switch to **ONLINE** as soon as the ESP32 hardware or Wokwi simulator sends real distance readings to `/api/iot/telemetry`.\n"
                f"3. We never display fake green slots when hardware is disconnected.",
                ["Check live UIT status", "What is ParkSense?"]
            )
        else:
            last = context.get("last_sensor_update", "Just now")
            return (
                f"**System Status: Healthy & Online!**\n\n"
                f"The ESP32 controller (`esp32-uit-01`) is connected and streaming live ultrasonic readings.\n"
                f"- **Last Sensor Update:** `{last}` UTC",
                ["Check live UIT status", "Which slot is recommended?"]
            )

    # 21. Fallback response for unhandled questions
    return (
        f"I understood your question, but I am specifically tuned for **ParkSense smart parking operations**.\n\n"
        f"You can ask me general questions about live slot availability, 5-minute reservations, saved locations, data privacy, or hardware indicators.",
        ["Check live UIT status", "Which slot is recommended?", "My active reservation", "Data & privacy"]
    )


def process_assistant_query(user_id, message_text):
    """
    Main entry point for assistant queries.
    Retrieves live context, attempts local SLM if active, or executes local deterministic engine.
    """
    if not message_text or not message_text.strip():
        return {
            "reply": "Please enter a question or click one of the suggested prompts below.",
            "suggestions": ["Check live UIT status", "Which slot is recommended?", "My active reservation", "Data & privacy"],
            "engine": "local-rule-engine",
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # 1. Fetch real-time context from SQLite
    context = get_system_context(user_id)

    # 2. Check if local Ollama SLM is running with prompt augmentation
    system_prompt = (
        f"You are ParkSense Assistant, an offline AI assistant for smart parking. "
        f"Answer clearly and concisely for drivers. System context: Location={context['location'].get('name')}, "
        f"DeviceOnline={context['is_online']}, AvailableSlots={context['available_count']}, "
        f"OccupiedSlots={context['occupied_count']}, ReservedSlots={context['reserved_count']}, "
        f"UserReservation={context['user_reservation']}."
    )
    ollama_reply = query_local_ollama(message_text, system_prompt)

    if ollama_reply:
        return {
            "reply": ollama_reply,
            "suggestions": ["Check live UIT status", "Which slot is recommended?", "My active reservation", "Data & privacy"],
            "engine": "local-ollama-slm",
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # 3. Built-in Deterministic Local Engine (Primary Offline Engine)
    reply, suggestions = match_intent_and_respond(message_text, context)

    return {
        "reply": reply,
        "suggestions": suggestions,
        "engine": "local-rule-engine",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
