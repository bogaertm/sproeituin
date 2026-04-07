#!/usr/bin/env python3
# ================================================================
# Sproeituin Pi - State machine + MQTT + Seriële communicatie
# Btechnics - Matthias Bogaert
# v1.15: TOCTOU fix in _veiligheid_monitor + GPIO herstart fix
#        (v1.14: error_serial status + GPIO bouncetime=20ms)
# ================================================================

import json
import time
import threading
import os
import serial
import paho.mqtt.client as mqtt
try:
    import RPi.GPIO as GPIO
    GPIO_BESCHIKBAAR = True
except ImportError:
    GPIO_BESCHIKBAAR = False
    print("WAARSCHUWING: RPi.GPIO niet beschikbaar — flowmeter uitgeschakeld")

MQTT_BROKER  = "192.168.1.117"
MQTT_PORT    = 1883
MQTT_USER    = "Sproeituin"
MQTT_PASS    = "SproeituinDePinte9840"

SERIAL_PORT    = "/dev/ttyACM0"
SERIAL_BAUD    = 115200
SERIAL_TIMEOUT = 5

ZONES_FILE    = "/home/admin/sproeituin_zones.json"
WATERLOG_FILE = "/home/admin/sproeituin_waterlog.json"
MAX_WATERLOG_ENTRIES = 200

GPIO_FLOW_PIN           = 17
FLOW_PULSES_PER_LITER   = 450
FLOW_CHECK_INTERVAL_S   = 1
FLOW_OPEN_TIMEOUT_S     = 5
FLOW_OPEN_MIN_PULSES    = 3
FLOW_GESLOTEN_MAX_PULSE = 2
FLOW_VENSTER_S          = 3

ZONES_DEFAULT = [
    {"id": 0, "name": "Basilicum",      "x": 200,  "y": 112, "ml": 50, "active": True},
    {"id": 1, "name": "Munt",           "x": 600,  "y": 112, "ml": 60, "active": True},
    {"id": 2, "name": "Rozemarijn",     "x": 1000, "y": 112, "ml": 40, "active": True},
    {"id": 3, "name": "Tijm",           "x": 1400, "y": 112, "ml": 35, "active": True},
    {"id": 4, "name": "Peterselie",     "x": 1800, "y": 112, "ml": 45, "active": True},
    {"id": 5, "name": "Salie",          "x": 200,  "y": 337, "ml": 40, "active": True},
    {"id": 6, "name": "Citroenmelisse", "x": 600,  "y": 337, "ml": 55, "active": True},
    {"id": 7, "name": "Oregano",        "x": 1000, "y": 337, "ml": 40, "active": True},
    {"id": 8, "name": "Bieslook",       "x": 1400, "y": 337, "ml": 50, "active": True},
    {"id": 9, "name": "Koriander",      "x": 1800, "y": 337, "ml": 45, "active": True},
]


# ── BESTANDSBEHEER ────────────────────────────────────────

def laad_zones():
    if os.path.exists(ZONES_FILE):
        try:
            with open(ZONES_FILE, "r") as f:
                zones = json.load(f)
                print(f"Zones geladen uit {ZONES_FILE}")
                return zones
        except Exception as e:
            print(f"Zones laden mislukt: {e} — standaard zones gebruikt")
    return [z.copy() for z in ZONES_DEFAULT]


def sla_zones_op(zones):
    try:
        with open(ZONES_FILE, "w") as f:
            json.dump(zones, f, indent=2)
    except Exception as e:
        print(f"Zones opslaan mislukt: {e}")


