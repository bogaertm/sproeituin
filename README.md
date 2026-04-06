# Btechnics Sproeituin

Home Assistant HACS integratie voor de automatische kruidentuin sproeituin.

## Installatie via HACS

1. Voeg deze repository toe als custom repository in HACS
2. Installeer "Btechnics Sproeituin"
3. Herstart Home Assistant
4. Ga naar Instellingen → Integraties → Btechnics Sproeituin

## Arduino

De Arduino sketch staat in de `arduino/` map.

## MQTT Topics

- `sproeituin/status` — systeem status
- `sproeituin/sensoren` — temperatuur, vochtigheid, VPD
- `sproeituin/positie` — X/Y positie
- `sproeituin/waterlog` — waterlog per zone
- `sproeituin/cmd/start` — start sproei cyclus
- `sproeituin/cmd/stop` — noodstop
- `sproeituin/cmd/home` — home positie
- `sproeituin/cmd/jog` — manuele beweging
- `sproeituin/cmd/zone` — zone instellen

## Btechnics

Matthias Bogaert — matthias@btechnics.be — www.btechnics.be
