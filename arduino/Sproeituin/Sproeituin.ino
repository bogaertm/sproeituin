// ================================================================
// Sproeituin v2.5 - Btechnics - Matthias Bogaert
// Webserver + OTA + MQTT + LED Matrix
// Geen extra libraries nodig buiten de standaard lijst
// ================================================================

#include <WiFiS3.h>
#include <ArduinoOTA.h>
#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"
#include <AccelStepper.h>
#include <DHT.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>

// ── INSTELLINGEN ─────────────────────────────────────────
const char* WIFI_SSID   = "BTECHNICS-WIFI";
const char* WIFI_PASS   = "98409840";
const char* MQTT_SERVER = "192.168.1.117";
const int   MQTT_PORT   = 1883;
const char* MQTT_CLIENT = "sproeituin";
const char* MQTT_USER   = "";
const char* MQTT_PASS_M = "";
const char* OTA_NAAM    = "sproeituin";
const char* OTA_PASS    = "btechnics123";

// ── PINOUT ────────────────────────────────────────────────
#define PIN_FLOW      2
#define PIN_STEP_X    3
#define PIN_DIR_X     4
#define PIN_STEP_Y    5
#define PIN_DIR_Y     6
#define PIN_ENA       7
#define PIN_RELAY     8
#define PIN_BUTTON    9
#define PIN_DHT       10
#define PIN_XMIN      11
#define PIN_YMIN      13
#define PIN_MOISTURE  A1

// ── MOTOR ─────────────────────────────────────────────────
#define STEPS_PER_MM  40
#define BED_X_MM      2000
#define BED_Y_MM      450
#define SPEED_HOMING  500
#define SPEED_TRAVEL  1600
#define ACCELERATION  400
#define SOFT_LIMIT_X  ((long)BED_X_MM * STEPS_PER_MM)
#define SOFT_LIMIT_Y  ((long)BED_Y_MM * STEPS_PER_MM)

// ── WATER ─────────────────────────────────────────────────
#define FLOW_PULSES_PER_LITER  450
#define FLOW_MIN_RATE          3
#define FLOW_TIMEOUT_MS        4000

// ── MQTT TOPICS ───────────────────────────────────────────
#define T_STATUS    "sproeituin/status"
#define T_SENSOR    "sproeituin/sensoren"
#define T_POSITIE   "sproeituin/positie"
#define T_WATERLOG  "sproeituin/waterlog"
#define T_CMD_START "sproeituin/cmd/start"
#define T_CMD_STOP  "sproeituin/cmd/stop"
#define T_CMD_HOME  "sproeituin/cmd/home"
#define T_CMD_LCD   "sproeituin/cmd/lcd"
#define T_CMD_ZONE  "sproeituin/cmd/zone"
#define T_CMD_JOG   "sproeituin/cmd/jog"

// ── OBJECTEN ──────────────────────────────────────────────
AccelStepper     stepperX(AccelStepper::DRIVER, PIN_STEP_X, PIN_DIR_X);
AccelStepper     stepperY(AccelStepper::DRIVER, PIN_STEP_Y, PIN_DIR_Y);
DHT              dht(PIN_DHT, DHT11);
WiFiClient       wifiClient;
PubSubClient     mqtt(wifiClient);
ArduinoLEDMatrix matrix;
WiFiServer       webServer(80);

// ── SYSTEEM ───────────────────────────────────────────────
enum SystemState { IDLE, HOMING, SPRAYING, JOGGING, ERROR_STATE };
SystemState state   = IDLE;
bool        isHomed = false;

// ── SETUP STATE MACHINE ───────────────────────────────────
enum SetupState { SS_WIFI_WAIT, SS_OTA_START, SS_MQTT_CONNECT, SS_MQTT_WAIT, SS_DONE };
SetupState    setupState = SS_WIFI_WAIT;
bool          setupKlaar = false;
unsigned long setupTimer = 0;
int           setupRetry = 0;

// ── WATER ─────────────────────────────────────────────────
volatile long flowPulses     = 0;
long          flowPulsesLast = 0;
long          sessionMl      = 0;
bool          valveOpen      = false;
unsigned long valveOpenedAt  = 0;
unsigned long lastFlowCheck  = 0;

// ── ZONES ─────────────────────────────────────────────────
struct Zone { char name[16]; int x_mm, y_mm, waterMl; bool active; };
Zone zones[10];
int  zoneCount = 0;

// ── LCD ───────────────────────────────────────────────────
enum LcdPage { PG_STATUS, PG_TEMP, PG_MOISTURE, PG_WATER, PG_ZONE };
LcdPage       lcdPage    = PG_STATUS;
unsigned long lastLcdUpd = 0;

// ── SENSOREN ──────────────────────────────────────────────
float         temp = 0, hum = 0, vpd = 0;
int           moisture    = 0;
unsigned long lastSensorR = 0;
unsigned long lastMqttPub = 0;

// ── KNOP ──────────────────────────────────────────────────
bool          btnWasPressed = false;
unsigned long lastBtnCheck  = 0;

// ── LED MATRIX ────────────────────────────────────────────
String        tickerMsg  = "BTECHNICS IOT  ";
unsigned long lastTicker = 0;
int           tickerPos  = 0;
unsigned long lastAnim   = 0;
int           animFrame  = 0;
const char*   animFrames[4] = {"|  ", "/  ", "-  ", "\\  "};

