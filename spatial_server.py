import cv2
import time
import math
import requests
from ultralytics import YOLO

# =================================================================================
# PROJECT: Spatial AI Power-Efficient Automation Server
# DESCRIPTION:
#   - Captures a frame every 10 seconds from camera
#   - Detects moving humans and computes ground coordinates
#   - Checks proximity to localized appliance zones (Light, Fan, etc.)
#   - Dispatches Wi-Fi HTTP toggle signals to ESP32 node
# =================================================================================

ESP32_IP = "http://192.168.1.50"  # Set your ESP32's actual Wi-Fi IP address
FRAME_INTERVAL = 10                # Capture & analyze interval in seconds
PROXIMITY_RADIUS = 150             # Proximity threshold in pixels / metric units

# Predefined appliance zone centroids in camera view (X, Y)
APPLIANCE_ZONES = {
    "light": (320, 240),
    "fan":   (500, 300)
}

print("[AI SERVER] Initializing YOLOv8 model...")
model = YOLO("yolov8n.pt")

cap = cv2.VideoCapture(0)  # 0 for webcam, or RTSP/HTTP URL for external camera

def send_esp32_command(light_state, fan_state):
    url = f"{ESP32_IP}/control?light={'on' if light_state else 'off'}&fan={'on' if fan_state else 'off'}"
    try:
        response = requests.get(url, timeout=2)
        print(f"[WIFI] Dispatched to ESP32: Light={light_state}, Fan={fan_state} -> HTTP {response.status_code}")
    except Exception as e:
        print(f"[WIFI ERROR] ESP32 unreachable: {e}")

print("[AI SERVER] Server started! Capturing frames every 10 seconds...")

while True:
    ret, frame = cap.read()
    if not ret:
        print("[CAMERA] Error reading frame. Retrying...")
        time.sleep(2)
        continue

    # Detect humans (YOLO class 0 = person)
    results = model(frame, classes=[0], verbose=False)

    light_active = False
    fan_active = False

    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            # Feet contact point for ground-plane spatial proximity
            human_x = int((x1 + x2) / 2)
            human_y = int(y2)

            # Draw human bounding box & ground marker
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
            cv2.circle(frame, (human_x, human_y), 5, (0, 0, 255), -1)

            # Proximity calculation to Light Zone
            dist_light = math.hypot(human_x - APPLIANCE_ZONES["light"][0], human_y - APPLIANCE_ZONES["light"][1])
            if dist_light < PROXIMITY_RADIUS:
                light_active = True

            # Proximity calculation to Fan Zone
            dist_fan = math.hypot(human_x - APPLIANCE_ZONES["fan"][0], human_y - APPLIANCE_ZONES["fan"][1])
            if dist_fan < PROXIMITY_RADIUS:
                fan_active = True

    # Draw Appliance Zone Overlays
    cv2.circle(frame, APPLIANCE_ZONES["light"], 35, (0, 255, 0) if light_active else (128, 128, 128), 2)
    cv2.putText(frame, f"LIGHT: {'ON' if light_active else 'OFF'}", (APPLIANCE_ZONES["light"][0]-45, APPLIANCE_ZONES["light"][1]-45),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0) if light_active else (128, 128, 128), 2)

    cv2.circle(frame, APPLIANCE_ZONES["fan"], 35, (0, 255, 255) if fan_active else (128, 128, 128), 2)
    cv2.putText(frame, f"FAN: {'ON' if fan_active else 'OFF'}", (APPLIANCE_ZONES["fan"][0]-45, APPLIANCE_ZONES["fan"][1]-45),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255) if fan_active else (128, 128, 128), 2)

    # Render server monitor window
    cv2.imshow("Spatial AI Power Automation Monitor", frame)
    cv2.waitKey(1)

    # Dispatch wireless command to ESP32
    send_esp32_command(light_active, fan_active)

    # Wait for the next 10-second capture cycle
    print(f"[TIMER] Sleeping for {FRAME_INTERVAL} seconds...")
    time.sleep(FRAME_INTERVAL)
