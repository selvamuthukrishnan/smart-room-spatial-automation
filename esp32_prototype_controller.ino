/*
 * =================================================================================
 * PROJECT: Spatial AI Power Automation - ESP32 Prototype Firmware
 * =================================================================================
 * HARDWARE:
 *   - ESP32 DevKit V1
 *   - 2-Channel 5V Relay Module (Opto-isolated)
 *   - 5V DC Toy Fan -> Switched via Relay 2 (GPIO 26)
 *   - 5V DC LED Strip -> Switched via Relay 1 (GPIO 25)
 *   - 5V USB Power Bank (Safe Low-Voltage DC Supply)
 *
 * HOW IT WORKS:
 *   - ESP32 connects to your Mobile Hotspot or Lab Wi-Fi
 *   - Hosts an HTTP WebServer on Port 80
 *   - Receives 10-second spatial toggle commands from PC Python AI server
 *   - Auto-timeout safety: Turns off loads if PC stops sending updates for 35s
 * =================================================================================
 */

#include <WiFi.h>
#include <WebServer.h>

// --- 🌐 WI-FI CREDENTIALS (Unga Hotspot / Wi-Fi Details Podunga) ---
const char* ssid     = "YOUR_HOTSPOT_NAME";
const char* password = "YOUR_HOTSPOT_PASSWORD";

// --- 🔌 GPIO PIN DEFINITIONS ---
const int PIN_LIGHT      = 25;  // Relay Channel 1 -> 5V LED Strip
const int PIN_FAN        = 26;  // Relay Channel 2 -> 5V DC Toy Fan
const int PIN_STATUS_LED = 2;   // Onboard Blue LED indicator

// Relay Active-LOW Logic (Most 5V relay modules trigger on LOW)
#define RELAY_ON   LOW
#define RELAY_OFF  HIGH

WebServer server(80);

// Status tracking
bool lightState = false;
bool fanState   = false;
unsigned long lastCommandTime = 0;
const unsigned long AUTO_SHUTOFF_TIMEOUT = 35000; // 35 seconds safety timeout

void setAppliances(bool light, bool fan) {
  lightState = light;
  fanState = fan;

  digitalWrite(PIN_LIGHT, lightState ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_FAN,   fanState   ? RELAY_ON : RELAY_OFF);

  Serial.printf("[STATE UPDATE] 5V LED Light: %s | 5V DC Fan: %s\n",
                lightState ? "ON" : "OFF",
                fanState   ? "ON" : "OFF");
}

// 🌐 HTML Mobile Dashboard (Direct phone browser-la IP open panni paakka)
void handleRoot() {
  String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<title>Spatial AI Smart Room</title>";
  html += "<style>body{font-family:Arial;text-align:center;background:#1e1e2e;color:#fff;padding:20px;}";
  html += ".card{background:#2a2a3c;padding:20px;border-radius:15px;margin:15px auto;max-width:350px;}";
  html += ".on{color:#4ade80;font-weight:bold;}.off{color:#f87171;font-weight:bold;}";
  html += "h1{color:#38bdf8;font-size:24px;}</style></head><body>";
  html += "<h1>🏠 Spatial AI Smart Room</h1>";
  html += "<div class='card'>";
  html += "<h3>💡 5V LED Light Strip</h3>";
  html += "<p>Status: <span class='" + String(lightState ? "on'>ONLINE (ACTIVE)" : "off'>OFFLINE (IDLE)") + "</span></p>";
  html += "</div>";
  html += "<div class='card'>";
  html += "<h3>🌀 5V DC Toy Fan</h3>";
  html += "<p>Status: <span class='" + String(fanState ? "on'>RUNNING (ACTIVE)" : "off'>STOPPED (IDLE)") + "</span></p>";
  html += "</div>";
  html += "<p style='color:#94a3b8;font-size:12px;'>Listening to PC YOLO-World 10s Scanner</p>";
  html += "</body></html>";
  server.send(200, "text/html", html);
}

