// ================================================================
// Sproeituin Arduino - Seriële motor controller v1.0
// Btechnics - Matthias Bogaert
// Board: Arduino UNO WiFi Rev2 (ATmega4809)
//
// Ontvangt JSON commando's via USB serieel van Raspberry Pi:
//   {"cmd":"jog","as":"x","mm":10}
//   {"cmd":"jog","as":"y","mm":-10}
//   {"cmd":"home"}
//   {"cmd":"stop"}
//   {"cmd":"move","x":200,"y":112}
//   {"cmd":"enable"}
//   {"cmd":"disable"}
//
// Stuurt status terug naar Pi:
//   {"status":"ok","x":0,"y":0}
//   {"status":"homed"}
//   {"status":"stopped"}
//   {"status":"error","msg":"timeout"}
// ================================================================

#include <ArduinoJson.h>

// ── PINOUT ────────────────────────────────────────────────
#define PIN_STEP_X    3
#define PIN_DIR_X     4
#define PIN_STEP_Y    5
#define PIN_DIR_Y     6
#define PIN_ENA       7
#define PIN_XMIN      11
#define PIN_YMIN      12

// ── MOTOR PARAMETERS ─────────────────────────────────────
#define STEPS_PER_MM      40
#define BED_X_MM          2000
#define BED_Y_MM          450
#define STAP_DELAY_US     150    // µs — identiek aan testscript, werkt betrouwbaar
#define HOMING_DELAY_US   500    // trager voor betrouwbare endstop detectie
#define SOFT_LIMIT_X      ((long)BED_X_MM * STEPS_PER_MM)
#define SOFT_LIMIT_Y      ((long)BED_Y_MM * STEPS_PER_MM)
#define HOMING_TIMEOUT_MS 30000

// ── POSITIE ───────────────────────────────────────────────
long posX = 0;
long posY = 0;
bool isHomed = false;
bool driversEnabled = false;

// ── STAP FUNCTIES ─────────────────────────────────────────
void stapX(bool vooruit) {
  digitalWrite(PIN_DIR_X, vooruit ? HIGH : LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_STEP_X, HIGH);
  delayMicroseconds(STAP_DELAY_US);
  digitalWrite(PIN_STEP_X, LOW);
  delayMicroseconds(STAP_DELAY_US);
}

void stapY(bool vooruit) {
  digitalWrite(PIN_DIR_Y, vooruit ? HIGH : LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_STEP_Y, HIGH);
  delayMicroseconds(STAP_DELAY_US);
  digitalWrite(PIN_STEP_Y, LOW);
  delayMicroseconds(STAP_DELAY_US);
}

void stapXHoming(bool vooruit) {
  digitalWrite(PIN_DIR_X, vooruit ? HIGH : LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_STEP_X, HIGH);
  delayMicroseconds(HOMING_DELAY_US);
  digitalWrite(PIN_STEP_X, LOW);
  delayMicroseconds(HOMING_DELAY_US);
}

void stapYHoming(bool vooruit) {
  digitalWrite(PIN_DIR_Y, vooruit ? HIGH : LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_STEP_Y, HIGH);
  delayMicroseconds(HOMING_DELAY_US);
  digitalWrite(PIN_STEP_Y, LOW);
  delayMicroseconds(HOMING_DELAY_US);
}

// ── DRIVERS ───────────────────────────────────────────────
void enableDrivers() {
  digitalWrite(PIN_ENA, LOW);   // TB6600: LOW = ingeschakeld
  delayMicroseconds(50);
  driversEnabled = true;
}

void disableDrivers() {
  digitalWrite(PIN_ENA, HIGH);  // TB6600: HIGH = uitgeschakeld
  driversEnabled = false;
}

// ── STATUS STUREN ─────────────────────────────────────────
void stuurStatus(const char* status) {
  StaticJsonDocument<128> doc;
  doc["status"] = status;
  doc["x"] = (int)(posX / STEPS_PER_MM);
  doc["y"] = (int)(posY / STEPS_PER_MM);
  doc["homed"] = isHomed;
  serializeJson(doc, Serial);
  Serial.println();
}

void stuurFout(const char* msg) {
  StaticJsonDocument<128> doc;
  doc["status"] = "error";
  doc["msg"] = msg;
  serializeJson(doc, Serial);
  Serial.println();
}