// LOG BUFFER
#define LOG_SIZE 12
char logBuf[LOG_SIZE][40];
int  logIdx = 0;

void addLog(const char* msg) {
  unsigned long s = millis() / 1000;
  snprintf(logBuf[logIdx % LOG_SIZE], 40, "[%lus] %s", s, msg);
  logIdx++;
  Serial.println(msg);
}

// WEBSERVER WATCHDOG
unsigned long lastWebRequest = 0;
unsigned long lastWebRestart = 0;

// ── HULPFUNCTIES ──────────────────────────────────────────
void safeStrCopy(char* dst, const char* src, size_t maxLen) {
  strncpy(dst, src, maxLen - 1);
  dst[maxLen - 1] = '\0';
}

void nonBlockingDelay(unsigned long ms) {
  unsigned long start = millis();
  while (millis() - start < ms) matrixUpdate();
}

void onFlowPulse() { if (valveOpen) flowPulses++; }

// ─────────────────────────────────────────────────────────
//  MATRIX
// ─────────────────────────────────────────────────────────
void matrixUpdate() {
  if (millis() - lastTicker < 500) return;
  lastTicker = millis();
  matrix.beginDraw();
  matrix.stroke(0xFFFFFFFF);
  matrix.textFont(Font_4x6);
  matrix.beginText(0, 1, 0xFFFFFF);
  if      (!setupKlaar)       matrix.print(animFrames[animFrame++ % 4]);
  else if (state == SPRAYING) matrix.print("SPR");
  else if (state == HOMING)   matrix.print("HOM");
  else if (state == JOGGING)  matrix.print("JOG");
  else if (state == ERROR_STATE) matrix.print("ERR");
  else                        matrix.print(" OK");
  matrix.endText();
  matrix.endDraw();
}

// ─────────────────────────────────────────────────────────
//  WEBSERVER HTML
// ─────────────────────────────────────────────────────────
void stuurOK(WiFiClient& client) {
  client.println(F("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK"));
}

