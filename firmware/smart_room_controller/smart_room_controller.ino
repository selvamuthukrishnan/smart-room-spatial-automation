#include <Wire.h>
#include <LiquidCrystal_I2C.h>

/*
 * Project: Smart Room Automation with Bidirectional Visitor Counter
 * Description: 
 *   - Automatically counts persons entering and exiting using two IR sensors.
 *   - Turns ON Light and Fan when visitor count > 0.
 *   - Turns OFF Light and Fan when visitor count == 0.
 */

// I2C LCD Configuration (default address 0x27 or 0x3F)
LiquidCrystal_I2C lcd(0x27, 16, 2);

// Pin Definitions
const int PIN_IR_OUTER = 2;   // IR Sensor 1 (Outer Gate / Door Entrance)
const int PIN_IR_INNER = 3;   // IR Sensor 2 (Inner Room Entrance)
const int PIN_RELAY_LIGHT = 7; // Relay 1 -> Light
const int PIN_RELAY_FAN = 8;   // Relay 2 -> Fan

// Visitor Tracking Variables
int visitorCount = 0;
bool outerTriggered = false;
bool innerTriggered = false;
unsigned long triggerTimestamp = 0;
const unsigned long TIMEOUT_MS = 3000; // 3 seconds timeout to reset partial entry

// Relay Logic (Most relay boards are active-LOW)
#define RELAY_ON  LOW
#define RELAY_OFF HIGH

void updateDisplay() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Visitors: ");
  lcd.print(visitorCount);
  
  lcd.setCursor(0, 1);
  if (visitorCount > 0) {
    lcd.print("Appliances: ON ");
  } else {
    lcd.print("Appliances: OFF");
  }
}

void setup() {
  Serial.begin(9600);

  pinMode(PIN_IR_OUTER, INPUT);
  pinMode(PIN_IR_INNER, INPUT);
  pinMode(PIN_RELAY_LIGHT, OUTPUT);
  pinMode(PIN_RELAY_FAN, OUTPUT);

  // Initialize appliances to OFF
  digitalWrite(PIN_RELAY_LIGHT, RELAY_OFF);
  digitalWrite(PIN_RELAY_FAN, RELAY_OFF);

  // LCD Setup
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Smart Room Init");
  lcd.setCursor(0, 1);
  lcd.print("Ready...");
  delay(1500);
  
  updateDisplay();
  Serial.println("Smart Room Controller Started.");
}

void loop() {
  // Read sensor states (Active LOW when obstacle/person detected)
  int outerVal = digitalRead(PIN_IR_OUTER);
  int innerVal = digitalRead(PIN_IR_INNER);

  // 1. Detect initial sensor trigger
  if (outerVal == LOW && !outerTriggered && !innerTriggered) {
    outerTriggered = true;
    triggerTimestamp = millis();
    delay(40); // Debounce
  }

  if (innerVal == LOW && !innerTriggered && !outerTriggered) {
    innerTriggered = true;
    triggerTimestamp = millis();
    delay(40); // Debounce
  }

  // 2. ENTRY DETECTED: Outer triggered first, now Inner is triggered
  if (outerTriggered && innerVal == LOW) {
    visitorCount++;
    outerTriggered = false;
    innerTriggered = false;
    Serial.print("[ENTRY] Person entered! Current count: ");
    Serial.println(visitorCount);
    updateDisplay();
    delay(350); // Sensor pass cooldown
  }

  // 3. EXIT DETECTED: Inner triggered first, now Outer is triggered
  if (innerTriggered && outerVal == LOW) {
    if (visitorCount > 0) {
      visitorCount--;
    }
    outerTriggered = false;
    innerTriggered = false;
    Serial.print("[EXIT] Person left! Current count: ");
    Serial.println(visitorCount);
    updateDisplay();
    delay(350); // Sensor pass cooldown
  }

  // 4. Timeout safety: Reset flags if person stepped back without completing entry/exit
  if ((outerTriggered || innerTriggered) && (millis() - triggerTimestamp > TIMEOUT_MS)) {
    outerTriggered = false;
    innerTriggered = false;
    Serial.println("[TIMEOUT] Partial pass reset.");
  }

  // 5. Appliance Automation Control
  if (visitorCount > 0) {
    digitalWrite(PIN_RELAY_LIGHT, RELAY_ON);
    digitalWrite(PIN_RELAY_FAN, RELAY_ON);
  } else {
    digitalWrite(PIN_RELAY_LIGHT, RELAY_OFF);
    digitalWrite(PIN_RELAY_FAN, RELAY_OFF);
  }
}