// ── BEWEGING ─────────────────────────────────────────────
void beweegNaar(long doelX, long doelY) {
  doelX = constrain(doelX, 0L, SOFT_LIMIT_X);
  doelY = constrain(doelY, 0L, SOFT_LIMIT_Y);
  long deltaX = doelX - posX;
  long deltaY = doelY - posY;
  long stX = abs(deltaX);
  long stY = abs(deltaY);
  bool vooruitX = deltaX > 0;
  bool vooruitY = deltaY > 0;
  long maxStappen = max(stX, stY);
  long tX = 0, tY = 0;
  for (long i = 0; i < maxStappen; i++) {
    tX += stX;
    tY += stY;
    if (tX >= maxStappen) { stapX(vooruitX); tX -= maxStappen; }
    if (tY >= maxStappen) { stapY(vooruitY); tY -= maxStappen; }
  }
  posX = doelX;
  posY = doelY;
}

// ── HOMING ────────────────────────────────────────────────
void homeAxes() {
  enableDrivers();

  // X naar endstop
  unsigned long tStart = millis();
  while (digitalRead(PIN_XMIN) == HIGH) {
    stapXHoming(false);  // richting endstop
    if (millis() - tStart > HOMING_TIMEOUT_MS) {
      stuurFout("X homing timeout"); disableDrivers(); return;
    }
  }
  // 5mm terug
  for (int i = 0; i < 5 * STEPS_PER_MM; i++) stapX(true);
  posX = 0;

  // Y naar endstop
  tStart = millis();
  while (digitalRead(PIN_YMIN) == HIGH) {
    stapYHoming(false);
    if (millis() - tStart > HOMING_TIMEOUT_MS) {
      stuurFout("Y homing timeout"); disableDrivers(); return;
    }
  }
  for (int i = 0; i < 5 * STEPS_PER_MM; i++) stapY(true);
  posY = 0;

  isHomed = true;
  stuurStatus("homed");
}

// ── COMMANDO VERWERKING ───────────────────────────────────
void verwerkCommando(const char* json) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, json);
  if (err) { stuurFout("json fout"); return; }

  const char* cmd = doc["cmd"] | "";

  if (strcmp(cmd, "jog") == 0) {
    const char* as = doc["as"] | "x";
    int mm = doc["mm"] | 0;
    if (mm == 0) { stuurFout("mm=0"); return; }
    enableDrivers();
    if (as[0] == 'x') {
      long doel = constrain(posX + (long)mm * STEPS_PER_MM, 0L, SOFT_LIMIT_X);
      long delta = doel - posX;
      bool vooruit = delta > 0;
      for (long i = 0; i < abs(delta); i++) stapX(vooruit);
      posX = doel;
    } else {
      long doel = constrain(posY + (long)mm * STEPS_PER_MM, 0L, SOFT_LIMIT_Y);
      long delta = doel - posY;
      bool vooruit = delta > 0;
      for (long i = 0; i < abs(delta); i++) stapY(vooruit);
      posY = doel;
    }
    stuurStatus("ok");

  } else if (strcmp(cmd, "home") == 0) {
    homeAxes();

  } else if (strcmp(cmd, "move") == 0) {
    int x = doc["x"] | (int)(posX / STEPS_PER_MM);
    int y = doc["y"] | (int)(posY / STEPS_PER_MM);
    enableDrivers();
    beweegNaar((long)x * STEPS_PER_MM, (long)y * STEPS_PER_MM);
    stuurStatus("ok");

  } else if (strcmp(cmd, "stop") == 0) {
    disableDrivers();
    stuurStatus("stopped");

  } else if (strcmp(cmd, "enable") == 0) {
    enableDrivers();
    stuurStatus("ok");

  } else if (strcmp(cmd, "disable") == 0) {
    disableDrivers();
    stuurStatus("ok");

  } else if (strcmp(cmd, "status") == 0) {
    stuurStatus("ok");

  } else {
    stuurFout("onbekend commando");
  }
}

// ── SETUP EN LOOP ─────────────────────────────────────────
String serieleBuffer = "";

void setup() {
  Serial.begin(115200);
  pinMode(PIN_STEP_X, OUTPUT);
  pinMode(PIN_DIR_X,  OUTPUT);
  pinMode(PIN_STEP_Y, OUTPUT);
  pinMode(PIN_DIR_Y,  OUTPUT);
  pinMode(PIN_ENA,    OUTPUT);
  pinMode(PIN_XMIN,   INPUT_PULLUP);
  pinMode(PIN_YMIN,   INPUT_PULLUP);
  disableDrivers();
  serieleBuffer.reserve(256);
  stuurStatus("ready");
}

void loop() {
  // Seriële buffer uitlezen — één JSON per lijn
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      serieleBuffer.trim();
      if (serieleBuffer.length() > 0) {
        verwerkCommando(serieleBuffer.c_str());
      }
      serieleBuffer = "";
    } else {
      serieleBuffer += c;
    }
  }
}
