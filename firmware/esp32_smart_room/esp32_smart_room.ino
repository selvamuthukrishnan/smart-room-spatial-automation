/*
 * =================================================================================
 * PROJECT: Cardboard Smart Room Mini Project (ESP32)
 * COMPONENTS:
 *   - ESP32 Dev Board
 *   - 2x IR Sensors (Entrance & Exit)
 *   - DC Toy Motor (Fan)
 *   - LED Strip / Module (Light)
 *   - 2-Channel Relay Module (or NPN Transistor switches)
 *   - 3.7V Li-ion Battery / 5V Power
 * =================================================================================
 */

// LCD theva patta mattum idhai uncomment pannunga, illana thevailla:
// #define USE_LCD 

#ifdef USE_LCD
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
LiquidCrystal_I2C lcd(0x27, 16, 2);
#endif

// --- PIN DEFINITIONS ---
const int PIN_IR_OUTER = 18;    // Gate veliya irukura IR Sensor (IR1)
const int PIN_IR_INNER = 19;    // Room ulla irukura IR Sensor (IR2)

const int PIN_LIGHT    = 25;    // LED Strip switch panna (Relay IN1 / Transistor Base)
const int PIN_FAN      = 26;    // DC Toy Motor switch panna (Relay IN2 / Transistor Base)

// --- VARIABLES ---
int visitorCount = 0;
bool outerTriggered = false;
bool innerTriggered = false;
unsigned long triggerTimestamp = 0;
const unsigned long TIMEOUT_MS = 2500; // 2.5 seconds timeout

// Relay Active-LOW (Direct Transistor use panna HIGH/LOW maathikalam)
// Neenga Relay module use pannina: ON = LOW, OFF = HIGH
// Neenga BC547 transistor use pannina: ON = HIGH, OFF = LOW
#define LOAD_ON  LOW
#define LOAD_OFF HIGH

void controlAppliances(bool state) {
  if (state) {
    digitalWrite(PIN_LIGHT, LOAD_ON);
    digitalWrite(PIN_FAN, LOAD_ON);
    Serial.println("[LOADS] LIGHT & FAN -> ON");
  } else {
    digitalWrite(PIN_LIGHT, LOAD_OFF);
    digitalWrite(PIN_FAN, LOAD_OFF);
    Serial.println("[LOADS] LIGHT & FAN -> OFF");
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  // Sensor pins (Input)
  pinMode(PIN_IR_OUTER, INPUT);
  pinMode(PIN_IR_INNER, INPUT);

  // Load control pins (Output)
  pinMode(PIN_LIGHT, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);

  // Modhalla ella appliances-um OFF la irukanum
  controlAppliances(false);

#ifdef USE_LCD
  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Smart Room Mini");
  lcd.setCursor(0, 1);
  lcd.print("Count: 0 | OFF");
#endif

  Serial.println("=========================================");
  Serial.println("  CARDBOARD SMART ROOM SYSTEM READY!    ");
  Serial.println("=========================================");
}

void loop() {
  // IR sensors read pandrom (Obstacle vandha LOW aagum)
  int outerVal = digitalRead(PIN_IR_OUTER);
  int innerVal = digitalRead(PIN_IR_INNER);

  // 1. First trigger detection
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

  // 2. ENTRY SEQUENCE (Outer -> Inner)
  if (outerTriggered && innerVal == LOW) {
    visitorCount++;
    outerTriggered = false;
    innerTriggered = false;

    Serial.print(">>> [ENTRY] Aalu ulla vandhutaaru! Count: ");
    Serial.println(visitorCount);
    
#ifdef USE_LCD
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Visitors: ");
    lcd.print(visitorCount);
    lcd.setCursor(0, 1);
    lcd.print("Status: ON ");
#endif

    delay(400); // Cooldown
  }

  // 3. EXIT SEQUENCE (Inner -> Outer)
  if (innerTriggered && outerVal == LOW) {
    if (visitorCount > 0) {
      visitorCount--;
    }
    outerTriggered = false;
    innerTriggered = false;

    Serial.print("<<< [EXIT] Aalu veliya poitaaru! Count: ");
    Serial.println(visitorCount);

#ifdef USE_LCD
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Visitors: ");
    lcd.print(visitorCount);
    lcd.setCursor(0, 1);
    if (visitorCount > 0) lcd.print("Status: ON ");
    else lcd.print("Status: OFF");
#endif

    delay(400); // Cooldown
  }

  // 4. Timeout reset (Aalu paadhila ninnu thirumbita reset aaganum)
  if ((outerTriggered || innerTriggered) && (millis() - triggerTimestamp > TIMEOUT_MS)) {
    outerTriggered = false;
    innerTriggered = false;
    Serial.println("[RESET] Halfway pass cleared.");
  }

  // 5. Automatic Light & Fan Switching
  if (visitorCount > 0) {
    controlAppliances(true);
  } else {
    controlAppliances(false);
  }
}
