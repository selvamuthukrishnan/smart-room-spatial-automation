# 🏠 Spatial AI Power-Efficient Smart Room Automation

A computer-vision-driven, power-efficient IoT automation system designed to eliminate energy wastage in classrooms, seminar halls, and laboratory environments using **Custom Fine-Tuned YOLOv8 Models**, **3D Perspective Homography Depth Grids**, and **ESP32 Microcontroller Relay Hardware**.

---

## 🌟 Key Upgrades & Recent System Improvements

| Feature | Previous / Outdated Setup | Modern Upgraded System |
|---|---|---|
| **Human Detection Model** | Generic COCO / basic YOLO-World | **Custom Fine-Tuned Classroom CCTV YOLOv8s-World (27 MB)** with **93.5% mAP50** and **6.2 MB YOLOv8n** edge fallback |
| **Spatial Zone Mapping** | Static 2D boxes or crude proximity circles | **3D Floor Perspective Homography Grid** with Sutherland-Hodgman clipping & multi-cell row/col polygons (`R1-C1` to `R5-C4`) |
| **Zone Calibration** | Manual editing of hardcoded pixel coordinates | **Interactive Web Calibration UI (`/calibrate`)** — visual click-and-assign cells to appliances with real-time JSON sync |
| **Camera Movement Handling** | Static ROIs broke when camera bumped | **Sub-Pixel Auto-Shift Compensation (`cv2.phaseCorrelate`)** automatically detects camera/tripod movement and shifts grid in real time |
| **Detection Frequency** | Intermittent / delayed scans | **Real-Time Continuous Frame-by-Frame Inference** with instant occupancy tracking & student feet coordinate containment |
| **Visual Overlays & HUD** | Basic bounding box rectangles | **Translucent HUD Overlay** with color-coded active cells, 3D guide beam connectors from ceiling appliances to students, and always-on-top monitor |
| **Web Dashboard** | Static mock controls | **Integrated Digital Twin (`index.html`)** with live **MJPEG Video Stream (`/video_feed`)**, live **Calibrated Spaces Widget**, and live telemetry |
| **ESP32 Synchronization** | Manual browser-only push | **Autonomous Dual-Mode Sync**: Throttled server dispatch (1.2s) + Autonomous ESP32 polling (`/api/status` every 2s) + Bidirectional IR counter |
| **Testing & Evaluation Tools** | None | **`play_training_footage.bat`** interactive player (Space pause, F/R seek, S screenshot) + end-to-end training pipeline scripts |

---

## 🚀 System Architecture & Working Flow

```
                      [ Classroom CCTV / Mobile Video / Webcam ]
                                           │
                                           ▼
                    [ Custom Fine-Tuned YOLOv8s-World (27 MB) ]
                          (Real-Time Student Detection)
                                           │
                                           ▼
                    [ 3D Perspective Homography Floor Grid ]
                      (Student Feet Polygon Containment Test)
                                           │
                                           ▼
                    [ Spatial AI Server (spatial_server.py) ]
                     - Auto-Camera Shift Compensation
                     - Live MJPEG Streamer (/video_feed)
                     - REST API Engine & State Manager
                                           │
               ┌───────────────────────────┴───────────────────────────┐
               ▼                                                       ▼
    [ Web Dashboard (index.html) ]                          [ ESP32 DevKit V1 Hardware ]
    - Live MJPEG Camera Feed                                - Dual-Mode: HTTP Push & Poll
    - Calibrated Appliance Spaces Widget                    - Bidirectional Doorway IR Counter
    - 10-Zone Micro-Grid Digital Twin                       - Opto-Isolated 2-Channel Relay
    - Live Power & Cost Savings Telemetry                                  │
                                                   ┌───────────────────────┴───────────────────────┐
                                                   ▼                                               ▼
                                      [ Physical Relay Channel 1 ]                    [ Physical Relay Channel 2 ]
                                         (GPIO 25: Front Benches)                        (GPIO 26: Back Benches)
```

---

## 🔌 Hardware-to-Relay Pin Mapping

The physical testbed utilizes an **ESP32 DevKit V1** coupled with a **2-Channel Opto-Isolated 5V Relay Module** and **Bidirectional IR Doorway Sensors**:

