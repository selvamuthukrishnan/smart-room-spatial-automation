# 👨‍💻 Engineering Documentation & Project Log: Saravanan S

**Project:** Spatial AI Power-Efficient Smart Room Automation  
**Lead Hardware & Systems Architect:** Saravanan S  
**Hardware Platform:** DOIT ESP32 DevKit V1 & 2-Channel 5V Opto-Isolated Relay Module  
**Integration Stack:** C++ (Arduino/ESP32), JavaScript (HTML5/Tailwind), Python, YOLOv8 Spatial AI  

---

## 📌 1. Executive Summary

This document provides a comprehensive record of the engineering journey, architectural decisions, hardware configuration, and personal contributions made by **Saravanan S** in the development of the **Spatial AI Power-Efficient Smart Room Automation** project.

Saravanan spearheaded the end-to-end hardware system design, microcontroller firmware development, networking infrastructure, and the interface bridging the physical prototype with the software dashboard and machine learning occupancy detection engine.

---

## 🎯 2. Saravanan's Vision & Architectural Innovations

### The Core Problem
Conventional smart room automation systems often rely on crude whole-room motion sensors (PIR) that energize all lights and fans whenever any movement is detected. In large lecture halls, university laboratories, and co-working offices, this causes immense energy wastage when only a few occupants are seated in specific zones.

### Saravanan's Solution: 10-Zone Micro-Grid Model
To solve this, Saravanan conceptualized a **micro-zoned workstation model** representing 10 distinct desk units:
- Each **Workstation Unit** consists of a localized **Desk Fan** and **Desk Light**.
- Power is dynamically delivered **only** to occupied workstation units based on real-time spatial computer vision.

### The Hybrid "Physical Hardware + Digital Twin" Architecture
Faced with the practical constraints of a rapid-prototyping 2-channel relay testbed, Saravanan engineered an elegant dual-layer architecture:
1. **Physical Prototype Layer (Units 1 & 2):**
   - Connected directly to high-power physical electrical loads via a 2-channel relay.
   - Proves real-world electrical switching, relay safety, and low-latency Wi-Fi actuation.
2. **Digital Twin Layer (Units 3 to 10):**
   - Simulated virtually on the interactive dashboard.
   - Computes whole-room energy conservation metrics, kilowatt-hour (kWh) reduction curves, and real-time power savings without requiring a bulky 10-relay physical rig during academic evaluation.

```
                         [ Spatial AI Detection ]
                         (Friend's ML Pipeline)
                                    │
                                    ▼
                     [ Central Web Dashboard ]
                    (index.html / 10 Workstations)
                                    │
               ┌────────────────────┴────────────────────┐
               ▼                                         ▼
    [ MAIN PHYSICAL HARDWARE ]               [ DIGITAL TWIN (VIRTUAL) ]
    - Unit 1 (Index 0): Relay 1 (GPIO 25)    - Units 3 through 10
      Switches: Fan 1 + Light 1               Virtual rendering & real-time
    - Unit 2 (Index 1): Relay 2 (GPIO 26)     room energy metrics
      Switches: Fan 2 + Light 2
```

---

## 🔌 3. Detailed Hardware Configuration & Engineering

Saravanan meticulously planned and executed the hardware setup, ensuring electrical isolation, safe voltage switching, and rock-solid Wi-Fi communication.

### 3.1 Hardware Bill of Materials (BOM)
* **Microcontroller:** ESP32 DOIT DevKit V1 (30-pin, Xtensa dual-core 240MHz, 4MB Flash).
* **USB-to-UART Bridge:** WCH CH9102 high-speed serial controller (connected on `COM9`).
* **Switching Module:** 2-Channel 5V Opto-Isolated Relay Board (Songle 10A 250VAC / 30VDC).
* **Loads:** 
  - Unit 1 Load: Desk Fan 1 + Desk Lamp 1 (Combined).
  - Unit 2 Load: Desk Fan 2 + Desk Lamp 2 (Combined).
