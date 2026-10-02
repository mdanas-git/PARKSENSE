"""
ParkSense - Smart IoT Parking Management Backend
Author: mdanas-git (https://github.com/mdanas-git)
Flask RESTful API, SQLite DB, JWT Authentication, and IoT Telemetry
"""

import os
import sqlite3
import time
from datetime import datetime, timedelta

import jwt  # type: ignore
from flask import Flask, jsonify, request, send_from_directory  # type: ignore
from flask_cors import CORS  # type: ignore
from werkzeug.security import check_password_hash, generate_password_hash  # type: ignore

from assistant_engine import process_assistant_query

# Core System Build Fingerprint: 6d64616e61732d676974
CORE_BUILD_ID = "6d64616e61732d676974"

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
# Dynamically locate frontend directory across project structures
for candidate in [
    os.path.abspath(os.path.join(BACKEND_DIR, "..", "frontend")),
    os.path.abspath(os.path.join(BACKEND_DIR, "frontend")),
    BACKEND_DIR,
]:
    if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "index.html")):
        FRONTEND_DIR = candidate
        break
else:
    FRONTEND_DIR = BACKEND_DIR

app = Flask(__name__)
# Allow CORS from local and tunnel origins
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

app.config["SECRET_KEY"] = os.environ.get("PARKSENSE_SECRET_KEY", "parksense-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2MB max payload (anti-DoS protection)
DB_PATH = os.environ.get("PARKSENSE_DB", os.path.join(BACKEND_DIR, "parksense.db"))


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # 1. Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Columns migration on users table
    cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    for col, col_def in [
        ("role", "TEXT NOT NULL DEFAULT 'user'"),
        ("phone_number", "TEXT DEFAULT ''"),
        ("vehicle_name", "TEXT DEFAULT ''"),
        ("vehicle_reg_number", "TEXT DEFAULT ''"),
        ("is_suspended", "INTEGER NOT NULL DEFAULT 0"),
        ("plain_password", "TEXT DEFAULT ''"),
    ]:
        if col not in cols:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {col_def}")

    # Seed the three designated test accounts with role and plain password
    seed_users = [
        ("Tester1", "testadmin@gmail.com", "admin", "12345678"),
        ("Tester2", "testeditor@gmail.com", "editor", "12345678"),
        ("Tester3", "testuser@gmail.com", "user", "12345678"),
    ]
    for name, email, role, pwd in seed_users:
        existing = c.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        pwd_hash = generate_password_hash(pwd)
        if existing:
            c.execute("""
                UPDATE users
                SET name = ?, role = ?, plain_password = ?, password_hash = ?
                WHERE email = ?
            """, (name, role, pwd, pwd_hash, email))
        else:
            c.execute("""
                INSERT INTO users (name, email, role, plain_password, password_hash)
                VALUES (?, ?, ?, ?, ?)
            """, (name, email, role, pwd, pwd_hash))

    # 2. Locations table
    c.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            address TEXT NOT NULL,
            total_slots INTEGER NOT NULL DEFAULT 4,
            device_id TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'OFFLINE',
            last_sensor_update TEXT,
            is_published INTEGER NOT NULL DEFAULT 1,
            proposal_status TEXT NOT NULL DEFAULT 'approved',
            created_by INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users (id)
        )
    """)

    # 3. Parking slots table
    c.execute("""
        CREATE TABLE IF NOT EXISTS parking_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location_id INTEGER NOT NULL,
            slot_number INTEGER NOT NULL,
            label TEXT NOT NULL,
            physical_state TEXT NOT NULL DEFAULT 'UNKNOWN',
            distance_cm REAL,
            last_updated TEXT,
            FOREIGN KEY (location_id) REFERENCES locations (id) ON DELETE CASCADE,
            UNIQUE(location_id, slot_number)
        )
    """)

    # 4. User saved locations
    c.execute("""
        CREATE TABLE IF NOT EXISTS saved_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (location_id) REFERENCES locations (id) ON DELETE CASCADE,
            UNIQUE(user_id, location_id)
        )
    """)

    # 5. Reservations table
    c.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slot_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            cancelled_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (slot_id) REFERENCES parking_slots (id) ON DELETE CASCADE,
            FOREIGN KEY (location_id) REFERENCES locations (id) ON DELETE CASCADE
        )
    """)

    # Unique index preventing two concurrent ACTIVE reservations on the same slot
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_slot_reservation
        ON reservations (slot_id) WHERE status = 'ACTIVE'
    """)

    # Seed initial demonstration location: UIT Parking
    c.execute("SELECT id FROM locations WHERE name = ?", ("UIT Parking",))
    row = c.fetchone()
    if not row:
        c.execute("""
            INSERT INTO locations (name, address, total_slots, device_id, status, is_published, proposal_status)
            VALUES (?, ?, ?, ?, ?, 1, 'approved')
        """, ("UIT Parking", "United Institute of Technology, Prayagraj", 4, "esp32-uit-01", "OFFLINE"))
        loc_id = c.lastrowid
        for i in range(1, 5):
            c.execute("""
                INSERT INTO parking_slots (location_id, slot_number, label, physical_state)
                VALUES (?, ?, ?, 'UNKNOWN')
            """, (loc_id, i, f"S{i}"))

    # 6. Login and Security Audit Logs table
    c.execute("""
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            email TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            status TEXT NOT NULL,
            timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
        )
    """)

    conn.commit()
    conn.close()


def create_token(user):
    payload = {
        "user_id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user.get("role", "user"),
        "exp": datetime.utcnow() + timedelta(days=7),
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


def get_user_by_email(email):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_id(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_authenticated_user():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    payload = None
    # Verify using current key or legacy key to maintain zero-downtime browser session continuity
    for key in (app.config["SECRET_KEY"], "parksense-secret-key", "parksense-secret-key-dev-fallback"):
        try:
            payload = jwt.decode(token, key, algorithms=["HS256"])
            break
        except Exception:
            continue

    if not payload:
        return None


    user = get_user_by_id(payload.get("user_id"))
    if user and user.get("is_suspended"):
        return None
    return user


def expire_stale_reservations(conn):
    """Expire any active reservation past server expiry time."""
    conn.execute("""
        UPDATE reservations
        SET status = 'EXPIRED'
        WHERE status = 'ACTIVE' AND datetime(expires_at) <= datetime('now')
    """)


def is_sensor_fresh(last_sensor_update):
    """Sensor data is considered fresh only if updated within the last 30 seconds."""
    if not last_sensor_update:
        return False
    try:
        # SQLite CURRENT_TIMESTAMP format is 'YYYY-MM-DD HH:MM:SS'
        dt = datetime.strptime(last_sensor_update, "%Y-%m-%d %H:%M:%S")
        return (datetime.utcnow() - dt).total_seconds() <= 30
    except Exception:
        return False


# ==================== Security Firewall & Bot Protection ====================

BLOCKED_PATHS_PREFIXES = (
    "/wp-", "/.env", "/.git", "/phpmyadmin", "/xmlrpc.php",
    "/cgi-bin", "/setup.php", "/eval-stdin", "/actuator", "/.aws", "/vendor"
)

BLOCKED_BOT_USER_AGENTS = (
    "sqlmap", "nikto", "masscan", "nmap", "zgrab", "censys", "shodan", "acunetix", "havij", "w3af"
)

_rate_limits = {}
_failed_logins = {}


def get_client_ip():
    """Extract real client IP considering Cloudflare and reverse proxies."""
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "127.0.0.1"
    )


def extract_single_name(full_name):
    """Extract a single first/given name from complete name (e.g. 'Mohammad Anas Khan' -> 'Anas')."""
    if not full_name:
        return "User"
    parts = full_name.strip().split()
    if not parts:
        return "User"
    if len(parts) > 1 and parts[0].lower() in ("mohammad", "mohammed", "mohd", "md", "mr", "dr", "mrs", "ms"):
        return parts[1]
    return parts[0]


def log_login_event(email, user_id=None, status="FAILED"):
    """Audit every login attempt with IP address, user-agent, and status."""
    try:
        conn = get_db_connection()
        client_ip = get_client_ip()
        ua = (request.headers.get("User-Agent") or "")[:250]
        conn.execute(
            "INSERT INTO login_logs (user_id, email, ip_address, user_agent, status) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, client_ip, ua, status),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print("Login logging error:", e)


def check_rate_limit(key, max_requests=120, window_sec=60):
    now = time.time()
    timestamps = _rate_limits.get(key, [])
    timestamps = [t for t in timestamps if now - t < window_sec]
    if len(timestamps) >= max_requests:
        _rate_limits[key] = timestamps
        return False
    timestamps.append(now)
    _rate_limits[key] = timestamps
    return True


def record_failed_attempt(client_ip, email):
    now = time.time()
    for key in (f"ip:{client_ip}", f"email:{email}"):
        attempts = _failed_logins.get(key, [])
        attempts = [t for t in attempts if now - t < 600]
        attempts.append(now)
        _failed_logins[key] = attempts


def clear_failed_attempts(client_ip, email):
    for key in (f"ip:{client_ip}", f"email:{email}"):
        _failed_logins.pop(key, None)


def check_brute_force_lockout(client_ip, email):
    now = time.time()
    for key in (f"ip:{client_ip}", f"email:{email}"):
        attempts = _failed_logins.get(key, [])
        recent = [t for t in attempts if now - t < 600]
        if len(recent) >= 5:
            oldest_relevant = recent[-5]
            remaining = int(900 - (now - oldest_relevant))
            if remaining > 0:
                return True, remaining
    return False, 0


@app.before_request
def security_firewall():
    # 1. Block common bot and malware probe patterns
    path_lower = request.path.lower()
    if any(p in path_lower for p in BLOCKED_PATHS_PREFIXES):
        return jsonify({"message": "Access Forbidden: Malicious path probe blocked."}), 403

    # 2. Block known scanner User-Agents
    ua_lower = (request.headers.get("User-Agent") or "").lower()
    if any(bot in ua_lower for bot in BLOCKED_BOT_USER_AGENTS):
        return jsonify({"message": "Access Forbidden: Automated vulnerability scanner blocked."}), 403

    # 3. Apply sliding-window rate limiting per IP
    client_ip = get_client_ip()
    if request.path.startswith("/api/login") or request.path.startswith("/api/signup"):
        if not check_rate_limit(f"auth:{client_ip}", max_requests=50, window_sec=60):
            return jsonify({"message": "Too many requests. Please slow down."}), 429
    elif not request.path.startswith("/api/iot/"):
        if not check_rate_limit(client_ip, max_requests=150, window_sec=60):
            return jsonify({"message": "Rate limit exceeded. Please wait a minute."}), 429


@app.after_request
def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Core-Engine"] = "0x6d64616e61732d676974"
    return response


# ==================== Frontend / Static Web Routes ====================

@app.route("/", methods=["GET"])
def serve_root():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/index.html", methods=["GET"])
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/frontend.html", methods=["GET"])
def serve_frontend():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/style.css", methods=["GET"])
def serve_css():
    return send_from_directory(FRONTEND_DIR, "style.css", mimetype="text/css")


@app.route("/script.js", methods=["GET"])
def serve_js():
    return send_from_directory(FRONTEND_DIR, "script.js", mimetype="application/javascript")


@app.route("/parksense-logo-white.png", methods=["GET"])
def serve_logo():
    for sub in ["assets", ""]:
        logo_path = os.path.join(FRONTEND_DIR, sub, "parksense-logo-white.png") if sub else os.path.join(FRONTEND_DIR, "parksense-logo-white.png")
        if os.path.exists(logo_path):
            dir_to_serve = os.path.dirname(logo_path)
            return send_from_directory(dir_to_serve, "parksense-logo-white.png", mimetype="image/png")
    return send_from_directory(FRONTEND_DIR, "parksense-logo-white.png", mimetype="image/png")


@app.route("/favicon.ico", methods=["GET"])
def serve_favicon():
    fav_path = os.path.join(FRONTEND_DIR, "favicon.ico")
    if os.path.exists(fav_path):
        return send_from_directory(FRONTEND_DIR, "favicon.ico")
    return serve_logo()


ALLOWED_STATIC_EXTENSIONS = {".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2", ".ttf"}

@app.route("/<path:filename>", methods=["GET"])
def serve_static_fallback(filename):
    """Safely serve additional static assets while shielding sensitive backend files."""
    if filename.startswith("api/"):
        return jsonify({"message": "Not Found"}), 404
    base_name = os.path.basename(filename)
    _, ext = os.path.splitext(base_name)
    if ext.lower() in ALLOWED_STATIC_EXTENSIONS or base_name in ("index.html", "frontend.html"):
        file_path = os.path.join(FRONTEND_DIR, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return send_from_directory(FRONTEND_DIR, filename)
    return jsonify({"message": "Not Found"}), 404


# ==================== Core Auth Routes ====================

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "message": "ParkSense Flask API is running",
        "build_ref": "6d64616e61732d676974"
    }), 200


@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"message": "Name, email and password are required"}), 400

    if len(password) < 8:
        return jsonify({"message": "Password must be at least 8 characters"}), 400

    if get_user_by_email(email):
        return jsonify({"message": "This email is already registered."}), 409

    password_hash = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash, plain_password, role) VALUES (?, ?, ?, ?, 'user')",
        (name, email, password_hash, password),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    user = {"id": user_id, "name": name, "email": email, "role": "user"}
    return jsonify({
        "message": "User created successfully",
        "token": create_token(user),
        "user": user,
    }), 201


@app.route("/api/login", methods=["POST"])
def login():
    client_ip = get_client_ip()
    data = request.get_json(silent=True) or {}

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"message": "Email and password are required"}), 400

    # Brute-force bot and credential-stuffing defense
    is_locked, remaining_lock = check_brute_force_lockout(client_ip, email)
    if is_locked:
        log_login_event(email, None, status="LOCKED_OUT")
        return jsonify({"message": f"Too many failed attempts. Temporary lockout active for {remaining_lock} seconds."}), 429

    user = get_user_by_email(email)

    if not user or not check_password_hash(user["password_hash"], password):
        record_failed_attempt(client_ip, email)
        log_login_event(email, user["id"] if user else None, status="FAILED")
        return jsonify({"message": "Wrong email or password."}), 401

    if user.get("is_suspended"):
        log_login_event(email, user["id"], status="SUSPENDED")
        return jsonify({"message": "This account has been suspended by an administrator."}), 403

    clear_failed_attempts(client_ip, email)
    log_login_event(email, user["id"], status="SUCCESS")

    token = create_token({
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user.get("role", "user"),
    })

    return jsonify({
        "message": "Login successful",
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user.get("role", "user"),
        },
    }), 200


@app.route("/api/profile", methods=["GET"])
def profile():
    user = get_authenticated_user()
    if not user:
        return jsonify({"message": "Unauthorized"}), 401

    return jsonify({
        "message": "Profile accessed",
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user.get("role", "user"),
            "phone_number": user.get("phone_number") or "",
            "vehicle_name": user.get("vehicle_name") or "",
            "vehicle_reg_number": user.get("vehicle_reg_number") or "",
            "created_at": user.get("created_at"),
        },
    }), 200


@app.route("/api/profile", methods=["PUT"])
def update_profile():
    user = get_authenticated_user()
    if not user:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or user["name"]).strip()
    phone_number = (data.get("phone_number") or "").strip()
    vehicle_name = (data.get("vehicle_name") or "").strip()
    vehicle_reg_number = (data.get("vehicle_reg_number") or "").strip().upper()

    if not name:
        return jsonify({"message": "Name cannot be empty."}), 400

    conn = get_db_connection()
    conn.execute("""
        UPDATE users
        SET name = ?, phone_number = ?, vehicle_name = ?, vehicle_reg_number = ?
        WHERE id = ?
    """, (name, phone_number, vehicle_name, vehicle_reg_number, user["id"]))
    conn.commit()
    conn.close()

    updated = get_user_by_id(user["id"])
    return jsonify({
        "message": "Profile updated successfully.",
        "user": {
            "id": updated["id"],
            "name": updated["name"],
            "email": updated["email"],
            "role": updated.get("role", "user"),
            "phone_number": updated.get("phone_number") or "",
            "vehicle_name": updated.get("vehicle_name") or "",
            "vehicle_reg_number": updated.get("vehicle_reg_number") or "",
        },
    }), 200


@app.route("/api/auth/change-password", methods=["PUT"])
def change_password():
    user = get_authenticated_user()
    if not user:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if not current_password or not new_password:
        return jsonify({"message": "Current and new password are required."}), 400

    if not check_password_hash(user["password_hash"], current_password):
        return jsonify({"message": "Incorrect current password."}), 400

    if len(new_password) < 8:
        return jsonify({"message": "New password must be at least 8 characters."}), 400

    new_hash = generate_password_hash(new_password)
    conn = get_db_connection()
    conn.execute("UPDATE users SET password_hash = ?, plain_password = ? WHERE id = ?", (new_hash, new_password, user["id"]))
    conn.commit()
    conn.close()

    return jsonify({"message": "Password updated successfully."}), 200


@app.route("/api/profile/account", methods=["DELETE"])
def delete_account():
    user = get_authenticated_user()
    if not user:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    if not data.get("confirm"):
        return jsonify({"message": "Account deletion requires confirmation."}), 400

    conn = get_db_connection()
    # Cancel user's active reservations
    conn.execute("UPDATE reservations SET status = 'CANCELLED' WHERE user_id = ? AND status = 'ACTIVE'", (user["id"],))
    # Remove user's saved locations
    conn.execute("DELETE FROM saved_locations WHERE user_id = ?", (user["id"],))
    # Delete the user account
    conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    conn.commit()
    conn.close()

    return jsonify({"message": "Account and associated personal records deleted successfully."}), 200


# ==================== Locations & Dashboard Routes ====================

@app.route("/api/locations", methods=["GET"])
def list_locations():
    current_user = get_authenticated_user()
    conn = get_db_connection()
    expire_stale_reservations(conn)

    # Only show published locations to users, sorted alphabetically
    locations = conn.execute("""
        SELECT * FROM locations
        WHERE is_published = 1
        ORDER BY name COLLATE NOCASE ASC
    """).fetchall()

    saved_set = set()
    if current_user:
        saved_rows = conn.execute(
            "SELECT location_id FROM saved_locations WHERE user_id = ?",
            (current_user["id"],),
        ).fetchall()
        saved_set = {row["location_id"] for row in saved_rows}

    result = []
    for loc in locations:
        loc_id = loc["id"]
        fresh = is_sensor_fresh(loc["last_sensor_update"])

        slots = conn.execute(
            "SELECT * FROM parking_slots WHERE location_id = ?",
            (loc_id,),
        ).fetchall()

        total = len(slots)
        if not fresh or loc["status"] != "ONLINE":
            summary = "Offline / Pending Connection"
            available_count = None
            occupied_count = None
            reserved_count = None
        else:
            avail = 0
            occ = 0
            res = 0
            for slot in slots:
                # Check active reservation
                active_res = conn.execute("""
                    SELECT id FROM reservations
                    WHERE slot_id = ? AND status = 'ACTIVE'
                """, (slot["id"],)).fetchone()

                if slot["physical_state"] == "OCCUPIED":
                    occ += 1
                elif active_res:
                    res += 1
                elif slot["physical_state"] == "AVAILABLE":
                    avail += 1

            available_count = avail
            occupied_count = occ
            reserved_count = res
            summary = f"{avail} available, {occ} occupied"

        result.append({
            "id": loc["id"],
            "name": loc["name"],
            "address": loc["address"],
            "total_slots": total,
            "status": "ONLINE" if fresh and loc["status"] == "ONLINE" else "OFFLINE",
            "last_sensor_update": loc["last_sensor_update"],
            "is_fresh": fresh,
            "status_summary": summary,
            "available_count": available_count,
            "occupied_count": occupied_count,
            "reserved_count": reserved_count,
            "is_saved": loc_id in saved_set,
        })

    conn.close()
    return jsonify({"locations": result}), 200


@app.route("/api/locations/<int:loc_id>", methods=["GET"])
def get_location_detail(loc_id):
    current_user = get_authenticated_user()
    conn = get_db_connection()
    expire_stale_reservations(conn)

    loc = conn.execute("SELECT * FROM locations WHERE id = ?", (loc_id,)).fetchone()
    if not loc:
        conn.close()
        return jsonify({"message": "Location not found."}), 404

    fresh = is_sensor_fresh(loc["last_sensor_update"])
    device_online = fresh and loc["status"] == "ONLINE"

    slots_rows = conn.execute("""
        SELECT * FROM parking_slots
        WHERE location_id = ?
        ORDER BY slot_number ASC
    """, (loc_id,)).fetchall()

    slots_data = []
    avail_count = 0
    occ_count = 0
    res_count = 0
    unknown_count = 0
    first_available_slot = None

    for s in slots_rows:
        slot_id = s["id"]
        # Check active reservation for this slot
        active_res = conn.execute("""
            SELECT r.*, u.id as res_user_id, u.name as res_user_name
            FROM reservations r
            JOIN users u ON r.user_id = u.id
            WHERE r.slot_id = ? AND r.status = 'ACTIVE'
        """, (slot_id,)).fetchone()

        # Physical status rules
        reserved_by = None
        if not device_online:
            display_status = "UNKNOWN"
            detail_text = "Sensor status not connected"
            unknown_count += 1
            can_reserve = False
        else:
            # Physical occupancy overrides reservation
            if s["physical_state"] == "OCCUPIED" or (s["distance_cm"] is not None and s["distance_cm"] <= 10.0):
                display_status = "OCCUPIED"
                detail_text = f"Occupied ({s['distance_cm']:.1f} cm)" if s["distance_cm"] else "Occupied"
                occ_count += 1
                can_reserve = False
                # If a car parked in a reserved slot, cancel the reservation
                if active_res:
                    conn.execute("UPDATE reservations SET status = 'COMPLETED' WHERE id = ?", (active_res["id"],))
                    conn.commit()
            elif active_res:
                display_status = "RESERVED"
                is_mine = current_user and active_res["user_id"] == current_user["id"]
                detail_text = "Reserved (by you)" if is_mine else "Reserved for 5 min"
                reserved_by = extract_single_name(active_res["res_user_name"])
                res_count += 1
                can_reserve = False
            elif s["physical_state"] == "AVAILABLE" or (s["distance_cm"] is not None and s["distance_cm"] > 10.0):
                display_status = "AVAILABLE"
                detail_text = f"Clear ({s['distance_cm']:.1f} cm)" if s["distance_cm"] else "Clear / Ready"
                avail_count += 1
                can_reserve = True
                if first_available_slot is None:
                    first_available_slot = s["label"]
            else:
                display_status = "UNKNOWN"
                detail_text = "No echo / Sensor unverified"
                unknown_count += 1
                can_reserve = False

        slots_data.append({
            "id": slot_id,
            "slot_number": s["slot_number"],
            "label": s["label"],
            "status": display_status,
            "detail": detail_text,
            "can_reserve": can_reserve,
            "is_reserved_by_me": bool(current_user and active_res and active_res["user_id"] == current_user["id"]),
            "reserved_by": reserved_by,
        })

    is_saved = False
    if current_user:
        saved_row = conn.execute(
            "SELECT id FROM saved_locations WHERE user_id = ? AND location_id = ?",
            (current_user["id"], loc_id),
        ).fetchone()
        is_saved = bool(saved_row)

    conn.close()

    # Formulate summary counts: if offline, display as unavailable (None)
    summary = {
        "total_slots": len(slots_rows),
        "available": avail_count if device_online else None,
        "occupied": occ_count if device_online else None,
        "reserved": res_count if device_online else None,
        "unknown": unknown_count if device_online else len(slots_rows),
    }

    return jsonify({
        "location": {
            "id": loc["id"],
            "name": loc["name"],
            "address": loc["address"],
            "device_status": "ONLINE" if device_online else "OFFLINE",
            "connection_pill": "Online" if device_online else "Connection pending",
            "last_sensor_update": loc["last_sensor_update"],
            "is_fresh": device_online,
            "is_saved": is_saved,
            "recommended_slot": first_available_slot if (device_online and first_available_slot) else "Not available",
            "summary": summary,
            "slots": slots_data,
        }
    }), 200


@app.route("/api/locations", methods=["POST"])
def add_location():
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    address = (data.get("address") or "").strip()
    total_slots = int(data.get("total_slots") or 4)

    if not name or not address:
        return jsonify({"message": "Location name and address are required."}), 400

    if total_slots < 1 or total_slots > 20:
        return jsonify({"message": "Total slots must be between 1 and 20."}), 400

    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM locations WHERE name = ?", (name,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"message": "A parking location with this name already exists."}), 409

    user_role = current_user.get("role", "user")

    if user_role in ("admin", "editor"):
        # Authorized editors and admins create active facilities directly
        cursor = conn.execute("""
            INSERT INTO locations (name, address, total_slots, status, is_published, proposal_status, created_by)
            VALUES (?, ?, ?, 'OFFLINE', 1, 'approved', ?)
        """, (name, address, total_slots, current_user["id"]))
        loc_id = cursor.lastrowid

        for i in range(1, total_slots + 1):
            conn.execute("""
                INSERT INTO parking_slots (location_id, slot_number, label, physical_state)
                VALUES (?, ?, ?, 'UNKNOWN')
            """, (loc_id, i, f"S{i}"))

        conn.commit()
        conn.close()
        return jsonify({
            "message": "Parking location created and published successfully.",
            "location_id": loc_id,
            "location": {
                "id": loc_id,
                "name": name,
                "address": address,
                "total_slots": total_slots,
                "proposal_status": "approved",
                "is_published": True,
            },
            "is_published": True,
        }), 201
    else:
        # Standard users submit location proposals for admin/editor review
        cursor = conn.execute("""
            INSERT INTO locations (name, address, total_slots, status, is_published, proposal_status, created_by)
            VALUES (?, ?, ?, 'OFFLINE', 0, 'pending', ?)
        """, (name, address, total_slots, current_user["id"]))
        loc_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jsonify({
            "message": "Parking location request submitted successfully! It is pending approval by an Admin or Editor.",
            "location_id": loc_id,
            "location": {
                "id": loc_id,
                "name": name,
                "address": address,
                "total_slots": total_slots,
                "proposal_status": "pending",
                "is_published": False,
            },
            "is_published": False,
        }), 202


@app.route("/api/locations/logs", methods=["GET"])
def get_location_logs():
    """View all location requests, status, and creator details. Accessible to Admin and Editor."""
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Authentication required."}), 401

    if current_user.get("role") not in ("admin", "editor"):
        return jsonify({"message": "Privileges required: Admin or Editor only."}), 403

    conn = get_db_connection()
    logs = conn.execute("""
        SELECT l.id, l.name, l.address, l.total_slots, l.proposal_status, l.is_published, l.created_at,
               u.name as creator_name, u.email as creator_email
        FROM locations l
        LEFT JOIN users u ON l.created_by = u.id
        ORDER BY l.id DESC
    """).fetchall()
    conn.close()

    return jsonify({
        "locations": [
            {
                "id": l["id"],
                "name": l["name"],
                "address": l["address"],
                "total_slots": l["total_slots"],
                "proposal_status": l["proposal_status"],
                "is_published": bool(l["is_published"]),
                "created_at": l["created_at"],
                "creator_name": l["creator_name"] or "System Admin",
                "creator_email": l["creator_email"] or "admin@parksense.com"
            }
            for l in logs
        ]
    }), 200


@app.route("/api/locations/<int:location_id>/approve", methods=["PUT"])
def approve_location(location_id):
    """Approve a proposed parking location. Accessible to Admin and Editor."""
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Authentication required."}), 401

    if current_user.get("role") not in ("admin", "editor"):
        return jsonify({"message": "Privileges required: Admin or Editor only."}), 403

    conn = get_db_connection()
    loc = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
    if not loc:
        conn.close()
        return jsonify({"message": "Parking location not found."}), 404

    # Mark as approved and published
    conn.execute("""
        UPDATE locations
        SET is_published = 1, proposal_status = 'approved'
        WHERE id = ?
    """, (location_id,))

    # Ensure slots exist
    existing_slots = conn.execute("SELECT COUNT(*) FROM parking_slots WHERE location_id = ?", (location_id,)).fetchone()[0]
    if existing_slots == 0:
        for i in range(1, int(loc["total_slots"]) + 1):
            conn.execute("""
                INSERT INTO parking_slots (location_id, slot_number, label, physical_state)
                VALUES (?, ?, ?, 'UNKNOWN')
            """, (location_id, i, f"S{i}"))

    conn.commit()
    conn.close()

    return jsonify({
        "message": f"Parking location '{loc['name']}' has been approved and published successfully.",
        "location_id": location_id
    }), 200


@app.route("/api/locations/<int:location_id>", methods=["DELETE"])
def delete_location(location_id):
    """Delete a parking location. Accessible strictly by administrators."""
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Authentication required."}), 401

    if current_user.get("role") != "admin":
        return jsonify({"message": "Administrator privileges required: only Admin can delete parking locations."}), 403

    conn = get_db_connection()
    loc = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
    if not loc:
        conn.close()
        return jsonify({"message": "Parking location not found."}), 404

    # Cancel active reservations on this location
    conn.execute("""
        UPDATE reservations
        SET status = 'CANCELLED'
        WHERE location_id = ? AND status = 'ACTIVE'
    """, (location_id,))

    # Remove references
    conn.execute("DELETE FROM saved_locations WHERE location_id = ?", (location_id,))
    conn.execute("DELETE FROM parking_slots WHERE location_id = ?", (location_id,))
    conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))

    conn.commit()
    conn.close()

    return jsonify({"message": f"Parking location '{loc['name']}' was deleted successfully."}), 200


# ==================== Saved Locations Routes ====================

@app.route("/api/user/saved-locations", methods=["GET"])
def get_saved_locations():
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    expire_stale_reservations(conn)

    saved = conn.execute("""
        SELECT l.*, sl.created_at as saved_at
        FROM saved_locations sl
        JOIN locations l ON sl.location_id = l.id
        WHERE sl.user_id = ? AND l.is_published = 1
        ORDER BY l.name COLLATE NOCASE ASC
    """, (current_user["id"],)).fetchall()

    result = []
    for loc in saved:
        fresh = is_sensor_fresh(loc["last_sensor_update"])
        slots = conn.execute("SELECT * FROM parking_slots WHERE location_id = ?", (loc["id"],)).fetchall()

        if not fresh or loc["status"] != "ONLINE":
            summary = "Offline / Pending Connection"
        else:
            avail = sum(1 for s in slots if s["physical_state"] == "AVAILABLE")
            occ = sum(1 for s in slots if s["physical_state"] == "OCCUPIED")
            summary = f"{avail} available, {occ} occupied"

        result.append({
            "id": loc["id"],
            "name": loc["name"],
            "address": loc["address"],
            "total_slots": len(slots),
            "status": "ONLINE" if fresh and loc["status"] == "ONLINE" else "OFFLINE",
            "status_summary": summary,
            "is_saved": True,
        })

    conn.close()
    return jsonify({"saved_locations": result}), 200


@app.route("/api/user/saved-locations/<int:loc_id>", methods=["POST"])
def save_location(loc_id):
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    loc = conn.execute("SELECT id FROM locations WHERE id = ?", (loc_id,)).fetchone()
    if not loc:
        conn.close()
        return jsonify({"message": "Location not found."}), 404

    conn.execute("""
        INSERT OR IGNORE INTO saved_locations (user_id, location_id)
        VALUES (?, ?)
    """, (current_user["id"], loc_id))
    conn.commit()
    conn.close()

    return jsonify({"message": "Location saved to your favourites.", "is_saved": True}), 200


@app.route("/api/user/saved-locations/<int:loc_id>", methods=["DELETE"])
def unsave_location(loc_id):
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    conn.execute("""
        DELETE FROM saved_locations
        WHERE user_id = ? AND location_id = ?
    """, (current_user["id"], loc_id))
    conn.commit()
    conn.close()

    return jsonify({"message": "Location removed from your favourites.", "is_saved": False}), 200


# ==================== Reservations Routes ====================

@app.route("/api/reservations", methods=["POST"])
def create_reservation():
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    slot_id = data.get("slot_id")
    location_id = data.get("location_id")

    if not slot_id or not location_id:
        return jsonify({"message": "slot_id and location_id are required."}), 400

    conn = get_db_connection()
    expire_stale_reservations(conn)

    # 1. Check user doesn't already hold an active reservation
    existing_user_res = conn.execute("""
        SELECT r.id, s.label, l.name
        FROM reservations r
        JOIN parking_slots s ON r.slot_id = s.id
        JOIN locations l ON r.location_id = l.id
        WHERE r.user_id = ? AND r.status = 'ACTIVE'
    """, (current_user["id"],)).fetchone()

    if existing_user_res:
        conn.close()
        return jsonify({
            "message": f"You already have an active reservation for {existing_user_res['label']} at {existing_user_res['name']}. Cancel it before making a new one."
        }), 400

    # 2. Check location freshness & sensor state
    loc = conn.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
    if not loc:
        conn.close()
        return jsonify({"message": "Location not found."}), 404

    if not is_sensor_fresh(loc["last_sensor_update"]) or loc["status"] != "ONLINE":
        conn.close()
        return jsonify({"message": "Reservations are disabled: sensors are offline or status is unconfirmed."}), 400

    # 3. Check slot existence and physical state
    slot = conn.execute("""
        SELECT * FROM parking_slots
        WHERE id = ? AND location_id = ?
    """, (slot_id, location_id)).fetchone()

    if not slot:
        conn.close()
        return jsonify({"message": "Slot not found at this location."}), 404

    if slot["physical_state"] != "AVAILABLE" or (slot["distance_cm"] is not None and slot["distance_cm"] <= 10.0):
        conn.close()
        return jsonify({"message": "Slot is not physically available for reservation."}), 400

    # 4. Check active reservation on this slot
    slot_res = conn.execute("""
        SELECT id FROM reservations
        WHERE slot_id = ? AND status = 'ACTIVE'
    """, (slot_id,)).fetchone()

    if slot_res:
        conn.close()
        return jsonify({"message": "This slot is already reserved by another user."}), 409

    # 5. Insert reservation with 5-minute expiry
    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=5)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor = conn.execute("""
            INSERT INTO reservations (user_id, slot_id, location_id, status, created_at, expires_at)
            VALUES (?, ?, ?, 'ACTIVE', ?, ?)
        """, (current_user["id"], slot_id, location_id, now_str, expires_str))
        conn.commit()
        res_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"message": "This slot was just reserved by another user."}), 409

    conn.close()

    return jsonify({
        "message": "Slot reserved for 5 minutes!",
        "reservation": {
            "id": res_id,
            "slot_id": slot_id,
            "slot_label": slot["label"],
            "location_id": location_id,
            "location_name": loc["name"],
            "created_at": now_str,
            "expires_at": expires_str,
            "duration_seconds": 300,
            "remaining_seconds": 300,
        },
    }), 201


@app.route("/api/reservations/<int:res_id>", methods=["DELETE"])
def cancel_reservation(res_id):
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    res = conn.execute("SELECT * FROM reservations WHERE id = ?", (res_id,)).fetchone()
    if not res:
        conn.close()
        return jsonify({"message": "Reservation not found."}), 404

    # Enforce ownership: only reservation owner can cancel
    if res["user_id"] != current_user["id"]:
        conn.close()
        return jsonify({"message": "You can only cancel your own reservations."}), 403

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        UPDATE reservations
        SET status = 'CANCELLED', cancelled_at = ?
        WHERE id = ?
    """, (now_str, res_id))
    conn.commit()
    conn.close()

    return jsonify({"message": "Reservation cancelled successfully."}), 200


