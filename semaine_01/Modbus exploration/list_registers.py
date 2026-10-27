"""List the registers readable on a Modbus RTU slave.

Usage: uv run list_registers.py SLAVE [--first ADDRESS] [--last ADDRESS]

Holding registers (function 0x03) and input registers (function 0x04) are read
from FIRST_REGISTER to LAST_REGISTER. A slave refuses a whole read as soon as one
register in it is not readable, so the scan starts with single registers and
doubles the block size after each success; after a refusal it goes back to
single registers. This is fast on dense register maps and costs one request per
address on sparse ones (PROBE_DELAY + ~65 ms each). Serial settings, colors and
PROBE_DELAY are shared with scan_modbus.py.

Every request is shown in hex (cyan) followed by the answer (green, or red when
it is invalid); the readable registers are summarized after each function.
"""

import argparse
import struct
import sys
import time

import serial

from scan_modbus import (
    CYAN, DEVICE, EXCEPTIONS, GATEWAY_EXCEPTIONS, GREEN, PARITY, PROBE_DELAY, RED, RESET, STOPBITS, TIMEOUT, crc16,
    request_frame,
)

# --- Configuration ---------------------------------------------------------
BAUDRATE = 9600
FIRST_REGISTER = 0
LAST_REGISTER = 1023                # the protocol goes up to 65535, but sparse maps take one request per address
BLOCK_SIZE = 125                    # maximum allowed by the Modbus specification
FUNCTIONS = {
    0x03: "Holding registers",
    0x04: "Input registers",
}
# ---------------------------------------------------------------------------

ILLEGAL_FUNCTION = 0x01
ILLEGAL_DATA_VALUE = 0x03  # e.g. too many registers requested
NO_ANSWER = 0              # pseudo exception code: no answer, or invalid frame


class FunctionNotSupported(Exception):
    pass


def exchange(port: serial.Serial, slave: int, function: int, start: int, count: int):
    """Send a read request and return (request, raw answer)."""
    request = request_frame(slave, function, start, count)

    time.sleep(PROBE_DELAY)
    port.reset_input_buffer()
    port.write(request)

    answer = port.read(3)  # slave, function, byte count or exception code
    if len(answer) == 3 and answer[0] == slave:
        # exception: 3 bytes + CRC; normal read: 3 bytes + data + CRC
        remaining = 2 if answer[1] & 0x80 else answer[2] + 2
        timeout = port.timeout
        port.timeout = timeout + remaining * 11 / port.baudrate  # leave time for the data to arrive
        answer += port.read(remaining)
        port.timeout = timeout
    return request, answer


def decode(answer: bytes, slave: int, function: int, count: int):
    """Return (values, exception): `values` is a list of ints on success, otherwise
    it is None and `exception` is the Modbus exception code (NO_ANSWER if the
    slave did not answer or the frame is invalid).
    """
    if len(answer) < 5 or answer[0] != slave:
        return None, NO_ANSWER
    expected = 5 if answer[1] & 0x80 else 5 + answer[2]
    if len(answer) != expected or crc16(answer) != 0:
        return None, NO_ANSWER

    if answer[1] == function | 0x80:
        return None, answer[2]
    if answer[1] != function or answer[2] != 2 * count:
        return None, NO_ANSWER
    return list(struct.unpack(f">{count}H", answer[3:-2])), None


def show_exchange(start: int, count: int, request: bytes, answer: bytes, values, exception: int):
    """Print a request and its answer in hex, followed by the outcome."""
    valid = values is not None or exception != NO_ANSWER
    line = f"  {start:5d} x{count:<3d}  {CYAN}{request.hex(' ')}{RESET}"
    if answer:
        line += f"  {GREEN if valid else RED}{answer.hex(' ')}{RESET}"
    if values is not None:
        line += "  ok"
    elif valid:
        line += f"  exception 0x{exception:02X}: {EXCEPTIONS.get(exception, 'unknown')}"
    else:
        line += "  invalid answer" if answer else "  no answer"
    print(line)


def read_registers(port: serial.Serial, slave: int, function: int, start: int, count: int):
    """Read `count` registers from `start`, showing the frames exchanged.

    Returns (values, exception) as `decode` does.
    """
    request, answer = exchange(port, slave, function, start, count)
    values, exception = decode(answer, slave, function, count)
    show_exchange(start, count, request, answer, values, exception)
    return values, exception


def scan(read, function: int, first: int, last: int):
    """Yield (address, value) for each readable register in [first, last], in order.

    `read(function, start, count)` returns (values, exception) like `read_registers`.
    """
    address, size, max_size = first, 1, BLOCK_SIZE
    while address <= last:
        count = min(size, last - address + 1)
        values, exception = read(function, address, count)
        if values is not None:
            yield from enumerate(values, address)
            address += count
            size = min(size * 2, max_size)
        elif exception == ILLEGAL_FUNCTION:
            raise FunctionNotSupported
        elif count > 1:
            # something in the block is refused: go back to single registers
            if exception == ILLEGAL_DATA_VALUE:
                max_size = count // 2  # the slave does not accept that many registers at once
            size = 1
        else:
            address += 1


def list_all(slave: int, read, first: int, last: int):
    """Print the readable registers of each type in FUNCTIONS."""
    # any valid frame (even an exception) proves that the slave is there
    _, exception = read(0x03, 0, 1)
    if exception in (NO_ANSWER, *GATEWAY_EXCEPTIONS):
        sys.exit(f"Slave {slave} does not answer.")

    for function, name in FUNCTIONS.items():
        print(f"\n{name} (function 0x{function:02X}):")
        try:
            readable = list(scan(read, function, first, last))
        except FunctionNotSupported:
            print("  not supported by this slave")
            continue
        print()
        for address, value in readable:
            print(f"  {address:5d}  0x{address:04X}  =  0x{value:04X}  {value:5d}")
        print(f"  {len(readable)} register(s) readable")


def slave_address(text: str) -> int:
    value = int(text)
    if not 1 <= value <= 247:
        raise argparse.ArgumentTypeError("must be between 1 and 247")
    return value


def add_register_arguments(parser: argparse.ArgumentParser):
    parser.add_argument("slave", type=slave_address, help="slave address (1..247)")
    parser.add_argument("--first", type=lambda s: int(s, 0), default=FIRST_REGISTER, help="first register (default %(default)s)")
    parser.add_argument("--last", type=lambda s: int(s, 0), default=LAST_REGISTER, help="last register (default %(default)s)")


def check_range(parser: argparse.ArgumentParser, args: argparse.Namespace):
    if not 0 <= args.first <= args.last <= 0xFFFF:
        parser.error("registers must satisfy 0 <= first <= last <= 65535")


def main():
    parser = argparse.ArgumentParser(description="List the registers readable on a Modbus RTU slave.")
    add_register_arguments(parser)
    args = parser.parse_args()
    check_range(parser, args)

    with serial.Serial(DEVICE, BAUDRATE, parity=PARITY, stopbits=STOPBITS, timeout=TIMEOUT) as port:
        time.sleep(0.1)  # let the adapter settle

        print(f"Slave {args.slave} on {DEVICE} at {BAUDRATE} baud, registers {args.first}..{args.last}")
        list_all(args.slave, lambda function, start, count: read_registers(port, args.slave, function, start, count), args.first, args.last)


if __name__ == "__main__":
    main()
