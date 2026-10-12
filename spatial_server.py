import os
import json
import cv2
import time
import math
import socket
import threading
import requests
import numpy as np
from flask import Flask, Response, jsonify, request, render_template_string
from ultralytics import YOLO

# =================================================================================
# PROJECT: Spatial AI Smart Room - Server with Auto-Shift & Calibration UI
# =================================================================================

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "appliances_config.json")

def get_local_ip():
    """Dynamically finds the laptop's actual IP address on Wi-Fi / Hotspot network"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

# --- 📱 CAMERA & ESP32 CONFIGURATION ---
CAMERA_SOURCE = 0  # 0 for webcam or "http://<PHONE_IP>:8080/video"
ESP32_IP = "http://192.168.43.125"

# --- 🎯 LOAD APPLIANCES CONFIGURATION ---
def load_appliances():
    default_config = {
        "fan_top_left": {"name": "Fan 1 (Top Left)", "type": "fan", "roi": [25, 200, 235, 220], "zone_centroid": [150, 480]},
        "fan_top_center": {"name": "Fan 2 (Top Center)", "type": "fan", "roi": [415, 200, 230, 225], "zone_centroid": [530, 480]},
        "fan_top_right": {"name": "Fan 3 (Top Right)", "type": "fan", "roi": [860, 190, 230, 230], "zone_centroid": [970, 480]},
        "fan_mid_left": {"name": "Fan 4 (Row 2 Left)", "type": "fan", "roi": [260, 500, 130, 130], "zone_centroid": [320, 650]},
        "fan_mid_center": {"name": "Fan 5 (Row 2 Center)", "type": "fan", "roi": [515, 500, 140, 135], "zone_centroid": [580, 650]},
        "fan_mid_right": {"name": "Fan 6 (Row 2 Right)", "type": "fan", "roi": [805, 510, 155, 140], "zone_centroid": [880, 650]},
        "light_left": {"name": "Light 1 (Wall Lamp Left)", "type": "light", "roi": [80, 520, 95, 110], "zone_centroid": [150, 650]},
        "light_center_tube": {"name": "Light 2 (Center Tube Light)", "type": "light", "roi": [740, 485, 210, 45], "zone_centroid": [840, 600]}
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for k, v in loaded.items():
                    v["vision_state"] = "OFF"
                    v["control_state"] = False
                return loaded
        except Exception as e:
            print(f"[CONFIG] Error loading {CONFIG_FILE}: {e}")
    for k, v in default_config.items():
        v["vision_state"] = "OFF"
        v["control_state"] = False
    return default_config

def save_appliances_to_disk(config_data):
    clean_data = {}
    for k, v in config_data.items():
        clean_data[k] = {
            "name": v.get("name", k),
            "type": v.get("type", "fan"),
            "roi": list(v.get("roi", [100, 100, 150, 150])),
            "zone_centroid": list(v.get("zone_centroid", [100, 200]))
        }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_data, f, indent=2)
    print(f"[CONFIG] Saved {len(clean_data)} appliances to {CONFIG_FILE}")

APPLIANCES = load_appliances()
WORKSTATION_UNITS = [False] * 10

# --- GLOBAL THREADING STATE ---
latest_frame = None
raw_camera_frame = None
prev_gray_frame = None
ref_gray_32f = None
camera_shift_x = 0
camera_shift_y = 0
lock = threading.Lock()
PROXIMITY_RADIUS = 280
SCAN_INTERVAL_SEC = 10.0
last_scan_time = 0
humans_detected_count = 0
remaining_time_global = 10.0

# --- INITIALIZE FLASK SERVER ---
app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/")
@app.route("/dashboard")
@app.route("/dashboard.html")
def serve_index_html():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content, mimetype="text/html")
    return "Error: index.html not found", 404

# --- 🎯 INTERACTIVE VISUAL CALIBRATION PAGE ---
CALIBRATION_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Room Appliance Visual Calibration</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .crosshair-cur { cursor: crosshair; }
        .canvas-container { position: relative; display: inline-block; }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-4 md:p-6 font-sans">
    <div class="max-w-7xl mx-auto space-y-5">
        <!-- HEADER -->
        <header class="flex flex-col md:flex-row justify-between items-start md:items-center pb-4 border-b border-slate-800 gap-4">
            <div>
                <h1 class="text-2xl font-bold text-sky-400 flex items-center gap-2">
                    <span>🎯</span> Interactive Appliance Calibration
                </h1>
                <p class="text-sm text-slate-400 mt-1">
                    Click anywhere on the camera frame to place a box for any Fan 🌀 or Light 💡!
                </p>
            </div>
            <div class="flex gap-3">
                <button onclick="resetCameraShift()" class="px-4 py-2 bg-amber-600 hover:bg-amber-500 rounded-lg text-sm font-semibold transition">
                    🔄 Reset Auto-Shift
                </button>
                <a href="/" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm font-semibold transition flex items-center gap-2">
                    <span>🏠</span> Back to Dashboard
                </a>
            </div>
        </header>

        <!-- MAIN LAYOUT -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- CANVAS AREA -->
            <div class="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl">
                <div class="flex justify-between items-center mb-3">
                    <span class="text-xs uppercase tracking-wider font-bold text-slate-400">Live Video Canvas (Click to Place Box)</span>
                    <span id="shift-indicator" class="text-xs font-mono text-emerald-400 bg-emerald-950/60 px-2.5 py-1 rounded border border-emerald-800">
                        Camera Shift: (0px, 0px)
                    </span>
                </div>
                <div class="canvas-container overflow-hidden rounded-xl border border-slate-700 w-full flex justify-center bg-black">
                    <canvas id="calib-canvas" class="crosshair-cur max-w-full h-auto shadow-inner"></canvas>
                </div>
                <p class="text-xs text-slate-500 mt-2 text-center">
                    💡 Click on a fan or light on the screen &bull; Drag to resize or adjust in the panel &bull; Click Save when done.
                </p>
            </div>

            <!-- APPLIANCE CONTROL PANEL -->
            <div class="space-y-4">
                <!-- ACTIVE SELECTION EDITOR -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl">
                    <h3 class="text-base font-bold text-white mb-3 flex items-center gap-2">
                        <span>✏️</span> Add / Edit Appliance
                    </h3>
                    
                    <div class="space-y-3.5 text-sm">
                        <div>
                            <label class="text-xs text-slate-400">Appliance Name:</label>
                            <input id="prop-name" type="text" placeholder="e.g. Fan 1 (Top Left)" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-sky-500 mt-1">
                        </div>

                        <div>
                            <label class="text-xs text-slate-400">Appliance Type:</label>
                            <div class="grid grid-cols-2 gap-2 mt-1">
                                <button type="button" id="btn-type-fan" onclick="setType('fan')" class="py-2 px-3 rounded-lg border border-sky-500 bg-sky-950/60 text-sky-300 font-semibold flex items-center justify-center gap-1.5">
                                    <span>🌀</span> Ceiling Fan
                                </button>
                                <button type="button" id="btn-type-light" onclick="setType('light')" class="py-2 px-3 rounded-lg border border-slate-700 bg-slate-950 text-slate-400 font-semibold flex items-center justify-center gap-1.5">
                                    <span>💡</span> Tube Light
                                </button>
                            </div>
                        </div>

                        <div class="grid grid-cols-2 gap-2 pt-1">
                            <div>
                                <label class="text-xs text-slate-400">Width (px): <span id="val-w" class="text-sky-400 font-mono">200</span></label>
                                <input id="prop-w" type="range" min="40" max="450" value="200" oninput="updatePropSize()" class="w-full mt-1">
                            </div>
                            <div>
                                <label class="text-xs text-slate-400">Height (px): <span id="val-h" class="text-sky-400 font-mono">200</span></label>
                                <input id="prop-h" type="range" min="30" max="450" value="200" oninput="updatePropSize()" class="w-full mt-1">
                            </div>
                        </div>

                        <button onclick="commitActiveAppliance()" class="w-full py-2.5 bg-sky-600 hover:bg-sky-500 text-white rounded-lg font-bold transition shadow-lg shadow-sky-900/30">
                            ➕ Add to List
                        </button>
                    </div>
                </div>

                <!-- CONFIGURED APPLIANCES LIST -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl max-h-[380px] flex flex-col">
                    <div class="flex justify-between items-center mb-3 pb-2 border-b border-slate-800">
                        <span class="text-xs uppercase font-bold text-slate-400">Mapped Appliances (<span id="appliance-count">0</span>)</span>
                        <button onclick="clearAllAppliances()" class="text-xs text-red-400 hover:text-red-300">Clear All</button>
                    </div>
                    
                    <div id="appliances-list" class="space-y-2 overflow-y-auto flex-1 pr-1 text-xs">
                        <!-- Populated by JS -->
                    </div>

                    <button onclick="saveAllToBackend()" class="w-full mt-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-bold transition shadow-lg shadow-emerald-900/30">
                        💾 Save Calibration Permanently
                    </button>
                </div>
            </div>
        </div>
    </div>

    <script>
        const canvas = document.getElementById('calib-canvas');
        const ctx = canvas.getContext('2d');
        const img = new Image();

        let currentType = 'fan';
        let appliances = {};
        let activeKey = null;
        let pendingClick = null;

        function refreshFrame() {
            img.src = '/video_feed?' + new Date().getTime();
        }

        img.onload = () => {
            if (canvas.width !== img.naturalWidth) {
                canvas.width = img.naturalWidth;
                canvas.height = img.naturalHeight;
            }
            redrawCanvas();
        };

        function redrawCanvas() {
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

            // Draw all configured appliances
            for (const [key, item] of Object.entries(appliances)) {
                const [x, y, w, h] = item.roi;
                const isSelected = (key === activeKey);

                ctx.strokeStyle = isSelected ? '#38bdf8' : (item.type === 'fan' ? '#22c55e' : '#eab308');
                ctx.lineWidth = isSelected ? 3 : 2;
                ctx.strokeRect(x, y, w, h);

                ctx.fillStyle = isSelected ? '#38bdf8' : (item.type === 'fan' ? '#22c55e' : '#eab308');
                ctx.font = 'bold 12px sans-serif';
                ctx.fillText(`${item.type === 'fan' ? '🌀' : '💡'} ${item.name}`, x + 4, y - 6 > 15 ? y - 6 : y + 16);
            }

            // Draw pending click preview
            if (pendingClick) {
                const w = parseInt(document.getElementById('prop-w').value);
                const h = parseInt(document.getElementById('prop-h').value);
                const x = pendingClick.x - Math.floor(w / 2);
                const y = pendingClick.y - Math.floor(h / 2);

                ctx.strokeStyle = '#f43f5e';
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 6]);
                ctx.strokeRect(x, y, w, h);
                ctx.setLineDash([]);
            }
        }

        canvas.addEventListener('click', (e) => {
            const rect = canvas.getBoundingClientRect();
            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;

            const clickX = Math.round((e.clientX - rect.left) * scaleX);
            const clickY = Math.round((e.clientY - rect.top) * scaleY);

            pendingClick = { x: clickX, y: clickY };
            const defaultName = (currentType === 'fan' ? 'Ceiling Fan ' : 'Tube Light ') + (Object.keys(appliances).length + 1);
            document.getElementById('prop-name').value = defaultName;
            redrawCanvas();
        });

        function setType(type) {
            currentType = type;
            const fanBtn = document.getElementById('btn-type-fan');
            const lightBtn = document.getElementById('btn-type-light');
            if (type === 'fan') {
                fanBtn.className = "py-2 px-3 rounded-lg border border-sky-500 bg-sky-950/60 text-sky-300 font-semibold flex items-center justify-center gap-1.5";
                lightBtn.className = "py-2 px-3 rounded-lg border border-slate-700 bg-slate-950 text-slate-400 font-semibold flex items-center justify-center gap-1.5";
                document.getElementById('prop-w').value = 200;
                document.getElementById('prop-h').value = 200;
            } else {
                lightBtn.className = "py-2 px-3 rounded-lg border border-amber-500 bg-amber-950/60 text-amber-300 font-semibold flex items-center justify-center gap-1.5";
                fanBtn.className = "py-2 px-3 rounded-lg border border-slate-700 bg-slate-950 text-slate-400 font-semibold flex items-center justify-center gap-1.5";
                document.getElementById('prop-w').value = 220;
                document.getElementById('prop-h').value = 50;
            }
            updatePropSize();
        }

        function updatePropSize() {
            document.getElementById('val-w').innerText = document.getElementById('prop-w').value;
            document.getElementById('val-h').innerText = document.getElementById('prop-h').value;
            redrawCanvas();
        }

        function commitActiveAppliance() {
            if (!pendingClick) {
                alert("Please click anywhere on the camera frame first to set position!");
                return;
            }
            const name = document.getElementById('prop-name').value.trim() || 'Appliance';
            const w = parseInt(document.getElementById('prop-w').value);
            const h = parseInt(document.getElementById('prop-h').value);
            const x = Math.max(0, pendingClick.x - Math.floor(w / 2));
            const y = Math.max(0, pendingClick.y - Math.floor(h / 2));
            const key = 'custom_' + currentType + '_' + Date.now();

            appliances[key] = {
                name: name,
                type: currentType,
                roi: [x, y, w, h],
                zone_centroid: [x + Math.floor(w / 2), y + h + 150]
            };

            pendingClick = null;
            renderList();
            redrawCanvas();
        }

        function deleteAppliance(key) {
            delete appliances[key];
            if (activeKey === key) activeKey = null;
            renderList();
            redrawCanvas();
        }

        function clearAllAppliances() {
            if (confirm("Clear all configured appliances?")) {
                appliances = {};
                activeKey = null;
                renderList();
                redrawCanvas();
            }
        }

        function renderList() {
            const list = document.getElementById('appliances-list');
            document.getElementById('appliance-count').innerText = Object.keys(appliances).length;
            list.innerHTML = '';

            for (const [key, item] of Object.entries(appliances)) {
                const el = document.createElement('div');
                el.className = 'flex justify-between items-center p-2.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-slate-700';
                el.innerHTML = `
                    <div>
                        <div class="font-bold text-white flex items-center gap-1.5">
                            <span>${item.type === 'fan' ? '🌀' : '💡'}</span> ${item.name}
                        </div>
                        <div class="text-[10px] text-slate-400 font-mono">
                            ROI: [${item.roi.join(', ')}]
                        </div>
                    </div>
                    <button onclick="deleteAppliance('${key}')" class="px-2 py-1 bg-red-950/80 text-red-400 border border-red-800/80 rounded hover:bg-red-900 transition">
                        Remove
                    </button>
                `;
                list.appendChild(el);
            }
        }

        function loadFromBackend() {
            fetch('/api/appliances')
                .then(r => r.json())
                .then(data => {
                    appliances = data.appliances || {};
                    renderList();
                    redrawCanvas();
                });
        }

        function saveAllToBackend() {
            fetch('/api/save_appliances', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ appliances: appliances })
            })
            .then(r => r.json())
            .then(res => {
                alert("🎉 Calibration saved successfully! All boxes updated live on Dashboard.");
            })
            .catch(e => alert("Error saving: " + e));
        }

        function resetCameraShift() {
            fetch('/api/reset_shift', { method: 'POST' })
                .then(r => r.json())
                .then(d => alert("Camera reference reset to current view."));
        }

        // Live shift monitoring
        setInterval(() => {
            fetch('/api/camera_shift')
                .then(r => r.json())
                .then(d => {
                    document.getElementById('shift-indicator').innerText = `Camera Shift: (${d.dx}px, ${d.dy}px)`;
                }).catch(() => {});
        }, 1000);

        setInterval(refreshFrame, 2000);
        loadFromBackend();
        refreshFrame();
    </script>
</body>
</html>
"""

