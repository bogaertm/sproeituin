// ================================================================
// Sproeituin Arduino - Seriële motor controller v1.14
// Btechnics - Matthias Bogaert
// Board: Arduino UNO WiFi Rev2 (ATmega4809)
// v1.14: HOMING_TIMEOUT_MS verhoogd van 30s naar 45s
//        Berekening: 2000mm * 40 stappen/mm * 400µs = 32s
//        30s timeout was te kort bij volledig uitgereden as
// ================================================================

#include <ArduinoJson.h>

#define PIN_STEP_X    3
#define PIN_DIR_X     4
#define PIN_STEP_Y    5
#define PIN_DIR_Y     6
#define PIN_ENA       7
#define PIN_RELAY     8
#define PIN_XMIN      11
#define PIN_XMAX      10
#define PIN_YMIN      12
#define PIN_YMAX      9

#define STEPS_PER_MM      40
#define BED_X_MM          2000
#define BED_Y_MM          450
#define STAP_DELAY_US     50
#define HOMING_DELAY_US   200
#define SOFT_LIMIT_X      ((long)BED_X_MM * STEPS_PER_MM)
#define SOFT_LIMIT_Y      ((long)BED_Y_MM * STEPS_PER_MM)
#define HOMING_TIMEOUT_MS 45000   // was 30000 — 32s nodig bij volledig uitgereden as
#define SERIEEL_CHECK_MS  10

long posX         = 0;
long posY         = 0;
bool isHomed      = false;
bool stopGevraagd = false;
bool klepOpen     = false;

char serieleBuffer[256];
int  bufferPos    = 0;

void stuurStatus(const char* status);
void stuurFout(const char* msg);
void enableDrivers();
void disableDrivers();
void openKlep();
void sluitKlep();

// ── SERIEEL NOODSTOP CHECK ────────────────────────────────
// Enkel karakter '!' als noodstop — alle andere bytes genegeerd
// tijdens beweging zodat volgende JSON commando's intact blijven.
void checkSerieel() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '!') {
      stopGevraagd = true;
    }
  }
}

void openKlep() {
  digitalWrite(PIN_RELAY, HIGH);
  klepOpen = true;
}

void sluitKlep() {
  digitalWrite(PIN_RELAY, LOW);
  klepOpen = false;
}

void stapX(bool vooruit) {
  if (vooruit  && digitalRead(PIN_XMAX) == LOW) return;
  if (!vooruit && digitalRead(PIN_XMIN) == LOW) return;
  digitalWrite(PIN_DIR_X, vooruit ? HIGH : LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_STEP_X, HIGH);
  delayMicroseconds(STAP_DELAY_US);
  digitalWrite(PIN_STEP_X, LOW);
  delayMicroseconds(STAP_DELAY_US);
}

void stapY(bool vooruit) {
  if (vooruit  && digitalRead(PIN_YMAX) == LOW) return;
  if (!vooruit && digitalRead(PIN_YMIN) == LOW) return;
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

void enableDrivers() {
  digitalWrite(PIN_ENA, LOW);
  delayMicroseconds(50);
}

void disableDrivers() {
  digitalWrite(PIN_ENA, HIGH);
}

void stuurStatus(const char* status) {
  StaticJsonDocument<128> doc;
  doc["status"] = status;
  doc["x"]      = (long)(posX / STEPS_PER_MM);
  doc["y"]      = (long)(posY / STEPS_PER_MM);
  doc["homed"]  = isHomed;
  doc["klep"]   = klepOpen;
  serializeJson(doc, Serial);
  Serial.println();
}

void stuurFout(const char* msg) {
  StaticJsonDocument<128> doc;
  doc["status"] = "error";
  doc["msg"]    = msg;
  serializeJson(doc, Serial);
  Serial.println();
}

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
  unsigned long lastCheck = millis();

  for (long i = 0; i < maxStappen; i++) {
    if (millis() - lastCheck >= SERIEEL_CHECK_MS) {
      lastCheck = millis();
      checkSerieel();
      if (stopGevraagd) {
        sluitKlep();
        disableDrivers();
        stuurStatus("stopped");
        return;
      }
    }
    tX += stX;
    tY += stY;
    if (tX >= maxStappen) {
      stapX(vooruitX);
      posX += vooruitX ? 1 : -1;
      tX -= maxStappen;
    }
    if (tY >= maxStappen) {
      stapY(vooruitY);
      posY += vooruitY ? 1 : -1;
      tY -= maxStappen;
    }
  }
}