void stuurWebpagina(WiFiClient& client) {
  client.println(F("HTTP/1.1 200 OK"));
  client.println(F("Content-Type: text/html; charset=utf-8"));
  client.println(F("Connection: close"));
  client.println();
  client.println(F("<!DOCTYPE html><html><head><meta charset='utf-8'>"));
  client.println(F("<meta name='viewport' content='width=device-width,initial-scale=1'>"));
  client.println(F("<title>Sproeituin - Btechnics</title>"));
  client.println(F("<style>"));
  client.println(F("body{font-family:Arial,sans-serif;margin:0;padding:16px;background:#f5f5f5;color:#333}"));
  client.println(F("h1{color:#ED6928;margin:0 0 4px}h1 small{font-size:13px;color:#999;font-weight:normal}"));
  client.println(F("h2{color:#F59E32;margin:16px 0 8px;font-size:15px}"));
  client.println(F(".card{background:#fff;border-radius:8px;padding:14px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,.08)}"));
  client.println(F(".grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}"));
  client.println(F(".metric{background:#f9f9f9;border-radius:6px;padding:8px;text-align:center}"));
  client.println(F(".metric .val{font-size:18px;font-weight:bold;color:#ED6928}"));
  client.println(F(".metric .lbl{font-size:10px;color:#999}"));
  client.println(F("button{padding:10px 14px;border:none;border-radius:6px;cursor:pointer;font-size:13px;margin:3px}"));
  client.println(F(".g{background:#22c55e;color:#fff}.r{background:#ef4444;color:#fff}.b{background:#3b82f6;color:#fff}.o{background:#f59e0b;color:#fff}"));
  client.println(F(".jog{width:46px;height:46px;padding:0;font-size:18px}"));
  client.println(F(".jg{display:grid;grid-template-columns:repeat(3,46px);gap:5px;justify-content:center;margin:8px 0}"));
  client.println(F(".st{display:inline-block;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:bold}"));
  client.println(F(".ok{background:#dcfce7;color:#16a34a}.bz{background:#dbeafe;color:#1d4ed8}.er{background:#fee2e2;color:#dc2626}"));
  client.println(F("input[type=text],input[type=number]{padding:5px;border:1px solid #ddd;border-radius:4px;box-sizing:border-box}"));
  client.println(F("table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:5px 6px;border-bottom:1px solid #eee}th{color:#aaa;font-weight:normal}"));
  client.println(F("#px,#py{font-size:18px;font-weight:bold;color:#ED6928}"));
  client.println(F("</style>"));
  // JavaScript - geen page reload voor jog en commando's
  client.println(F("<script>"));
  client.println(F("function cmd(url){fetch(url).then(()=>{if(url.includes('jog'))updatePos()}).catch(()=>{})}"));
  client.println(F("function updatePos(){fetch('/pos').then(r=>r.text()).then(t=>{var p=t.split(',');document.getElementById('px').innerText=p[0]+' mm';document.getElementById('py').innerText=p[1]+' mm'})}"));
  client.println(F("setInterval(function(){fetch('/status').then(r=>r.text()).then(t=>{var p=t.split(',');"));
  client.println(F("document.getElementById('st').className='st '+p[0];document.getElementById('st').innerText=p[1];"));
  client.println(F("document.getElementById('px').innerText=p[2]+' mm';document.getElementById('py').innerText=p[3]+' mm'})},3000);"));
  client.println(F("</script></head><body>"));

  // Header
  client.print(F("<h1>Sproeituin <small>"));
  client.print(WiFi.localIP());
  client.println(F("</small></h1>"));

  // Status
  client.println(F("<div class='card'>"));
  client.print(F("<span class='st "));
  if      (state == IDLE)     client.print(F("ok' id='st'>Klaar"));
  else if (state == SPRAYING) client.print(F("bz' id='st'>Sproeiing"));
  else if (state == HOMING)   client.print(F("bz' id='st'>Homing"));
  else if (state == JOGGING)  client.print(F("bz' id='st'>Manueel"));
  else                        client.print(F("er' id='st'>FOUT"));
  client.println(F("</span>&nbsp;"));
  client.print(isHomed ? F("<span class='st ok'>Gehomed</span>") : F("<span class='st er'>Niet gehomed</span>"));
  client.println(F("</div>"));

  // Sensoren
  client.println(F("<div class='card'><h2>Sensoren</h2><div class='grid'>"));
  client.print(F("<div class='metric'><div class='val'>")); client.print(temp,1); client.println(F("°C</div><div class='lbl'>Temp</div></div>"));
  client.print(F("<div class='metric'><div class='val'>")); client.print(hum,0);  client.println(F("%</div><div class='lbl'>Vochtigheid</div></div>"));
  client.print(F("<div class='metric'><div class='val'>")); client.print(vpd,2);  client.println(F("kPa</div><div class='lbl'>VPD</div></div>"));
  client.print(F("<div class='metric'><div class='val'>")); client.print(map(moisture,1023,0,0,100)); client.println(F("%</div><div class='lbl'>Bodem</div></div>"));
  client.print(F("<div class='metric'><div class='val'>")); client.print(sessionMl); client.println(F("ml</div><div class='lbl'>Sessie</div></div>"));
  client.print(F("<div class='metric'><div class='val'>")); client.print(WiFi.RSSI()); client.println(F("dBm</div><div class='lbl'>WiFi</div></div>"));
  client.println(F("</div></div>"));

  // Bediening
  client.println(F("<div class='card'><h2>Bediening</h2>"));
  client.println(F("<button class='g' onclick=\"cmd('/start')\">Sproei starten</button>"));
  client.println(F("<button class='r' onclick=\"cmd('/stop')\">Noodstop</button>"));
  client.println(F("<button class='b' onclick=\"cmd('/home')\">Home</button>"));
  client.println(F("</div>"));

  // Jog
  client.println(F("<div class='card'><h2>Manuele bediening</h2>"));
  client.println(F("<div style='display:flex;gap:12px;align-items:center;margin-bottom:8px'>"));
  client.println(F("X: <span id='px'>"));
  client.print((int)(stepperX.currentPosition()/STEPS_PER_MM));
  client.println(F(" mm</span>&nbsp;&nbsp;Y: <span id='py'>"));
  client.print((int)(stepperY.currentPosition()/STEPS_PER_MM));
  client.println(F(" mm</span></div>"));
  client.println(F("<div class='jg'>"));
  client.println(F("<div></div><button class='o jog' onclick=\"cmd('/jog?as=y&mm=10')\">▲</button><div></div>"));
  client.println(F("<button class='o jog' onclick=\"cmd('/jog?as=x&mm=-10')\">◀</button>"));
  client.println(F("<button class='jog' style='background:#ddd' onclick=\"cmd('/home')\">⌂</button>"));
  client.println(F("<button class='o jog' onclick=\"cmd('/jog?as=x&mm=10')\">▶</button>"));
  client.println(F("<div></div><button class='o jog' onclick=\"cmd('/jog?as=y&mm=-10')\">▼</button><div></div>"));
  client.println(F("</div>"));
  client.println(F("<div style='margin-top:6px'>Stap: "));
  client.println(F("<button onclick=\"jogStap=1\" style='padding:4px 8px;background:#eee;border:none;border-radius:4px'>1mm</button>"));
  client.println(F("<button onclick=\"jogStap=10\" style='padding:4px 8px;background:#f59e0b;color:#fff;border:none;border-radius:4px'>10mm</button>"));
  client.println(F("<button onclick=\"jogStap=50\" style='padding:4px 8px;background:#eee;border:none;border-radius:4px'>50mm</button>"));
  client.println(F("<button onclick=\"jogStap=100\" style='padding:4px 8px;background:#eee;border:none;border-radius:4px'>100mm</button>"));
  client.println(F("</div></div>"));
  // Fix jog stapgrootte via JS
  client.println(F("<script>var jogStap=10;"));
  client.println(F("document.querySelectorAll('.jg button').forEach(b=>{var orig=b.getAttribute('onclick');"));
  client.println(F("if(orig&&orig.includes('jog')){b.onclick=function(){var u=orig.replace('/jog?as=','').replace(\"')\",\"\").replace(\"cmd('\",\"\");"));
  client.println(F("var parts=u.split('&mm=');cmd('/jog?as='+parts[0]+'&mm='+(parseInt(parts[1])>0?jogStap:-jogStap))}}})</script>"));

  // Zones
  client.println(F("<div class='card'><h2>Plantenzones</h2>"));
  client.println(F("<table><tr><th>#</th><th>Naam</th><th>X</th><th>Y</th><th>ml</th><th>Aan</th><th></th></tr>"));
  for (int i = 0; i < zoneCount; i++) {
    client.print(F("<tr><form action='/zone' method='get'>"));
    client.print(F("<input type='hidden' name='id' value='")); client.print(i); client.print(F("'>"));
    client.print(F("<td>")); client.print(i); client.print(F("</td>"));
    client.print(F("<td><input type='text' name='name' value='")); client.print(zones[i].name); client.print(F("' style='width:80px'></td>"));
    client.print(F("<td><input type='number' name='x' value='")); client.print(zones[i].x_mm); client.print(F("' style='width:55px'></td>"));
    client.print(F("<td><input type='number' name='y' value='")); client.print(zones[i].y_mm); client.print(F("' style='width:55px'></td>"));
    client.print(F("<td><input type='number' name='ml' value='")); client.print(zones[i].waterMl); client.print(F("' style='width:50px'></td>"));
    client.print(F("<td><input type='checkbox' name='active' value='1'")); if (zones[i].active) client.print(F(" checked")); client.print(F("></td>"));
    client.println(F("<td><button type='submit' style='background:#ED6928;color:#fff;border:none;border-radius:4px;padding:3px 8px;cursor:pointer'>OK</button></td>"));
    client.println(F("</form></tr>"));
  }
  client.println(F("</table></div>"));
  client.println(F("<p style='text-align:center;margin-top:8px'><a href='/log' style='color:#999;font-size:12px'>Log bekijken</a></p>"));
  client.println(F("</body></html>"));
}