@app.route("/calibrate")
def serve_calibrate():
    return render_template_string(CALIBRATION_HTML)

@app.route("/api/appliances")
def api_get_appliances():
    with lock:
        return jsonify({"appliances": APPLIANCES})

@app.route("/api/save_appliances", methods=["POST"])
def api_save_appliances():
    global APPLIANCES
    data = request.json
    new_appliances = data.get("appliances", {})
    with lock:
        for k, v in new_appliances.items():
            v["vision_state"] = "OFF"
            v["control_state"] = False
        APPLIANCES = new_appliances
        save_appliances_to_disk(APPLIANCES)
    return jsonify({"success": True})

@app.route("/api/camera_shift")
def api_camera_shift():
    with lock:
        return jsonify({"dx": camera_shift_x, "dy": camera_shift_y})

@app.route("/api/reset_shift", methods=["POST"])
def api_reset_shift():
    global ref_gray_32f, camera_shift_x, camera_shift_y
    with lock:
        ref_gray_32f = None
        camera_shift_x = 0
        camera_shift_y = 0
    return jsonify({"success": True})

def generate_video_stream():
    """Live MJPEG video streaming for dashboard & calibration"""
    while True:
        with lock:
            if latest_frame is None:
                time.sleep(0.04)
                continue
            ret, buffer = cv2.imencode(".jpg", latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                time.sleep(0.04)
                continue
            frame_bytes = buffer.tobytes()

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
        time.sleep(0.04)

@app.route("/video_feed")
def video_feed():
    return Response(generate_video_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/status")
@app.route("/status")
def api_status():
    """Unified API consumed by index.html and ESP32"""
    with lock:
        unit1_active = False
        unit2_active = False
        if "fan_top_left" in APPLIANCES and APPLIANCES["fan_top_left"]["control_state"]: unit1_active = True
        if "light_left" in APPLIANCES and APPLIANCES["light_left"]["control_state"]: unit1_active = True
        if "fan_top_center" in APPLIANCES and APPLIANCES["fan_top_center"]["control_state"]: unit2_active = True
        if "light_center_tube" in APPLIANCES and APPLIANCES["light_center_tube"]["control_state"]: unit2_active = True

        active_count = sum(1 for u in WORKSTATION_UNITS if u)
        energy_saved = int(round((1.0 - (max(active_count, 1) / 10.0)) * 100))

        return jsonify({
            "units": WORKSTATION_UNITS,
            "unit_1": {"active": unit1_active, "name": "Workstation 01 (Hardware Relay 1)"},
            "unit_2": {"active": unit2_active, "name": "Workstation 02 (Hardware Relay 2)"},
            "relay_1": unit1_active,
            "relay_2": unit2_active,
            "active_units": active_count,
            "energy_saved_percent": energy_saved,
            "humans_detected": humans_detected_count,
            "scan_seconds_remaining": f"{remaining_time_global:.1f}",
            "esp32_ip": ESP32_IP,
            "camera_shift": {"dx": camera_shift_x, "dy": camera_shift_y},
            "appliances": APPLIANCES
        })

@app.route("/api/update", methods=["GET", "POST"])
@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    global WORKSTATION_UNITS
    with lock:
        if request.is_json:
            data = request.json
            if "appliance" in data:
                key = data["appliance"]
                if key in APPLIANCES:
                    APPLIANCES[key]["control_state"] = not APPLIANCES[key]["control_state"]
            if "unit" in data:
                uid = int(data["unit"])
                if 0 <= uid < 10:
                    WORKSTATION_UNITS[uid] = not WORKSTATION_UNITS[uid]
        elif request.args:
            for k, v in request.args.items():
                if k.startswith("unit_"):
                    try:
                        idx = int(k.split("_")[1]) - 1
                        if 0 <= idx < 10:
                            WORKSTATION_UNITS[idx] = (v.lower() == "on")
                    except Exception:
                        pass
    return jsonify({"success": True})

def start_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

# Start web server thread
flask_thread = threading.Thread(target=start_flask, daemon=True)
flask_thread.start()

# --- VISION ON / OFF DETECTION ENGINES ---
def detect_fan_spinning(curr_gray, prev_gray, roi):
    x, y, w, h = roi
    fh, fw = curr_gray.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)

    if x2 <= x1 or y2 <= y1:
        return "OFF"

    crop_curr = curr_gray[y1:y2, x1:x2]
    crop_prev = prev_gray[y1:y2, x1:x2]

    diff = cv2.absdiff(crop_curr, crop_prev)
    _, thresh = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
    motion_score = np.mean(thresh)

    return "ON (SPINNING)" if motion_score > 3.5 else "OFF (STILL)"

def detect_light_illuminated(frame, roi):
    x, y, w, h = roi
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)

    if x2 <= x1 or y2 <= y1:
        return "OFF"

    crop = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    
    mean_val = np.mean(gray)
    bright_percentile = np.percentile(gray, 90)

    if mean_val > 175 or bright_percentile > 230:
        return "ON (GLOWING)"
    else:
        return "OFF (DARK)"

