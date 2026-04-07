# Sproeituin - Installatiegids
## Btechnics - Matthias Bogaert

---

## Overzicht bestanden

| Bestand | Bestemming | Omschrijving |
|---------|-----------|--------------|
| sproeituin_arduino_v1_14.txt | Arduino IDE | Motorcontroller sketch |
| sproeituin_pi_v1_14.py | /home/admin/sproeituin.py | Hoofdscript Pi |
| sproeituin.service | /etc/systemd/system/ | Autostart service |
| kalibratie_flowmeter.py | /home/admin/ | Flowmeter kalibratie |

---

## Stap 1 — Arduino flashen

1. Open Arduino IDE op je computer
2. Kopieer de inhoud van `sproeituin_arduino_v1_14.txt`
3. Selecteer board: Arduino UNO WiFi Rev2
4. Flash naar de Arduino
5. Open Serial Monitor (115200 baud) en controleer:
   `{"status":"ready","x":0,"y":0,"homed":false,"klep":false}`

---

## Stap 2 — Pi voorbereiding

SSH verbinden:
```
ssh admin@192.168.1.173
```

Python venv aanmaken en packages installeren:
```bash
python3 -m venv ~/sproeituin-venv
source ~/sproeituin-venv/bin/activate
pip install paho-mqtt pyserial
```

Controleer Arduino verbinding:
```bash
ls /dev/ttyACM*
# Verwacht: /dev/ttyACM0
```

Controleer dialout rechten:
```bash
groups
# admin moet in de dialout groep staan
# Indien niet: sudo usermod -a -G dialout admin
# Daarna uitloggen en opnieuw inloggen
```

---

## Stap 3 — Scripts kopiëren naar Pi

Vanuit je computer (vervang IP indien nodig):
```bash
scp sproeituin_pi_v1_14.py admin@192.168.1.173:/home/admin/sproeituin.py
scp kalibratie_flowmeter.py admin@192.168.1.173:/home/admin/kalibratie_flowmeter.py
```

---

## Stap 4 — Script testen

Op de Pi:
```bash
source ~/sproeituin-venv/bin/activate
python3 ~/sproeituin.py
```

Verwachte output:
```
Verbinden met Arduino op /dev/ttyACM0...
Arduino: {"status":"ready","x":0,"y":0,"homed":false,"klep":false}
Veiligheidsmonitor gestart
Verbinden met MQTT op 192.168.1.117...
Sproeituin gestart.
```

Controleer in Home Assistant of het topic sproeituin/status verschijnt.
Stop het script met Ctrl+C als alles werkt.

---

## Stap 5 — Autostart service installeren

Op de Pi:
```bash
sudo nano /etc/systemd/system/sproeituin.service
```

Plak de volledige inhoud van sproeituin.service en sla op.

Service activeren:
```bash
sudo systemctl daemon-reload
sudo systemctl enable sproeituin
sudo systemctl start sproeituin
```

Status controleren:
```bash
sudo systemctl status sproeituin
```

Logs live bekijken:
```bash
journalctl -u sproeituin -f
```

---

## Stap 6 — Flowmeter kalibreren

Voer dit uit NA installatie van de flowmeter en wateraansluiting:
```bash
source ~/sproeituin-venv/bin/activate
python3 ~/kalibratie_flowmeter.py
```

Werkwijze:
1. Houd een maatbeker van 1 liter klaar
2. Open de watertoevoer handmatig
3. Start het script en druk ENTER
4. Laat exact 1 liter doorstromen
5. Druk Ctrl+C
6. Noteer het aantal pulsen
7. Pas FLOW_PULSES_PER_LITER aan in sproeituin.py
8. Herstart de service: sudo systemctl restart sproeituin

---

## Hardware checklist voor installatie

- [ ] Arduino UNO WiFi Rev2 aangesloten via USB op Pi
- [ ] TB6600 drivers aangesloten op 24VDC
- [ ] Buck converter 24V → 5V/3A voor Pi voeding
- [ ] Endstop X aangesloten op pin 11 (XMIN)
- [ ] Endstop X-max op pin 10 (XMAX)
- [ ] Endstop Y aangesloten op pin 12 (YMIN)
- [ ] Endstop Y-max op pin 9 (YMAX)
- [ ] Relais 24V magneetklep op pin 8
- [ ] YF-S201 flowmeter op Pi GPIO pin 17
- [ ] 100nF condensator tussen GPIO 17 en GND (EMI filter)
- [ ] 4.7kΩ pull-up weerstand tussen GPIO 17 en 3.3V
- [ ] Common GND Arduino en Pi verbonden

---

## MQTT topics overzicht

| Topic | Richting | Omschrijving |
|-------|----------|-------------|
| sproeituin/status | Pi → HA | idle/homing/homed/spraying/stopped/error_* |
| sproeituin/positie | Pi → HA | {"x":mm,"y":mm} |
| sproeituin/zones | Pi → HA | Volledige zoneslijst |
| sproeituin/waterlog | Pi → HA | Log per sproeibeurt |
| sproeituin/waterlog/overzicht | Pi → HA | Samenvatting per plant |
| sproeituin/alarm | Pi → HA | Lek of geen water alarm |
| sproeituin/log | Pi → HA | Debug berichten |
| sproeituin/cmd/home | HA → Pi | Start homing |
| sproeituin/cmd/start | HA → Pi | Start sproei cyclus |
| sproeituin/cmd/stop | HA → Pi | Noodstop |
| sproeituin/cmd/reset | HA → Pi | Reset na fout |
| sproeituin/cmd/jog | HA → Pi | {"as":"x","mm":10} |
| sproeituin/cmd/demo | HA → Pi | Demo sproei |
| sproeituin/cmd/demo_ml | HA → Pi | Demo ml instellen |
| sproeituin/cmd/zone | HA → Pi | Zone bijwerken |
| sproeituin/cmd/positie_opslaan | HA → Pi | Huidige positie opslaan |
| sproeituin/cmd/zone_toevoegen | HA → Pi | Nieuwe zone |
| sproeituin/cmd/zone_verwijderen | HA → Pi | Zone verwijderen |

---

## Test-checklist voor ingebruikname

1. [ ] Script starten zonder Arduino → status moet error_serial worden
2. [ ] Homing uitvoeren vanuit uiterste hoek → moet binnen 45s lukken
3. [ ] Noodstop tijdens beweging → motoren stoppen + klep dicht
4. [ ] Simuleer lek → status error_lek binnen 3 seconden
5. [ ] Sproei cyclus uitvoeren → waterlog.json correct bijgeschreven
6. [ ] Pi herstarten → service start automatisch opnieuw

---

## Configuratie variabelen sproeituin.py

| Variabele | Standaard | Aanpassen als... |
|-----------|-----------|-----------------|
| MQTT_BROKER | 192.168.1.117 | HA op ander IP |
| FLOW_PULSES_PER_LITER | 450 | Na kalibratie aanpassen |
| FLOW_VENSTER_S | 3 | Te veel valse alarmen → verhogen naar 5 |
| FLOW_OPEN_TIMEOUT_S | 5 | Waterdruk laag → verhogen |
| FLOW_OPEN_MIN_PULSES | 3 | Aanpassen na kalibratie |
| SERIAL_TIMEOUT | 5 | Niet aanpassen |