void stuurRedirect(WiFiClient& client, const char* url) {
  client.print(F("HTTP/1.1 302 Found\r\nLocation: "));
  client.print(url);
  client.println(F("\r\nConnection: close\r\n"));
}

void handleWebServer() {
  WiFiClient client = webServer.available();
  if (!client) return;

  unsigned long timeout = millis() + 500;
  while (!client.available() && millis() < timeout) { matrixUpdate(); }
  if (!client.available()) { client.stop(); return; }

  String req = client.readStringUntil('\r');
  client.flush();

  // Parseer URL — commando's sturen "OK" terug zonder page reload
  if (req.indexOf("GET /start") >= 0) {
    if (state == IDLE) startSprayCycle();
    stuurOK(client);

  } else if (req.indexOf("GET /stop") >= 0) {
    emergencyStop();
    stuurOK(client);

  } else if (req.indexOf("GET /home") >= 0) {
    if (state == IDLE) homeAxes();
    stuurOK(client);

  } else if (req.indexOf("GET /jog") >= 0) {
    // Stuur response EERST — dan beweegt de motor via de hoofdloop
    int asIdx = req.indexOf("as=");
    int mmIdx = req.indexOf("mm=");
    if (asIdx >= 0 && mmIdx >= 0) {
      char asChar = req.charAt(asIdx + 3);
      int mm = req.substring(mmIdx + 3).toInt();
      if (mm != 0 && (state == IDLE || state == JOGGING)) {
        enableDrivers();
        state = JOGGING;
        if (asChar == 'x') {
          long doel = constrain(stepperX.currentPosition() + (long)mm * STEPS_PER_MM, 0L, SOFT_LIMIT_X);
          stepperX.moveTo(doel);
        } else {
          long doel = constrain(stepperY.currentPosition() + (long)mm * STEPS_PER_MM, 0L, SOFT_LIMIT_Y);
          stepperY.moveTo(doel);
        }
      }
    }
    // Stuur positie terug — motor beweegt verder in de hoofdloop
    client.println(F("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n"));
    client.print((int)(stepperX.currentPosition()/STEPS_PER_MM));
    client.print(",");
    client.println((int)(stepperY.currentPosition()/STEPS_PER_MM));

  } else if (req.indexOf("GET /pos") >= 0) {
    // Geeft X,Y terug voor live update
    client.println(F("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n"));
    client.print((int)(stepperX.currentPosition()/STEPS_PER_MM));
    client.print(",");
    client.println((int)(stepperY.currentPosition()/STEPS_PER_MM));

  } else if (req.indexOf("GET /status") >= 0) {
    // Geeft status,label,X,Y terug voor live update
    client.println(F("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n"));
    String klasse, label;
    if      (state == IDLE)     { klasse="ok";  label="Klaar"; }
    else if (state == SPRAYING) { klasse="bz";  label="Sproeiing"; }
    else if (state == HOMING)   { klasse="bz";  label="Homing"; }
    else if (state == JOGGING)  { klasse="bz";  label="Manueel"; }
    else                        { klasse="er";  label="FOUT"; }
    client.print(klasse); client.print(","); client.print(label); client.print(",");
    client.print((int)(stepperX.currentPosition()/STEPS_PER_MM)); client.print(",");
    client.println((int)(stepperY.currentPosition()/STEPS_PER_MM));

  } else if (req.indexOf("GET /zone") >= 0) {
    int idIdx = req.indexOf("id=");
    int nmIdx = req.indexOf("name=");
    int xIdx  = req.indexOf("&x=");
    int yIdx  = req.indexOf("&y=");
    int mlIdx = req.indexOf("&ml=");
    int acIdx = req.indexOf("&active=");
    if (idIdx >= 0) {
      int id = req.substring(idIdx + 3).toInt();
      if (id >= 0 && id < 10) {
        if (nmIdx >= 0) {
          String naam = req.substring(nmIdx + 5);
          naam = naam.substring(0, naam.indexOf('&'));
          naam.replace("+", " ");
          safeStrCopy(zones[id].name, naam.c_str(), 16);
        }
        if (xIdx  >= 0) zones[id].x_mm    = req.substring(xIdx  + 3).toInt();
        if (yIdx  >= 0) zones[id].y_mm    = req.substring(yIdx  + 3).toInt();
        if (mlIdx >= 0) zones[id].waterMl = req.substring(mlIdx + 4).toInt();
        zones[id].active = (acIdx >= 0);
      }
    }
    stuurRedirect(client, "/");

  } else if (req.indexOf("GET /log") >= 0) {
    client.println(F("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n"));
    client.println(F("<html><head><meta charset='utf-8'><meta http-equiv='refresh' content='5'>"));
    client.println(F("<title>Log</title><style>body{font-family:monospace;padding:16px;background:#111;color:#0f0}"));
    client.println(F("h1{color:#ED6928}p{margin:2px 0;font-size:13px}</style></head><body>"));
    client.println(F("<h1>Sproeituin Log</h1>"));
    client.print(F("<p>Uptime: ")); client.print(millis()/1000); client.println(F("s</p>"));
    client.print(F("<p>WiFi: ")); client.print(WiFi.localIP()); client.println(F("</p>"));
    client.print(F("<p>MQTT: ")); client.println(mqtt.connected() ? F("OK") : F("NIET verbonden"));
    client.println(F("<hr>"));
    int start = logIdx > LOG_SIZE ? logIdx - LOG_SIZE : 0;
    for (int i = start; i < logIdx; i++) {
      client.print(F("<p>")); client.print(logBuf[i % LOG_SIZE]); client.println(F("</p>"));
    }
    client.println(F("<p><a href='/' style='color:#ED6928'>Terug</a></p></body></html>"));

  } else {
    stuurWebpagina(client);
  }

  client.stop();  // geen delay meer
}

