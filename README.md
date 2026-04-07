# Sproeituin - Btechnics automatische kruidentuin

Automatische sproei-installatie voor kruidentuin op XY-frame.

## Architectuur

```
Home Assistant (MQTT) ──► Raspberry Pi 4 (Python state machine)
                                    │
                                    │ USB serieel (JSON)
                                    ▼
                          Arduino UNO WiFi Rev2
                                    │
                          TB6600 drivers → Nema17 motoren
```

## Hardware

- **Raspberry Pi 4** — state machine, MQTT client, TouchKio display
- **Arduino UNO WiFi Rev2** — dedicated motor controller via USB serieel
- **2x DRI0043 TB6600** — stappenmotor drivers
- **2x Nema17** — X-as parallel, 1x Nema17 Y-as
- **YF-S201** — flowmeter watermeting
- **DHT11** — temperatuur en vochtigheid
- **24V magneetklep** — water aan/uit
- **Officiële Pi 7" touchscreen** — TouchKio kiosk display

## Mappen

| Map | Inhoud |
|-----|--------|
| `arduino/` | Arduino sketch voor motor controller |
| `pi/` | Python state machine voor Raspberry Pi |
| `custom_components/btechnics_sproeituin/` | HACS HA integratie |

## Arduino installatie

1. Open `arduino/sproeituin_arduino.ino` in Arduino IDE
2. Board: **Arduino megaAVR Boards → Arduino Uno WiFi Rev2**
3. Upload

## Pi installatie

```bash
cd pi
pip3 install -r requirements.txt
bash installeer.sh
```

## MQTT Topics

### Inkomend (HA → Pi)
| Topic | Payload |
|-------|---------|
| `sproeituin/cmd/jog` | `{"as":"x","mm":10}` |
| `sproeituin/cmd/home` | leeg |
| `sproeituin/cmd/start` | leeg |
| `sproeituin/cmd/stop` | leeg |
| `sproeituin/cmd/zone` | `{"id":0,"name":"...","x":200,"y":112,"ml":50,"active":true}` |

### Uitgaand (Pi → HA)
| Topic | Payload |
|-------|---------|
| `sproeituin/status` | `online/idle/homing/homed/spraying/stopped/error_noflow` |
| `sproeituin/positie` | `{"x":0,"y":0}` |
| `sproeituin/waterlog` | `{"zone":"Basilicum","ml":50}` |
| `sproeituin/log` | `"[123s] tekst"` |

## Zones

| ID | Naam | X (mm) | Y (mm) | Water (ml) |
|----|------|--------|--------|------------|
| 0 | Basilicum | 200 | 112 | 50 |
| 1 | Munt | 600 | 112 | 60 |
| 2 | Rozemarijn | 1000 | 112 | 40 |
| 3 | Tijm | 1400 | 112 | 35 |
| 4 | Peterselie | 1800 | 112 | 45 |
| 5 | Salie | 200 | 337 | 40 |
| 6 | Citroenmelisse | 600 | 337 | 55 |
| 7 | Oregano | 1000 | 337 | 40 |
| 8 | Bieslook | 1400 | 337 | 50 |
| 9 | Koriander | 1800 | 337 | 45 |
