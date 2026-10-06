import time

import serial

from cavro_valve import CAVRO_VALVE_ERRORS, CavroValve
from config import VALVE_BAUD_RATE, VALVE_SERIAL_PORT
from flow_pump_loader import close_active_flow_pump_controller
from user_interface import main_menu


def main():
    try:
        with serial.Serial(
            VALVE_SERIAL_PORT,
            VALVE_BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
        ) as serial_connection:
            time.sleep(0.3)
            cavro_valve = CavroValve(serial_connection)
            firmware = cavro_valve.send_command("&")
            if firmware is None:
                raise RuntimeError("Não foi possível comunicar com a válvula.")
            if firmware["error"] != 0:
                raise RuntimeError(
                    f"Válvula reportou erro {firmware['error']}: "
                    f"{CAVRO_VALVE_ERRORS.get(firmware['error'], 'Desconhecido')}"
                )

            print()
            print("=" * 72)
            print("VÁLVULA CAVRO CONECTADA")
            print("=" * 72)
            print(f"Firmware: {firmware['data']}")
            current_channel = cavro_valve.get_current_channel()
            print(f"Canal atual: {current_channel}")
            main_menu(cavro_valve)
            print()
            print("Comunicação encerrada.")
    except serial.SerialException as error:
        print()
        print(f"Erro de comunicação serial: {error}")
    except KeyboardInterrupt:
        print()
        print()
        print("Programa interrompido pelo usuário.")
    except Exception as error:
        print()
        print("=" * 72)
        print("ERRO")
        print("=" * 72)
        print(error)
    finally:
        close_active_flow_pump_controller()


if __name__ == "__main__":
    main()