| Component | ESP32 GPIO Pin | Logic Level | Hardware Controlled | Role |
|---|---|---|---|---|
| **Relay Channel 1** | **GPIO 25** | Active LOW | **Block 1 (Front Benches / Light 1)** | 🟢 **Physical Hardware** |
| **Relay Channel 2** | **GPIO 26** | Active LOW | **Block 2 (Back Benches / Fan 1)** | 🟢 **Physical Hardware** |
| **Doorway Sensor 1 (OUT)** | **GPIO 18** | Active LOW | Entrance / Outer Gate IR Obstacle Sensor | 🚪 Bidirectional Counter |
| **Doorway Sensor 2 (IN)** | **GPIO 19** | Active LOW | Room Interior / Inner Gate IR Obstacle Sensor | 🚪 Bidirectional Counter |
| **Status Indicator** | **GPIO 2** | Active HIGH | Onboard Blue LED | 💡 Wi-Fi & System Heartbeat |
| **Digital Twin Units** | *Virtual* | *N/A* | Units 03 to 10 (Tracked on Dashboard) | 🖥️ Micro-Grid Digital Twin |

> **⚡ Hardware Safety & Power Isolation:**
> 1. ESP32 GPIO pins output a maximum of ~12 mA. DC loads (motors, 12V LED strips, AC appliances) are powered through the relay module with a common ground (`GND`).
> 2. The firmware includes an **automatic 35-second failsafe shutoff**: if no status update is received from the server, all relays safely turn OFF.

---

## 📐 3D Perspective Homography Grid & Calibration

Standard 2D bounding boxes fail in overhead CCTV setups because perspective causes students seated in back rows to appear smaller and shifted relative to ceiling appliances.

```
       Far End (Small Cells)
     ┌────────────────────────┐  Row 1 (R1-C1 .. R1-C4)
     │  R1-C1  │  R1-C2  │... │  Row 2
     ├─────────┴─────────┴────┤
     │                        │  Row 3
     ├────────────────────────┤
     │                        │  Row 4
     │                        │  Row 5 (R5-C1 .. R5-C4)
     └────────────────────────┘
       Near End (Large Cells)
```

### How the Spatial Engine Works:
1. **Homography Grid Definition**: Four corner points define the floor boundary. The area is subdivided into a grid (e.g., $5 \text{ rows} \times 4 \text{ columns}$).
2. **Sutherland-Hodgman Polygon Clipping**: Grid cells extending past camera boundaries are automatically clipped against frame dimensions ($1920 \times 1080$).
3. **Student Feet Coordinates**: Rather than using bounding box centroids (which shift depending on whether a student sits, stands, or leans), the AI extracts the bottom-center point:
   $$\text{Feet Point} = \left( \frac{x_1 + x_2}{2}, y_2 \right)$$
4. **Point-in-Polygon Containment (`cv2.pointPolygonTest`)**: Feet coordinates are checked against each appliance's assigned perspective cells. When a student enters any assigned cell, that appliance activates immediately.
5. **Auto-Camera Shift Compensation (`cv2.phaseCorrelate`)**: If the camera or mobile tripod is shifted or bumped, sub-pixel phase correlation detects $(\Delta x, \Delta y)$ and dynamically shifts the entire grid without requiring re-calibration.

---

## 🎯 Interactive Web Calibration (`/calibrate`)

To configure or modify room zones:
1. Start the server and navigate to `http://localhost:5000/calibrate`.
2. **Four-Corner Floor Boundary**: Drag the 4 corner handles to align with the classroom floor perspective.
3. **Appliance Cell Assignment**: Click on any grid cell (e.g., `R4-C1`, `R5-C2`) to assign it to **Fans** or **Lights**.
4. **Save & Auto-Sync**: Click **Save Configuration**. The changes are saved to `appliances_config.json` and immediately reloaded by the running server without restarting.

---

## 🧠 Custom Fine-Tuned YOLOv8 Models

The system includes custom YOLOv8 models trained on high-resolution college classroom CCTV footage (`dataset/roboflow_yolov8`):

