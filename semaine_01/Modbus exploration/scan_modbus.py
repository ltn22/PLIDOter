"""Scan a Modbus RTU (RS485) bus through a USB adapter.

For each slave address, send a Read Holding Registers request (function 0x03)
for register 0. A slave is considered present if it answers with a valid frame
(correct CRC), including an exception response (e.g. "illegal data address").
"""

import struct
import sys
import time

import serial

# --- Configuration ---------------------------------------------------------
DEVICE = "/dev/cu.usbserial-11240"  # see `ls /dev/cu.usb*`
BAUDRATES = [9600]                  # e.g. [9600, 19200, 38400, 115200] to try several speeds
PARITY = serial.PARITY_NONE         # PARITY_NONE, PARITY_EVEN or PARITY_ODD
STOPBITS = 1
TIMEOUT = 0.3                       # seconds to wait for an answer per address (measured latency: ~100 ms)
PROBE_DELAY = 1.0                   # seconds to wait before each request
FIRST_ADDRESS = 1
LAST_ADDRESS = 247
# ---------------------------------------------------------------------------

# request in cyan, valid response in green, invalid response in red
CYAN, GREEN, RED, RESET = ("\033[36m", "\033[32m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("",) * 4

EXCEPTIONS = {
    0x01: "illegal function",
    0x02: "illegal data address",
    0x03: "illegal data value",
    0x04: "slave device failure",
    0x0A: "gateway path unavailable",
    0x0B: "gateway target device failed to respond",
}
GATEWAY_EXCEPTIONS = (0x0A, 0x0B)  # nothing answered on the serial side of a Modbus TCP gateway


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def request_frame(address: int, function: int = 0x03, start: int = 0, count: int = 1) -> bytes:
    """RTU request reading `count` registers from `start`, CRC included."""
    request = struct.pack(">BBHH", address, function, start, count)
    return request + struct.pack("<H", crc16(request))


def describe(address: int, frame: bytes):
    """Describe the answer to the register read, or return None if `frame` is not a valid answer from `address`."""
    if len(frame) < 5 or frame[0] != address:
        return None
    # exception: 3 bytes + CRC; normal read: 3 bytes + data + CRC
    expected = 5 if frame[1] & 0x80 else 5 + frame[2]
    if len(frame) != expected or crc16(frame) != 0:
        return None

    if frame[1] & 0x80:
        meaning = EXCEPTIONS.get(frame[2], "unknown")
        return f"answers (exception 0x{frame[2]:02X}: {meaning})"
    return "register 0 = " + frame[3:-2].hex()


def probe(port: serial.Serial, address: int):
    """Query one address.

    Returns (request, received bytes, description). The description is None if
    nothing was received or if the received frame is invalid (bad CRC, etc.).
    """
    request = request_frame(address)

    time.sleep(PROBE_DELAY)
    port.reset_input_buffer()
    port.write(request)

    frame = port.read(3)  # address, function, byte count or exception code
    if len(frame) == 3 and frame[0] == address:
        frame += port.read(2 if frame[1] & 0x80 else frame[2] + 2)
    return request, frame, describe(address, frame)


def main():
    found = []
    for baudrate in BAUDRATES:
        print(f"Scanning {DEVICE} at {baudrate} baud ({FIRST_ADDRESS}..{LAST_ADDRESS})")
        with serial.Serial(DEVICE, baudrate, parity=PARITY, stopbits=STOPBITS, timeout=TIMEOUT) as port:
            time.sleep(0.1)  # let the adapter settle
            for address in range(FIRST_ADDRESS, LAST_ADDRESS + 1):
                request, response, result = probe(port, address)
                line = f"  slave {address:3d}  {CYAN}{request.hex(' ')}{RESET}"
                if response:
                    line += f"  {GREEN if result else RED}{response.hex(' ')}{RESET}"
                if result:
                    line += f"  {result}"
                    found.append((baudrate, address))
                print(line)

    if not found:
        print("No slave found.")
    else:
        print(f"{len(found)} slave(s) found:")
        for baudrate, address in found:
            print(f"  address {address} ({baudrate} baud)")


if __name__ == "__main__":
    main()