* **Power Supply:** 5V regulated DC supply with shared ground reference.

---

### 3.2 Pin Mapping & Electrical Interconnects

| Unit # | Role | ESP32 Pin | Relay Input | Relay Output | Controlled Appliances |
|---|---|---|---|---|---|
| **Unit 1 (Index `0`)** | 🟢 **Main Hardware** | **GPIO 25** | `IN1` | `COM1` → `NO1` | **Fan 1 + Light 1 (Combined)** |
| **Unit 2 (Index `1`)** | 🟢 **Main Hardware** | **GPIO 26** | `IN2` | `COM2` → `NO2` | **Fan 2 + Light 2 (Combined)** |
| **Units 3 to 10** | 🖥️ **Digital Twin** | *N/A* | *N/A* | *N/A* | Tracked via Software |

#### Common Load Wiring Strategy
On each workstation desk, the positive/phase lines for both the fan and the light are bonded together and fed into the relay's **Normally Open (`NO`)** contact, while the source power is fed into the **Common (`COM`)** terminal.
* When **Relay 1** energizes (`GPIO 25` goes `LOW`/Active), **both Fan 1 and Light 1 turn ON simultaneously**.
* When **Relay 2** energizes (`GPIO 26` goes `LOW`/Active), **both Fan 2 and Light 2 turn ON simultaneously**.
* Neutral/Ground wires share a secure common junction.

---

### 3.3 RF & Networking Breakthrough: 2.4 GHz vs 5 GHz Wi-Fi
During the initial hardware commissioning, the ESP32 failed to establish an IP connection with the mobile hotspot. Saravanan diagnosed the root cause:
* **The Root Cause:** The mobile hotspot was broadcasting exclusively on the **5.0 GHz Wi-Fi frequency band**. The onboard ESP32 radio transceiver only supports **2.4 GHz 802.11 b/g/n**.
* **The Solution:** Saravanan reconfigured the mobile hotspot AP band to **2.4 GHz**, allowing the ESP32 to instantly authenticate, obtain an IP address via DHCP, and begin serving HTTP requests at 115200 baud.

---

## 💻 4. Firmware & Software Architecture

