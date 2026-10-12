/*
 * =================================================================================
 * PROJECT: Spatial AI Power Automation - ESP32 Prototype Firmware
 * =================================================================================
 * HARDWARE:
 *   - ESP32 DevKit V1
 *   - 2-Channel 5V Relay Module (Opto-isolated)
 *   - Unit 1 (Desk 1: Fan 1 + Light 1) -> Switched via Relay 1 (GPIO 25)
 *   - Unit 2 (Desk 2: Fan 2 + Light 2) -> Switched via Relay 2 (GPIO 26)
 *   - 5V USB Power Bank / 3.7V Battery with Booster
 *
 * HOW IT WORKS:
 *   - Connects to Wi-Fi / Hotspot
 *   - Hosts an HTTP WebServer on Port 80 (receives direct push commands from Dashboard)
 *   - Can also actively POLL / RETRIEVE status from the Dashboard Server (GET /api/status)
 *   - Auto-timeout safety: Turns off loads if no updates for 35s
 * =================================================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>

// --- 🌐 WI-FI CREDENTIALS (Enter your Mobile Hotspot / Wi-Fi details here) ---
const char* ssid     = "YOUR_HOTSPOT_NAME";      // e.g. "MyHotspot"
const char* password = "YOUR_HOTSPOT_PASSWORD";  // e.g. "12345678"

// --- 🌐 DASHBOARD RETRIEVAL / POLLING CONFIGURATION ---
// Set to true to automatically retrieve status from the dashboard server
bool ENABLE_DASHBOARD_POLLING = true;
// Dashboard API endpoint URL to fetch status from (Update with your Dashboard Server IP):
const char* dashboardPollUrl = "http://192.168.43.125:5000/api/status";

unsigned long lastPollTime = 0;
const unsigned long POLL_INTERVAL_MS = 2000; // Poll dashboard every 2 seconds

// --- 🔌 GPIO PIN DEFINITIONS ---
// Unit 1 (Desk 1: Fan 1 + Light 1 combined unit) -> Relay Channel 1
const int PIN_UNIT_1     = 25;  
// Unit 2 (Desk 2: Fan 2 + Light 2 combined unit) -> Relay Channel 2
const int PIN_UNIT_2     = 26;  
const int PIN_STATUS_LED = 2;   // Onboard Blue LED indicator

// Aliases for backward compatibility
const int PIN_LIGHT      = PIN_UNIT_1;
const int PIN_FAN        = PIN_UNIT_2;

// Relay Active-LOW Logic (Most 5V relay modules trigger on LOW)
#define RELAY_ON   LOW
#define RELAY_OFF  HIGH

WebServer server(80);

// Status tracking for the 2 Physical Workstation Units
bool unit1State = false; // Relay 1 (Unit 1: Fan 1 + Light 1)
bool unit2State = false; // Relay 2 (Unit 2: Fan 2 + Light 2)
unsigned long lastCommandTime = 0;
const unsigned long AUTO_SHUTOFF_TIMEOUT = 35000; // 35 seconds safety timeout

void setAppliances(bool u1, bool u2) {
  unit1State = u1;
  unit2State = u2;

  digitalWrite(PIN_UNIT_1, unit1State ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_UNIT_2, unit2State ? RELAY_ON : RELAY_OFF);

  Serial.printf("[RELAY UPDATE] Unit 1 (Fan 1 + Light 1): %s | Unit 2 (Fan 2 + Light 2): %s\n",
                unit1State ? "ON" : "OFF",
                unit2State ? "ON" : "OFF");
}

// Helper to extract boolean value for a key from JSON string without external libraries
bool extractJsonBool(const String& json, const String& key) {
  int keyIdx = json.indexOf("\"" + key + "\"");
  if (keyIdx == -1) keyIdx = json.indexOf(key);
  if (keyIdx == -1) return false;

  int colonIdx = json.indexOf(':', keyIdx);
  if (colonIdx == -1) return false;

  String fragment = json.substring(colonIdx + 1, colonIdx + 12);
  fragment.toLowerCase();

  return (fragment.indexOf("true") != -1 || fragment.indexOf("1") != -1 || 
          fragment.indexOf("\"on\"") != -1 || fragment.indexOf("on") != -1);
}

// Helper to extract boolean value from an array by index: e.g. "units": [1, 0, 1] or raw [1, 0, 1]
bool extractArrayBoolByIndex(const String& payload, const String& arrayKey, int targetIndex) {
  int keyIdx = -1;
  if (arrayKey.length() > 0) {
    keyIdx = payload.indexOf("\"" + arrayKey + "\"");
    if (keyIdx == -1) keyIdx = payload.indexOf(arrayKey);
  } else {
    keyIdx = payload.indexOf('[');
  }
  
  if (keyIdx == -1) return false;

  int bracketStart = payload.indexOf('[', keyIdx);
  int bracketEnd   = payload.indexOf(']', bracketStart);
  if (bracketStart == -1 || bracketEnd == -1) return false;

  String arrayContent = payload.substring(bracketStart + 1, bracketEnd);
  int currentIndex = 0;
  int startPos = 0;
  while (startPos < arrayContent.length()) {
    int commaPos = arrayContent.indexOf(',', startPos);
    String item = (commaPos == -1) ? arrayContent.substring(startPos) : arrayContent.substring(startPos, commaPos);
    item.trim();
    item.toLowerCase();

    if (currentIndex == targetIndex) {
      return (item == "1" || item == "true" || item.indexOf("on") != -1 || item.indexOf("\"on\"") != -1);
    }

    if (commaPos == -1) break;
    startPos = commaPos + 1;
    currentIndex++;
  }
  return false;
}

// 📡 Actively Retrieve Status from Dashboard Server (Pull Mode)
void pollDashboard() {
  if (WiFi.status() != WL_CONNECTED || !ENABLE_DASHBOARD_POLLING) return;

  HTTPClient http;
  http.begin(dashboardPollUrl);
  http.setTimeout(1500); // 1.5s non-blocking timeout
  int httpCode = http.GET();

  if (httpCode == HTTP_CODE_OK) {
    String payload = http.getString();
    lastCommandTime = millis();

    // 1. Check Unit 1 (Index 0 in array OR key-value in JSON)
    bool u1_arr = extractArrayBoolByIndex(payload, "units", 0)  ||
                  extractArrayBoolByIndex(payload, "fans", 0)   ||
                  extractArrayBoolByIndex(payload, "lights", 0) ||
                  extractArrayBoolByIndex(payload, "status", 0) ||
                  extractArrayBoolByIndex(payload, "data", 0)   ||
                  extractArrayBoolByIndex(payload, "", 0);

    bool u1_key = extractJsonBool(payload, "unit_1")  || 
                  extractJsonBool(payload, "unit1")   || 
                  extractJsonBool(payload, "relay_1") ||
                  extractJsonBool(payload, "light_1") ||
                  extractJsonBool(payload, "fan_1")   ||
                  extractJsonBool(payload, "light");

    bool u1 = u1_arr || u1_key;

    // 2. Check Unit 2 (Index 1 in array OR key-value in JSON)
    bool u2_arr = extractArrayBoolByIndex(payload, "units", 1)  ||
                  extractArrayBoolByIndex(payload, "fans", 1)   ||
                  extractArrayBoolByIndex(payload, "lights", 1) ||
                  extractArrayBoolByIndex(payload, "status", 1) ||
                  extractArrayBoolByIndex(payload, "data", 1)   ||
                  extractArrayBoolByIndex(payload, "", 1);

    bool u2_key = extractJsonBool(payload, "unit_2")  || 
                  extractJsonBool(payload, "unit2")   || 
                  extractJsonBool(payload, "relay_2") ||
                  extractJsonBool(payload, "light_2") ||
                  extractJsonBool(payload, "fan_2")   ||
                  extractJsonBool(payload, "fan");

    bool u2 = u2_arr || u2_key;

    if (u1 != unit1State || u2 != unit2State) {
      Serial.printf("[DASHBOARD RETRIEVE] New status from dashboard -> Unit 1 (Index 0): %s | Unit 2 (Index 1): %s\n",
                    u1 ? "ON" : "OFF", u2 ? "ON" : "OFF");
      setAppliances(u1, u2);
    }
  }
  http.end();
}

// 🌐 HTML Dashboard on ESP32
void handleRoot() {
  String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<title>Spatial AI Smart Room</title>";
  html += "<style>body{font-family:Arial;text-align:center;background:#1e1e2e;color:#fff;padding:20px;}";
  html += ".card{background:#2a2a3c;padding:20px;border-radius:15px;margin:15px auto;max-width:350px;}";
  html += ".on{color:#4ade80;font-weight:bold;}.off{color:#f87171;font-weight:bold;}";
  html += "h1{color:#38bdf8;font-size:24px;}</style></head><body>";
  html += "<h1>🏠 Spatial AI Smart Room</h1>";
  html += "<div class='card'>";
  html += "<h3>💡 Unit 01 (Fan 1 + Light 1)</h3>";
  html += "<p>Relay 1: <span class='" + String(unit1State ? "on'>ONLINE (ACTIVE)" : "off'>OFFLINE (IDLE)") + "</span></p>";
  html += "</div>";
  html += "<div class='card'>";
  html += "<h3>🌀 Unit 02 (Fan 2 + Light 2)</h3>";
  html += "<p>Relay 2: <span class='" + String(unit2State ? "on'>ONLINE (ACTIVE)" : "off'>OFFLINE (IDLE)") + "</span></p>";
  html += "</div>";
  html += "<p style='color:#94a3b8;font-size:12px;'>Retrieving status from Dashboard</p>";
  html += "</body></html>";
  server.send(200, "text/html", html);
}

// 📡 API Endpoint: Handles direct Push requests from Dashboard or Friend
// URL Example: http://<ESP32_IP>/control?unit_1=on&unit_2=off
// Also supports: light=on, fan=off, fan_1=on, light_1=on, etc.
void handleControl() {
  lastCommandTime = millis();
  digitalWrite(PIN_STATUS_LED, HIGH);

  bool newU1 = unit1State;
  bool newU2 = unit2State;

  // 0. Parse Index parameter (e.g. /control?index=0&state=on or ?i=1&state=off)
  if (server.hasArg("index") || server.hasArg("i") || server.hasArg("idx")) {
    int idx = -1;
    if (server.hasArg("index")) idx = server.arg("index").toInt();
    else if (server.hasArg("i")) idx = server.arg("i").toInt();
    else if (server.hasArg("idx")) idx = server.arg("idx").toInt();

    bool state = false;
    if (server.hasArg("state")) state = (server.arg("state") == "on" || server.arg("state") == "1" || server.arg("state") == "true");
    else if (server.hasArg("val")) state = (server.arg("val") == "on" || server.arg("val") == "1" || server.arg("val") == "true");
    else if (server.hasArg("status")) state = (server.arg("status") == "on" || server.arg("status") == "1" || server.arg("status") == "true");

    if (idx == 0) newU1 = state;
    else if (idx == 1 && server.hasArg("index") && server.arg("index") == "1") newU2 = state;
    else if (idx == 2) newU2 = state;
  }

  // 1. Parse Unit 1 commands (Relay 1 -> Fan 1 + Light 1)
  if (server.hasArg("unit_1")) {
    newU1 = (server.arg("unit_1") == "on" || server.arg("unit_1") == "true" || server.arg("unit_1") == "1");
  } else if (server.hasArg("unit1")) {
    newU1 = (server.arg("unit1") == "on" || server.arg("unit1") == "true" || server.arg("unit1") == "1");
  } else if (server.hasArg("relay_1")) {
    newU1 = (server.arg("relay_1") == "on" || server.arg("relay_1") == "true" || server.arg("relay_1") == "1");
  } else {
    // Check if individual light_1 or fan_1 or light is active
    bool l1 = server.hasArg("light")   && (server.arg("light") == "on");
    bool l1_a = server.hasArg("light_1") && (server.arg("light_1") == "on");
    bool f1 = server.hasArg("fan_1")   && (server.arg("fan_1") == "on");
    if (server.hasArg("light") || server.hasArg("light_1") || server.hasArg("fan_1")) {
      newU1 = (l1 || l1_a || f1);
    }
  }

  // 2. Parse Unit 2 commands (Relay 2 -> Fan 2 + Light 2)
  if (server.hasArg("unit_2")) {
    newU2 = (server.arg("unit_2") == "on" || server.arg("unit_2") == "true" || server.arg("unit_2") == "1");
  } else if (server.hasArg("unit2")) {
    newU2 = (server.arg("unit2") == "on" || server.arg("unit2") == "true" || server.arg("unit2") == "1");
  } else if (server.hasArg("relay_2")) {
    newU2 = (server.arg("relay_2") == "on" || server.arg("relay_2") == "true" || server.arg("relay_2") == "1");
  } else {
    // Check if individual light_2 or fan_2 or fan is active
    bool f2 = server.hasArg("fan")     && (server.arg("fan") == "on");
    bool f2_a = server.hasArg("fan_2")   && (server.arg("fan_2") == "on");
    bool l2 = server.hasArg("light_2") && (server.arg("light_2") == "on");
    if (server.hasArg("fan") || server.hasArg("fan_2") || server.hasArg("light_2")) {
      newU2 = (f2 || f2_a || l2);
    }
  }

  setAppliances(newU1, newU2);

  server.send(200, "text/plain", "OK: COMMAND APPLIED");
  digitalWrite(PIN_STATUS_LED, LOW);
}

// JSON Status endpoint
void handleStatus() {
  String json = "{\"unit_1\":" + String(unit1State ? "true" : "false") + 
                ",\"unit_2\":" + String(unit2State ? "true" : "false") + 
                ",\"relay_1\":" + String(unit1State ? "true" : "false") + 
                ",\"relay_2\":" + String(unit2State ? "true" : "false") + 
                ",\"light\":" + String(unit1State ? "true" : "false") + 
                ",\"fan\":" + String(unit2State ? "true" : "false") + "}";
  server.send(200, "application/json", json);
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n========================================================");
  Serial.println("   SPATIAL AI SMART ROOM - ESP32 PROTOTYPE CONTROLLER   ");
  Serial.println("========================================================");

  // Pin Modes
  pinMode(PIN_UNIT_1, OUTPUT);
  pinMode(PIN_UNIT_2, OUTPUT);
  pinMode(PIN_STATUS_LED, OUTPUT);

  // Initial State: OFF (Safety First)
  setAppliances(false, false);
  digitalWrite(PIN_STATUS_LED, LOW);

  // Connect to Wi-Fi
  Serial.printf("[WIFI] Scanning nearby 2.4 GHz networks...\n");
  int n = WiFi.scanNetworks();
  if (n == 0) {
    Serial.println("[WIFI] No 2.4 GHz networks found.");
  } else {
    Serial.printf("[WIFI] Found %d networks:\n", n);
    for (int i = 0; i < n; ++i) {
      Serial.printf("  -> '%s' (Signal: %d dBm)\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i));
    }
  }

  Serial.printf("\n[WIFI] Connecting to network: '%s'\n", ssid);
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
  } else {
    Serial.println("\n[WIFI ERROR] Could not connect. Check Hotspot credentials!");
  }

  // Setup Server Routes
  server.on("/", HTTP_GET, handleRoot);
  server.on("/control", HTTP_GET, handleControl);
  server.on("/status", HTTP_GET, handleStatus);
  server.on("/api/status", HTTP_GET, handleStatus);

  server.begin();
  Serial.println("[SERVER] HTTP Server started on Port 80.");
  lastCommandTime = millis();
}

void loop() {
  server.handleClient();

  // 📡 Periodically retrieve status from Dashboard Server
  if (millis() - lastPollTime >= POLL_INTERVAL_MS) {
    lastPollTime = millis();
    pollDashboard();
  }

  // 🛡️ Safety Auto-Timeout: If no updates received for 35 seconds, turn OFF loads
  if ((unit1State || unit2State) && (millis() - lastCommandTime > AUTO_SHUTOFF_TIMEOUT)) {
    Serial.println("\n[AUTO-SHUTOFF] No dashboard signals received for 35s. Powering down appliances.");
    setAppliances(false, false);
  }
}
