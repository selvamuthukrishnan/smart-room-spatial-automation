# 🏠 Spatial AI Power-Efficient Smart Room Automation

A computer-vision-driven, power-efficient IoT automation system designed to minimize energy wastage in large rooms, seminar halls, and laboratory environments.

---

## 🚀 Key Features
- **Periodic Spatial AI Analysis:** Captures a frame every 10 seconds to detect human positions relative to fixed appliances (Fans, Lights, AC, etc.).
- **Proximity-Based Appliance Toggling:** Dynamically energizes only the localized zones where humans are present instead of powering the entire room.
- **Zero-Wiring Lab Retrofit:** Uses an opto-isolated Smart Extension Box that plugs directly into standard wall sockets without modifying lab electrical infrastructure.
- **Dual Microcontroller Compatibility:** Supports standard **ESP32 DevKit** with external AI camera modules as well as **ESP32-CAM (AI-Thinker)** standalone setups.

---

## 📁 Repository Structure
```
├── circuit_diagram.jpg               # Hardware circuit connection diagram
├── esp32_cam_circuit_diagram.jpg     # ESP32-CAM pinout and wiring schematic
├── spatial_server.py                 # Python YOLOv8 spatial proximity server
├── esp32_smart_room.ino              # Standard ESP32 2-IR / capacity automation sketch
├── esp32_cam_smart_room.ino          # ESP32-CAM standalone appliance control sketch
├── smart_room_controller.ino         # Arduino Uno baseline controller sketch
└── WIRING_AND_SETUP.md               # Detailed hardware wiring and pin connection guide
```

---

## 🛠️ Hardware Requirements
- **ESP32 Dev Board / ESP32-CAM**
- **2-Channel / 4-Channel 5V Opto-isolated Relay Module** (10A 250V AC)
- **External AI Vision Camera Module** (or USB Webcam/Surveillance IP Camera)
- **Smart Extension Box / 230V AC Sockets** for Appliances (Desk Fan, Lamp)
- **5V DC Battery / Power Bank** for Controller Logic

---

## 💻 Software Setup

### 1. Python Server (PC)
```bash
pip install ultralytics opencv-python requests
python spatial_server.py
```

### 2. ESP32 Firmware
1. Open `esp32_smart_room.ino` or `esp32_cam_smart_room.ino` in Arduino IDE.
2. Select Board: **DOIT ESP32 DEVKIT V1** or **AI Thinker ESP32-CAM**.
3. Upload and open Serial Monitor at **115200 baud**.