@app.route("/api/user/active-reservation", methods=["GET"])
def get_user_active_reservation():
    current_user = get_authenticated_user()
    if not current_user:
        return jsonify({"message": "Unauthorized"}), 401

    conn = get_db_connection()
    expire_stale_reservations(conn)

    res = conn.execute("""
        SELECT r.*, s.label as slot_label, s.physical_state, s.distance_cm, l.name as location_name, l.address as location_address
        FROM reservations r
        JOIN parking_slots s ON r.slot_id = s.id
        JOIN locations l ON r.location_id = l.id
        WHERE r.user_id = ? AND r.status = 'ACTIVE'
    """, (current_user["id"],)).fetchone()

    if not res:
        conn.close()
        return jsonify({"active_reservation": None}), 200

    # Calculate remaining seconds from server time
    try:
        expiry_dt = datetime.strptime(res["expires_at"], "%Y-%m-%d %H:%M:%S")
        remaining = int((expiry_dt - datetime.utcnow()).total_seconds())
    except Exception:
        remaining = 0

    if remaining <= 0:
        conn.execute("UPDATE reservations SET status = 'EXPIRED' WHERE id = ?", (res["id"],))
        conn.commit()
        conn.close()
        return jsonify({"active_reservation": None}), 200

    conn.close()

    return jsonify({
        "active_reservation": {
            "id": res["id"],
            "slot_id": res["slot_id"],
            "slot_label": res["slot_label"],
            "location_id": res["location_id"],
            "location_name": res["location_name"],
            "location_address": res["location_address"],
            "created_at": res["created_at"],
            "expires_at": res["expires_at"],
            "remaining_seconds": remaining,
        }
    }), 200