// ─────────────────────────────────────────────────────────
//  SETUP
// ─────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  matrix.begin();

  pinMode(PIN_ENA,      OUTPUT);
  pinMode(PIN_RELAY,    OUTPUT);
  pinMode(PIN_BUTTON,   INPUT_PULLUP);
  pinMode(PIN_XMIN,     INPUT_PULLUP);
  pinMode(PIN_YMIN,     INPUT_PULLUP);
  pinMode(PIN_MOISTURE, INPUT);

  disableDrivers();
  closeValve();

  stepperX.setMaxSpeed(SPEED_TRAVEL); stepperX.setAcceleration(ACCELERATION);
  stepperY.setMaxSpeed(SPEED_TRAVEL); stepperY.setAcceleration(ACCELERATION);
  stepperX.setCurrentPosition(0);     stepperY.setCurrentPosition(0);

  attachInterrupt(digitalPinToInterrupt(PIN_FLOW), onFlowPulse, RISING);

  dht.begin();

  addZone("Basilicum",       200,  112, 50);
  addZone("Munt",            600,  112, 60);
  addZone("Rozemarijn",     1000,  112, 40);
  addZone("Tijm",           1400,  112, 35);
  addZone("Peterselie",     1800,  112, 45);
  addZone("Salie",           200,  337, 40);
  addZone("Citroenmelisse",  600,  337, 55);
  addZone("Oregano",        1000,  337, 40);
  addZone("Bieslook",       1400,  337, 50);
  addZone("Koriander",      1800,  337, 45);

  lcdPrint("WiFi verbinden", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  setupState = SS_WIFI_WAIT;
  setupTimer = millis();
}

// ── MQTT herverbinding timer ───────────────────────────────
unsigned long lastMqttRetry = 0;

// ─────────────────────────────────────────────────────────
//  LOOP — webserver en matrix draaien altijd
//  MQTT is optioneel en blokkeert nooit de rest
// ─────────────────────────────────────────────────────────
void loop() {
  matrixUpdate();  // altijd als eerste

  if (!setupKlaar) {
    setupLoop();
    return;
  }

  // Altijd uitvoeren — onafhankelijk van MQTT
  ArduinoOTA.poll();
  handleWebServer();

  // Herstart webserver als meer dan 5 min geen request
  if (millis() - lastWebRestart > 300000) {
    lastWebRestart = millis();
    webServer.end();
    webServer.begin();
    addLog("Webserver herstart");
  }

  stepperX.run();
  stepperY.run();

  // Zet state terug naar IDLE als motoren klaar zijn met jog
  if (state == JOGGING && !stepperX.isRunning() && !stepperY.isRunning()) {
    state = IDLE;
    publishPositie();
  }

  handleButton();
  handleFlowMonitor();

  // MQTT — probeer elke 30 seconden opnieuw als niet verbonden
  if (mqtt.connected()) {
    mqtt.loop();
  } else if (millis() - lastMqttRetry > 30000) {
    lastMqttRetry = millis();
    if (mqtt.connect(MQTT_CLIENT, MQTT_USER, MQTT_PASS_M, T_STATUS, 1, true, "offline")) {
      mqtt.publish(T_STATUS, "online", true);
      mqtt.subscribe(T_CMD_START); mqtt.subscribe(T_CMD_STOP);
      mqtt.subscribe(T_CMD_HOME);  mqtt.subscribe(T_CMD_LCD);
      mqtt.subscribe(T_CMD_ZONE);  mqtt.subscribe(T_CMD_JOG);
      addLog("MQTT herverbonden");
    }
  }

  if (millis() - lastSensorR > 10000) { readSensors();    lastSensorR = millis(); }
  if (millis() - lastMqttPub > 30000) { publishSensors(); lastMqttPub = millis(); }
  if (millis() - lastLcdUpd  > 2000)  { updateLcd();      lastLcdUpd  = millis(); }
}