| Model File | Size | Architecture | mAP50 | Target Deployment |
|---|---|---|---|---|
| `models/classroom_cctv_yolov8s_world.pt` | **27.0 MB** | YOLOv8s-World (Fine-Tuned) | **93.5%** | Primary High-Accuracy Model (GPU / Desktop CPU) |
| `models/classroom_cctv_yolov8n.pt` | **6.2 MB** | YOLOv8n (Fine-Tuned) | **83.7%** | Ultra-Fast Edge / Embedded SBC Deployment |
| `yolov8s-world.pt` | 28.0 MB | Base YOLO-World | N/A | Automated Fallback |

### Automated Model Loading Hierarchy:
`spatial_server.py` automatically checks and loads the best available model on startup:
```python
if os.path.exists("models/classroom_cctv_yolov8s_world.pt"):
    # High-accuracy 27MB model
elif os.path.exists("models/classroom_cctv_yolov8n.pt"):
    # Lightweight 6MB model
else:
    # Base fallback model
```

---

## 🖥️ Live Web Dashboard (`index.html`)

The dashboard serves as both a live monitoring console and a **10-Zone Micro-Grid Digital Twin**:
* **Live MJPEG Camera Stream**: Real-time video from `/video_feed` with perspective grids, active cell highlights, student bounding boxes, and 3D guide beam connectors.
* **Calibrated Appliance Spaces Widget**: Displays real-time status (`⚡ TURNED ON` vs `○ OFF`, `PEOPLE IN AREA` vs `Vacant Area`) for each calibrated zone with a one-click link to `/calibrate`.
* **10-Unit Workstation Matrix**: Real-time status cards for all 10 workstation units (Units 1 & 2 linked to physical relays; Units 3–10 tracked virtually).
* **Live Energy Telemetry**:
  * Real-Time Active Power ($\text{W}$)
  * Base Maximum Power ($\text{W}$)
  * Live Energy Saved ($\%$)
  * Cumulative kWh Saved & Cost Reduction ($\text{₹}$)
* **ESP32 Connection Controller**: Top-right connection panel to input the ESP32 IP, ping the device, and monitor live round-trip latency.

---

## 📁 Repository Structure

```
├── appliances_config.json               # Saved 3D perspective grid corners & appliance cell assignments
├── index.html                           # Primary Digital Twin dashboard with live stream & telemetry
├── spatial_server.py                    # Core Spatial AI computer vision engine & Flask server
├── run_spatial_server.bat               # 1-Click launcher for Spatial AI server & dashboard
├── play_training_footage.bat            # 1-Click launcher for CCTV training footage live player
├── dataset/                             # Roboflow classroom CCTV training dataset
│   └── roboflow_yolov8/
│       ├── data.yaml                    # Dataset configuration
│       ├── train/                       # Classroom training frames
│       ├── valid/                       # Validation frames
│       └── test/                        # Test frames
├── firmware/                            # Microcontroller source code
│   ├── esp32_prototype_controller/      # Active ESP32 firmware (Relays + IR Doorway Counter)
│   │   └── esp32_prototype_controller.ino
│   ├── esp32_cam_smart_room/            # Standalone ESP32-CAM firmware
│   ├── esp32_smart_room/                # Standalone 2-IR doorway counter firmware
│   └── smart_room_controller/           # Legacy Arduino Uno prototype firmware
├── models/                              # Pre-trained and fine-tuned AI weights
│   ├── classroom_cctv_yolov8s_world.pt  # Custom fine-tuned 27MB high-accuracy model
│   ├── classroom_cctv_yolov8n.pt        # Custom fine-tuned 6.2MB lightweight model
│   └── Classroom Video/                 # Real classroom CCTV footage (EEE1_classroom.mp4, demo clips)
├── PIN_DIAGRAMS/                        # Hardware schematics & wiring diagrams
│   ├── circuit_diagram.jpg
│   ├── cctv_mobile_vision_setup.jpg
│   ├── dc_prototype_pin_diagram.jpg
│   ├── esp32_cam_circuit_diagram.jpg
│   └── spatial_ai_pin_diagram.jpg
├── scripts/                             # Utility & evaluation scripts
│   ├── play_training_footage.py         # CCTV footage interactive detection player
│   ├── train_and_test_yolov8s.py        # End-to-end training & evaluation pipeline (YOLOv8s)
│   ├── train_classroom_yolo.py          # YOLOv8n training pipeline
│   ├── test_model_visual.py             # Visual detection tester
│   ├── extract_cctv_frames.py           # Video frame extraction utility
│   └── process_classroom_video.py       # CCTV video processing utility
├── Report/                              # Technical project reports & generator
├── Saravanan/                           # Engineering logs & architecture documentation
└── WIRING_AND_SETUP.md                  # Comprehensive step-by-step wiring guide
```

