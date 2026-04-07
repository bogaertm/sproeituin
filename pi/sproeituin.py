#!/usr/bin/env python3
# ================================================================
# Sproeituin Pi - State machine + MQTT + Seriële communicatie
# Btechnics - Matthias Bogaert
#
# Verbindingen:
#   MQTT broker: 192.168.1.117:1883 (Home Assistant Mosquitto)
#   Arduino:     /dev/ttyACM0 via USB serieel (115200 baud)
#
# MQTT topics inkomend (HA → Pi):
#   sproeituin/cmd/jog    {"as":"x","mm":10}
#   sproeituin/cmd/home   (leeg)
#   sproeituin/cmd/start  (leeg)
#   sproeituin/cmd/stop   (leeg)
#   sproeituin/cmd/zone   {"id":0,"name":"Basilicum","x":200,"y":112,"ml":50,"active":true}
#
# MQTT topics uitgaand (Pi → HA):
#   sproeituin/status     online/offline/homing/homed/spraying/idle/stopped/error_noflow
#   sproeituin/sensoren   {"temp":x,"humidity":x,"vpd":x,"moisture":x,...}
#   sproeituin/positie    {"x":x,"y":y}
#   sproeituin/waterlog   {"zone":"naam","ml":x}
#   sproeituin/log        "[123s] tekst"
# ================================================================

import json
import time
import threading
import serial
import paho.mqtt.client as mqtt

# ── INSTELLINGEN ──────────────────────────────────────────
MQTT_BROKER   = "192.168.1.117"
MQTT_PORT     = 1883
MQTT_USER     = "Sproeituin"
MQTT_PASS     = "SproeituinDePinte9840"
MQTT_CLIENT   = "sproeituin_pi"

SERIAL_PORT   = "/dev/ttyACM0"
SERIAL_BAUD   = 115200

# ── ZONES ────────────────────────────────────────────────
ZONES = [
    {"id": 0,  "name": "Basilicum",      "x": 200,  "y": 112, "ml": 50, "active": True},
    {"id": 1,  "name": "Munt",           "x": 600,  "y": 112, "ml": 60, "active": True},
    {"id": 2,  "name": "Rozemarijn",     "x": 1000, "y": 112, "ml": 40, "active": True},
    {"id": 3,  "name": "Tijm",           "x": 1400, "y": 112, "ml": 35, "active": True},
    {"id": 4,  "name": "Peterselie",     "x": 1800, "y": 112, "ml": 45, "active": True},
    {"id": 5,  "name": "Salie",          "x": 200,  "y": 337, "ml": 40, "active": True},
    {"id": 6,  "name": "Citroenmelisse", "x": 600,  "y": 337, "ml": 55, "active": True},
    {"id": 7,  "name": "Oregano",        "x": 1000, "y": 337, "ml": 40, "active": True},
    {"id": 8,  "name": "Bieslook",       "x": 1400, "y": 337, "ml": 50, "active": True},
    {"id": 9,  "name": "Koriander",      "x": 1800, "y": 337, "ml": 45, "active": True},
]