// ─────────────────────────────────────────────────────────
//  SETUP STATE MACHINE
// ─────────────────────────────────────────────────────────
void setupLoop() {
  switch (setupState) {
    case SS_WIFI_WAIT:
      if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0,0,0,0)) {
        // Extra wachttijd zodat DHCP volledig klaar is
        if (millis() - setupTimer < 2000) break;
        addLog("WiFi OK"); Serial.println(WiFi.localIP());
        lcdPrint("WiFi OK", WiFi.localIP().toString().c_str());
        setupState = SS_OTA_START;
        setupTimer = millis();
      } else if (WiFi.status() == WL_CONNECTED) {
        // Verbonden maar nog geen IP — reset timer
        setupTimer = millis();
      } else if (millis() - setupTimer > 15000) {
        Serial.println(F("WiFi timeout"));
        setupState = SS_MQTT_CONNECT;
      }
      break;

    case SS_OTA_START:
      ArduinoOTA.begin(WiFi.localIP(), OTA_NAAM, OTA_PASS, InternalStorage);
      webServer.begin();
      addLog("OTA + Webserver klaar");
      mqtt.setServer(MQTT_SERVER, MQTT_PORT);
      mqtt.setCallback(mqttCallback);
      mqtt.setBufferSize(512);
      setupState = SS_MQTT_CONNECT;
      setupRetry = 0;
      break;

    case SS_MQTT_CONNECT:
      lcdPrint("MQTT verbinden", MQTT_SERVER);
      if (mqtt.connect(MQTT_CLIENT, MQTT_USER, MQTT_PASS_M, T_STATUS, 1, true, "offline")) {
        mqtt.publish(T_STATUS, "online", true);
        mqtt.subscribe(T_CMD_START); mqtt.subscribe(T_CMD_STOP);
        mqtt.subscribe(T_CMD_HOME);  mqtt.subscribe(T_CMD_LCD);
        mqtt.subscribe(T_CMD_ZONE);  mqtt.subscribe(T_CMD_JOG);
        addLog("MQTT OK");
        setupState = SS_DONE;
      } else {
        char mqttLog[32]; snprintf(mqttLog, 32, "MQTT mislukt rc=%d", mqtt.state()); addLog(mqttLog);
        setupRetry++;
        // Na 5 pogingen toch verder — webserver werkt ook zonder MQTT
        if (setupRetry > 5) {
          Serial.println(F("MQTT overgeslagen — verder zonder"));
          setupState = SS_DONE;
        } else {
          setupTimer = millis();
          setupState = SS_MQTT_WAIT;
        }
      }
      break;

    case SS_MQTT_WAIT:
      if (millis() - setupTimer > 2000) setupState = SS_MQTT_CONNECT;
      break;

    case SS_DONE:
      setupKlaar = true; setupRetry = 0; tickerPos = 0;
      setLcdColor(0, 255, 0);
      lcdPrint("Btechnics IOT", "Klaar");
      addLog("Setup klaar");
      break;
  }
}