---

## 💻 Step-by-Step Execution Guide

### Step 1: Flash the ESP32 Controller
1. Open `firmware/esp32_prototype_controller/esp32_prototype_controller.ino` in Arduino IDE.
2. Update your Wi-Fi / Hotspot credentials:
   ```cpp
   const char* ssid     = "YOUR_WIFI_SSID";
   const char* password = "YOUR_WIFI_PASSWORD";
   ```
3. Update `dashboardPollUrl` with your laptop's local IP (e.g., `http://192.168.43.125:5000/api/status`).
4. Select board **DOIT ESP32 DEVKIT V1** and upload at **115200 baud**.
5. Note the assigned IP address from the Serial Monitor (e.g., `http://192.168.43.125`).

---

### Step 2: Run the Spatial AI Server
Double-click `run_spatial_server.bat` or run via command line:

```bash
# Default: Runs on classroom video or test demo clip
python spatial_server.py

# Run using live Laptop Webcam / USB Camera:
python spatial_server.py --webcam

# Run on a custom video file:
python spatial_server.py "models/Classroom Video/EEE1_classroom.mp4"
```

The server initializes on port `5000`:
* **Web Dashboard**: `http://localhost:5000`
* **Calibration Tool**: `http://localhost:5000/calibrate`
* **Live Video Feed**: `http://localhost:5000/video_feed`

---

### Step 3: Calibrate the Room Space
1. Open `http://localhost:5000/calibrate` in your browser.
2. Adjust the 4 perspective corner handles to cover the classroom floor area.
3. Select an appliance (e.g., `Block 1 (Front Benches)`, `Block 2 (Back Benches)`) and click the grid cells corresponding to that area.
4. Click **Save Configuration**.

---

### Step 4: Play & Test CCTV Training Footage
To test the custom fine-tuned model interactively with keyboard controls:

```bash
# Using batch file:
play_training_footage.bat

# Or directly via Python:
python scripts/play_training_footage.py --video "models/Classroom Video/EEE1_classroom.mp4"
```

**Keyboard Controls:**
* `[SPACE]` : Pause / Resume
* `[F]` : Fast-forward 5 seconds
* `[R]` : Rewind 5 seconds
* `[S]` : Save Screenshot with bounding box detections
* `[Q]` / `[ESC]` : Exit

---

## 🌐 Server API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/` or `/dashboard` | `GET` | Serves the Digital Twin web dashboard (`index.html`) |
| `/calibrate` | `GET` | Serves the interactive 3D perspective calibration UI |
| `/video_feed` | `GET` | Real-time multipart MJPEG video stream with HUD overlays |
| `/api/status` | `GET` | Returns full JSON telemetry (appliance states, detected people, energy metrics) |
| `/api/appliances` | `GET` | Returns current grid corners and appliance cell assignments |
| `/api/save_appliances` | `POST` | Saves updated grid corners and assigned cells to `appliances_config.json` |
| `/api/camera_shift` | `GET` | Returns current auto-detected $(\Delta x, \Delta y)$ camera shift offset |
| `/api/reset_shift` | `POST` | Resets auto-shift compensation offset to $(0, 0)$ |
| `/api/toggle` | `POST` | Manual appliance control toggle endpoint |

---

## 🔬 Model Training & Benchmarking

To retrain or evaluate the model on the classroom CCTV dataset:

```bash
# Train YOLOv8s-World (25 epochs, imgsz=512):
python scripts/train_and_test_yolov8s.py

# Train lightweight YOLOv8n:
python scripts/train_classroom_yolo.py
```

Training metrics and validation outputs are automatically saved to `runs/detect/`. Best weights are deployed directly to `models/classroom_cctv_yolov8s_world.pt`.