# ==================== ESP32 / Wokwi Telemetry Ingestion ====================

@app.route("/api/iot/telemetry", methods=["POST"])
def iot_telemetry():
    """Endpoint for ESP32 MicroPython / simulator bridge to post real sensor readings."""
    data = request.get_json(silent=True)
    if data is None:
        try:
            import json as _json
            raw_text = request.get_data(as_text=True)
            data = _json.loads(raw_text) if raw_text else None
        except Exception:
            data = None

    if not data or not isinstance(data, dict) or not any(k in data for k in ("device_id", "facility_id", "location_id", "slots")):
        return jsonify({"message": "Invalid or empty telemetry payload"}), 400

    device_id = data.get("device_id")
    facility_id = data.get("facility_id") or data.get("location_id")
    slots_data = data.get("slots") or []

    conn = get_db_connection()
    expire_stale_reservations(conn)

    loc = None
    if device_id:
        loc = conn.execute("SELECT * FROM locations WHERE device_id = ?", (device_id,)).fetchone()
    if not loc and facility_id:
        loc = conn.execute("SELECT * FROM locations WHERE id = ?", (facility_id,)).fetchone()
    if not loc and not device_id and not facility_id:
        # Default fallback to primary UIT Parking if neither specified
        loc = conn.execute("SELECT * FROM locations WHERE name = ?", ("UIT Parking",)).fetchone()

    if not loc:
        conn.close()
        return jsonify({"message": f"Device or facility '{device_id or facility_id}' not registered."}), 404

    loc_id = loc["id"]
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # Update location device status to ONLINE with current timestamp
    conn.execute("""
        UPDATE locations
        SET status = 'ONLINE', last_sensor_update = ?
        WHERE id = ?
    """, (now_str, loc_id))

    # Update slot readings
    for item in slots_data:
        try:
            slot_num = int(item.get("slot_number"))
        except (TypeError, ValueError):
            continue

        raw_dist = item.get("distance_cm")
        try:
            dist = float(raw_dist) if raw_dist is not None else None
        except (TypeError, ValueError):
            dist = None

        # Distance threshold: negative or extreme distances (> 1000cm) indicate sensor error/offline.
        # Wokwi simulation reports open bays at ~405-410cm, which are valid AVAILABLE slots.
        if dist is None or dist < 0 or dist > 1000:
            phys_state = "UNKNOWN"
            dist_val = None
        elif dist <= 10.0:
            phys_state = "OCCUPIED"
            dist_val = dist
            # Physical occupancy cancels any active reservation on this slot
            conn.execute("""
                UPDATE reservations
                SET status = 'COMPLETED', cancelled_at = ?
                WHERE slot_id = (SELECT id FROM parking_slots WHERE location_id = ? AND slot_number = ?)
                  AND status = 'ACTIVE'
            """, (now_str, loc_id, slot_num))
        else:
            phys_state = "AVAILABLE"
            dist_val = dist

        conn.execute("""
            UPDATE parking_slots
            SET physical_state = ?, distance_cm = ?, last_updated = ?
            WHERE location_id = ? AND slot_number = ?
        """, (phys_state, dist_val, now_str, loc_id, slot_num))

    conn.commit()

    # Query active reservations for this facility to return to the ESP32
    active_res = conn.execute("""
        SELECT r.id, r.slot_id, s.slot_number, s.label, r.expires_at
        FROM reservations r
        JOIN parking_slots s ON r.slot_id = s.id
        WHERE r.location_id = ? AND r.status = 'ACTIVE'
    """, (loc_id,)).fetchall()

    now_dt = datetime.utcnow()
    res_map = {}
    for r in active_res:
        try:
            exp_dt = datetime.strptime(r["expires_at"], "%Y-%m-%d %H:%M:%S")
            rem = max(0, int((exp_dt - now_dt).total_seconds()))
        except Exception:
            rem = 0
        if rem > 0:
            res_map[r["slot_number"]] = rem

    total_slots = loc["total_slots"] if loc["total_slots"] else 4
    reservations_list = [
        {
            "slot_number": sn,
            "label": f"S{sn}",
            "is_reserved": (sn in res_map),
            "remaining_seconds": res_map.get(sn, 0)
        }
        for sn in range(1, total_slots + 1)
    ]

    conn.close()
    return jsonify({
        "status": "ok",
        "message": "Telemetry processed.",
        "device_id": loc["device_id"],
        "location_id": loc_id,
        "location_name": loc["name"],
        "server_time": now_str,
        "reservations": reservations_list
    }), 200


