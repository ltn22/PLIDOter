"""List the registers readable on a Modbus RTU slave, through a TCP gateway.

Usage: uv run list_registers_tcp.py GATEWAY_IP SLAVE

The gateway must be in transparent mode (see scan_modbus_tcp.py): we send Modbus RTU
frames over the TCP connection.

Holding registers (function 0x03) and input registers (function 0x04) are read one by
one. A register that the slave refuses is answered with an error (exception code 2,
"illegal data address") instead of its value.
"""

import socket
import struct
import sys
import time

PORT = 502
TIMEOUT = 1.0  # seconds to wait for an answer
PAUSE = 1.0    # seconds between two requests
FIRST_REGISTER = 0
LAST_REGISTER = 1023
FUNCTIONS = {0x03: "Holding registers", 0x04: "Input registers"}

CYAN, GREEN, RED, RESET = "\033[36m", "\033[32m", "\033[31m", "\033[0m"  # request, valid answer, invalid answer


def crc16(data):
    """CRC of a Modbus RTU frame. Computed over a frame that includes its CRC, it gives 0."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def ask(ip, slave, function, register):
    """Send a request to read one register and return (request, answer)."""
    request = struct.pack(">BBHH", slave, function, register, 1)  # slave, function, first register, number of registers
    request += struct.pack("<H", crc16(request))                  # CRC, low byte first

    with socket.create_connection((ip, PORT), timeout=TIMEOUT) as sock:
        sock.sendall(request)
        try:
            answer = sock.recv(256)
        except TimeoutError:
            answer = b""  # nobody answered
    return request, answer


def is_valid(answer, slave):
    return len(answer) >= 5 and answer[0] == slave and crc16(answer) == 0


if len(sys.argv) != 3:
    sys.exit("Usage: uv run list_registers_tcp.py GATEWAY_IP SLAVE")
ip, slave = sys.argv[1], int(sys.argv[2])

print(f"Slave {slave} through {ip}:{PORT}, registers {FIRST_REGISTER}..{LAST_REGISTER}")
try:
    # any valid answer, even an error, proves that the slave is there
    if not is_valid(ask(ip, slave, 0x03, 0)[1], slave):
        sys.exit(f"Slave {slave} does not answer.")

    for function, name in FUNCTIONS.items():
        print(f"\n{name} (function 0x{function:02X}):")
        readable = {}
        for register in range(FIRST_REGISTER, LAST_REGISTER + 1):
            time.sleep(PAUSE)
            request, answer = ask(ip, slave, function, register)
            valid = is_valid(answer, slave)

            line = f"  {register:5d}  {CYAN}{request.hex(' ')}{RESET}"
            if answer:
                line += f"  {GREEN if valid else RED}{answer.hex(' ')}{RESET}"
            if valid and not answer[1] & 0x80:  # a value, not an error
                readable[register] = int.from_bytes(answer[3:5], "big")
                line += f"  value {readable[register]}"
            print(line)

        print()
        for register, value in readable.items():
            print(f"  {register:5d}  0x{register:04X}  =  0x{value:04X}  {value:5d}")
        print(f"  {len(readable)} register(s) readable")
except OSError as error:
    sys.exit(f"Cannot talk to {ip}:{PORT}: {error}")