# ── STATE MACHINE ────────────────────────────────────────
class Sproeituin:
    def __init__(self):
        self.state = "idle"
        self.is_homed = False
        self.pos_x = 0
        self.pos_y = 0
        self.pending_start_after_home = False

        # Seriële verbinding met Arduino
        self.ser = None
        self.ser_lock = threading.Lock()

        # MQTT
        self.mqtt = None
        self.start_time = time.time()

        # Zones
        self.zones = ZONES.copy()

    # ── LOGGING ──────────────────────────────────────────
    def log(self, msg):
        uptime = int(time.time() - self.start_time)
        print(f"[{uptime}s] {msg}")
        if self.mqtt:
            self.mqtt.publish("sproeituin/log", f"[{uptime}s] {msg}", retain=False)

    def status(self, s):
        self.state = s
        self.log(f"Status: {s}")
        if self.mqtt:
            self.mqtt.publish("sproeituin/status", s, retain=True)

    def publish_positie(self):
        if self.mqtt:
            data = {"x": self.pos_x, "y": self.pos_y}
            self.mqtt.publish("sproeituin/positie", json.dumps(data), retain=True)

    # ── SERIEEL NAAR ARDUINO ─────────────────────────────
    def stuur_arduino(self, commando: dict, wacht_antwoord=True) -> dict:
        if not self.ser:
            return {"status": "error", "msg": "geen seriële verbinding"}
        try:
            with self.ser_lock:
                lijn = json.dumps(commando) + "\n"
                self.ser.write(lijn.encode())
                self.ser.flush()
                if wacht_antwoord:
                    antwoord = self.ser.readline().decode().strip()
                    if antwoord:
                        result = json.loads(antwoord)
                        if "x" in result:
                            self.pos_x = result["x"]
                        if "y" in result:
                            self.pos_y = result["y"]
                        return result
        except Exception as e:
            self.log(f"Serieel fout: {e}")
        return {"status": "error"}

    # ── COMMANDO'S ───────────────────────────────────────
    def cmd_jog(self, as_naam, mm):
        if self.state not in ("idle", "jogging"):
            self.log(f"Jog genegeerd: state={self.state}")
            return
        self.state = "jogging"
        result = self.stuur_arduino({"cmd": "jog", "as": as_naam, "mm": mm})
        self.state = "idle"
        self.publish_positie()
        self.log(f"Jog {as_naam} {mm}mm klaar")

    def cmd_home(self):
        if self.state != "idle":
            self.log(f"Home genegeerd: state={self.state}")
            return
        self.status("homing")
        self.log("Homing gestart")
        result = self.stuur_arduino({"cmd": "home"}, wacht_antwoord=True)
        if result.get("status") == "homed":
            self.is_homed = True
            self.pos_x = 0
            self.pos_y = 0
            self.status("homed")
            self.publish_positie()
            if self.pending_start_after_home:
                self.pending_start_after_home = False
                self.cmd_start()
        else:
            self.log(f"Homing fout: {result}")
            self.status("error")

    def cmd_stop(self):
        self.stuur_arduino({"cmd": "stop"}, wacht_antwoord=False)
        self.status("stopped")

    def cmd_start(self):
        if not self.is_homed:
            self.log("Niet gehomed — eerst homen")
            self.pending_start_after_home = True
            threading.Thread(target=self.cmd_home, daemon=True).start()
            return
        if self.state != "idle":
            self.log(f"Start genegeerd: state={self.state}")
            return
        threading.Thread(target=self._sproei_cyclus, daemon=True).start()

    def _sproei_cyclus(self):
        self.status("spraying")
        totaal_ml = 0
        for zone in self.zones:
            if not zone["active"] or self.state != "spraying":
                continue
            self.log(f"Zone: {zone['name']}")
            result = self.stuur_arduino({"cmd": "move", "x": zone["x"], "y": zone["y"]})
            if result.get("status") != "ok":
                self.log(f"Move fout naar {zone['name']}")
                continue
            self.publish_positie()

            # Sproei simulatie — pas aan met echte flowmeter via Pi GPIO
            # TODO: koppel flowmeter aan Pi GPIO pin en meet ml
            time.sleep(2)  # tijdelijk: 2s sproei per zone
            ml = zone["ml"]
            totaal_ml += ml

            if self.mqtt:
                self.mqtt.publish("sproeituin/waterlog",
                    json.dumps({"zone": zone["name"], "ml": ml}))

        # Terug naar home
        self.stuur_arduino({"cmd": "move", "x": 0, "y": 0})
        self.stuur_arduino({"cmd": "disable"})
        self.publish_positie()
        self.status("idle")
        self.log(f"Sproei klaar {totaal_ml} ml")

    def cmd_zone_update(self, data):
        zone_id = data.get("id", -1)
        if 0 <= zone_id < len(self.zones):
            for key in ("name", "x", "y", "ml", "active"):
                if key in data:
                    self.zones[zone_id][key] = data[key]
            self.log(f"Zone {zone_id} bijgewerkt")


# ── MQTT SETUP ───────────────────────────────────────────
sproeituin = Sproeituin()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        sproeituin.log("MQTT verbonden")
        client.publish("sproeituin/status", "online", retain=True)
        client.subscribe("sproeituin/cmd/jog")
        client.subscribe("sproeituin/cmd/home")
        client.subscribe("sproeituin/cmd/start")
        client.subscribe("sproeituin/cmd/stop")
        client.subscribe("sproeituin/cmd/zone")
    else:
        print(f"MQTT verbinding mislukt rc={rc}")

def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode().strip()

    if topic == "sproeituin/cmd/jog":
        try:
            data = json.loads(payload) if payload else {}
            as_naam = data.get("as", "x")
            mm = data.get("mm", 0)
            threading.Thread(target=sproeituin.cmd_jog,
                args=(as_naam, mm), daemon=True).start()
        except Exception as e:
            sproeituin.log(f"Jog fout: {e}")

    elif topic == "sproeituin/cmd/home":
        threading.Thread(target=sproeituin.cmd_home, daemon=True).start()

    elif topic == "sproeituin/cmd/start":
        sproeituin.cmd_start()

    elif topic == "sproeituin/cmd/stop":
        sproeituin.cmd_stop()

    elif topic == "sproeituin/cmd/zone":
        try:
            data = json.loads(payload)
            sproeituin.cmd_zone_update(data)
        except Exception as e:
            sproeituin.log(f"Zone update fout: {e}")

def on_disconnect(client, userdata, rc):
    sproeituin.log(f"MQTT verbroken rc={rc}")

# ── MAIN ─────────────────────────────────────────────────
def main():
    # Seriële verbinding met Arduino
    print(f"Verbinden met Arduino op {SERIAL_PORT}...")
    try:
        sproeituin.ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=35)
        time.sleep(2)  # wacht op Arduino reset na verbinding
        # Lees welkomstbericht
        welkom = sproeituin.ser.readline().decode().strip()
        print(f"Arduino: {welkom}")
    except Exception as e:
        print(f"WAARSCHUWING: Geen Arduino verbinding: {e}")
        print("Script gaat door zonder Arduino (test modus)")

    # MQTT verbinding
    print(f"Verbinden met MQTT op {MQTT_BROKER}...")
    client = mqtt.Client(client_id=MQTT_CLIENT)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.will_set("sproeituin/status", "offline", retain=True)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    sproeituin.mqtt = client

    print("Sproeituin gestart. Wacht op commando's...")
    client.loop_forever()

if __name__ == "__main__":
    main()