@app.route("/api/iot/status", methods=["GET"])
def iot_status():
    """Endpoint for ESP32 or external monitors to query current device reservations."""
    device_id = request.args.get("device_id") or "esp32-uit-01"
    conn = get_db_connection()
    expire_stale_reservations(conn)

    loc = conn.execute("SELECT * FROM locations WHERE device_id = ?", (device_id,)).fetchone()
    if not loc:
        conn.close()
        return jsonify({"message": f"Device {device_id} not registered."}), 404

    loc_id = loc["id"]
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    now_dt = datetime.utcnow()

    active_res = conn.execute("""
        SELECT r.id, r.slot_id, s.slot_number, s.label, r.expires_at
        FROM reservations r
        JOIN parking_slots s ON r.slot_id = s.id
        WHERE r.location_id = ? AND r.status = 'ACTIVE'
    """, (loc_id,)).fetchall()

    res_map = {}
    for r in active_res:
        try:
            exp_dt = datetime.strptime(r["expires_at"], "%Y-%m-%d %H:%M:%S")
            rem = max(0, int((exp_dt - now_dt).total_seconds()))
        except Exception:
            rem = 0
        if rem > 0:
            res_map[r["slot_number"]] = rem

    total_slots = loc["total_slots"] if loc["total_slots"] else 4
    reservations_list = [
        {
            "slot_number": sn,
            "label": f"S{sn}",
            "is_reserved": (sn in res_map),
            "remaining_seconds": res_map.get(sn, 0)
        }
        for sn in range(1, total_slots + 1)
    ]
    conn.close()

    return jsonify({
        "status": "ok",
        "device_id": loc["device_id"],
        "location_id": loc_id,
        "location_name": loc["name"],
        "server_time": now_str,
        "reservations": reservations_list
    }), 200


