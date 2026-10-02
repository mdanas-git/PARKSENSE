"""
ParkSense Wokwi Tunnel Runner
Author: mdanas-git (https://github.com/mdanas-git)
Launches Cloudflare tunnel, retrieves public HTTPS endpoint, and synchronizes ESP32 config.
"""

import os
import re
import shutil
import subprocess
import sys
import time

workspace = os.path.dirname(os.path.abspath(__file__))
cloudflared_path = os.path.join(workspace, "cloudflared.exe")

if not os.path.exists(cloudflared_path):
    which_bin = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if which_bin:
        cloudflared_path = which_bin
    else:
        # Check standard installation paths (e.g. winget, Program Files)
        std_candidates = [
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "cloudflared", "cloudflared.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "cloudflared", "cloudflared.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", "cloudflared.exe"),
            os.path.abspath(os.path.join(workspace, "..", "cloudflared.exe")),
        ]
        for cand in std_candidates:
            if os.path.exists(cand):
                cloudflared_path = cand
                break

if not os.path.exists(cloudflared_path):
    print(f"Error: cloudflared.exe not found in {workspace} or PATH.")
    input("Press Enter to exit...")
    sys.exit(1)

print("=" * 65)
print("     PARKSENSE -- WOKWI HARDWARE INTEGRATION TUNNEL")
print("=" * 65)
print("\nStarting Cloudflare Tunnel to local Flask backend (port 5000)...")
print("Please wait a few seconds for Cloudflare to assign a public URL...\n")

# Start cloudflared as a child process
proc = subprocess.Popen(
    [cloudflared_path, "tunnel", "--url", "http://localhost:5000"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
    cwd=workspace
)

tunnel_url = None
url_regex = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

# Read output line by line until URL is found
for line in iter(proc.stdout.readline, ""):
    sys.stdout.write(line)
    sys.stdout.flush()
    if not tunnel_url:
        match = url_regex.search(line)
        if match:
            tunnel_url = match.group(0)
            
            # Automatically update main.py and test_e2e_integration.py across modular and root locations
            targets = [
                os.path.join(workspace, "main.py"),
                os.path.join(workspace, "firmware", "main.py"),
                os.path.join(workspace, "test_e2e_integration.py"),
                os.path.join(workspace, "tests", "test_e2e_integration.py"),
                os.path.join(workspace, "..", "firmware", "main.py"),
                os.path.join(workspace, "..", "main.py"),
                os.path.join(workspace, "..", "tests", "test_e2e_integration.py"),
                os.path.join(workspace, "..", "test_e2e_integration.py"),
            ]
            for extra_dir in [
                os.path.abspath(os.path.join(workspace, "..", "Parksense")),
                os.path.abspath(os.path.join(workspace, "..", "PARKSENSE_WOKWI")),
                os.path.abspath(os.path.join(workspace, "..")),
            ]:
                if os.path.isdir(extra_dir):
                    targets.extend([
                        os.path.join(extra_dir, "main.py"),
                        os.path.join(extra_dir, "firmware", "main.py"),
                        os.path.join(extra_dir, "test_e2e_integration.py"),
                        os.path.join(extra_dir, "tests", "test_e2e_integration.py"),
                    ])
            seen = set()
            for target in targets:
                target_norm = os.path.normpath(target).lower()
                if target_norm in seen:

                    continue
                seen.add(target_norm)
                if os.path.exists(target):
                    try:
                        with open(target, "r", encoding="utf-8") as f:
                            c = f.read()
                        c = re.sub(
                            r'BACKEND_BASE_URL\s*=\s*["\'][^"\']+["\']',
                            f'BACKEND_BASE_URL = "{tunnel_url}"',
                            c
                        )
                        c = re.sub(
                            r'TUNNEL_URL\s*=\s*["\'][^"\']+["\']',
                            f'TUNNEL_URL = "{tunnel_url}"',
                            c
                        )
                        with open(target, "w", encoding="utf-8") as f:
                            f.write(c)
                    except Exception as err:
                        print(f"Notice: could not update {target}: {err}")

            # Try to copy to Windows clipboard
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{tunnel_url}'"],
                    capture_output=True,
                    timeout=2
                )
                copied_msg = "(COPIED TO CLIPBOARD AUTOMATICALLY!)"
            except Exception:
                copied_msg = ""

            print("\n" + "#" * 65)
            print("  WOKWI TUNNEL IS NOW ACTIVE AND CONNECTED TO FLASK!")
            print("#" * 65)
            print(f"\n  >> PUBLIC URL: {tunnel_url}")
            if copied_msg:
                print(f"     {copied_msg}")
            print("\n  NEXT STEPS:")
            print("  1. In Wokwi editor, open 'main.py' and verify Line 42:")
            print(f"     BACKEND_BASE_URL = \"{tunnel_url}\"")
            print("  2. Click the green Restart / Play button in Wokwi.")
            print("  3. Your Wokwi circuit will now stream telemetry to Flask!")
            print(f"  4. Open your ParkSense website anywhere (phone, PC, laptop):")
            print(f"     >> {tunnel_url}")
            print("     (Also accessible locally at http://localhost:5000 or http://localhost:8000)")
            print("\n  DO NOT CLOSE THIS TERMINAL WINDOW while using Wokwi!")
            print("#" * 65 + "\n")

proc.wait()
