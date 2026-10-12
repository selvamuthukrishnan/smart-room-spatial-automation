import cv2
import time
import math
import threading
import requests
import numpy as np
from flask import Flask, render_template_string, jsonify, request
from ultralytics import YOLO

# =================================================================================
# PROJECT: Spatial AI Power Automation - Smart Classroom System
# =================================================================================

# --- 📱 CAMERA & ESP32 CONFIGURATION ---
# Change to your phone's IP Webcam URL e.g. "http://192.168.43.1:8080/video", or 0 for webcam
CAMERA_SOURCE = 0  
ESP32_IP = "http://192.168.43.125"

# --- 🎯 CLASSROOM APPLIANCES REGISTRY (Extracted from Reference Frame) ---
# Each appliance has its calibrated position, zone proximity, and live states:
APPLIANCES = {
    # TOP ROW CEILING FANS
    "fan_top_left": {
        "name": "Fan 1 (Top Left)",
        "type": "fan",
        "roi": (25, 200, 235, 220),       # (x, y, w, h)
        "zone_centroid": (150, 480),     # Associated seating area on floor
        "vision_state": "OFF",           # Vision detected: ON (Spinning) / OFF (Still)
        "control_state": False           # Relayed control: True (Active) / False
    },
    "fan_top_center": {
        "name": "Fan 2 (Top Center)",
        "type": "fan",
        "roi": (415, 200, 230, 225),
        "zone_centroid": (530, 480),
        "vision_state": "OFF",
        "control_state": False
    },
    "fan_top_right": {
        "name": "Fan 3 (Top Right)",
        "type": "fan",
        "roi": (860, 190, 230, 230),
        "zone_centroid": (970, 480),
        "vision_state": "OFF",
        "control_state": False
    },

    # MIDDLE ROW CEILING FANS
    "fan_mid_left": {
        "name": "Fan 4 (Row 2 Left)",
        "type": "fan",
        "roi": (260, 500, 130, 130),
        "zone_centroid": (320, 650),
        "vision_state": "OFF",
        "control_state": False
    },
    "fan_mid_center": {
        "name": "Fan 5 (Row 2 Center)",
        "type": "fan",
        "roi": (515, 500, 140, 135),
        "zone_centroid": (580, 650),
        "vision_state": "OFF",
        "control_state": False
    },
    "fan_mid_right": {
        "name": "Fan 6 (Row 2 Right)",
        "type": "fan",
        "roi": (805, 510, 155, 140),
        "zone_centroid": (880, 650),
        "vision_state": "OFF",
        "control_state": False
    },

    # LIGHT FIXTURES
    "light_left": {
        "name": "Light 1 (Wall Lamp Left)",
        "type": "light",
        "roi": (80, 520, 95, 110),
        "zone_centroid": (150, 650),
        "vision_state": "OFF",
        "control_state": False
    },
    "light_center_tube": {
        # 💡 THE CENTER TUBE LIGHT (Now Calibrated & Integrated!)
        "name": "Light 2 (Center Tube Light)",
        "type": "light",
        "roi": (740, 485, 210, 45),     # Horizontal glowing fluorescent tube
        "zone_centroid": (840, 600),
        "vision_state": "OFF",
        "control_state": False
    }
}

# --- GLOBAL VARIABLES & LOCKS ---
prev_gray_frame = None
latest_frame = None
lock = threading.Lock()
PROXIMITY_RADIUS = 280
SCAN_INTERVAL_SEC = 10.0
last_scan_time = 0

