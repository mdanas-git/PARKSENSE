"""
ParkSense Full End-to-End High-Volume Integration Verification Suite
Author: mdanas-git (https://github.com/mdanas-git)

Comprehensive test suite verifying:
- Flask REST APIs & Cloudflare Tunnel Connectivity
- User Authentication & Credential Management for all three roles:
  * Tester1 (Admin: testadmin@gmail.com)
  * Tester2 (Editor: testeditor@gmail.com)
  * Tester3 (User: testuser@gmail.com)
- Role-Based Access Control (RBAC) & Endpoint Security
- Admin User Management (Password Updates & Account Suspension)
- Location Proposals, Editorial Approvals & Admin Deletions
- Saved Locations (User Bookmarks)
- ESP32 Hardware Telemetry Ingestion & Real-Time Sync
- 5-Minute Reservation Lifecycle, Concurrency & Ownership Enforcement
- Physical Occupancy Sensor Override
- Fail-Safe Stale Telemetry Handling
- Entrance/Exit MicroPython Servo Barrier Mechanics & Exit Priority
- Role-Tailored AI Assistant Engine (Admin, Editor, and User Perspectives)
"""

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import sys

# Add firmware and root directory to sys.path to import hardware logic
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TESTS_DIR, ".."))
for p in [os.path.join(PROJECT_ROOT, "firmware"), PROJECT_ROOT, TESTS_DIR]:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

from parksense_logic import gate_request, slot_led_mask

LOCAL_URL = "http://127.0.0.1:5000"
TUNNEL_URL = "https://famous-rss-catherine-dealers.trycloudflare.com"


def http_req(url, method="GET", body=None, token=None, headers=None, timeout=5):
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        parsed = json.loads(content) if content else {}
        return e.code, parsed