# ==================== Admin Management & Audit Routes ====================

@app.route("/api/admin/users", methods=["GET"])
def admin_get_users():
    current_user = get_authenticated_user()
    if not current_user or current_user.get("role") != "admin":
        return jsonify({"message": "Administrator privileges required."}), 403

    conn = get_db_connection()
    users = conn.execute("""
        SELECT u.id, u.name, u.email, u.role, u.is_suspended, u.created_at,
               u.vehicle_name, u.vehicle_reg_number, u.plain_password, u.password_hash,
               (SELECT ip_address FROM login_logs WHERE user_id = u.id ORDER BY id DESC LIMIT 1) as last_ip,
               (SELECT timestamp FROM login_logs WHERE user_id = u.id ORDER BY id DESC LIMIT 1) as last_login
        FROM users u
        ORDER BY u.id ASC
    """).fetchall()
    conn.close()

    return jsonify({
        "users": [
            {
                "id": u["id"],
                "name": u["name"],
                "email": u["email"],
                "role": u["role"],
                "is_suspended": bool(u["is_suspended"]),
                "created_at": u["created_at"],
                "vehicle_name": u["vehicle_name"],
                "vehicle_reg_number": u["vehicle_reg_number"],
                "password": u["plain_password"] or "12345678",
                "last_ip": u["last_ip"] or "No logins recorded",
                "last_login": u["last_login"] or "Never"
            }
            for u in users
        ]
    }), 200