// ─────────────────────────────────────────────────────────
//  MQTT CALLBACK
// ─────────────────────────────────────────────────────────
void mqttCallback(char* topic, byte* payload, unsigned int len) {
  char msg[256]; memset(msg, 0, sizeof(msg));
  memcpy(msg, payload, min((unsigned int)(sizeof(msg)-1), len));

  if      (strcmp(topic, T_CMD_START) == 0) { if (state==IDLE) startSprayCycle(); }
  else if (strcmp(topic, T_CMD_STOP)  == 0) { emergencyStop(); }
  else if (strcmp(topic, T_CMD_HOME)  == 0) { if (state==IDLE) homeAxes(); }
  else if (strcmp(topic, T_CMD_LCD)   == 0) {
    if      (strcmp(msg,"status")   == 0) lcdPage = PG_STATUS;
    else if (strcmp(msg,"temp")     == 0) lcdPage = PG_TEMP;
    else if (strcmp(msg,"moisture") == 0) lcdPage = PG_MOISTURE;
    else if (strcmp(msg,"water")    == 0) lcdPage = PG_WATER;
    else if (strcmp(msg,"zone")     == 0) lcdPage = PG_ZONE;
    updateLcd();
  } else if (strcmp(topic, T_CMD_ZONE) == 0) {
    StaticJsonDocument<192> doc;
    if (!deserializeJson(doc, msg)) {
      int id = doc["id"] | -1;
      if (id >= 0 && id < 10) {
        safeStrCopy(zones[id].name, doc["name"] | zones[id].name, 16);
        zones[id].x_mm    = doc["x"]      | zones[id].x_mm;
        zones[id].y_mm    = doc["y"]      | zones[id].y_mm;
        zones[id].waterMl = doc["ml"]     | zones[id].waterMl;
        zones[id].active  = doc["active"] | zones[id].active;
        if (id >= zoneCount) zoneCount = id + 1;
      }
    }
  } else if (strcmp(topic, T_CMD_JOG) == 0) {
    if (state==IDLE || state==JOGGING) {
      StaticJsonDocument<64> doc;
      if (!deserializeJson(doc, msg)) {
        const char* as = doc["as"] | "x"; int mm = doc["mm"] | 0;
        if (mm != 0) {
          enableDrivers(); state = JOGGING;
          if (strcmp(as,"x")==0) {
            long d = constrain(stepperX.currentPosition()+(long)mm*STEPS_PER_MM, 0L, SOFT_LIMIT_X);
            stepperX.moveTo(d);
            while (stepperX.isRunning()) { stepperX.run(); mqtt.loop(); ArduinoOTA.poll(); matrixUpdate(); }
          } else {
            long d = constrain(stepperY.currentPosition()+(long)mm*STEPS_PER_MM, 0L, SOFT_LIMIT_Y);
            stepperY.moveTo(d);
            while (stepperY.isRunning()) { stepperY.run(); mqtt.loop(); ArduinoOTA.poll(); matrixUpdate(); }
          }
          state = IDLE; publishPositie();
        }
      }
    }
  }
}

// ─────────────────────────────────────────────────────────
//  MQTT PUBLICEREN
// ─────────────────────────────────────────────────────────
void publishSensors() {
  StaticJsonDocument<256> doc;
  doc["temp"]=temp; doc["humidity"]=hum; doc["vpd"]=vpd;
  doc["moisture"]=moisture; doc["state"]=(int)state;
  doc["homed"]=isHomed; doc["water_ml"]=sessionMl; doc["rssi"]=WiFi.RSSI();
  char buf[256]; serializeJson(doc, buf);
  mqtt.publish(T_SENSOR, buf, true);
}

void publishPositie() {
  StaticJsonDocument<64> doc;
  doc["x"]=(int)(stepperX.currentPosition()/STEPS_PER_MM);
  doc["y"]=(int)(stepperY.currentPosition()/STEPS_PER_MM);
  char buf[64]; serializeJson(doc, buf);
  mqtt.publish(T_POSITIE, buf, true);
}

void publishWaterLog(const char* naam, int ml) {
  StaticJsonDocument<128> doc; doc["zone"]=naam; doc["ml"]=ml;
  char buf[128]; serializeJson(doc, buf);
  mqtt.publish(T_WATERLOG, buf);
}

// ─────────────────────────────────────────────────────────
//  SENSOREN
// ─────────────────────────────────────────────────────────
void readSensors() {
  float t = dht.readTemperature(); float h = dht.readHumidity();
  if (!isnan(t) && !isnan(h)) {
    temp=t; hum=h;
    float svp = 0.6108f*exp(17.27f*t/(t+237.3f));
    vpd = svp*(1.0f-h/100.0f);
  }
  moisture = analogRead(PIN_MOISTURE);

}

// ─────────────────────────────────────────────────────────
//  LCD
// ─────────────────────────────────────────────────────────
void updateLcd() {}

void setLcdColor(int r, int g, int b) {}
void lcdPrint(const char* r1, const char* r2) { addLog(r1); }

// ─────────────────────────────────────────────────────────
//  KNOP
// ─────────────────────────────────────────────────────────
void handleButton() {
  if (millis()-lastBtnCheck < 50) return; lastBtnCheck=millis();
  bool pressed=(digitalRead(PIN_BUTTON)==LOW);
  if (pressed && !btnWasPressed) {
    btnWasPressed=true;
    if      (state==IDLE)     startSprayCycle();
    else if (state==SPRAYING) emergencyStop();
  }
  if (!pressed) btnWasPressed=false;
}

// ─────────────────────────────────────────────────────────
//  HOMING
// ─────────────────────────────────────────────────────────
void homeAxes() {
  if (state!=IDLE) return;
  state=HOMING; lcdPrint("Homing...","Even geduld");
  mqtt.publish(T_STATUS,"homing"); enableDrivers();

  stepperX.setMaxSpeed(SPEED_HOMING); stepperX.move(-9999999L);
  while (digitalRead(PIN_XMIN)==HIGH) { stepperX.run(); mqtt.loop(); ArduinoOTA.poll(); matrixUpdate(); }
  stepperX.stop(); stepperX.setCurrentPosition(0); nonBlockingDelay(300);
  stepperX.moveTo(5L*STEPS_PER_MM);
  while (stepperX.isRunning()) { stepperX.run(); matrixUpdate(); }
  stepperX.setCurrentPosition(0);

  stepperY.setMaxSpeed(SPEED_HOMING); stepperY.move(-9999999L);
  while (digitalRead(PIN_YMIN)==HIGH) { stepperY.run(); mqtt.loop(); ArduinoOTA.poll(); matrixUpdate(); }
  stepperY.stop(); stepperY.setCurrentPosition(0); nonBlockingDelay(300);
  stepperY.moveTo(5L*STEPS_PER_MM);
  while (stepperY.isRunning()) { stepperY.run(); matrixUpdate(); }
  stepperY.setCurrentPosition(0);

  stepperX.setMaxSpeed(SPEED_TRAVEL); stepperY.setMaxSpeed(SPEED_TRAVEL);
  isHomed=true; state=IDLE;
  mqtt.publish(T_STATUS,"homed"); publishPositie();
  lcdPrint("Homing klaar","Klaar"); setLcdColor(0,255,0);
}

