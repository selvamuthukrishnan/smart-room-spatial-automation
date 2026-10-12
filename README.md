# 🏠 Spatial AI Power-Efficient Smart Room Automation

A computer-vision-driven, power-efficient IoT automation system designed to minimize energy wastage in large rooms, seminar halls, and laboratory environments.

---

## 🚀 System Architecture & Working Flow

The room is modeled into **10 Workstation Units** (each unit consists of a paired **Desk Fan + Desk Light**). 

Because the physical prototype testbed uses a **2-Channel Opto-Isolated Relay Module**, the workload is split into:
* **2 Main Physical Hardware Units** (physically wired to relays).
* **8 Digital Twin Units** (tracked virtually on the dashboard to demonstrate full-room scalability and live energy efficiency).

```
                      [ ML Computer Vision Model ]
                                   │
                                   ▼
                   [ Web Dashboard (index.html) ]
                   10-Zone Micro-Grid Digital Twin
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
   [ MAIN PHYSICAL HARDWARE ]               [ DIGITAL TWIN (VIRTUAL) ]
   - Unit 01 (Index 0): Relay 1 (GPIO 25)    - Unit 03 to Unit 10
     Switches: Fan 1 + Light 1                Tracked on dashboard &
   - Unit 02 (Index 1): Relay 2 (GPIO 26)     energy savings calculations
     Switches: Fan 2 + Light 2
```

---

## 🔌 Hardware-to-Relay Pin Mapping

| Unit # | Role | ESP32 GPIO Pin | Relay Channel | Physical Appliances Controlled |
|---|---|---|---|---|
| **Unit 01 (Index `0`)** | 🟢 **MAIN HARDWARE** | **GPIO 25** | **Relay Channel 1** | **Fan 1 + Light 1 (Combined)** |
| **Unit 02 (Index `1`)** | 🟢 **MAIN HARDWARE** | **GPIO 26** | **Relay Channel 2** | **Fan 2 + Light 2 (Combined)** |
| **Units 03 to 10** | 🖥️ **Digital Twin** | *None (Virtual)* | *None* | Tracked on Dashboard |

> **⚠️ Hardware Note:** On each physical desk, the fan and light are wired together to the same relay channel. Activating Unit 1 turns ON both Fan 1 and Light 1 together; activating Unit 2 turns ON both Fan 2 and Light 2 together.

---

## 🤝 ML Model & Dashboard Integration Guide (For Team / ML Developer)

When updating the occupancy of the room from the ML model, please use the following methods:

### Method A: Update Through `index.html` (Recommended)
`index.html` exposes two global JavaScript functions on the `window` object:

#### 1. Update All 10 Units at Once (Array of 10 items):
Pass a 10-element array of booleans (`1`/`0` or `true`/`false`):
```javascript
// Index 0 = Unit 1 (Relay 1), Index 1 = Unit 2 (Relay 2), Indices 2-9 = Units 3-10
window.setAllUnits([1, 0, 1, 0, 0, 0, 0, 0, 0, 0]);
```
* **Unit 1 (Index `0`) = `1`** $\rightarrow$ Triggers **Relay 1 ON** (`GPIO 25`).
* **Unit 2 (Index `1`) = `0`** $\rightarrow$ Triggers **Relay 2 OFF** (`GPIO 26`).
* **Units 3 to 10** update virtually on the dashboard and adjust the **Live Energy Saved %** metric.

#### 2. Update a Single Unit by Index:
```javascript
// Control Unit 1 (Index 0) -> Physical Relay 1 (Fan 1 + Light 1):
window.setUnitStatus(0, true);   // ON
window.setUnitStatus(0, false);  // OFF

// Control Unit 2 (Index 1) -> Physical Relay 2 (Fan 2 + Light 2):
window.setUnitStatus(1, true);   // ON
window.setUnitStatus(1, false);  // OFF

// Control any virtual unit (Units 3 to 10):
window.setUnitStatus(2, true);   // Unit 3 ON (Virtual only)
```

---

### Method B: Direct HTTP Call to ESP32 (Optional)
If your Python ML script wants to send HTTP requests directly to the ESP32:

```python
import requests

ESP32_IP = "http://192.168.43.125"  # Replace with your ESP32 IP from Serial Monitor

# 1. Update by Unit Name:
requests.get(f"{ESP32_IP}/control?unit_1=on&unit_2=off")

# 2. Update by Index:
requests.get(f"{ESP32_IP}/control?index=0&state=on")   # Relay 1 (Unit 1) ON
requests.get(f"{ESP32_IP}/control?index=1&state=off")  # Relay 2 (Unit 2) OFF
```

---

## 📁 Repository Structure
```
├── esp32_prototype_controller/
│   └── esp32_prototype_controller.ino # ESP32 firmware (controls Relays 1 & 2 for Units 1 & 2)
├── index.html                         # Primary Digital Twin dashboard with live ESP32 sync
├── dashboard.html                     # Standalone dashboard mirror
├── dashboard_server.py                # Optional local Python HTTP server for index.html & API
├── spatial_server.py                  # Computer vision proximity scanner (ML baseline)
├── run_spatial_server.bat             # 1-Click launcher for local testing
├── circuit_diagram.jpg                # Hardware connection schematic
├── dc_prototype_pin_diagram.jpg       # 5V safe DC prototype pinout diagram
└── WIRING_AND_SETUP.md                # Step-by-step wiring and common ground guide
```

---

## 💻 Running the Project

### 1. Flash the ESP32:
1. Open `esp32_prototype_controller/esp32_prototype_controller.ino` in Arduino IDE.
2. Enter your Wi-Fi / Hotspot name (`ssid`) and password (`password`).
3. Upload to your ESP32 board (**DOIT ESP32 DEVKIT V1**) at **115200 baud**.
4. Check the Serial Monitor for the assigned IP address (e.g. `http://192.168.43.125`).

### 2. Launch the Dashboard:
1. Open `index.html` in Google Chrome.
2. Enter the ESP32 IP in the top-right connection box and click **Ping**.
3. Toggle cards or use `window.setAllUnits(...)` to control physical hardware and view live energy savings!