@app.route("/api/admin/users/<int:target_user_id>/suspend", methods=["PUT"])
def admin_toggle_suspend(target_user_id):
    current_user = get_authenticated_user()
    if not current_user or current_user.get("role") != "admin":
        return jsonify({"message": "Administrator privileges required."}), 403

    if current_user["id"] == target_user_id:
        return jsonify({"message": "You cannot suspend your own administrator account."}), 400

    data = request.get_json(silent=True) or {}
    if "suspend" in data:
        suspend = bool(data["suspend"])
    elif "is_suspended" in data:
        suspend = bool(data["is_suspended"])
    else:
        suspend = True

    conn = get_db_connection()
    target = conn.execute("SELECT * FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target:
        conn.close()
        return jsonify({"message": "User not found."}), 404

    conn.execute("UPDATE users SET is_suspended = ? WHERE id = ?", (1 if suspend else 0, target_user_id))
    conn.commit()
    conn.close()

    action_label = "suspended" if suspend else "reactivated"
    return jsonify({
        "message": f"User {target['name']} ({target['email']}) has been {action_label}.",
        "is_suspended": suspend
    }), 200


@app.route("/api/admin/users/<int:target_user_id>/role", methods=["PUT"])
def admin_update_role(target_user_id):
    """Assign roles: Admin, Editor, User. Accessible strictly by administrators."""
    current_user = get_authenticated_user()
    if not current_user or current_user.get("role") != "admin":
        return jsonify({"message": "Administrator privileges required."}), 403

    data = request.get_json(silent=True) or {}
    new_role = (data.get("role") or "").strip().lower()

    if new_role not in ("admin", "editor", "user"):
        return jsonify({"message": "Invalid role. Allowed roles are: Admin, Editor, User."}), 400

    if current_user["id"] == target_user_id and new_role != "admin":
        return jsonify({"message": "You cannot remove your own administrator privileges."}), 400

    conn = get_db_connection()
    target = conn.execute("SELECT * FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target:
        conn.close()
        return jsonify({"message": "User not found."}), 404

    conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, target_user_id))
    conn.commit()
    conn.close()

    return jsonify({
        "message": f"Role for {target['name']} updated to {new_role.capitalize()}.",
        "role": new_role
    }), 200


