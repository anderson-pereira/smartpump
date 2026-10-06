import time

from config import VALVE_ADDRESS, VALVE_CHANNEL_COUNT


CAVRO_VALVE_ERRORS = {
    0: "Sem erro",
    1: "Erro de inicialização",
    2: "Comando inválido",
    3: "Operando inválido",
    6: "Falha EEPROM",
    7: "Dispositivo não inicializado",
    8: "Falha interna",
    9: "Plunger overload",
    10: "Valve overload",
    11: "Plunger move not allowed",
    12: "Falha interna",
    14: "ADC failure",
    15: "Command overflow",
}


class CavroValve:
    """Control a Cavro multichannel valve through an existing serial connection."""

    def __init__(self, serial_connection):
        self.serial_connection = serial_connection

    def read_response(self):
        """Read and interpret one Cavro DT response."""
        response = self.serial_connection.read_until(b"\n")
        time.sleep(0.01)
        response += self.serial_connection.read_all()

        if not response:
            return None

        start = response.find(b"/0")
        if start < 0 or len(response) < start + 3:
            return None

        status = response[start + 2]
        error_code = status & 0x0F
        ready = bool(status & 0x20)
        etx = response.find(b"\x03", start + 3)
        data = response[start + 3:etx] if etx >= 0 else response[start + 3:]

        return {
            "raw": response,
            "status": status,
            "error": error_code,
            "ready": ready,
            "data": data.decode("ascii", errors="replace"),
        }

    def send_command(self, command):
        """Send a Cavro command and return its response."""
        self.serial_connection.reset_input_buffer()
        packet = f"/{VALVE_ADDRESS}{command}\r".encode("ascii")
        self.serial_connection.write(packet)
        self.serial_connection.flush()
        time.sleep(0.05)
        return self.read_response()

    def wait_until_ready(self, timeout=10):
        """Wait until the valve completes its current command."""
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            response = self.send_command("Q")
            if response is None:
                time.sleep(0.1)
                continue

            if response["error"] != 0:
                description = CAVRO_VALVE_ERRORS.get(
                    response["error"],
                    "Erro desconhecido",
                )
                if response["error"] in (7, 10):
                    raise RuntimeError(
                        f"Erro {response['error']}: {description}. "
                        "Considere executar o homing manual."
                    )
                raise RuntimeError(f"Erro {response['error']}: {description}")

            if response["ready"]:
                return True
            time.sleep(0.1)

        raise TimeoutError("Timeout esperando a bomba ficar READY.")

    def get_current_channel(self):
        """Return the channel currently reported by the valve."""
        response = self.send_command("?6")
        if response is None or response["error"] != 0:
            return None
        return response["data"]

    def get_status(self):
        """Return the current valve status response."""
        return self.send_command("Q")

    def select_channel(
        self,
        channel,
        show=True,
        before_channel_change=None,
        after_channel_change=None,
    ):
        """Select a channel, calling optional hooks around a real movement."""
        if channel not in range(1, VALVE_CHANNEL_COUNT + 1):
            raise ValueError(f"Canal deve estar entre 1 e {VALVE_CHANNEL_COUNT}.")

        current_channel = self.get_current_channel()
        if current_channel is None:
            raise RuntimeError("Não foi possível determinar o canal atual.")

        try:
            current_channel_number = int(current_channel)
        except ValueError:
            raise RuntimeError(
                f"Posição inválida reportada pela bomba: {current_channel!r}. "
                "Talvez seja necessário executar o homing."
            )

        if current_channel_number == channel:
            if show:
                print(f"Canal {channel} já está selecionado.")
            return True

        clockwise_distance = (channel - current_channel_number) % VALVE_CHANNEL_COUNT
        counterclockwise_distance = (
            current_channel_number - channel
        ) % VALVE_CHANNEL_COUNT
        if clockwise_distance <= counterclockwise_distance:
            command, direction, steps = "I", "horário", clockwise_distance
        else:
            command, direction, steps = "O", "anti-horário", counterclockwise_distance

        if show:
            print(f"Canal {current_channel_number} -> {channel}")
            print(f"Movimento: {direction} ({steps} passo(s))")

        if before_channel_change is not None:
            before_channel_change()

        response = self.send_command(f"{command}{channel}R")
        if response is None:
            raise RuntimeError("A bomba não respondeu ao comando de movimento.")
        if response["error"] != 0:
            raise RuntimeError(
                f"Erro {response['error']}: "
                f"{CAVRO_VALVE_ERRORS.get(response['error'], 'Desconhecido')}"
            )

        self.wait_until_ready(timeout=10)
        confirmed_channel = self.get_current_channel()
        if confirmed_channel != str(channel):
            raise RuntimeError(
                f"Canal solicitado: {channel}. Bomba reportou: {confirmed_channel!r}"
            )
        if show:
            print(f"Canal {channel} confirmado.")

        if after_channel_change is not None:
            after_channel_change()

        return True

    def home(self):
        """Run manual valve homing; it is never invoked automatically."""
        print()
        print("=" * 60)
        print("HOMING DA VÁLVULA")
        print("=" * 60)
        print()
        print("A válvula será inicializada e referenciada no canal 1.")
        print("O movimento será realizado fisicamente pela bomba.")
        print()

        confirmation = input("Executar homing? [s/N]: ").strip().lower()
        if confirmation not in ("s", "sim", "y", "yes"):
            print()
            print("Homing cancelado.")
            return False

        print()
        print("Executando homing...")
        response = self.send_command("w1,0R")
        if response is None:
            raise RuntimeError("A bomba não respondeu ao comando de homing.")
        if response["error"] != 0:
            raise RuntimeError(
                f"Erro ao iniciar homing: {response['error']} - "
                f"{CAVRO_VALVE_ERRORS.get(response['error'], 'Desconhecido')}"
            )

        self.wait_until_ready(timeout=20)
        channel = self.get_current_channel()
        print()
        print("=" * 60)
        print("HOMING CONCLUÍDO")
        print("=" * 60)
        print(f"Canal reportado: {channel}")
        if channel == "1":
            print("Referência estabelecida corretamente no canal 1.")
        else:
            print("ATENÇÃO: a válvula terminou o homing, mas não reportou o canal 1.")
        return True