# --- INITIALIZE FLASK DASHBOARD ---
app = Flask(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Classroom AI Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background: #0f172a; color: #f8fafc; padding: 25px; }
        header { text-align: center; margin-bottom: 30px; }
        h1 { color: #38bdf8; font-size: 28px; margin-bottom: 8px; }
        p.subtitle { color: #94a3b8; font-size: 14px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; max-width: 1300px; margin: 0 auto; }
        .card { background: #1e293b; border-radius: 14px; padding: 20px; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); transition: all 0.3s; }
        .card:hover { transform: translateY(-3px); border-color: #38bdf8; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .card-title { font-size: 16px; font-weight: 600; color: #e2e8f0; }
        .badge { padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; text-transform: uppercase; }
        .badge-on { background: #166534; color: #4ade80; border: 1px solid #22c55e; }
        .badge-off { background: #334155; color: #94a3b8; border: 1px solid #475569; }
        .status-box { background: #0f172a; border-radius: 8px; padding: 12px; margin-bottom: 15px; font-size: 13px; line-height: 1.6; }
        .status-box span { font-weight: 600; }
        .btn-toggle { width: 100%; padding: 10px; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .btn-active { background: #ef4444; color: white; }
        .btn-active:hover { background: #dc2626; }
        .btn-idle { background: #3b82f6; color: white; }
        .btn-idle:hover { background: #2563eb; }
        .banner { background: #1e1b4b; border: 1px solid #6366f1; border-radius: 10px; padding: 15px; margin: 0 auto 25px auto; max-width: 1300px; display: flex; justify-content: space-between; align-items: center; }
    </style>
</head>
<body>
    <header>
        <h1>⚡ Smart Classroom AI Spatial Dashboard</h1>
        <p class="subtitle">Real-time Vision Status Detection & Capacity-based Appliance Automation</p>
    </header>

    <div class="banner">
        <div>
            <strong style="color: #a5b4fc;">Live Detection Status:</strong>
            <span id="scan-timer" style="color: #fbcfe8; margin-left: 10px;">Scanning every 10 seconds...</span>
        </div>
        <div style="font-size: 13px; color: #cbd5e1;">Connected ESP32: <code>{{ esp32_ip }}</code></div>
    </div>

    <div class="grid" id="appliances-grid">
        <!-- Rendered dynamically via JavaScript -->
    </div>

    <script>
        function updateDashboard() {
            fetch('/api/status')
                .then(res => res.json())
                .then(data => {
                    const grid = document.getElementById('appliances-grid');
                    grid.innerHTML = '';
                    
                    for (const [key, item] of Object.entries(data.appliances)) {
                        const isVisionOn = item.vision_state.includes('ON');
                        const isControlOn = item.control_state;

                        const card = document.createElement('div');
                        card.className = 'card';
                        card.innerHTML = `
                            <div class="card-header">
                                <span class="card-title">${item.type === 'fan' ? '🌀' : '💡'} ${item.name}</span>
                                <span class="badge ${isVisionOn ? 'badge-on' : 'badge-off'}">${item.vision_state}</span>
                            </div>
                            <div class="status-box">
                                <div>Physical Status: <span style="color: ${isVisionOn ? '#4ade80' : '#94a3b8'}">${item.vision_state}</span></div>
                                <div>System Output: <span style="color: ${isControlOn ? '#38bdf8' : '#64748b'}">${isControlOn ? 'ENERGIZED (ON)' : 'POWER SAVING (OFF)'}</span></div>
                            </div>
                            <button class="btn-toggle ${isControlOn ? 'btn-active' : 'btn-idle'}" onclick="toggleAppliance('${key}')">
                                ${isControlOn ? 'Power OFF' : 'Power ON'}
                            </button>
                        `;
                        grid.appendChild(card);
                    }
                });
        }

        function toggleAppliance(key) {
            fetch('/api/toggle', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({appliance: key})
            }).then(() => updateDashboard());
        }

        setInterval(updateDashboard, 1500);
        updateDashboard();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML, esp32_ip=ESP32_IP)

@app.route("/api/status")
def api_status():
    with lock:
        return jsonify({"appliances": APPLIANCES})

@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    data = request.json
    key = data.get("appliance")
    with lock:
        if key in APPLIANCES:
            APPLIANCES[key]["control_state"] = not APPLIANCES[key]["control_state"]
    return jsonify({"success": True})

def start_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

# Start Dashboard in a background thread
flask_thread = threading.Thread(target=start_flask, daemon=True)
flask_thread.start()
print("[DASHBOARD] Web Dashboard running live at http://localhost:5000")

# --- VISION ON / OFF DETECTION ENGINES ---
def detect_fan_spinning(curr_gray, prev_gray, roi):
    """
    Detects if fan is ON (Spinning) vs OFF (Still) using inter-frame motion energy
    """
    x, y, w, h = roi
    # Clamp inside frame
    fh, fw = curr_gray.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)

    if x2 <= x1 or y2 <= y1:
        return "OFF"

    crop_curr = curr_gray[y1:y2, x1:x2]
    crop_prev = prev_gray[y1:y2, x1:x2]

    # Absolute difference between consecutive frames inside the fan ROI
    diff = cv2.absdiff(crop_curr, crop_prev)
    _, thresh = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
    motion_score = np.mean(thresh)

    # If motion energy > 3.5, fan blades are rotating fast
    return "ON (SPINNING)" if motion_score > 3.5 else "OFF (STILL)"

def detect_light_illuminated(frame, roi):
    """
    Detects if light is ON (Glowing) vs OFF (Dark) using pixel luminance & threshold
    """
    x, y, w, h = roi
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)

    if x2 <= x1 or y2 <= y1:
        return "OFF"

    crop = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    
    # Calculate average luminance & top highlight percentile
    mean_val = np.mean(gray)
    bright_percentile = np.percentile(gray, 90)

    # Illuminated fluorescent tubes have severe highlight saturation
    if mean_val > 175 or bright_percentile > 230:
        return "ON (GLOWING)"
    else:
        return "OFF (DARK)"

# --- MAIN AI COMPUTER VISION LOOP ---
print("[AI SERVER] Initializing YOLO-World Model...")
model = YOLO("yolov8s-world.pt")
model.set_classes(["person", "ceiling fan", "tube light", "lamp", "fluorescent light"])

cap = cv2.VideoCapture(CAMERA_SOURCE)
window_name = "Spatial AI Smart Classroom Vision Monitor"
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

print("\n=======================================================")
print(" SMART CLASSROOM SPATIAL AI ENGINE ACTIVE             ")
print(" Dashboard URL: http://localhost:5000                 ")
print(" Press 'q' or 'ESC' to exit cleanly                   ")
print("=======================================================\n")

while True:
    ret, frame = cap.read()
    if not ret or frame is None:
        time.sleep(0.1)
        continue

    curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if prev_gray_frame is None:
        prev_gray_frame = curr_gray.copy()

    current_time = time.time()
    time_since_last_scan = current_time - last_scan_time
    remaining_time = max(0.0, SCAN_INTERVAL_SEC - time_since_last_scan)

    # 1. Real-time Physical Vision Status Detection (Runs every frame)
    with lock:
        for key, item in APPLIANCES.items():
            if item["type"] == "fan":
                item["vision_state"] = detect_fan_spinning(curr_gray, prev_gray_frame, item["roi"])
            elif item["type"] == "light":
                item["vision_state"] = detect_light_illuminated(frame, item["roi"])

    prev_gray_frame = curr_gray.copy()

    # 2. 10-Second Spatial Proximity Scan (Human Detection & Automation)
    if time_since_last_scan >= SCAN_INTERVAL_SEC:
        last_scan_time = current_time
        print(f"\n[AI SCANNER] Evaluating occupancy at {time.strftime('%H:%M:%S')}...")

        results = model(frame, verbose=False)[0]
        detected_humans = []

        for box in results.boxes:
            label = results.names[int(box.cls[0])].lower()
            if "person" in label and float(box.conf[0]) > 0.28:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                hx, hy = int((x1 + x2) / 2), int(y2)
                detected_humans.append((hx, hy))

        # Check occupancy under each appliance zone
        with lock:
            for key, item in APPLIANCES.items():
                zx, zy = item["zone_centroid"]
                occupied = False
                for (hx, hy) in detected_humans:
                    if math.hypot(hx - zx, hy - zy) < PROXIMITY_RADIUS:
                        occupied = True
                        break
                item["control_state"] = occupied

    # 3. Render Visual Overlays on Video Feed
    with lock:
        # Draw Appliances Bounding Boxes & Real-time Vision Status
        for key, item in APPLIANCES.items():
            x, y, w, h = item["roi"]
            is_on = "ON" in item["vision_state"]
            color = (0, 255, 0) if is_on else (80, 80, 80)
            
            # Box around fan or tube light
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, f"{item['name']}: {item['vision_state']}", 
                        (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)

            # Zone circle on seating area
            zx, zy = item["zone_centroid"]
            active_color = (0, 255, 255) if item["control_state"] else (60, 60, 60)
            cv2.circle(frame, (zx, zy), 25, active_color, 2)

    # Top Status Banner
    banner_bg = (20, 20, 30)
    cv2.rectangle(frame, (10, 10), (520, 50), banner_bg, -1)
    status_text = f"Dashboard: http://localhost:5000 | Next Scan: {remaining_time:.1f}s"
    cv2.putText(frame, status_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

    cv2.imshow(window_name, frame)

    # Quit logic
    key = cv2.waitKey(20) & 0xFF
    if key in [ord('q'), ord('Q'), 27]:
        break
    if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
        break

cap.release()
cv2.destroyAllWindows()
print("[SHUTDOWN] System exited successfully.")