def send_esp32_hardware(relay1, relay2):
    try:
        url = f"{ESP32_IP}/control?light={'on' if relay1 else 'off'}&fan={'on' if relay2 else 'off'}"
        requests.get(url, timeout=0.8)
    except Exception:
        pass

# --- MAIN AI COMPUTER VISION LOOP ---
print("\n" + "="*70)
print(" 🚀 SPATIAL AI SMART ROOM - DIGITAL TWIN SERVER ACTIVE")
print("="*70)
print(f" 💻 Local Dashboard:       http://localhost:5000")
print(f" 🎯 Appliance Calibration: http://localhost:5000/calibrate")
print(f" 📱 Mobile Link:           http://{LOCAL_IP}:5000")
print(f" 🌐 Target ESP32 Hardware: {ESP32_IP}")
print("-" * 70)
print(" 💡 TIP: If the camera moves, open http://localhost:5000/calibrate to")
print("         click and adjust your appliance boxes in 5 seconds!")
print("="*70 + "\n")

print("[AI SERVER] Loading YOLO-World...")
model = YOLO("yolov8s-world.pt")
model.set_classes(["person", "ceiling fan", "tube light", "lamp", "fluorescent light"])

cap = cv2.VideoCapture(CAMERA_SOURCE)
window_name = "Spatial AI Smart Classroom Vision Monitor"
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

