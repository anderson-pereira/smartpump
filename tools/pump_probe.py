import serial
import time

PORT = "COM21"
ADDRESS = 1


class IsmatecISM832:
    def __init__(self, port, address=1):
        self.address = address

        self.ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
        )

        time.sleep(0.2)

    def _write(self, command):
        message = f"{self.address}{command}\r"

        self.ser.reset_input_buffer()

        print(f"TX: {message!r}")

        self.ser.write(message.encode("ascii"))
        self.ser.flush()

    def command_char(self, command):
        """
        Comandos cuja resposta é um caractere:
        *, #, + ou -
        """
        self._write(command)

        response = self.ser.read(1).decode(
            "ascii",
            errors="replace"
        )

        print(f"RX: {response!r}")

        return response

    def command_line(self, command):
        """
        Comandos cuja resposta é uma string
        terminada por CR/LF.
        """
        self._write(command)

        response = self.ser.read_until(b"\n").decode(
            "ascii",
            errors="replace"
        ).strip()

        print(f"RX: {response!r}")

        return response

    # ---------------------------------
    # Identificação
    # ---------------------------------

    def identify(self):
        return self.command_line("#")

    # ---------------------------------
    # Controle
    # ---------------------------------

    def start(self):
        response = self.command_char("H")

        if response == "*":
            print("Bomba iniciada.")
            return True

        print(f"Falha ao iniciar: {response!r}")
        return False

    def stop(self):
        response = self.command_char("I")

        if response == "*":
            print("Bomba parada.")
            return True

        print(f"Falha ao parar: {response!r}")
        return False

    # ---------------------------------
    # Estado
    # ---------------------------------

    def is_running(self):
        response = self.command_char("E")

        if response == "+":
            return True

        if response == "-":
            return False

        return None

    # ---------------------------------
    # Velocidade
    # ---------------------------------

    def get_speed(self):
        response = self.command_line("S")

        try:
            return float(response)
        except ValueError:
            return None

    # ---------------------------------

    def close(self):
        self.ser.close()


if __name__ == "__main__":

    pump = IsmatecISM832(
        port=PORT,
        address=ADDRESS
    )

    try:
        print("\n--- Identificação ---")

        identification = pump.identify()

        print("Bomba:", identification)

        print("\n--- Estado ---")

        running = pump.is_running()

        print("Em funcionamento:", running)

        print("\n--- Velocidade ---")

        speed = pump.get_speed()

        print("Velocidade:", speed, "rpm")

        input("\nENTER para iniciar a bomba...")

        pump.start()

        time.sleep(5)

        input("\nENTER para parar a bomba...")

        pump.stop()

    finally:
        pump.close()