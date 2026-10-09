/*
 * =================================================================================
 * PROJECT: ESP32-CAM Smart Room Automation (Camera Based)
 * HARDWARE:
 *   - ESP32-CAM (AI-Thinker model with OV2640 camera)
 *   - 2-Channel 5V Relay Module
 *   - DC Toy Motor (Fan) -> Switched via Relay IN2 (GPIO 13)
 *   - LED Light Strip    -> Switched via Relay IN1 (GPIO 12)
 *   - 3.7V Li-ion Battery (Powers Motor & LED Strip)
 * =================================================================================
 */

#include "esp_camera.h"
#include <WiFi.h>

// --- Wi-Fi Credentials (Set your Hotspot / Router details) ---
const char* ssid = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";

// --- RELAY PIN DEFINITIONS FOR ESP32-CAM ---
// ESP32-CAM-la camera pins pogha free-ah irukura best pins:
const int PIN_RELAY_LIGHT = 12; // Light Relay (IN1)
const int PIN_RELAY_FAN   = 13; // Fan Relay (IN2)

// Relay active LOW logic
#define RELAY_ON  LOW
#define RELAY_OFF HIGH

// AI-Thinker ESP32-CAM Camera Pin Map
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

void setAppliances(bool state) {
  if (state) {
    digitalWrite(PIN_RELAY_LIGHT, RELAY_ON);
    digitalWrite(PIN_RELAY_FAN, RELAY_ON);
    Serial.println("[APPLIANCES] LIGHT & FAN -> ON");
  } else {
    digitalWrite(PIN_RELAY_LIGHT, RELAY_OFF);
    digitalWrite(PIN_RELAY_FAN, RELAY_OFF);
    Serial.println("[APPLIANCES] LIGHT & FAN -> OFF");
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("\n--- ESP32-CAM Smart Room System Starting ---");

  // Relay output setup
  pinMode(PIN_RELAY_LIGHT, OUTPUT);
  pinMode(PIN_RELAY_FAN, OUTPUT);

  // Initial state: OFF
  setAppliances(false);

  // Camera Configuration
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  // Camera Init
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return;
  }
  Serial.println("Camera Init Success!");

  // Wi-Fi Connection
  WiFi.begin(ssid, password);
  Serial.print("Connecting to Wi-Fi");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWi-Fi Connected!");
    Serial.print("Camera Stream IP Address: http://");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWi-Fi not connected (Running in Standalone mode)");
  }
}

void loop() {
  // Capture Frame from Camera
  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    delay(1000);
    return;
  }

  /*
   * Note for Viva/Demo:
   * When person is detected via camera (or via laptop OpenCV stream):
   * Call: setAppliances(true) -> Light and Fan ON!
   * When person exits / timeout occurs:
   * Call: setAppliances(false) -> Light and Fan OFF!
   */

  // Return the frame buffer back to driver
  esp_camera_fb_return(fb);
  delay(100);
}