def laad_waterlog():
    if os.path.exists(WATERLOG_FILE):
        try:
            with open(WATERLOG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def sla_waterlog_op(log):
    try:
        with open(WATERLOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print(f"Waterlog opslaan mislukt: {e}")


def hernummer_zones(zones):
    for i, zone in enumerate(zones):
        zone["id"] = i
    return zones


# ── STATE MACHINE ─────────────────────────────────────────

class Sproeituin:
    def __init__(self):
        self.state         = "idle"
        self.state_lock    = threading.Lock()

        self._is_homed     = False
        self._homed_lock   = threading.Lock()

        self._pending_start_after_home = False

        self.pos_x         = 0
        self.pos_y         = 0
        self.ser           = None
        self.ser_lock      = threading.Lock()
        self.beweging_lock = threading.Lock()
        self.zones_lock    = threading.Lock()
        self.mqtt_client   = None
        self.start_time    = time.time()
        self.zones         = laad_zones()
        self.waterlog      = laad_waterlog()
        self.demo_ml       = 20

        self._relais_open       = False
        self._relais_open_sinds = 0.0
        self._relais_lock       = threading.Lock()

        self._flow_pulsen       = 0
        self._flow_lock         = threading.Lock()
        self._veiligheid_actief = True
        self._veiligheid_thread = None

        self._flow_venster_pulsen = 0
        self._flow_venster_teller = 0

        if GPIO_BESCHIKBAAR:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(GPIO_FLOW_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            try:
                GPIO.remove_event_detect(GPIO_FLOW_PIN)
            except Exception:
                pass
            try:
                GPIO.add_event_detect(
                    GPIO_FLOW_PIN, GPIO.RISING,
                    callback=self._flow_interrupt,
                    bouncetime=20)
                print(f"Flowmeter actief op GPIO {GPIO_FLOW_PIN} (bouncetime=20ms)")
            except RuntimeError as e:
                print(f"WAARSCHUWING: GPIO flowmeter setup mislukt: {e} — flowmeter uitgeschakeld")

    def start_veiligheid(self):
        self._veiligheid_thread = threading.Thread(
            target=self._veiligheid_monitor, daemon=True)
        self._veiligheid_thread.start()

    # ── IS_HOMED PROPERTY ────────────────────────────────
    @property
    def is_homed(self) -> bool:
        with self._homed_lock:
            return self._is_homed

    @is_homed.setter
    def is_homed(self, waarde: bool):
        with self._homed_lock:
            self._is_homed = waarde

    # ── PENDING START PROPERTY ───────────────────────────
    @property
    def pending_start_after_home(self) -> bool:
        with self.state_lock:
            return self._pending_start_after_home

    @pending_start_after_home.setter
    def pending_start_after_home(self, waarde: bool):
        with self.state_lock:
            self._pending_start_after_home = waarde

    # ── RELAIS PROPERTY ──────────────────────────────────
    @property
    def relais_open(self) -> bool:
        with self._relais_lock:
            return self._relais_open

    @relais_open.setter
    def relais_open(self, waarde: bool):
        with self._relais_lock:
            self._relais_open = waarde

    @property
    def relais_open_sinds(self) -> float:
        with self._relais_lock:
            return self._relais_open_sinds

    # ── FLOWMETER ────────────────────────────────────────
    def _flow_interrupt(self, channel):
        with self._flow_lock:
            self._flow_pulsen += 1

    def _lees_en_reset_flow(self) -> int:
        with self._flow_lock:
            pulsen = self._flow_pulsen
            self._flow_pulsen = 0
        return pulsen

    # ── VEILIGHEIDSMONITOR ────────────────────────────────
    def _veiligheid_monitor(self):
        while self._veiligheid_actief:
            time.sleep(FLOW_CHECK_INTERVAL_S)
            if not GPIO_BESCHIKBAAR:
                continue

            pulsen_dit_interval = self._lees_en_reset_flow()

            totaal_pulsen = None
            with self._flow_lock:
                self._flow_venster_pulsen += pulsen_dit_interval
                self._flow_venster_teller += 1
                if self._flow_venster_teller >= FLOW_VENSTER_S:
                    totaal_pulsen             = self._flow_venster_pulsen
                    self._flow_venster_pulsen = 0
                    self._flow_venster_teller = 0

            if totaal_pulsen is None:
                continue

            relais_nu_open = self.relais_open

            if not relais_nu_open and totaal_pulsen > FLOW_GESLOTEN_MAX_PULSE:
                self.log(
                    f"⚠️ LEKDETECTIE: relais gesloten maar "
                    f"{totaal_pulsen} pulsen/{FLOW_VENSTER_S}s")
                self._noodstop_lek()
            elif relais_nu_open:
                tijd_open = time.time() - self.relais_open_sinds
                if (tijd_open > FLOW_OPEN_TIMEOUT_S
                        and totaal_pulsen < FLOW_OPEN_MIN_PULSES):
                    self.log(
                        f"⚠️ GEEN WATER: relais {tijd_open:.0f}s open, "
                        f"slechts {totaal_pulsen} pulsen/{FLOW_VENSTER_S}s")
                    self._noodstop_geen_water()

    def _noodstop_lek(self):
        self.log("🚨 NOODSTOP LEK — klep sluiten")
        self._stuur_klep_dicht_direct()
        self.relais_open = False
        self.set_status("error_lek")
        if self.mqtt_client:
            self.mqtt_client.publish(
                "sproeituin/alarm",
                json.dumps({
                    "type":    "lek",
                    "bericht": "Klep vast open gedetecteerd — systeem geblokkeerd",
                    "tijd":    time.strftime("%Y-%m-%d %H:%M:%S"),
                }), retain=True)

    def _noodstop_geen_water(self):
        self.log("🚨 NOODSTOP GEEN WATER — klep sluiten")
        self._stuur_klep_dicht_direct()
        self.relais_open = False
        self.set_status("error_geen_water")
        if self.mqtt_client:
            self.mqtt_client.publish(
                "sproeituin/alarm",
                json.dumps({
                    "type":    "geen_water",
                    "bericht": "Geen flow bij open klep",
                    "tijd":    time.strftime("%Y-%m-%d %H:%M:%S"),
                }), retain=True)

    def _stuur_klep_dicht_direct(self):
        if self.ser is None:
            self.log("Klep_dicht direct: geen seriële verbinding")
            return
        try:
            self.ser.write(
                (json.dumps({"cmd": "klep_dicht"}) + "\n").encode())
            self.ser.flush()
            time.sleep(0.05)
            self.ser.reset_input_buffer()
        except Exception as e:
            self.log(f"Klep_dicht direct schrijf fout: {e}")

    # ── RELAIS BEHEER ─────────────────────────────────────
    def open_klep(self):
        with self._relais_lock:
            self._relais_open       = True
            self._relais_open_sinds = time.time()
        self._lees_en_reset_flow()
        with self._flow_lock:
            self._flow_venster_pulsen = 0
            self._flow_venster_teller = 0

    def sluit_klep(self):
        self.relais_open = False
        self._lees_en_reset_flow()
        with self._flow_lock:
            self._flow_venster_pulsen = 0
            self._flow_venster_teller = 0

    def lees_flow_ml(self) -> float:
        pulsen = self._lees_en_reset_flow()
        return (pulsen / FLOW_PULSES_PER_LITER) * 1000

    # ── LOGGING ──────────────────────────────────────────
    def log(self, msg):
        uptime = int(time.time() - self.start_time)
        print(f"[{uptime}s] {msg}")
        if self.mqtt_client:
            try:
                self.mqtt_client.publish(
                    "sproeituin/log", f"[{uptime}s] {msg}", retain=False)
            except Exception:
                pass

    def set_status(self, s):
        with self.state_lock:
            self.state = s
        self.log(f"Status: {s}")
        if self.mqtt_client:
            try:
                self.mqtt_client.publish("sproeituin/status", s, retain=True)
            except Exception:
                pass

    def get_state(self) -> str:
        with self.state_lock:
            return self.state

    def publish_positie(self):
        if self.mqtt_client:
            try:
                self.mqtt_client.publish(
                    "sproeituin/positie",
                    json.dumps({"x": self.pos_x, "y": self.pos_y}),
                    retain=True)
            except Exception:
                pass

    def publish_zones(self):
        if self.mqtt_client:
            try:
                with self.zones_lock:
                    data = list(self.zones)
                self.mqtt_client.publish(
                    "sproeituin/zones", json.dumps(data), retain=True)
            except Exception:
                pass

    def publish_waterlog_overzicht(self):
        if not self.mqtt_client:
            return
        try:
            overzicht = {}
            for naam, entries in self.waterlog.items():
                totaal  = sum(e["ml"] for e in entries)
                laatste = entries[-1] if entries else None
                overzicht[naam] = {
                    "totaal_ml":     totaal,
                    "aantal_keer":   len(entries),
                    "laatste_datum": laatste["datum"] if laatste else None,
                    "laatste_tijd":  laatste["tijd"]  if laatste else None,
                    "laatste_ml":    laatste["ml"]    if laatste else None,
                }
            self.mqtt_client.publish(
                "sproeituin/waterlog/overzicht",
                json.dumps(overzicht), retain=True)
        except Exception as e:
            self.log(f"Waterlog overzicht fout: {e}")

    # ── SERIEEL NAAR ARDUINO ─────────────────────────────
    def stuur_arduino(self, commando: dict, wacht=True) -> dict:
        if not self.ser:
            return {"status": "error", "msg": "geen seriële verbinding"}
        try:
            with self.ser_lock:
                self.ser.write((json.dumps(commando) + "\n").encode())
                self.ser.flush()
                if wacht:
                    antwoord = self.ser.readline().decode().strip()
                    if not antwoord:
                        self.log(f"Serieel timeout: geen antwoord op {commando}")
                        return {"status": "error"}
                    result = json.loads(antwoord)
                    self.pos_x = result.get("x", self.pos_x)
                    self.pos_y = result.get("y", self.pos_y)
                    return result
        except serial.SerialException as e:
            self.log(f"Serieel verbinding verbroken: {e}")
            threading.Thread(target=self._probeer_herverbinden, daemon=True).start()
        except Exception as e:
            self.log(f"Serieel fout: {e}")
        return {"status": "error"}

    def _probeer_herverbinden(self):
        self.log("Serieel: herverbinding proberen...")
        for poging in range(1, 6):
            time.sleep(3)
            try:
                with self.ser_lock:
                    if self.ser:
                        try:
                            self.ser.close()
                        except Exception:
                            pass
                    self.ser = serial.Serial(
                        SERIAL_PORT, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
                    time.sleep(2)
                    welkom = self.ser.readline().decode().strip()
                self.log(f"Arduino herverbonden (poging {poging}): {welkom}")
                return
            except Exception as e:
                self.log(f"Herverbinding poging {poging} mislukt: {e}")
        self.log("FOUT: Arduino herverbinding opgegeven na 5 pogingen")

    # ── WATER LOG REGISTRATIE ────────────────────────────
    def registreer_water(self, naam, ml):
        datum = time.strftime("%Y-%m-%d")
        uur   = time.strftime("%H:%M:%S")
        if naam not in self.waterlog:
            self.waterlog[naam] = []
        self.waterlog[naam].append({"datum": datum, "tijd": uur, "ml": ml})
        if len(self.waterlog[naam]) > MAX_WATERLOG_ENTRIES:
            self.waterlog[naam] = self.waterlog[naam][-MAX_WATERLOG_ENTRIES:]
        sla_waterlog_op(self.waterlog)
        totaal = sum(e["ml"] for e in self.waterlog[naam])
        if self.mqtt_client:
            self.mqtt_client.publish(
                "sproeituin/waterlog",
                json.dumps({
                    "zone": naam, "ml": ml,
                    "totaal_ml": totaal, "datum": datum, "tijd": uur,
                }))
        self.publish_waterlog_overzicht()

    # ── SPROEI HULPFUNCTIE ───────────────────────────────
    def _sproei_zone(self, zone, ml_override=None) -> float:
        ml_doel = ml_override if ml_override is not None else zone["ml"]
        self.log(f"Zone: {zone['name']} — {ml_doel}ml")
        result = self.stuur_arduino(
            {"cmd": "move", "x": zone["x"], "y": zone["y"]})
        if result.get("status") != "ok":
            self.log(f"Move fout: {result}")
            return 0.0
        self.publish_positie()

        self.open_klep()
        self.stuur_arduino({"cmd": "klep_open"}, wacht=True)

        ml_effectief = 0.0

        if GPIO_BESCHIKBAAR:
            self.log(f"Sproei gestart — wacht op {ml_doel}ml")
            zone_start = time.time()
            while ml_effectief < ml_doel:
                if self.get_state() in ("stopped", "error_lek", "error_geen_water"):
                    self.stuur_arduino({"cmd": "klep_dicht"}, wacht=True)
                    self.sluit_klep()
                    return 0.0
                if time.time() - zone_start > 60:
                    self.log(f"WAARSCHUWING: sproei timeout 60s voor {zone['name']}")
                    self.stuur_arduino({"cmd": "klep_dicht"}, wacht=True)
                    self.sluit_klep()
                    break
                time.sleep(0.5)
                ml_effectief += self.lees_flow_ml()
        else:
            self.log("WAARSCHUWING: flowmeter niet actief, vaste wachttijd gebruikt")
            wacht_tot = time.time() + max(1.0, ml_doel * 0.05)
            while time.time() < wacht_tot:
                if self.get_state() in ("stopped", "error_lek", "error_geen_water"):
                    self.stuur_arduino({"cmd": "klep_dicht"}, wacht=True)
                    self.sluit_klep()
                    return 0.0
                time.sleep(0.1)
            ml_effectief = ml_doel

        self.stuur_arduino({"cmd": "klep_dicht"}, wacht=True)
        self.sluit_klep()
        ml_effectief = round(ml_effectief, 1)
        self.log(f"Zone {zone['name']} klaar — {ml_effectief}ml gegeven")
        self.registreer_water(zone["name"], ml_effectief)
        return ml_effectief

    # ── COMMANDO'S ───────────────────────────────────────
    def cmd_jog(self, as_naam, mm):
        if not self.beweging_lock.acquire(blocking=False):
            self.log("Jog genegeerd: beweging al bezig")
            return
        try:
            if self.get_state() not in ("idle", "jogging"):
                self.log(f"Jog genegeerd: state={self.get_state()}")
                return
            try:
                self.set_status("jogging")
                self.stuur_arduino({"cmd": "jog", "as": as_naam, "mm": mm})
            finally:
                if self.get_state() != "stopped":
                    self.set_status("idle")
            if self.get_state() != "stopped":
                self.publish_positie()
                self.log(f"Jog {as_naam} {mm}mm klaar — X={self.pos_x}mm Y={self.pos_y}mm")
        finally:
            self.beweging_lock.release()

    def cmd_home(self):
        if not self.beweging_lock.acquire(blocking=False):
            self.log("Home genegeerd: beweging al bezig")
            return
        try:
            if self.get_state() != "idle":
                self.log(f"Home genegeerd: state={self.get_state()}")
                return
            self.set_status("homing")
            self.log("Homing gestart — rijdt naar eindstops om positie te bepalen")
            result = self.stuur_arduino({"cmd": "home"})
            if result.get("status") == "homed":
                self.is_homed = True
                self.pos_x = 0
                self.pos_y = 0
                self.set_status("homed")
                self.publish_positie()
                self.log("Positie bekend: X=0mm Y=0mm")
                if self.pending_start_after_home:
                    self.pending_start_after_home = False
                    threading.Thread(target=self._sproei_cyclus, daemon=True).start()
            elif result.get("status") == "stopped":
                self.log("Homing gestopt door noodstop")
                self.set_status("stopped")
            else:
                self.log("FOUT: homing timeout of geen antwoord van Arduino")
                self.set_status("error")
        finally:
            self.beweging_lock.release()

    def cmd_stop(self):
        self._stuur_klep_dicht_direct()
        self.sluit_klep()
        if self.ser:
            try:
                self.ser.write(b"!\n")
                self.ser.flush()
            except Exception as e:
                self.log(f"Stop schrijf fout: {e}")
        self.set_status("stopped")

    def cmd_reset(self):
        if self.get_state() not in (
                "error", "error_lek", "error_geen_water", "stopped",
                "error_serial"):
            self.log(f"Reset genegeerd: state={self.get_state()}")
            return
        self.is_homed = False
        self._stuur_klep_dicht_direct()
        self.sluit_klep()
        if not self.beweging_lock.locked():
            self.stuur_arduino({"cmd": "disable"})
        else:
            self.log("Reset: beweging bezig — disable overgeslagen")
        if self.mqtt_client:
            self.mqtt_client.publish("sproeituin/alarm", "", retain=True)
        self.set_status("idle")
        self.log("Systeem gereset — homing opnieuw vereist")

    def cmd_start(self):
        if not self.is_homed:
            self.log("Niet gehomed — eerst homen voor sproei")
            self.pending_start_after_home = True
            threading.Thread(target=self.cmd_home, daemon=True).start()
            return
        if self.get_state() != "idle":
            self.log(f"Start genegeerd: state={self.get_state()}")
            return
        threading.Thread(target=self._sproei_cyclus, daemon=True).start()

    def cmd_demo(self, ml=None):
        if not self.is_homed:
            self.log("Demo genegeerd: systeem niet gehomed")
            return
        if self.get_state() != "idle":
            self.log(f"Demo genegeerd: state={self.get_state()}")
            return
        if ml is not None:
            self.demo_ml = ml
        threading.Thread(target=self._demo_cyclus, daemon=True).start()

    def cmd_demo_ml_instellen(self, ml):
        self.demo_ml = ml
        self.log(f"Demo ml ingesteld op {self.demo_ml}ml per plant")
        if self.mqtt_client:
            self.mqtt_client.publish(
                "sproeituin/demo_ml", str(self.demo_ml), retain=True)

    def _sproei_cyclus(self):
        if not self.beweging_lock.acquire(blocking=False):
            self.log("Sproei genegeerd: beweging al bezig")
            return
        try:
            self.set_status("spraying")
            totaal_ml = 0.0
            with self.zones_lock:
                zones_snapshot = list(self.zones)
            for zone in zones_snapshot:
                if not zone["active"] or self.get_state() != "spraying":
                    continue
                ml_effectief = self._sproei_zone(zone)
                totaal_ml += ml_effectief
            if self.get_state() != "stopped":
                self.stuur_arduino({"cmd": "move", "x": 0, "y": 0})
            self.stuur_arduino({"cmd": "disable"})
            self.publish_positie()
            if self.get_state() != "stopped":
                self.set_status("idle")
            self.log(f"Sproei klaar — totaal {round(totaal_ml, 1)}ml")
        finally:
            self.beweging_lock.release()

    def _demo_cyclus(self):
        if not self.beweging_lock.acquire(blocking=False):
            self.log("Demo genegeerd: beweging al bezig")
            return
        try:
            self.set_status("spraying")
            self.log(f"Demo gestart — {self.demo_ml}ml per actieve plant")
            totaal_ml = 0.0
            with self.zones_lock:
                zones_snapshot = list(self.zones)
            for zone in zones_snapshot:
                if not zone["active"] or self.get_state() != "spraying":
                    continue
                ml_effectief = self._sproei_zone(zone, ml_override=self.demo_ml)
                totaal_ml += ml_effectief
            if self.get_state() != "stopped":
                self.stuur_arduino({"cmd": "move", "x": 0, "y": 0})
            self.stuur_arduino({"cmd": "disable"})
            self.publish_positie()
            if self.get_state() != "stopped":
                self.set_status("idle")
            self.log(f"Demo klaar — totaal {round(totaal_ml, 1)}ml")
        finally:
            self.beweging_lock.release()

    def cmd_zone_update(self, data):
        zone_id = data.get("id", -1)
        naam = None
        ml   = None
        with self.zones_lock:
            idx = next((i for i, z in enumerate(self.zones) if z["id"] == zone_id), -1)
            if idx >= 0:
                for key in ("name", "x", "y", "ml", "active"):
                    if key in data:
                        self.zones[idx][key] = data[key]
                naam = self.zones[idx]["name"]
                ml   = self.zones[idx]["ml"]
                sla_zones_op(self.zones)
        if idx >= 0:
            self.publish_zones()
            self.log(f"Zone {zone_id} ({naam}) bijgewerkt — ml={ml}")
        else:
            self.log(f"Ongeldige zone id: {zone_id}")

    def cmd_positie_opslaan(self, data):
        if not self.is_homed:
            self.log("Positie opslaan mislukt: systeem niet gehomed")
            return
        zone_id = data.get("id", -1)
        naam = None
        ml   = None
        with self.zones_lock:
            idx = next((i for i, z in enumerate(self.zones) if z["id"] == zone_id), -1)
            if idx >= 0:
                self.zones[idx]["x"] = self.pos_x
                self.zones[idx]["y"] = self.pos_y
                if "ml" in data:
                    self.zones[idx]["ml"] = data["ml"]
                naam = self.zones[idx]["name"]
                ml   = self.zones[idx]["ml"]
                sla_zones_op(self.zones)
        if idx >= 0:
            self.publish_zones()
            self.log(
                f"Positie opgeslagen als zone {zone_id} ({naam}): "
                f"X={self.pos_x}mm Y={self.pos_y}mm ml={ml}")
        else:
            self.log(f"Ongeldige zone id: {zone_id}")

    def cmd_zone_toevoegen(self, data):
        if not self.is_homed and "x" not in data:
            self.log("Zone toevoegen mislukt: niet gehomed")
            return
        with self.zones_lock:
            nieuwe_id = max((z["id"] for z in self.zones), default=-1) + 1
            nieuwe_zone = {
                "id":     nieuwe_id,
                "name":   data.get("name", f"Zone {nieuwe_id}"),
                "x":      data.get("x", self.pos_x),
                "y":      data.get("y", self.pos_y),
                "ml":     data.get("ml", 50),
                "active": data.get("active", True),
            }
            self.zones.append(nieuwe_zone)
            sla_zones_op(self.zones)
        self.publish_zones()
        self.log(
            f"Nieuwe zone: id={nieuwe_id} naam={nieuwe_zone['name']} "
            f"X={nieuwe_zone['x']}mm Y={nieuwe_zone['y']}mm ml={nieuwe_zone['ml']}ml")

    def cmd_zone_verwijderen(self, data):
        zone_id = data.get("id", -1)
        with self.zones_lock:
            voor = len(self.zones)
            self.zones = [z for z in self.zones if z["id"] != zone_id]
            verwijderd = len(self.zones) < voor
            if verwijderd:
                self.zones = hernummer_zones(self.zones)
                sla_zones_op(self.zones)
        if verwijderd:
            self.publish_zones()
            self.log(f"Zone {zone_id} verwijderd — zones hernummerd")
        else:
            self.log(f"Zone {zone_id} niet gevonden")


# ── MQTT ─────────────────────────────────────────────────
sproeituin = Sproeituin()


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        sproeituin.log("MQTT verbonden")
        client.subscribe("sproeituin/cmd/jog")
        client.subscribe("sproeituin/cmd/home")
        client.subscribe("sproeituin/cmd/start")
        client.subscribe("sproeituin/cmd/stop")
        client.subscribe("sproeituin/cmd/reset")
        client.subscribe("sproeituin/cmd/demo")
        client.subscribe("sproeituin/cmd/demo_ml")
        client.subscribe("sproeituin/cmd/zone")
        client.subscribe("sproeituin/cmd/positie_opslaan")
        client.subscribe("sproeituin/cmd/zone_toevoegen")
        client.subscribe("sproeituin/cmd/zone_verwijderen")
        # FIX 1: status weerspiegelt werkelijke toestand — niet altijd "online"
        client.publish("sproeituin/status", sproeituin.get_state(), retain=True)
        sproeituin.publish_zones()
        sproeituin.publish_positie()
        sproeituin.publish_waterlog_overzicht()
        client.publish("sproeituin/demo_ml", str(sproeituin.demo_ml), retain=True)
    else:
        print(f"MQTT verbinding mislukt: {reason_code}")


def on_message(client, userdata, msg):
    topic   = msg.topic
    payload = msg.payload.decode().strip()
    try:
        if topic == "sproeituin/cmd/jog":
            data = json.loads(payload) if payload else {}
            threading.Thread(
                target=sproeituin.cmd_jog,
                args=(data.get("as", "x"), data.get("mm", 0)),
                daemon=True).start()
        elif topic == "sproeituin/cmd/home":
            threading.Thread(target=sproeituin.cmd_home, daemon=True).start()
        elif topic == "sproeituin/cmd/start":
            threading.Thread(target=sproeituin.cmd_start, daemon=True).start()
        elif topic == "sproeituin/cmd/stop":
            sproeituin.cmd_stop()
        elif topic == "sproeituin/cmd/reset":
            threading.Thread(target=sproeituin.cmd_reset, daemon=True).start()
        elif topic == "sproeituin/cmd/demo":
            data = json.loads(payload) if payload else {}
            sproeituin.cmd_demo(ml=data.get("ml", None))
        elif topic == "sproeituin/cmd/demo_ml":
            try:
                ml = int(json.loads(payload).get("ml")) \
                    if payload.startswith("{") else int(payload)
                sproeituin.cmd_demo_ml_instellen(ml)
            except (ValueError, TypeError):
                sproeituin.log(f"Ongeldige demo ml waarde: {payload}")
        elif topic == "sproeituin/cmd/zone":
            sproeituin.cmd_zone_update(json.loads(payload))
        elif topic == "sproeituin/cmd/positie_opslaan":
            sproeituin.cmd_positie_opslaan(json.loads(payload) if payload else {})
        elif topic == "sproeituin/cmd/zone_toevoegen":
            sproeituin.cmd_zone_toevoegen(json.loads(payload) if payload else {})
        elif topic == "sproeituin/cmd/zone_verwijderen":
            sproeituin.cmd_zone_verwijderen(json.loads(payload) if payload else {})
    except Exception as e:
        sproeituin.log(f"Bericht fout {topic}: {e}")


def on_disconnect(client, userdata, flags, reason_code, properties):
    sproeituin.log(f"MQTT verbroken: {reason_code}")


def main():
    print(f"Verbinden met Arduino op {SERIAL_PORT}...")
    arduino_verbonden = False
    try:
        with sproeituin.ser_lock:
            sproeituin.ser = serial.Serial(
                SERIAL_PORT, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
            time.sleep(2)
            welkom = sproeituin.ser.readline().decode().strip()
        print(f"Arduino: {welkom}")
        arduino_verbonden = True
    except Exception as e:
        print(f"WAARSCHUWING: Geen Arduino: {e}")
        # FIX 1: status direct op error_serial zetten bij geen verbinding
        sproeituin.set_status("error_serial")

    if arduino_verbonden:
        sproeituin.start_veiligheid()
        print("Veiligheidsmonitor gestart")
    else:
        print("WAARSCHUWING: veiligheidsmonitor niet gestart — geen Arduino verbinding")

    print(f"Verbinden met MQTT op {MQTT_BROKER}...")
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="sproeituin-pi")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.will_set("sproeituin/status", "offline", retain=True)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    sproeituin.mqtt_client = client
    print("Sproeituin gestart.")
    client.loop_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSysteem handmatig afgesloten.")
        # Klep sluiten bij afsluiting
        sproeituin._stuur_klep_dicht_direct()
        sproeituin.sluit_klep()
        # MQTT offline melding
        if sproeituin.mqtt_client:
            try:
                sproeituin.mqtt_client.publish(
                    "sproeituin/status", "offline", retain=True)
                sproeituin.mqtt_client.disconnect()
            except Exception:
                pass
        # GPIO opruimen
        if GPIO_BESCHIKBAAR:
            GPIO.cleanup()
            print("GPIO opgeruimd.")
