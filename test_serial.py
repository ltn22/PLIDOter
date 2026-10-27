import serial
import time

# Configuration du port
# Sur Mac : souvent /dev/tty.usbserial-XXXX ou /dev/tty.usbmodemXXXX
# Sur Ubuntu : souvent /dev/ttyUSB0 ou /dev/ttyACM0
SERIAL_PORT = '/dev/tty.usbserial-11240' 
BAUD_RATE = 9600 # Vitesse standard

def envoyer_donnees():
    try:
        # Initialisation de la connexion
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
            print(f"Connecté au port {SERIAL_PORT}")
            time.sleep(2)  # Pause pour laisser le temps à l'appareil de s'initialiser

            while True:
                message = "Hello World\n"
                # Important : les données doivent être encodées en bytes
                ser.write(message.encode('utf-8'))
                
                print(f"Données envoyées : {message.strip()}")
                time.sleep(1) # Envoyer toutes les secondes

    except serial.SerialException as e:
        print(f"Erreur : Impossible d'ouvrir le port série. {e}")
    except KeyboardInterrupt:
        print("\nProgramme arrêté par l'utilisateur.")

if __name__ == "__main__":
    envoyer_donnees()