while True:
    ret, frame = cap.read()
    if not ret or frame is None:
        time.sleep(0.1)
        continue

    fh, fw = frame.shape[:2]
    curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    curr_gray_32f = np.float32(curr_gray)

    # =========================================================================
    # 🔄 AUTO-SHIFT DETECTION (Compensates if someone bumped/moved the phone!)
    # =========================================================================
    if ref_gray_32f is None:
        ref_gray_32f = curr_gray_32f.copy()
    else:
        try:
            # Phase correlation computes sub-pixel translation (dx, dy)
            shift, response = cv2.phaseCorrelate(ref_gray_32f, curr_gray_32f)
            # Only apply if confidence response is strong and shift is reasonable
            if response > 0.45 and (abs(shift[0]) < fw / 3 and abs(shift[1]) < fh / 3):
                camera_shift_x = int(round(-shift[0]))
                camera_shift_y = int(round(-shift[1]))
        except Exception:
            pass

    if prev_gray_frame is None:
        prev_gray_frame = curr_gray.copy()

    current_time = time.time()
    time_since_last_scan = current_time - last_scan_time
    remaining_time = max(0.0, SCAN_INTERVAL_SEC - time_since_last_scan)
    remaining_time_global = remaining_time

    # 1. Real-time Physical Vision Status Detection (Every frame with auto-shift offset)
    with lock:
        for key, item in APPLIANCES.items():
            ox, oy, ow, oh = item["roi"]
            # Apply auto-shift compensation
            sx = ox + camera_shift_x
            sy = oy + camera_shift_y
            shifted_roi = (sx, sy, ow, oh)

            if item["type"] == "fan":
                item["vision_state"] = detect_fan_spinning(curr_gray, prev_gray_frame, shifted_roi)
            elif item["type"] == "light":
                item["vision_state"] = detect_light_illuminated(frame, shifted_roi)

    prev_gray_frame = curr_gray.copy()

    # 2. 10-Second Spatial Proximity Scan (Human Detection)
    if time_since_last_scan >= SCAN_INTERVAL_SEC:
        last_scan_time = current_time
        results = model(frame, verbose=False)[0]
        detected_humans = []

        for box in results.boxes:
            label = results.names[int(box.cls[0])].lower()
            if "person" in label and float(box.conf[0]) > 0.28:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                hx, hy = int((x1 + x2) / 2), int(y2)
                detected_humans.append((hx, hy))

        with lock:
            humans_detected_count = len(detected_humans)
            for i, (key, item) in enumerate(APPLIANCES.items()):
                zx = item["zone_centroid"][0] + camera_shift_x
                zy = item["zone_centroid"][1] + camera_shift_y
                occupied = False
                for (hx, hy) in detected_humans:
                    if math.hypot(hx - zx, hy - zy) < PROXIMITY_RADIUS:
                        occupied = True
                        break
                item["control_state"] = occupied
                if i < 10:
                    WORKSTATION_UNITS[i] = occupied

        # Dispatch hardware commands to ESP32
        r1 = APPLIANCES.get("fan_top_left", {}).get("control_state", False) or APPLIANCES.get("light_left", {}).get("control_state", False)
        r2 = APPLIANCES.get("fan_top_center", {}).get("control_state", False) or APPLIANCES.get("light_center_tube", {}).get("control_state", False)
        send_esp32_hardware(r1, r2)

    # 3. Render Visual Overlays on Video Feed
    with lock:
        for key, item in APPLIANCES.items():
            ox, oy, ow, oh = item["roi"]
            x = ox + camera_shift_x
            y = oy + camera_shift_y
            is_on = "ON" in item["vision_state"]
            color = (0, 255, 0) if is_on else (80, 80, 80)
            
            cv2.rectangle(frame, (x, y), (x + ow, y + oh), color, 2)
            cv2.putText(frame, f"{item['name']}: {item['vision_state']}", 
                        (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)

            zx = item["zone_centroid"][0] + camera_shift_x
            zy = item["zone_centroid"][1] + camera_shift_y
            active_color = (0, 255, 255) if item["control_state"] else (60, 60, 60)
            cv2.circle(frame, (zx, zy), 25, active_color, 2)

        # Store latest frame for live web stream
        latest_frame = frame.copy()

    # Top Status Banner
    banner_bg = (20, 20, 30)
    cv2.rectangle(frame, (10, 10), (640, 50), banner_bg, -1)
    status_text = f"Calibrate: /calibrate | Shift: ({camera_shift_x},{camera_shift_y})px | Scan: {remaining_time:.1f}s"
    cv2.putText(frame, status_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 2)

    cv2.imshow(window_name, frame)

    key = cv2.waitKey(20) & 0xFF
    if key in [ord('q'), ord('Q'), 27]:
        break
    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
        break

cap.release()
cv2.destroyAllWindows()
print("[SHUTDOWN] System exited successfully.")