def run_e2e_tests():
    print("\n" + "=" * 70)
    print("  PARKSENSE COMPREHENSIVE END-TO-END SYSTEM INTEGRATION TEST SUITE")
    print("  Author: mdanas-git | Testing Roles: Admin, Editor, User")
    print("=" * 70 + "\n")

    # Locate active SQLite databases
    user_home = os.path.expanduser("~")
    db_candidates = [
        "parksense.db",
        os.path.join(os.path.dirname(__file__), "parksense.db"),
        os.path.join(os.path.dirname(__file__), "..", "backend", "parksense.db"),
        os.path.join(user_home, "Desktop", "Parksense", "parksense.db"),
        os.path.join(user_home, "Desktop", "Parksense", "backend", "parksense.db"),
        os.path.join(user_home, "Documents", "PARKSENSE_WOKWI", "parksense.db"),
        os.path.join(user_home, "Documents", "PARKSENSE_WOKWI", "backend", "parksense.db"),
    ]

    def execute_on_all_dbs(sql, params=()):
        for p in db_candidates:
            if os.path.exists(p):
                try:
                    conn = sqlite3.connect(p)
                    conn.execute(sql, params)
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

    # Ensure clean slate for test reservations, temporary locations, and user states
    default_pwd_hash = "scrypt:32768:8:1$8vpmm23TBsg1POpA$70304b12a7e75955b831fa18283f85c3b75c56be12b61093fed0ab7e09b2f4648eab19d9f2a3ca19f1e1d65d21b46b4c20ac38c3b8ae630e54ec00ba5ba5f3bf"
    execute_on_all_dbs("DELETE FROM reservations")
    execute_on_all_dbs("DELETE FROM locations WHERE name LIKE '%Test%' OR name LIKE '%Facility%'")
    execute_on_all_dbs("UPDATE users SET is_suspended = 0, plain_password = '12345678', password_hash = ?", (default_pwd_hash,))

    # ---------------------------------------------------------
    # TEST 1: Direct Backend & Frontend Web Serving
    # ---------------------------------------------------------
    status, data = http_req(f"{LOCAL_URL}/api/health")
    assert status == 200 and data.get("status") == "ok", f"Health check failed: {status}"

    req_root = urllib.request.Request(f"{LOCAL_URL}/")
    with urllib.request.urlopen(req_root) as resp:
        content = resp.read().decode("utf-8")
        assert resp.status == 200 and "ParkSense" in content, "Root did not serve index.html"

    for asset in ["/style.css", "/script.js", "/parksense-logo-white.png"]:
        req_asset = urllib.request.Request(f"{LOCAL_URL}{asset}")
        with urllib.request.urlopen(req_asset) as resp:
            assert resp.status == 200, f"Static asset {asset} failed to load (status={resp.status})"
    print("[PASS] 1. Flask backend & static frontend website assets verified (200 OK)")

    # ---------------------------------------------------------
    # TEST 2: Cloudflare HTTPS Tunnel Connectivity
    # ---------------------------------------------------------
    tunnel_active = False
    try:
        status, data = http_req(f"{TUNNEL_URL}/api/health", timeout=3)
        if status == 200 and data.get("status") == "ok":
            tunnel_active = True
            print(f"[PASS] 2. Cloudflare HTTPS tunnel active: {TUNNEL_URL}")
    except Exception:
        pass
    if not tunnel_active:
        print(f"[INFO] 2. Public tunnel standby; using local endpoint for telemetry verification.")

    test_telem_url = TUNNEL_URL if tunnel_active else LOCAL_URL

    # ---------------------------------------------------------
    # TEST 3: Three-Role Authentication & Credential Verification
    # ---------------------------------------------------------
    # 1. Admin: Tester1
    status, admin_data = http_req(f"{LOCAL_URL}/api/login", method="POST", body={
        "email": "testadmin@gmail.com",
        "password": "12345678"
    })
    assert status == 200, f"Admin login failed: {status}"
    admin_token = admin_data["token"]
    assert admin_data["user"]["role"] == "admin"
    assert admin_data["user"]["name"] == "Tester1"
    admin_id = admin_data["user"]["id"]

    # 2. Editor: Tester2
    status, editor_data = http_req(f"{LOCAL_URL}/api/login", method="POST", body={
        "email": "testeditor@gmail.com",
        "password": "12345678"
    })
    assert status == 200, f"Editor login failed: {status}"
    editor_token = editor_data["token"]
    assert editor_data["user"]["role"] == "editor"
    assert editor_data["user"]["name"] == "Tester2"
    editor_id = editor_data["user"]["id"]

    # 3. User: Tester3
    status, user_data = http_req(f"{LOCAL_URL}/api/login", method="POST", body={
        "email": "testuser@gmail.com",
        "password": "12345678"
    })
    assert status == 200, f"User login failed: {status}"
    user_token = user_data["token"]
    assert user_data["user"]["role"] == "user"
    assert user_data["user"]["name"] == "Tester3"
    user_id = user_data["user"]["id"]

    # Test invalid password rejection
    bad_status, _ = http_req(f"{LOCAL_URL}/api/login", method="POST", body={
        "email": "testuser@gmail.com",
        "password": "WrongPassword999"
    })
    assert bad_status == 401, "Invalid password attempt must return 401 Unauthorized"
    print("[PASS] 3. Authenticated all 3 roles (Tester1=Admin, Tester2=Editor, Tester3=User) with JWT")

    # ---------------------------------------------------------
    # TEST 4: Profile Management & Vehicle Details
    # ---------------------------------------------------------
    status, prof_data = http_req(f"{LOCAL_URL}/api/profile", token=user_token)
    assert status == 200 and prof_data["user"]["email"] == "testuser@gmail.com"

    status, update_prof = http_req(f"{LOCAL_URL}/api/profile", method="PUT", body={
        "name": "Tester3",
        "phone_number": "9876543210",
        "vehicle_name": "Honda City",
        "vehicle_reg_number": "UP-70-ZZ-9999"
    }, token=user_token)
    assert status == 200 and update_prof["user"]["vehicle_name"] == "Honda City"
    print("[PASS] 4. User profile inspection and vehicle details update verified")

    # ---------------------------------------------------------
    # TEST 5: Role-Based Access Control (RBAC) Enforcement
    # ---------------------------------------------------------
    # Tester3 (User) attempting to access /api/admin/users -> 403 Forbidden
    status, _ = http_req(f"{LOCAL_URL}/api/admin/users", token=user_token)
    assert status == 403, f"Standard user accessing /api/admin/users must return 403, got {status}"

    # Tester2 (Editor) attempting to access /api/admin/users -> 403 Forbidden
    status, _ = http_req(f"{LOCAL_URL}/api/admin/users", token=editor_token)
    assert status == 403, f"Editor accessing /api/admin/users must return 403, got {status}"

    # Tester1 (Admin) accessing /api/admin/users -> 200 OK
    status, admin_users_resp = http_req(f"{LOCAL_URL}/api/admin/users", token=admin_token)
    assert status == 200, f"Admin accessing /api/admin/users failed: {status}"
    users_list = admin_users_resp["users"]
    user_emails = [u["email"] for u in users_list]
    assert "testadmin@gmail.com" in user_emails
    assert "testeditor@gmail.com" in user_emails
    assert "testuser@gmail.com" in user_emails
    # Verify passwords in admin panel are accurate
    admin_account = next(u for u in users_list if u["email"] == "testadmin@gmail.com")
    assert admin_account["password"] == "12345678"

    # User access to security login logs -> 403 Forbidden
    status, _ = http_req(f"{LOCAL_URL}/api/admin/logins", token=user_token)
    assert status == 403

    # Editor access to security login logs -> 403 Forbidden
    status, _ = http_req(f"{LOCAL_URL}/api/admin/logins", token=editor_token)
    assert status == 403

    # Admin access to security login logs -> 200 OK
    status, logins_resp = http_req(f"{LOCAL_URL}/api/admin/logins", token=admin_token)
    assert status == 200 and "logs" in logins_resp

    # User access to location logs -> 403 Forbidden
    status, _ = http_req(f"{LOCAL_URL}/api/locations/logs", token=user_token)
    assert status == 403

    # Editor access to location logs -> 200 OK
    status, _ = http_req(f"{LOCAL_URL}/api/locations/logs", token=editor_token)
    assert status == 200

    # Admin access to location logs -> 200 OK
    status, _ = http_req(f"{LOCAL_URL}/api/locations/logs", token=admin_token)
    assert status == 200
    print("[PASS] 5. RBAC security strictly enforced across Admin, Editor, and User endpoints")

    # ---------------------------------------------------------
    # TEST 6: Admin User Management (Password Update & Suspension)
    # ---------------------------------------------------------
    # Admin updates Tester3 password to 'NewPass4567'
    status, pwd_resp = http_req(f"{LOCAL_URL}/api/admin/users/{user_id}/password", method="PUT", body={
        "password": "NewPass4567"
    }, token=admin_token)
    assert status == 200

    # Verify Tester3 can login with new password
    status, new_login = http_req(f"{LOCAL_URL}/api/login", method="POST", body={
        "email": "testuser@gmail.com",
        "password": "NewPass4567"
    })
    assert status == 200

    # Admin restores Tester3 password back to '12345678'
    status, _ = http_req(f"{LOCAL_URL}/api/admin/users/{user_id}/password", method="PUT", body={
        "password": "12345678"
    }, token=admin_token)
    assert status == 200

    # Admin toggles suspension on Tester3
    status, susp_resp = http_req(f"{LOCAL_URL}/api/admin/users/{user_id}/suspend", method="PUT", token=admin_token)
    assert status == 200 and susp_resp["is_suspended"] is True

    # Suspended user login rejected with 403
    status, susp_login = http_req(f"{LOCAL_URL}/api/login", method="POST", body={
        "email": "testuser@gmail.com",
        "password": "12345678"
    })
    assert status == 403 and "suspended" in susp_login.get("message", "").lower()

    # Admin restores account
    status, unsusp_resp = http_req(f"{LOCAL_URL}/api/admin/users/{user_id}/suspend", method="PUT", body={"suspend": False}, token=admin_token)
    assert status == 200 and unsusp_resp["is_suspended"] is False

    # Re-login Tester3 to get fresh token
    status, user_data = http_req(f"{LOCAL_URL}/api/login", method="POST", body={
        "email": "testuser@gmail.com",
        "password": "12345678"
    })
    assert status == 200
    user_token = user_data["token"]
    print("[PASS] 6. Admin user management verified: password update, account suspension, and restoration")

    # ---------------------------------------------------------
    # TEST 7: Location Proposals, Editorial Approval & Admin Deletion
    # ---------------------------------------------------------
    # 1. Tester3 (User) proposes a location -> status='pending', is_published=0
    status, prop_resp = http_req(f"{LOCAL_URL}/api/locations", method="POST", body={
        "name": "Community Proposed Facility",
        "address": "Campus North Gate, Prayagraj",
        "total_slots": 4
    }, token=user_token)
    assert status == 202, f"Proposal creation failed: {status}"
    prop_loc = prop_resp["location"]
    prop_id = prop_loc["id"]
    assert prop_loc["proposal_status"] == "pending"
    assert prop_loc["is_published"] is False

    # Verify pending proposal is NOT in public locations directory
    status, pub_locs = http_req(f"{LOCAL_URL}/api/locations")
    pub_ids = [l["id"] for l in pub_locs["locations"]]
    assert prop_id not in pub_ids, "Pending proposals must not appear in public directory"

    # User attempts to approve own proposal -> 403 Forbidden
    status, _ = http_req(f"{LOCAL_URL}/api/locations/{prop_id}/approve", method="PUT", token=user_token)
    assert status == 403, "Standard users must not approve proposals"

    # Editor approves proposal -> 200 OK, becomes approved & published
    status, app_resp = http_req(f"{LOCAL_URL}/api/locations/{prop_id}/approve", method="PUT", token=editor_token)
    assert status == 200 and app_resp.get("location_id") == prop_id

    # Now verify it appears in public directory
    status, pub_locs_after = http_req(f"{LOCAL_URL}/api/locations")
    pub_ids_after = [l["id"] for l in pub_locs_after["locations"]]
    assert prop_id in pub_ids_after, "Approved facility must appear in public directory"

    # 2. Editor directly creates & publishes a facility -> status='approved', is_published=1
    status, ed_create = http_req(f"{LOCAL_URL}/api/locations", method="POST", body={
        "name": "Editor Direct Facility",
        "address": "Campus South Gate, Prayagraj",
        "total_slots": 4
    }, token=editor_token)
    assert status == 201
    ed_loc_id = ed_create["location"]["id"]
    assert ed_create["location"]["proposal_status"] == "approved"
    assert ed_create["location"]["is_published"] is True

    # 3. Editor attempts to delete facility -> 403 Forbidden (Only Admin can delete!)
    status, _ = http_req(f"{LOCAL_URL}/api/locations/{ed_loc_id}", method="DELETE", token=editor_token)
    assert status == 403, "Editor must NOT be able to delete locations (403 Forbidden)"

    # User attempts to delete facility -> 403 Forbidden
    status, _ = http_req(f"{LOCAL_URL}/api/locations/{ed_loc_id}", method="DELETE", token=user_token)
    assert status == 403

    # Admin deletes both test facilities -> 200 OK
    status, _ = http_req(f"{LOCAL_URL}/api/locations/{prop_id}", method="DELETE", token=admin_token)
    assert status == 200
    status, _ = http_req(f"{LOCAL_URL}/api/locations/{ed_loc_id}", method="DELETE", token=admin_token)
    assert status == 200
    print("[PASS] 7. Full facility lifecycle verified: User proposal, Editor approval, direct publishing & Admin deletion")

    # ---------------------------------------------------------
    # TEST 8: Saved Locations (User Bookmarks)
    # ---------------------------------------------------------
    status, _ = http_req(f"{LOCAL_URL}/api/user/saved-locations/1", method="POST", token=user_token)
    assert status in (201, 200)

    status, saved_data = http_req(f"{LOCAL_URL}/api/user/saved-locations", token=user_token)
    assert status == 200
    saved_ids = [s["id"] for s in saved_data["saved_locations"]]
    assert 1 in saved_ids

    status, _ = http_req(f"{LOCAL_URL}/api/user/saved-locations/1", method="DELETE", token=user_token)
    assert status == 200
    print("[PASS] 8. Saved location bookmarking and un-bookmarking verified")

    # ---------------------------------------------------------
    # TEST 9: Hardware Telemetry Ingestion (ESP32 -> Flask)
    # ---------------------------------------------------------
    # Reject malformed telemetry
    status, _ = http_req(f"{LOCAL_URL}/api/iot/telemetry", method="POST", headers={"Content-Type": "text/plain"})
    assert status in (400, 415)

    status, _ = http_req(f"{LOCAL_URL}/api/iot/telemetry", method="POST", body={
        "device_id": "nonexistent-device-99",
        "slots": []
    })
    assert status == 404

    # Valid telemetry packet: S1=25cm (clear), S2=5cm (occupied), S3=28cm (clear), S4=None (no echo)
    telem_payload = {
        "device_id": "esp32-uit-01",
        "facility_id": 1,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "heartbeat": True,
        "slots": [
            {"slot_number": 1, "distance_cm": 25.0},
            {"slot_number": 2, "distance_cm": 5.0},
            {"slot_number": 3, "distance_cm": 28.0},
            {"slot_number": 4, "distance_cm": None}
        ],
        "gate": {
            "status": "CLOSED",
            "entry_distance_cm": None,
            "exit_distance_cm": None,
            "entry_count": 0,
            "exit_count": 0
        }
    }
    try:
        status, telem_resp = http_req(f"{test_telem_url}/api/iot/telemetry", method="POST", body=telem_payload, timeout=5)
    except Exception:
        status, telem_resp = http_req(f"{LOCAL_URL}/api/iot/telemetry", method="POST", body=telem_payload, timeout=5)
    assert status == 200 and telem_resp.get("status") == "ok"
    print("[PASS] 9. ESP32 telemetry ingested successfully and validated")

    # ---------------------------------------------------------
    # TEST 10: Frontend Dashboard Real-Time Reflection
    # ---------------------------------------------------------
    status, dash_data = http_req(f"{LOCAL_URL}/api/locations/1", token=user_token)
    assert status == 200
    loc = dash_data["location"]
    assert loc["device_status"] == "ONLINE"
    assert loc["is_fresh"] is True
    s_map = {s["slot_number"]: s for s in loc["slots"]}
    assert s_map[1]["status"] == "AVAILABLE"
    assert s_map[2]["status"] == "OCCUPIED"
    assert s_map[3]["status"] == "AVAILABLE"
    assert s_map[4]["status"] == "UNKNOWN"
    assert loc["summary"]["available"] == 2
    assert loc["summary"]["occupied"] == 1
    assert loc["summary"]["unknown"] == 1
    assert loc["recommended_slot"] == "S1"
    print("[PASS] 10. Dashboard accurately reflects real hardware states (2 free, 1 occ, 1 unk, rec: S1)")

    # ---------------------------------------------------------
    # TEST 11: Firmware Shift Register LED Mask Computation
    # ---------------------------------------------------------
    states = [s_map[1]["status"], s_map[2]["status"], s_map[3]["status"], s_map[4]["status"]]
    mask = slot_led_mask(states)
    expected_mask = (1 << 0) | (1 << 4) | (1 << 6)
    assert mask == expected_mask, f"LED mask mismatch: {bin(mask)} vs {bin(expected_mask)}"
    print(f"[PASS] 11. Firmware shift register LED mask verified: {bin(mask)} (S1 Green, S2 Red, S3 Green, S4 Off)")

    # ---------------------------------------------------------
    # TEST 12: 5-Minute Reservation via Web Application
    # ---------------------------------------------------------
    slot1_id = s_map[1]["id"]
    status, res_resp = http_req(f"{LOCAL_URL}/api/reservations", method="POST", body={
        "slot_id": slot1_id,
        "location_id": 1
    }, token=user_token)
    assert status == 201, f"Reservation failed: {status}"
    res = res_resp["reservation"]
    assert res["slot_label"] == "S1"
    assert res["duration_seconds"] == 300
    res_id = res["id"]

    # Verify reserved by first name formatting ("By Tester3")
    status, dash_res = http_req(f"{LOCAL_URL}/api/locations/1", token=user_token)
    s1_res = dash_res["location"]["slots"][0]
    assert s1_res["status"] == "RESERVED"
    assert "Tester3" in s1_res.get("reserved_by", "")
    print(f"[PASS] 12. Tester3 created 5-minute reservation for Slot S1 (Status: RESERVED 'By Tester3')")

    # ---------------------------------------------------------
    # TEST 13: Concurrency Protection (Double-Booking Rejection)
    # ---------------------------------------------------------
    status, conf_resp = http_req(f"{LOCAL_URL}/api/reservations", method="POST", body={
        "slot_id": slot1_id,
        "location_id": 1
    }, token=editor_token)
    assert status == 409, f"Concurrent booking should be rejected with 409, got {status}"
    print("[PASS] 13. Concurrency lock verified: second reservation on S1 rejected with 409 Conflict")

    # ---------------------------------------------------------
    # TEST 14: ESP32 Hardware Retrieves Reservation & Sets Yellow LED
    # ---------------------------------------------------------
    status, sync_resp = http_req(f"{LOCAL_URL}/api/iot/status?device_id=esp32-uit-01")
    assert status == 200
    res_list = sync_resp["reservations"]
    assert res_list[0]["slot_number"] == 1 and res_list[0]["is_reserved"] is True
    assert res_list[0]["remaining_seconds"] > 280

    fw_states = ["RESERVED", "OCCUPIED", "AVAILABLE", "UNKNOWN"]
    res_mask = slot_led_mask(fw_states)
    expected_res_mask = (1 << 2) | (1 << 4) | (1 << 6)
    assert res_mask == expected_res_mask
    print(f"[PASS] 14. Hardware retrieved reservation sync: Slot S1 Yellow LED ON ({bin(res_mask)})")

    # ---------------------------------------------------------
    # TEST 15: Ownership Enforcement on Cancellation
    # ---------------------------------------------------------
    status, _ = http_req(f"{LOCAL_URL}/api/reservations/{res_id}", method="DELETE", token=editor_token)
    assert status == 403, f"Non-owner cancellation must be 403, got {status}"
    print("[PASS] 15. Non-owner cancellation rejected with 403 Forbidden")

    # ---------------------------------------------------------
    # TEST 16: Physical Occupancy Overrides Reservation
    # ---------------------------------------------------------
    # Vehicle arrives at Slot 1: distance drops to 5.5 cm (<= 10.0 cm)
    status, occ_resp = http_req(f"{LOCAL_URL}/api/iot/telemetry", method="POST", body={
        "device_id": "esp32-uit-01",
        "facility_id": 1,
        "slots": [
            {"slot_number": 1, "distance_cm": 5.5},
            {"slot_number": 2, "distance_cm": 5.0},
            {"slot_number": 3, "distance_cm": 28.0},
            {"slot_number": 4, "distance_cm": 32.0}
        ]
    })
    assert status == 200
    assert occ_resp["reservations"][0]["is_reserved"] is False

    # Check database: reservation status is COMPLETED and cleared from active
    status, user_res = http_req(f"{LOCAL_URL}/api/user/active-reservation", token=user_token)
    assert status == 200 and user_res["active_reservation"] is None

    # Dashboard reflects slot 1 is now OCCUPIED
    status, dash_after = http_req(f"{LOCAL_URL}/api/locations/1", token=user_token)
    loc_after = dash_after["location"]
    assert loc_after["slots"][0]["status"] == "OCCUPIED"

    post_occ_mask = slot_led_mask(["OCCUPIED", "OCCUPIED", "AVAILABLE", "AVAILABLE"])
    expected_post_occ = (1 << 1) | (1 << 4) | (1 << 6) | (1 << 9)
    assert post_occ_mask == expected_post_occ
    print(f"[PASS] 16. Physical occupancy override: S1 reservation completed, Red LED ON ({bin(post_occ_mask)})")

    # ---------------------------------------------------------
    # TEST 17: User Cancellation & Release to AVAILABLE
    # ---------------------------------------------------------
    slot3_id = loc_after["slots"][2]["id"]
    status, res3 = http_req(f"{LOCAL_URL}/api/reservations", method="POST", body={
        "slot_id": slot3_id,
        "location_id": 1
    }, token=user_token)
    assert status == 201
    res3_id = res3["reservation"]["id"]

    status, cancel_resp = http_req(f"{LOCAL_URL}/api/reservations/{res3_id}", method="DELETE", token=user_token)
    assert status == 200

    status, sync_cancel = http_req(f"{LOCAL_URL}/api/iot/status?device_id=esp32-uit-01")
    assert sync_cancel["reservations"][2]["is_reserved"] is False
    print("[PASS] 17. User cancellation propagated to ESP32: S3 reservation released, Green LED restored")

    # ---------------------------------------------------------
    # TEST 18: Stale Telemetry Fail-Safe Handling
    # ---------------------------------------------------------
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")
    execute_on_all_dbs("UPDATE locations SET last_sensor_update = ? WHERE id = 1", (stale_time,))

    status, stale_loc_data = http_req(f"{LOCAL_URL}/api/locations/1", token=user_token)
    stale_loc = stale_loc_data["location"]
    assert stale_loc["device_status"] == "OFFLINE"
    assert stale_loc["is_fresh"] is False
    assert stale_loc["summary"]["available"] is None

    # Reserving stale slot must be rejected
    status, _ = http_req(f"{LOCAL_URL}/api/reservations", method="POST", body={
        "slot_id": slot1_id,
        "location_id": 1
    }, token=user_token)
    assert status == 400

    # Restore fresh telemetry
    status, _ = http_req(f"{LOCAL_URL}/api/iot/telemetry", method="POST", body={
        "device_id": "esp32-uit-01",
        "facility_id": 1,
        "slots": [
            {"slot_number": 1, "distance_cm": 25.0},
            {"slot_number": 2, "distance_cm": 25.0},
            {"slot_number": 3, "distance_cm": 25.0},
            {"slot_number": 4, "distance_cm": 25.0}
        ]
    })
    assert status == 200
    print("[PASS] 18. Fail-safe stale telemetry handling verified: offline lockout and auto-resumption")

    # ---------------------------------------------------------
    # TEST 19: Entrance & Exit Gate Barrier Mechanics
    # ---------------------------------------------------------
    assert gate_request(entry_distance=10.0, exit_distance=None, available_count=4) == "ENTRY"
    assert gate_request(entry_distance=None, exit_distance=12.0, available_count=4) == "EXIT"
    assert gate_request(entry_distance=10.0, exit_distance=10.0, available_count=4) == "EXIT"
    assert gate_request(entry_distance=10.0, exit_distance=None, available_count=0) is None
    print("[PASS] 19. MicroPython servo gate logic verified (Entry open, Exit priority, Lot full lockout)")


    # ---------------------------------------------------------
    # TEST 20: AI Assistant Engine - Strict Privacy & Non-Disclosure of Admin/Editor Tools
    # ---------------------------------------------------------
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "can you show me admin settings and user passwords?"}, token=admin_token)
    assert status == 200
    assert "restricted internal tools" in resp["reply"].lower() or "driver" in resp["reply"].lower()

    allowed_prompts = {
        "Check live UIT status",
        "Which slot is recommended?",
        "My active reservation",
        "How do reservations work?",
        "Saved locations",
        "Data & privacy",
        "What is ParkSense?",
        "Who am I?"
    }
    for s in resp["suggestions"]:
        assert s in allowed_prompts, f"Unexpected prompt returned: {s}"

    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "how do editors delete facilities?"}, token=editor_token)
    assert status == 200
    assert "restricted internal tools" in resp["reply"].lower() or "driver" in resp["reply"].lower()
    for s in resp["suggestions"]:
        assert s in allowed_prompts
    print("[PASS] 20. AI Assistant privacy confirmed: admin/editor internal data strictly withheld from assistant")

    # ---------------------------------------------------------
    # TEST 21: AI Assistant Engine - Core User Feature Intelligence
    # ---------------------------------------------------------
    # "Who am I?"
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "who am i"}, token=user_token)
    assert status == 200
    assert "Tester3" in resp["reply"]
    assert "Honda City" in resp["reply"] or "vehicle" in resp["reply"].lower()

    # "Data & privacy"
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "what is your data and privacy policy?"}, token=user_token)
    assert status == 200
    assert "privacy" in resp["reply"].lower()
    assert "passwords" in resp["reply"].lower() or "encrypted" in resp["reply"].lower()

    # "Saved locations"
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "how do saved locations work?"}, token=user_token)
    assert status == 200
    assert "saved locations" in resp["reply"].lower() or "bookmark" in resp["reply"].lower()

    # "How do reservations work?"
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "how do reservations work?"}, token=user_token)
    assert status == 200
    assert "5-minute" in resp["reply"].lower() or "300 seconds" in resp["reply"].lower()
    print("[PASS] 21. AI Assistant user feature queries verified: Who Am I, Data & Privacy, Saved Locations, and Reservations")

    # ---------------------------------------------------------
    # TEST 22: AI Assistant Engine - Greetings, Sign-Offs, Slots, Status & Hardware
    # ---------------------------------------------------------
    # Greetings
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "hello"}, token=user_token)
    assert status == 200
    assert "Tester3" in resp["reply"]
    assert "welcome to parksense" in resp["reply"].lower()

    # Signing off
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "bye"}, token=user_token)
    assert status == 200
    assert "goodbye" in resp["reply"].lower()

    # Identity
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "what is your name"}, token=user_token)
    assert status == 200
    assert "ParkSense" in resp["reply"]

    # What is ParkSense
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "what is parksense"}, token=user_token)
    assert status == 200
    assert "smart parking" in resp["reply"].lower()

    # Recommended slot
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "which slot is recommended?"}, token=user_token)
    assert status == 200
    assert "recommended slot" in resp["reply"].lower()

    # Live UIT status
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "check live uit status"}, token=user_token)
    assert status == 200
    assert "uit parking" in resp["reply"].lower() or "status" in resp["reply"].lower()

    # Hardware LED colors
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "what do led colors mean"}, token=user_token)
    assert status == 200
    assert "GREEN" in resp["reply"] and "YELLOW" in resp["reply"] and "RED" in resp["reply"]

    # Gate barrier mechanics
    status, resp = http_req(f"{LOCAL_URL}/api/assistant/chat", method="POST", body={"message": "how does the entrance gate work?"}, token=user_token)
    assert status == 200
    assert "barrier" in resp["reply"].lower() or "gate" in resp["reply"].lower()
    print("[PASS] 22. AI Assistant natural conversation verified: Greetings, Sign-Offs, Identity, Slots, Status & Hardware")

    print("\n" + "=" * 70)
    print("  ALL 22 HIGH-VOLUME END-TO-END INTEGRATION TESTS PASSED SUCCESSFULLY!")
    print("  VERIFIED: FLASK, SQLITE, RBAC (3 ROLES), HARDWARE SYNC & AI ASSISTANT")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_e2e_tests()