@app.route("/api/admin/users/<int:target_user_id>/password", methods=["PUT"])
def admin_set_password(target_user_id):
    """Update user password directly. Accessible by administrators."""
    current_user = get_authenticated_user()
    if not current_user or current_user.get("role") != "admin":
        return jsonify({"message": "Administrator privileges required."}), 403

    data = request.get_json(silent=True) or {}
    new_password = (data.get("password") or "").strip()

    if not new_password or len(new_password) < 4:
        return jsonify({"message": "Password must be at least 4 characters."}), 400

    new_hash = generate_password_hash(new_password)
    conn = get_db_connection()
    target = conn.execute("SELECT * FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if not target:
        conn.close()
        return jsonify({"message": "User not found."}), 404

    conn.execute("UPDATE users SET password_hash = ?, plain_password = ? WHERE id = ?", (new_hash, new_password, target_user_id))
    conn.commit()
    conn.close()

    return jsonify({
        "message": f"Password for {target['name']} updated successfully to '{new_password}'.",
        "password": new_password
    }), 200


@app.route("/api/admin/logins", methods=["GET"])
def admin_get_logins():
    current_user = get_authenticated_user()
    if not current_user or current_user.get("role") != "admin":
        return jsonify({"message": "Administrator privileges required."}), 403

    conn = get_db_connection()
    logs = conn.execute("""
        SELECT l.id, l.email, l.ip_address, l.user_agent, l.status, l.timestamp,
               u.name as user_name
        FROM login_logs l
        LEFT JOIN users u ON l.user_id = u.id
        ORDER BY l.id DESC
        LIMIT 100
    """).fetchall()
    conn.close()

    return jsonify({
        "logs": [
            {
                "id": l["id"],
                "email": l["email"],
                "user_name": l["user_name"] or "Unknown",
                "ip_address": l["ip_address"] or "Unknown",
                "user_agent": l["user_agent"] or "Unknown",
                "status": l["status"],
                "timestamp": l["timestamp"]
            }
            for l in logs
        ]
    }), 200


# ==================== Local AI / Offline Assistant Route ====================

@app.route("/api/assistant/chat", methods=["POST"])
def assistant_chat():
    """Offline campus assistant endpoint supporting live state RAG and natural language queries."""
    user = get_authenticated_user()
    if not user:
        return jsonify({"message": "Authentication required."}), 401

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    result = process_assistant_query(user["id"], message)
    return jsonify(result), 200


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)