Saravanan guided the design of the ESP32 firmware ([`esp32_prototype_controller.ino`](file:///c:/Users/saravanan%20s/OneDrive/Documents/GitHub/smart-room-spatial-automation/firmware/esp32_prototype_controller/esp32_prototype_controller.ino)) to be robust, fault-tolerant, and versatile.

### 4.1 Inbound HTTP REST Server
The ESP32 runs a local HTTP server listening on port 80:
* `/status`: Returns live JSON telemetry with unit states, pin numbers, Wi-Fi RSSI, and system uptime.
* `/control`: Accepts multiple parameter formats for seamless integration:
  - **Index-based:** `/control?index=0&state=on` or `/control?index=1&state=off`
  - **Unit-based:** `/control?unit_1=on&unit_2=off`
  - **Legacy:** `/control?light=on&fan=off`

### 4.2 Array Parsing for Multi-Zone Control
Saravanan specified that the system must handle array-style inputs from the dashboard. The custom `extractArrayBoolByIndex()` parser enables the ESP32 to directly ingest JSON arrays like:
```json
{ "units": [1, 0, 1, 0, 0, 0, 0, 0, 0, 0] }
```
It extracts the boolean state at Index 0 (Unit 1) and Index 1 (Unit 2) without needing heavy external JSON parsing libraries, saving flash and RAM.

### 4.3 Safety Auto-Timeout Watchdog
To prevent appliances from staying indefinitely energized if the Wi-Fi connection drops or the ML server crashes, a **35-second fail-safe watchdog** was programmed into the main loop:
- If no update packet is received within 35 seconds, both relays automatically disengage to ensure complete electrical safety.

---

## 🤝 5. Team Leadership & Project Boundaries

One of Saravanan's key leadership decisions was ensuring smooth teamwork with his project partner:
1. **Guarding the ML Model:**  
   Saravanan established a strict project boundary: his friend is actively developing the machine learning vision model (`spatial_server.py`), so that codebase must remain untouched and uncorrupted.
2. **Clear Interface via `index.html`:**  
   Instead of modifying each other's scripts, Saravanan established `index.html` as the central integration bus. He provided his friend with two simple JavaScript functions:
   ```javascript
   // Friend's ML model updates all 10 desks:
   window.setAllUnits([1, 0, 1, 0, 0, 0, 0, 0, 0, 0]);

   // Or updates an individual desk:
   window.setUnitStatus(0, true); // Unit 1 ON
   ```
3. **Comprehensive Team Documentation:**  
   Saravanan directed the documentation of this entire flow in the root [`README.md`](file:///c:/Users/saravanan%20s/OneDrive/Documents/GitHub/smart-room-spatial-automation/README.md) so his teammate could immediately interface with the hardware without ambiguity.

---

## 🔒 6. Security, Privacy, and Clean Git Practices

Saravanan enforced strict data security and privacy policies throughout the development lifecycle:
* **Zero IP Leaks:** Mandated that private local IP addresses (such as `10.x.x.x`) are scrubbed and replaced with generic network placeholders (`192.168.43.125` / `<ESP32_IP_ADDRESS>`) before commits.
* **Credential Protection:** Ensured personal hotspot names and passwords are never pushed into public or private GitHub commits.

---

## 📜 7. Detailed Chronology of the Pairing Sessions

| Stage | Milestones & Technical Challenges | Resolution & Outcome |
|---|---|---|
| **Phase 1: Environment Setup** | Diagnosed missing local Python environment and toolchain on Windows. | Built isolated virtual environment with Python 3.11, PyTorch, Ultralytics, OpenCV, and Git 2.55. |
| **Phase 2: Hardware Interfacing** | ESP32 DevKit V1 detected on `COM9` via `CH9102` chip; CLI compilation errors for `{upload.speed}`. | Identified FQBN upload speed syntax: `esp32:esp32:esp32doit-devkit-v1:UploadSpeed=921600`. Successfully compiled firmware with 0 errors. |
| **Phase 3: Network Diagnosis** | ESP32 failed to associate with mobile hotspot AP. | Identified 5 GHz frequency incompatibility; switched hotspot to 2.4 GHz; connection established immediately. |
| **Phase 4: Architectural Pivot** | Clarified the physical 2-unit hardware constraint versus whole-room model. | Mapped Unit 1 (GPIO 25) and Unit 2 (GPIO 26) as physical loads; Units 3–10 configured as Digital Twins. |
| **Phase 5: Dashboard Engineering** | Designed rich digital twin UI in `index.html` with live metrics and bilateral sync. | Added dynamic badge indicators, energy savings math, and global JS hooks (`setAllUnits`). |
| **Phase 6: Team Documentation** | Needed to instruct teammate on ML integration without touching ML code. | Documented APIs and hardware mapping in `README.md`; sanitized all IP addresses and credentials. |

---

## 🏆 8. Summary of Saravanan's Key Contributions

- [x] **System Concept & Architecture:** Defined the 10-zone workstation micro-grid model.
- [x] **Hardware Assembly & Pin Assignment:** Configured ESP32 DevKit V1 with 2-channel opto-isolated relay on GPIO 25 & 26.
- [x] **Network & Wireless Engineering:** Solved the 2.4 GHz hotspot connection barrier and established low-latency HTTP transport.
- [x] **Microcontroller Firmware Development:** Authored C++ control routines, query parsers, and safety watchdogs.
- [x] **Full-Stack Dashboard Bridge:** Connected `index.html` directly to physical ESP32 GPIOs via asynchronous `fetch` requests.
- [x] **Collaborative Leadership:** Created clean API contracts for team members to integrate computer vision without code conflicts.
- [x] **Security & Code Quality:** Guaranteed complete privacy of personal credentials and local IP addresses.

---

*Authored and verified on October 12, 2026.*  
*Spatial AI Power-Efficient Smart Room Automation Project.*
