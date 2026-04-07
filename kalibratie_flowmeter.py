#!/usr/bin/env python3
# ================================================================
# Sproeituin - Flowmeter kalibratie
# Btechnics - Matthias Bogaert
#
# Gebruik:
#   source ~/sproeituin-venv/bin/activate
#   python3 kalibratie_flowmeter.py
#
# Werkwijze:
#   1. Houd een maatbeker van precies 1 liter klaar
#   2. Open de watertoevoer handmatig
#   3. Start dit script
#   4. Laat exact 1 liter water in de maatbeker lopen
#   5. Stop het script met Ctrl+C
#   6. Het script toont de gemeten pulsen
#   7. Vul die waarde in als FLOW_PULSES_PER_LITER in sproeituin.py
# ================================================================

import time
try:
    import RPi.GPIO as GPIO
except ImportError:
    print("FOUT: RPi.GPIO niet beschikbaar. Draai dit script op de Pi.")
    exit(1)

GPIO_FLOW_PIN = 17
pulsen        = 0
start_tijd    = None


def flow_interrupt(channel):
    global pulsen
    pulsen += 1


def main():
    global pulsen, start_tijd

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIO_FLOW_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(
        GPIO_FLOW_PIN, GPIO.RISING,
        callback=flow_interrupt,
        bouncetime=20)

    print("=" * 50)
    print("Sproeituin Flowmeter Kalibratie")
    print("=" * 50)
    print()
    print("Klaar. Open de watertoevoer en laat PRECIES 1 liter")
    print("water in een maatbeker lopen.")
    print()
    print("Druk ENTER om te starten...")
    input()

    pulsen     = 0
    start_tijd = time.time()
    print("Meting gestart — laat 1 liter doorstromen en druk Ctrl+C om te stoppen.")
    print()

    try:
        while True:
            duur = time.time() - start_tijd
            print(f"\rPulsen: {pulsen:5d}  |  Tijd: {duur:.1f}s  |  "
                  f"Huidig FLOW_PULSES_PER_LITER: {pulsen}", end="", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        duur = time.time() - start_tijd
        print()
        print()
        print("=" * 50)
        print(f"Meting gestopt na {duur:.1f} seconden")
        print(f"Totaal gemeten pulsen: {pulsen}")
        print()
        print(f"Stel in sproeituin.py in:")
        print(f"  FLOW_PULSES_PER_LITER = {pulsen}")
        print()
        print("Als de hoeveelheid water niet exact 1 liter was:")
        print("  Bereken: pulsen / gemeten_liters")
        print("  Voorbeeld: 380 pulsen bij 0.85L = 380/0.85 = 447")
        print("=" * 50)
    finally:
        GPIO.cleanup()


if __name__ == "__main__":
    main()
