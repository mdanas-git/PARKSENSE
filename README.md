# ParkSense 🚗⚡
### Intelligent IoT Smart Parking System with Real-Time Telemetry & Assistant

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Backend-Flask-000000?style=flat&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![ESP32](https://img.shields.io/badge/Hardware-ESP32%20MicroPython-E7352C?style=flat&logo=espressif&logoColor=white)](https://micropython.org)
[![Wokwi](https://img.shields.io/badge/Simulation-Wokwi-2B88D9?style=flat)](https://wokwi.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Author](https://img.shields.io/badge/Author-mdanas--git-blue)](https://github.com/mdanas-git)

---

## 🌟 Welcome to ParkSense!

Finding a parking spot shouldn't mean driving in circles, wasting fuel, or arriving late. **ParkSense** bridges real-world IoT hardware and a modern, responsive web application to make parking effortless, predictable, and stress-free.

Whether you're a driver looking for an open spot, a facility operator reviewing lot health, or a developer exploring IoT-to-cloud workflows, ParkSense provides a complete, working solution that you can run on physical hardware or simulate entirely in your web browser via **Wokwi**.

---

## 💡 Why ParkSense?

* **No More Guesswork:** Live ultrasonic sensors monitor parking bays in real-time with sub-second accuracy.
* **Guaranteed 5-Minute Spots:** Drivers can hold an available spot online for 300 seconds before arriving. If you arrive and park, the sensor automatically verifies your car and completes the booking!
* **Automated Smart Barrier:** An SG90 servo gate automatically welcomes vehicles when spots are free, prioritizes departing traffic, and stops entry when the lot is full.
* **Friendly Offline AI Assistant:** An integrated parking assistant answers driver questions, helps find spots, and tracks countdowns—all while respecting strict data privacy.
* **Zero Cost Simulation:** Don't have physical microcontrollers? The entire circuit (ESP32, sensors, shift registers, servo, and OLED) runs in the browser using the included Wokwi configuration.

---

## 🏗️ System Architecture

```text
 ┌─────────────────────────────────────────────────────────┐
 │               ESP32 Edge Node (Wokwi / Real)            │
 │  • 4x HC-SR04 Slot Sensors   • 74HC595 LED Shift Reg    │
 │  • Entry/Exit Gate Sensors   • SG90 Barrier Servo       │
 │  • SSD1306 OLED Display      • MicroPython Controller   │
 └────────────────────────────┬────────────────────────────┘
                              │
               HTTPS / JSON   │ Telemetry Stream (Every 2.5s)
               Reservation    │ Sync (Active Holds & LEDs)
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │                    Flask Backend & API                  │
 │  • RESTful Endpoints         • SQLite Data Persistence  │
 │  • Role-Based Access (RBAC)  • Fail-Safe Stale Engine   │
 │  • Sliding-Window Security   • Context-Aware AI Engine  │
 └────────────────────────────┬────────────────────────────┘
                              │
               Live Web UI    │ REST & Assistant API
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │                   ParkSense Web Interface               │
 │  • Real-Time Bay Status      • 5-Minute Reservations    │
 │  • Saved Locations Directory • In-App AI Chat Window    │
 │  • Admin & Editor Tools      • Responsive Mobile Design │
 └─────────────────────────────────────────────────────────┘
```

---

## 🚀 Key Features

### 1. 🟢 Real-Time Slot Detection & Visual LEDs
* **Dual-threshold filtering:** Vehicles within $\le 10\text{ cm}$ trigger immediate detection, with hysteresis verification to prevent sensor flicker.
* **Shift Register LED Matrix (74HC595):**
  * 🟢 **Green:** Slot is clear and ready for parking or reservation.
  * 🟡 **Yellow:** Slot is reserved for an incoming driver (5-minute countdown active).
  * 🔴 **Red:** Slot is physically occupied by a vehicle.
  * ⚫ **Off:** Hardware offline or unmonitored.

### 2. ⏱️ 5-Minute Reservations with Smart Auto-Complete
* Drivers can select any green bay and hold it exclusively for **5 minutes (300 seconds)**.
* **Hardware Sync:** The physical ESP32 updates its LED to Yellow immediately so other drivers on-site see that the spot is reserved.
* **Smart Occupancy Transition:** When the driver pulls into the reserved bay, the ultrasonic sensor detects the car and automatically marks the reservation completed.
* **Graceful Expiration:** If the driver doesn't arrive within 5 minutes, the spot releases back to the community automatically.

### 3. 🚧 Automated Entry & Exit Servo Barrier
* **Entry Check:** Opens only when at least one monitored bay is available.
* **Exit Priority:** Departing cars are cleared smoothly to avoid lot bottlenecks.
* **Lot Full Lockout:** Automatically stays closed and signals `LOT FULL` when all bays are occupied or reserved.

### 4. 🤖 Helpful ParkSense AI Assistant
* **Privacy-First:** Operates locally without leaking administrative passwords or sensitive system internals.
* **Driver Guidance:** Answers questions on live vacancies, recommended bays, reservation timers, and cancellation instructions.
* **Hardware Insight:** Explains LED colors, barrier gate mechanics, and ultrasonic sensor readings in friendly terms.
* **Quick Prompts:** Clean, curated prompt buttons help drivers get answers in just one click.

### 5. 👥 Three Clear User Roles
| Role | Capabilities |
| :--- | :--- |
| **Admin** | Full system control, user role management, account password overrides, account suspension, facility creation, and permanent deletion. |
| **Editor** | Direct facility publishing and community location review/approval via the Location Logs drawer. (Cannot delete locations or manage user accounts). |
| **User** | Browse parking locations, save favorites, reserve slots, update personal vehicle profile, and propose new locations for review. |

---

## ⚡ Quick Start Guide

Follow these steps to run ParkSense locally on your computer in under 3 minutes.

### 1. Clone the Repository
```bash
git clone https://github.com/mdanas-git/ParkSense.git
cd ParkSense
```

### 2. Set Up Python Environment
```bash
# Optional: Create and activate a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

### 3. Start the Backend Server
```bash
# Option A: Run directly via Python
python backend/backend.py

# Option B: Windows 1-Click Launcher
START_BACKEND.bat
```
Your backend will start on **`http://127.0.0.1:5000`**. Flask serves both the REST API and the static frontend application together on this port.

### 4. Launch the Frontend
Simply open **`http://localhost:5000`** in any modern web browser!

---

## 🖥️ Launching the Frontend Web Application

The ParkSense frontend is built using clean, responsive HTML5, modern CSS3, and vanilla JavaScript—**no Node.js, npm, or complex build toolchains are required**. Everything runs instantly out of the box!

### How to Access the Web Application

#### 1. On Your Local Machine (Desktop / Laptop)
Once `backend.py` is running, open your favorite browser and navigate to:
```text
http://localhost:5000
# or
http://127.0.0.1:5000
```

#### 2. On Your Mobile Device (Local Wi-Fi Network)
To test the responsive mobile interface on your smartphone or tablet over your home/office Wi-Fi:
1. Find your computer's local IP address:
   * **Windows:** Open PowerShell or Command Prompt and run `ipconfig` (find the `IPv4 Address`, e.g., `192.000.0.00`).
   * **macOS / Linux:** Run `ifconfig` or `ip addr`.
2. Connect your mobile device to the same Wi-Fi network.
3. Open your mobile browser and enter:
   ```text
   http://192.000.0.00:5000
   ```

#### 3. Remotely on Mobile Data / Anywhere in the World
Using the **Cloudflare Tunnel** (detailed below), you can open ParkSense from any smartphone over 4G/5G mobile data or share the link with colleagues without configuring complex router port forwarding or VPNs!

### Interactive Frontend Features & Navigation
* 🏢 **Live Parking Dashboard:** Real-time 4-slot visual layout (`S1`–`S4`), live vacancy counter, and 1-click 5-minute reservation drawer with a live countdown timer.
* 📍 **Locations Directory:** Browse facilities, filter by saved/favorite locations, and propose new monitored parking facilities.
* 📋 **Location Logs (Editor & Admin):** Dedicated drawer to review and approve community facility proposals or create new parking lots directly.
* ⚙️ **Admin Settings (Admin Only):** View user accounts, change user roles (`Admin`, `Editor`, `User`), manage passwords, and suspend/restore accounts.
* 💬 **ParkSense AI Assistant:** Bottom-right floating button opening a responsive chat window with fast quick prompts, hardware diagnostics, and driver assistance.

---

## 🌐 Launching & Configuring Cloudflare Tunnel

### Why Cloudflare Tunnel?

1. **Wokwi Cloud Simulation:** Wokwi's simulator runs in your web browser (`https://wokwi.com`). Because MicroPython inside Wokwi's cloud sandbox cannot directly reach your private `localhost:5000` or local LAN IP, Cloudflare Tunnel creates a free, secure, outbound-only HTTPS bridge (`https://<unique-id>.trycloudflare.com`) that routes Wokwi's telemetry requests directly to your local Flask server.
2. **Zero Router Configuration:** No opening firewall ports, no dynamic DNS, and no security risks to your home or office network.
### 1. One-Time Cloudflare Setup (Install via Terminal)

If Cloudflare is not already installed on your machine, install the official package via your terminal:

* **Windows (PowerShell / Command Prompt):**
  ```powershell
  winget install Cloudflare.cloudflared
  ```
* **macOS (Homebrew):**
  ```bash
  brew install cloudflared
  ```
* **Linux (Debian / Ubuntu):**
  ```bash
  sudo apt install cloudflared
  ```

---

### 2. How to Launch Cloudflare Tunnel

Choose the method that best matches your workflow:

#### Option 1: Windows 1-Click Batch Launcher (Recommended)
Simply double-click the included batch file in the project root:
```text
START_WOKWI_TUNNEL.bat
```
This automatically invokes the Python tunnel runner and keeps the tunnel connection active.

#### Option 2: Cross-Platform Python Runner (`tools/tunnel_runner.py`)
Run the automated runner directly from your terminal:
```bash
python tools/tunnel_runner.py
```

> [!TIP]
> **Automatic Firmware Synchronization:** `tunnel_runner.py` automatically detects the newly assigned Cloudflare HTTPS URL and updates `SERVER_URL` inside [`firmware/main.py`](firmware/main.py) for you! You never need to manually copy and paste tunnel URLs into your ESP32 code.

#### Option 3: Direct Cloudflared CLI Command
If you prefer running the `cloudflared` CLI command directly:
```bash
cloudflared tunnel --url http://localhost:5000
```

### Verifying Tunnel Connectivity

Once started, the terminal will display output similar to:
```text
=================================================================
     PARKSENSE -- WOKWI HARDWARE INTEGRATION TUNNEL
=================================================================

Starting Cloudflare Tunnel to local Flask backend (port 5000)...
Assigned Public Tunnel URL:
https://random-assigned-name.trycloudflare.com
Updated main.py SERVER_URL -> https://random-assigned-name.trycloudflare.com
```

You can verify the tunnel is live by opening `https://random-assigned-name.trycloudflare.com` in your browser or testing the API endpoint:
```bash
curl https://random-assigned-name.trycloudflare.com/api/locations
```

---

## 🔑 Test Accounts (Ready to Use)

The system comes pre-configured with three clean test accounts so you can explore all roles right away:

| Role | Email | Password | What You Can Test |
| :--- | :--- | :--- | :--- |
| **Admin** | `testadmin@gmail.com` | `12345678` | Manage user roles, passwords, suspend/restore accounts, delete facilities |
| **Editor** | `testeditor@gmail.com` | `12345678` | Create facilities directly, review and approve user proposals in Location Logs |
| **User** | `testuser@gmail.com` | `12345678` | Reserve slots, chat with the assistant, save locations, propose new facilities |

---

## 🔌 Running with Wokwi Simulation

Don't have an ESP32 board? You can run the entire hardware circuit in the cloud with [Wokwi](https://wokwi.com)!

### Step A: Start the Wokwi Tunnel
Start Cloudflare Tunnel using any of the methods above (e.g., `START_WOKWI_TUNNEL.bat` or `python tunnel_runner.py`).

### Step B: Launch Wokwi
1. Open [Wokwi](https://wokwi.com) and create or open an **ESP32 MicroPython** project.
2. Replace `diagram.json` with the project's [`diagram.json`](diagram.json).
3. Copy and paste the project firmware files into the Wokwi editor:
   * [`main.py`](main.py)
   * [`parksense_logic.py`](parksense_logic.py)
   * [`hcsr04.py`](hcsr04.py)
   * [`servo.py`](servo.py)
   * [`ssd1306.py`](ssd1306.py)
4. Click the green **Play** button!
   * The OLED will light up showing available spots.
   * Telemetry will start flowing directly to your live dashboard.
   * Reserving a slot in your browser will light up the Yellow LED in Wokwi!

---

## 🧰 Hardware Pinout Reference (ESP32)

If you are wiring a physical breadboard or custom PCB, connect the components as follows:

| Component | Pin Function | ESP32 GPIO |
| :--- | :--- | :--- |
| **Slot 1 (S1) Ultrasonic** | TRIG / ECHO | GPIO 16 / GPIO 34 |
| **Slot 2 (S2) Ultrasonic** | TRIG / ECHO | GPIO 17 / GPIO 35 |
| **Slot 3 (S3) Ultrasonic** | TRIG / ECHO | GPIO 18 / GPIO 36 |
| **Slot 4 (S4) Ultrasonic** | TRIG / ECHO | GPIO 19 / GPIO 39 |
| **Entry Gate Ultrasonic** | TRIG / ECHO | GPIO 23 / GPIO 32 |
| **Exit Gate Ultrasonic** | TRIG / ECHO | GPIO 26 / GPIO 33 |
| **Barrier Gate Servo (SG90)** | PWM Signal | GPIO 25 |
| **74HC595 Shift Register** | DATA (DS) / CLK (SHCP) / LATCH (STCP) | GPIO 13 / GPIO 14 / GPIO 12 |
| **SSD1306 OLED (128x64)** | I2C SDA / SCL | GPIO 21 / GPIO 22 |
| **Status Buzzer** | Signal | GPIO 27 |

---

## 📁 Project Directory Structure

```text
PARKSENSE/
│
├── backend/                  # 🐍 Backend API & Intelligence
│   ├── backend.py            # Flask API, JWT auth, and IoT telemetry ingestion
│   ├── assistant_engine.py   # Offline AI Assistant engine with context & intent matching
│   ├── parksense.db          # SQLite database storage
│   └── requirements.txt      # Python dependencies
│
├── frontend/                 # 🌐 Client Web Application
│   ├── index.html            # Main single-page interface
│   ├── script.js             # Client UI logic, live polling, and reactive state
│   ├── style.css             # Responsive styling for desktop and mobile
│   └── assets/               # Logos and static images
│       └── parksense-logo-white.png
│
├── firmware/                 # ⚡ ESP32 MicroPython & Wokwi Circuit
│   ├── main.py               # ESP32 main loop & HTTP telemetry client
│   ├── parksense_logic.py    # Edge decision & shift register logic
│   ├── hcsr04.py             # MicroPython driver for HC-SR04 ultrasonic sensors
│   ├── servo.py              # MicroPython driver for SG90 servo motor
│   ├── ssd1306.py            # MicroPython driver for I2C OLED display
│   ├── diagram.json          # Complete Wokwi circuit schematic definition
│   ├── wokwi-project.txt     # Wokwi project reference
│   └── wokwi.toml            # Wokwi simulator configuration
│
├── tools/                    # 🛠️ Launchers & Automation
│   ├── tunnel_runner.py      # Cloudflare tunnel automation & main.py sync
│   ├── cloudflared.exe       # Cloudflare tunnel binary
│   └── START_WOKWI_TUNNEL.bat# Tool batch launcher
│
├── tests/                    # 🧪 Automated Testing
│   └── test_e2e_integration.py # 22-point comprehensive automated system test suite
│
├── START_BACKEND.bat         # 1-click Windows launcher for Flask backend
├── START_WOKWI_TUNNEL.bat    # 1-click Windows launcher for Cloudflare tunnel
├── wokwi.toml                # Root Wokwi configuration file
├── requirements.txt          # Python package dependencies
├── README.md                 # Project documentation and guide
├── LICENSE                   # MIT License
└── .gitignore                # Git ignore rules
```

---

## 🧪 Comprehensive Automated Testing

ParkSense includes an automated 22-point end-to-end integration test suite covering the entire stack:
* Backend asset serving & Cloudflare tunnel verification
* Multi-role authentication & RBAC boundary checks
* User management, account suspension, and password updates
* Facility proposals, editor approvals, and admin deletions
* Real-time telemetry ingestion and slot vacancy calculations
* Shift register LED bitmask logic (Green / Red / Yellow)
* 5-minute reservations, concurrency locks, and auto-completion
* Stale hardware fail-safe detection
* Gate servo logic (arrival, exit priority, and lot-full lockout)
* AI Assistant privacy filters and natural language responses

To run the full suite:
```bash
python tests/test_e2e_integration.py
```

Expected result:
```text
======================================================================
  ALL 22 HIGH-VOLUME END-TO-END INTEGRATION TESTS PASSED SUCCESSFULLY!
  VERIFIED: FLASK, SQLITE, RBAC (3 ROLES), HARDWARE SYNC & AI ASSISTANT
======================================================================
```

---

## 🛡️ Security & Privacy

* **Password Security:** Passwords are protected using cryptographic hashing algorithms.
* **Token Authentication:** Secure JWT tokens handle authenticated sessions with strict expiration.
* **Bot & Abuse Protection:** Built-in sliding-window rate limiting protects the API from automated attacks and malicious scanners.
* **Driver Privacy:** The system monitors distance in centimeters—no cameras, facial recognition, or license plate tracking are used.

---

## 🤝 Contributing

Contributions, feedback, and suggestions are warmly welcome!
1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License & Acknowledgments

This project was created and tested by **[@mdanas-git](https://github.com/mdanas-git)** as a practical exploration into end-to-end IoT systems, developed with the support of modern pair-programming tools and open hardware platforms:

* **Concept & Direction:** Conceived, tested, and guided by [@mdanas-git](https://github.com/mdanas-git).
* **AI Pair Programming:** Architecture suggestions, code implementation, and test scaffolding assisted by Google DeepMind's Antigravity assistant.
* **Hardware Simulation:** [Wokwi](https://wokwi.com/) for ESP32 MicroPython circuit modeling and sensor simulation.
* **IoT Tunneling:** [Cloudflare Tunnels](https://www.cloudflare.com/) for secure local-to-cloud device connectivity.

Released under the **[MIT License](LICENSE)** — feel free to study, fork, or build upon this project!

Developed with ❤️ by **[@mdanas-git](https://github.com/mdanas-git)**.


