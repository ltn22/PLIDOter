"""Scan a Modbus RTU bus through a TCP gateway.

Usage: uv run scan_modbus_tcp.py GATEWAY_IP

The gateway must be in transparent mode: it forwards the bytes received on the TCP
connection to the RS485 bus, and sends back the bytes it receives from the bus. We
therefore speak Modbus RTU exactly as on a serial port: slave address, function,
data and a CRC.

For each slave address we read register 0 (function 0x03). A valid answer, even an
error (exception), proves that a slave is there.
"""

import socket
import struct
import sys
import time

PORT = 502
TIMEOUT = 1.0  # seconds to wait for an answer
PAUSE = 1.0    # seconds between two requests
FIRST_ADDRESS = 1
LAST_ADDRESS = 247

CYAN, GREEN, RED, RESET = "\033[36m", "\033[32m", "\033[31m", "\033[0m"  # request, valid answer, invalid answer


def crc16(data):
    """CRC of a Modbus RTU frame. Computed over a frame that includes its CRC, it gives 0."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def ask(ip, slave):
    """Send a request to read register 0 and return (request, answer)."""
    request = struct.pack(">BBHH", slave, 0x03, 0, 1)  # slave, function, first register, number of registers
    request += struct.pack("<H", crc16(request))       # CRC, low byte first

    with socket.create_connection((ip, PORT), timeout=TIMEOUT) as sock:
        sock.sendall(request)
        try:
            answer = sock.recv(256)
        except TimeoutError:
            answer = b""  # nobody answered
    return request, answer


if len(sys.argv) != 2:
    sys.exit("Usage: uv run scan_modbus_tcp.py GATEWAY_IP")
ip = sys.argv[1]

print(f"Scanning {ip}:{PORT} ({FIRST_ADDRESS}..{LAST_ADDRESS})")
found = []
try:
    for slave in range(FIRST_ADDRESS, LAST_ADDRESS + 1):
        time.sleep(PAUSE)
        request, answer = ask(ip, slave)
        valid = len(answer) >= 5 and answer[0] == slave and crc16(answer) == 0

        line = f"  slave {slave:3d}  {CYAN}{request.hex(' ')}{RESET}"
        if answer:
            line += f"  {GREEN if valid else RED}{answer.hex(' ')}{RESET}"
        if valid:
            found.append(slave)
            if answer[1] & 0x80:  # the function code has its top bit set when the slave reports an error
                line += f"  error {answer[2]}"
            else:
                line += f"  value {int.from_bytes(answer[3:5], 'big')}"
        print(line)
except OSError as error:
    sys.exit(f"Cannot talk to {ip}:{PORT}: {error}")

print(f"Slaves found: {found}")