// ─────────────────────────────────────────────────────────
//  SPROEI CYCLUS
// ─────────────────────────────────────────────────────────
void startSprayCycle() {
  if (!isHomed) homeAxes(); if (state!=IDLE) return;
  state=SPRAYING; sessionMl=0;
  mqtt.publish(T_STATUS,"spraying"); enableDrivers();
  for (int i=0;i<zoneCount;i++) { if (!zones[i].active||state!=SPRAYING) continue; sprayZone(i); }
  moveTo(0,0); waitForMove(); closeValve(); disableDrivers(); state=IDLE;
  mqtt.publish(T_STATUS,"idle"); publishSensors(); publishPositie();
  char buf[32]; snprintf(buf,sizeof(buf),"Klaar  %d ml",(int)sessionMl);
  lcdPrint("Sproei gedaan",buf); setLcdColor(0,255,0);
}

void sprayZone(int idx) {
  Zone& z=zones[idx]; char lcdBuf[17]; snprintf(lcdBuf,sizeof(lcdBuf),"%.16s",z.name);
  lcdPrint("Sproei:",lcdBuf); long startPulses=flowPulses;
  moveTo(z.x_mm,z.y_mm); waitForMove(); if (state!=SPRAYING) return;
  openValve(); unsigned long zoneStart=millis();
  while (state==SPRAYING) {
    mqtt.loop(); ArduinoOTA.poll(); matrixUpdate(); handleWebServer();
    int ml=(int)((flowPulses-startPulses)*1000L/FLOW_PULSES_PER_LITER);
    if (ml>=z.waterMl||millis()-zoneStart>30000) break;
  }
  closeValve();
  int ml=(int)((flowPulses-startPulses)*1000L/FLOW_PULSES_PER_LITER);
  sessionMl+=ml; publishWaterLog(z.name,ml); publishPositie();
}

// ─────────────────────────────────────────────────────────
//  BEWEGING
// ─────────────────────────────────────────────────────────
void moveTo(int x_mm,int y_mm) {
  stepperX.moveTo(constrain((long)x_mm*STEPS_PER_MM,0L,SOFT_LIMIT_X));
  stepperY.moveTo(constrain((long)y_mm*STEPS_PER_MM,0L,SOFT_LIMIT_Y));
}
void waitForMove() {
  while (stepperX.isRunning()||stepperY.isRunning()) {
    stepperX.run(); stepperY.run(); mqtt.loop(); ArduinoOTA.poll(); matrixUpdate();
    if (digitalRead(PIN_XMIN)==LOW&&stepperX.currentPosition()<=0) stepperX.stop();
    if (digitalRead(PIN_YMIN)==LOW&&stepperY.currentPosition()<=0) stepperY.stop();
  }
}

// ─────────────────────────────────────────────────────────
//  KLEP, FLOW, NOODSTOP, DRIVERS, ZONES
// ─────────────────────────────────────────────────────────
void openValve()  { digitalWrite(PIN_RELAY,HIGH); valveOpen=true;  valveOpenedAt=millis(); }
void closeValve() { digitalWrite(PIN_RELAY,LOW);  valveOpen=false; }

void handleFlowMonitor() {
  if (!valveOpen||millis()-lastFlowCheck<1000) return; lastFlowCheck=millis();
  long n=flowPulses-flowPulsesLast; flowPulsesLast=flowPulses;
  if (n<FLOW_MIN_RATE&&millis()-valveOpenedAt>FLOW_TIMEOUT_MS) {
    mqtt.publish(T_STATUS,"error_noflow"); lcdPrint("FOUT: geen flow","Check water!");
    setLcdColor(255,0,0); emergencyStop();
  }
}

void emergencyStop() {
  closeValve(); stepperX.stop(); stepperY.stop(); disableDrivers(); state=IDLE;
  mqtt.publish(T_STATUS,"stopped"); lcdPrint("NOODSTOP","Gestopt"); setLcdColor(255,0,0);
}

void enableDrivers()  { digitalWrite(PIN_ENA,HIGH); }
void disableDrivers() { digitalWrite(PIN_ENA,LOW);  }

void addZone(const char* name,int x,int y,int ml) {
  if (zoneCount>=10) return;
  safeStrCopy(zones[zoneCount].name,name,16);
  zones[zoneCount].x_mm=x; zones[zoneCount].y_mm=y;
  zones[zoneCount].waterMl=ml; zones[zoneCount].active=true; zoneCount++;
}