// 📡 API Endpoint: Handles requests from PC Python spatial_server.py
// URL Example: http://<ESP32_IP>/control?light=on&fan=off
void handleControl() {
  lastCommandTime = millis();

  // Flash onboard LED to confirm data packet received
  digitalWrite(PIN_STATUS_LED, HIGH);

  bool newLight = lightState;
  bool newFan   = fanState;

  // 1. Parse Light commands (handles 'light', 'tube_light', 'light_1')
  if (server.hasArg("light")) {
    newLight = (server.arg("light") == "on");
  } else if (server.hasArg("tube_light")) {
    newLight = (server.arg("tube_light") == "on");
  }

  // 2. Parse Fan commands (handles 'fan', 'fan_1', 'fan_2', 'fan_left', 'fan_center')
  if (server.hasArg("fan")) {
    newFan = (server.arg("fan") == "on");
  } else {
    // If multiple fan zones exist, turn ON if ANY fan zone is active
    bool anyFanOn = false;
    for (int i = 0; i < server.args(); i++) {
      String argName = server.argName(i);
      if (argName.indexOf("fan") >= 0 && server.arg(i) == "on") {
        anyFanOn = true;
        break;
      }
    }
    if (server.hasArg("fan_1") || server.hasArg("fan_2") || server.hasArg("fan_left")) {
      newFan = anyFanOn;
    }
  }

  setAppliances(newLight, newFan);

  server.send(200, "text/plain", "OK: COMMAND APPLIED");
  digitalWrite(PIN_STATUS_LED, LOW);
}

// JSON Status endpoint
void handleStatus() {
  String json = "{\"light\":" + String(lightState ? "true" : "false") + 
                ",\"fan\":" + String(fanState ? "true" : "false") + "}";
  server.send(200, "application/json", json);
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n========================================================");
  Serial.println("   SPATIAL AI SMART ROOM - ESP32 PROTOTYPE CONTROLLER   ");
  Serial.println("========================================================");

  // Pin Modes
  pinMode(PIN_LIGHT, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  pinMode(PIN_STATUS_LED, OUTPUT);

  // Initial State: OFF (Safety First)
  setAppliances(false, false);
  digitalWrite(PIN_STATUS_LED, LOW);

  // Connect to Wi-Fi
  Serial.printf("[WIFI] Connecting to network: %s\n", ssid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 30) {
    delay(500);
    Serial.print(".");
    digitalWrite(PIN_STATUS_LED, !digitalRead(PIN_STATUS_LED)); // Blink while connecting
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(PIN_STATUS_LED, HIGH); // Solid ON when connected
    Serial.println("\n[WIFI SUCCESS] Connected successfully!");
    Serial.print(">>> ESP32 IP ADDRESS: http://");
    Serial.println(WiFi.localIP());
    Serial.println("Copy this IP address and paste it into your spatial_server.py!");
  } else {
    Serial.println("\n[WIFI ERROR] Could not connect. Check Hotspot credentials!");
  }

  // Setup Server Routes
  server.on("/", HTTP_GET, handleRoot);
  server.on("/control", HTTP_GET, handleControl);
  server.on("/status", HTTP_GET, handleStatus);

  server.begin();
  Serial.println("[SERVER] HTTP Server started on Port 80.");
  lastCommandTime = millis();
}

void loop() {
  server.handleClient();

  // 🛡️ Safety Auto-Timeout: If PC server loses Wi-Fi connection or stops
  // sending frames for 35 seconds, turn OFF loads automatically to save power!
  if ((lightState || fanState) && (millis() - lastCommandTime > AUTO_SHUTOFF_TIMEOUT)) {
    Serial.println("\n[AUTO-SHUTOFF] No AI signals received for 35s. Powering down appliances.");
    setAppliances(false, false);
  }
}