void homeAxes() {
  isHomed = false;
  enableDrivers();
  unsigned long tStart    = millis();
  unsigned long lastCheck = millis();

  // ── X naar min eindstop ───────────────────────────────
  while (digitalRead(PIN_XMIN) == HIGH) {
    stapXHoming(false);
    posX--;
    if (millis() - lastCheck >= SERIEEL_CHECK_MS) {
      lastCheck = millis();
      checkSerieel();
      if (stopGevraagd) {
        posX = 0; posY = 0;
        sluitKlep(); disableDrivers(); stuurStatus("stopped"); return;
      }
    }
    if (millis() - tStart > HOMING_TIMEOUT_MS) {
      posX = 0; posY = 0; isHomed = false;
      stuurFout("X homing timeout");
      disableDrivers();
      return;
    }
  }

  // ── X backoff 5mm ─────────────────────────────────────
  checkSerieel();
  if (stopGevraagd) {
    posX = 0; posY = 0;
    sluitKlep(); disableDrivers(); stuurStatus("stopped"); return;
  }
  for (int i = 0; i < 5 * STEPS_PER_MM; i++) {
    stapXHoming(true);
    posX++;
    if (i % 20 == 0) {
      checkSerieel();
      if (stopGevraagd) {
        posX = 0; posY = 0;
        sluitKlep(); disableDrivers(); stuurStatus("stopped"); return;
      }
    }
  }
  posX = 0;

  // ── Y naar min eindstop ───────────────────────────────
  tStart = millis(); lastCheck = millis();
  while (digitalRead(PIN_YMIN) == HIGH) {
    stapYHoming(false);
    posY--;
    if (millis() - lastCheck >= SERIEEL_CHECK_MS) {
      lastCheck = millis();
      checkSerieel();
      if (stopGevraagd) {
        posX = 0; posY = 0;
        sluitKlep(); disableDrivers(); stuurStatus("stopped"); return;
      }
    }
    if (millis() - tStart > HOMING_TIMEOUT_MS) {
      posX = 0; posY = 0; isHomed = false;
      stuurFout("Y homing timeout");
      disableDrivers();
      return;
    }
  }

  // ── Y backoff 5mm ─────────────────────────────────────
  checkSerieel();
  if (stopGevraagd) {
    posX = 0; posY = 0;
    sluitKlep(); disableDrivers(); stuurStatus("stopped"); return;
  }
  for (int i = 0; i < 5 * STEPS_PER_MM; i++) {
    stapYHoming(true);
    posY++;
    if (i % 20 == 0) {
      checkSerieel();
      if (stopGevraagd) {
        posX = 0; posY = 0;
        sluitKlep(); disableDrivers(); stuurStatus("stopped"); return;
      }
    }
  }
  posY = 0;

  isHomed = true;
  disableDrivers();
  stuurStatus("homed");
}

void verwerkCommando(const char* json) {
  if (json[0] == '!') {
    stopGevraagd = true;
    sluitKlep();
    disableDrivers();
    stuurStatus("stopped");
    return;
  }

  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, json)) { stuurFout("json fout"); return; }
  const char* cmd = doc["cmd"] | "";

  stopGevraagd = false;

  if (strcmp(cmd, "jog") == 0) {
    const char* as = doc["as"] | "x";
    int mm = doc["mm"] | 0;
    if (mm == 0) { stuurFout("mm=0"); return; }
    enableDrivers();
    if (as[0] == 'x') {
      long doel  = constrain(posX + (long)mm * STEPS_PER_MM, 0L, SOFT_LIMIT_X);
      long delta = doel - posX;
      bool vooruit = delta > 0;
      unsigned long lastCheck = millis();
      for (long i = 0; i < abs(delta); i++) {
        stapX(vooruit);
        posX += vooruit ? 1 : -1;
        if (millis() - lastCheck >= SERIEEL_CHECK_MS) {
          lastCheck = millis();
          checkSerieel();
          if (stopGevraagd) { sluitKlep(); disableDrivers(); stuurStatus("stopped"); return; }
        }
      }
    } else {
      long doel  = constrain(posY + (long)mm * STEPS_PER_MM, 0L, SOFT_LIMIT_Y);
      long delta = doel - posY;
      bool vooruit = delta > 0;
      unsigned long lastCheck = millis();
      for (long i = 0; i < abs(delta); i++) {
        stapY(vooruit);
        posY += vooruit ? 1 : -1;
        if (millis() - lastCheck >= SERIEEL_CHECK_MS) {
          lastCheck = millis();
          checkSerieel();
          if (stopGevraagd) { sluitKlep(); disableDrivers(); stuurStatus("stopped"); return; }
        }
      }
    }
    disableDrivers();
    stuurStatus("ok");

  } else if (strcmp(cmd, "home") == 0) {
    homeAxes();

  } else if (strcmp(cmd, "move") == 0) {
    long x = doc.containsKey("x") ? doc["x"].as<long>() : (posX / STEPS_PER_MM);
    long y = doc.containsKey("y") ? doc["y"].as<long>() : (posY / STEPS_PER_MM);
    enableDrivers();
    beweegNaar(x * STEPS_PER_MM, y * STEPS_PER_MM);
    if (!stopGevraagd) {
      disableDrivers();
      stuurStatus("ok");
    }

  } else if (strcmp(cmd, "stop") == 0) {
    stopGevraagd = true;
    sluitKlep();
    disableDrivers();
    stuurStatus("stopped");

  } else if (strcmp(cmd, "klep_open") == 0) {
    openKlep();
    stuurStatus("ok");

  } else if (strcmp(cmd, "klep_dicht") == 0) {
    sluitKlep();
    stuurStatus("ok");

  } else if (strcmp(cmd, "enable") == 0) {
    enableDrivers(); stuurStatus("ok");

  } else if (strcmp(cmd, "disable") == 0) {
    disableDrivers(); stuurStatus("ok");

  } else if (strcmp(cmd, "status") == 0) {
    stuurStatus("ok");

  } else {
    stuurFout("onbekend commando");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_STEP_X, OUTPUT);
  pinMode(PIN_DIR_X,  OUTPUT);
  pinMode(PIN_STEP_Y, OUTPUT);
  pinMode(PIN_DIR_Y,  OUTPUT);
  pinMode(PIN_ENA,    OUTPUT);
  pinMode(PIN_RELAY,  OUTPUT);
  pinMode(PIN_XMIN,   INPUT_PULLUP);
  pinMode(PIN_XMAX,   INPUT_PULLUP);
  pinMode(PIN_YMIN,   INPUT_PULLUP);
  pinMode(PIN_YMAX,   INPUT_PULLUP);
  disableDrivers();
  sluitKlep();
  stuurStatus("ready");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      serieleBuffer[bufferPos] = '\0';
      if (bufferPos > 0) {
        verwerkCommando(serieleBuffer);
      }
      bufferPos = 0;
    } else if (bufferPos < 255) {
      serieleBuffer[bufferPos++] = c;
    }
  }
}
