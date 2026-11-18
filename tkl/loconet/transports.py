"""How TKL reaches LocoNet: a LocoBuffer USB or a BTLocoBridge (STUDIO-22), and the port list.

Ported from cda-tkl (scripts/serial-port.py, scripts/bluetooth-port.py and
src/connection-mode.mjs), without a gateway process in between:

- LocoBuffer USB: a serial port at 57600 baud, 8N1, with RTS/CTS flow control, as cda-tkl set
  it up. The port is opened exclusively, raw, and never as the controlling terminal.
- BTLocoBridge: paired with the computer first. On a Raspberry Pi TKL connects to its address
  over RFCOMM (AA:BB:CC:DD:EE:FF, channel 1–30); on a Mac it is the serial port the system made
  for it, /dev/cu.…, at 115200 without flow control.

The layer is thin and replaceable: a transport writes bytes, reads what has come within a
timeout and closes. The pretend LocoNet (tkl.loconet.simulator) is a transport too, and the
tests give a pretend serial port. Only POSIX: TKL runs on the station's computer or a Pi
(STV-27). No new dependency: termios and the socket module are Python's own.
"""

from __future__ import annotations

import contextlib
import os
import re
import select
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from contracts.tkl import LoconetType

LOCOBUFFER_BAUD: Final = 57600
BRIDGE_BAUD: Final = 115200
WRITE_SECONDS: Final = 2.0
CONNECT_SECONDS: Final = 20.0
CHUNK: Final = 4096
BLUETOOTH_ADDRESS: Final = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
DEVICE: Final = re.compile(r"^/dev/[^\s\x00-\x1f]+$")
PRETEND_PORT: Final = "latsas"
LABEL: Final = {
    LoconetType.LOCOBUFFER: "LocoBuffer USB",
    LoconetType.BTLOCOBRIDGE: "BTLocoBridge",
    LoconetType.PRETEND: "låtsas-LocoNet",
}


class TransportError(OSError):
    """The port could not be opened or used: the reason in Swedish."""


class Transport(Protocol):
    label: str

    def write(self, data: bytes) -> None: ...

    def read(self, timeout: float) -> bytes:
        """What has come within the timeout; nothing is b""."""
        ...

    def close(self) -> None: ...


def check_device(value: str, what: str) -> str:
    """A serial port under /dev, never a path out of it."""
    if not DEVICE.fullmatch(value) or ".." in value or len(value) > 255:
        raise TransportError(what)
    return value


def check_bridge(target: str, channel: int) -> str:
    """A BTLocoBridge's address AA:BB:CC:DD:EE:FF, with versals, or its paired serial port."""
    value = target.strip()
    if BLUETOOTH_ADDRESS.fullmatch(value):
        if not 1 <= channel <= 30:
            raise TransportError("Kanalen är 1–30.")
        return value.upper()
    return check_device(
        value,
        "Ange BTLocoBridgens adress AA:BB:CC:DD:EE:FF eller dess parade serieport under /dev.",
    )


@dataclass(frozen=True)
class Port:
    type: LoconetType
    path: str
    label: str


def ports(listdir: Callable[[str], list[str]] = os.listdir) -> list[Port]:
    """The serial ports a LocoBuffer USB or a paired BTLocoBridge can be on: the stable names
    under /dev/serial/by-id first (Linux), then ttyACM and ttyUSB, cu.usb… on a Mac; and
    Bluetooth's serial ports, /dev/rfcomm… and /dev/cu.… that is not USB."""
    found: list[Port] = []

    def listed(folder: str) -> list[str]:
        try:
            return sorted(listdir(folder))
        except OSError:
            return []

    for name in listed("/dev/serial/by-id"):
        found.append(Port(LoconetType.LOCOBUFFER, f"/dev/serial/by-id/{name}", name))
    for name in listed("/dev"):
        if re.fullmatch(r"tty(ACM|USB)\d+", name) or re.match(r"cu\.usb(serial|modem)", name):
            found.append(Port(LoconetType.LOCOBUFFER, f"/dev/{name}", name))
        elif re.fullmatch(r"rfcomm\d+", name) or (
            name.startswith("cu.")
            and not name.startswith("cu.usb")
            and "Bluetooth-Incoming" not in name
        ):
            found.append(Port(LoconetType.BTLOCOBRIDGE, f"/dev/{name}", name))
    return found


class SerialPort:
    """A raw POSIX serial port: 8N1, the baud rate and RTS/CTS as asked, opened exclusively."""

    def __init__(
        self,
        device: str,
        baud: int,
        rtscts: bool,
        *,
        label: str,
        termios_module: Any | None = None,
        fcntl_module: Any | None = None,
    ) -> None:
        import fcntl
        import termios

        self.label = label
        self._termios = termios_module or termios
        tio = self._termios
        try:
            self._fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as error:
            raise TransportError(_said(device, error)) from error
        try:
            if not os.isatty(self._fd):
                raise TransportError(f"{device} är ingen serieport.")
            (fcntl_module or fcntl).ioctl(self._fd, tio.TIOCEXCL)
            self._old = tio.tcgetattr(self._fd)
            flags = tio.CLOCAL | tio.CREAD | tio.CS8
            if rtscts:
                flow = getattr(tio, "CRTSCTS", 0)
                if not flow:
                    raise TransportError("RTS/CTS finns inte på den här datorn.")
                flags |= flow
            speed = getattr(tio, f"B{baud}")
            mode = tio.tcgetattr(self._fd)
            mode[:6] = [0, 0, flags, 0, speed, speed]
            mode[6][tio.VMIN] = 0
            mode[6][tio.VTIME] = 0
            tio.tcsetattr(self._fd, tio.TCSANOW, mode)
            tio.tcflush(self._fd, tio.TCIOFLUSH)
        except TransportError:
            os.close(self._fd)
            raise
        except OSError as error:
            os.close(self._fd)
            raise TransportError(_said(device, error)) from error

    def write(self, data: bytes) -> None:
        deadline = time.monotonic() + WRITE_SECONDS
        rest = memoryview(data)
        while rest:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TransportError("Serieporten tog inte emot meddelandet i tid.")
            _, writable, _ = select.select([], [self._fd], [], left)
            if not writable:
                continue
            try:
                rest = rest[os.write(self._fd, rest) :]
            except BlockingIOError:
                continue
            except OSError as error:
                raise TransportError(f"Serieporten: {error.strerror or error}.") from error

    def read(self, timeout: float) -> bytes:
        readable, _, _ = select.select([self._fd], [], [], timeout)
        if not readable:
            return b""
        try:
            data = os.read(self._fd, CHUNK)
        except BlockingIOError:
            return b""
        except OSError as error:
            raise TransportError(f"Serieporten: {error.strerror or error}.") from error
        if not data:
            raise TransportError("Serieporten försvann: är sladden urdragen?")
        return data

    def close(self) -> None:
        try:
            self._termios.tcflush(self._fd, self._termios.TCOFLUSH)
            self._termios.tcsetattr(self._fd, self._termios.TCSANOW, self._old)
        except OSError:
            pass
        with contextlib.suppress(OSError):
            os.close(self._fd)


class Rfcomm:
    """A BTLocoBridge over RFCOMM, by its address: paired in the system first."""

    def __init__(
        self,
        address: str,
        channel: int,
        *,
        connect: Callable[[str, int], socket.socket] | None = None,
    ) -> None:
        self.label = f"{LABEL[LoconetType.BTLOCOBRIDGE]} ({address})"
        try:
            self._sock = (connect or _rfcomm)(address, channel)
            self._sock.setblocking(False)
        except OSError as error:
            raise TransportError(
                f"BTLocoBridgen {address} svarar inte: {error}. Kontrollera att den är parad och "
                "påslagen."
            ) from error

    def write(self, data: bytes) -> None:
        deadline = time.monotonic() + WRITE_SECONDS
        rest = memoryview(data)
        while rest:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TransportError("BTLocoBridgen tog inte emot meddelandet i tid.")
            _, writable, _ = select.select([], [self._sock], [], left)
            if writable:
                try:
                    rest = rest[self._sock.send(rest) :]
                except BlockingIOError:
                    continue
                except OSError as error:
                    raise TransportError(f"Bluetooth-förbindelsen: {error}.") from error

    def read(self, timeout: float) -> bytes:
        readable, _, _ = select.select([self._sock], [], [], timeout)
        if not readable:
            return b""
        try:
            data = self._sock.recv(CHUNK)
        except BlockingIOError:
            return b""
        except OSError as error:
            raise TransportError(f"Bluetooth-förbindelsen: {error}.") from error
        if not data:
            raise TransportError("Bluetooth-förbindelsen bröts.")
        return data

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._sock.close()


def _rfcomm(address: str, channel: int) -> socket.socket:
    family = getattr(socket, "AF_BLUETOOTH", None)
    protocol = getattr(socket, "BTPROTO_RFCOMM", None)
    if family is None or protocol is None:
        raise OSError(
            "Bluetooth RFCOMM finns inte på den här datorn. Para kortet i systemet och välj dess "
            "serieport i stället"
        )
    sock = socket.socket(family, socket.SOCK_STREAM, protocol)
    sock.settimeout(CONNECT_SECONDS)
    sock.connect((address, channel))
    return sock


def _said(device: str, error: OSError) -> str:
    text = error.strerror or str(error)
    if error.errno in (13, 16) or "busy" in text.lower():
        return (
            f"{device} kan inte öppnas: {text}. Stäng JMRI och andra program som kan använda "
            "porten och försök igen."
        )
    return f"{device} kan inte öppnas: {text}."


def open_port(kind: LoconetType, port: str, channel: int = 1) -> Transport:
    """A LocoBuffer USB or a BTLocoBridge, opened. TransportError with the reason."""
    if kind == LoconetType.LOCOBUFFER:
        device = check_device(
            port, "Ange LocoBufferns serieport under /dev, till exempel /dev/ttyACM0."
        )
        label = f"{LABEL[kind]} ({device})"
        return SerialPort(device, LOCOBUFFER_BAUD, True, label=label)
    if kind == LoconetType.BTLOCOBRIDGE:
        target = check_bridge(port, channel)
        if BLUETOOTH_ADDRESS.fullmatch(target):
            return Rfcomm(target, channel)
        return SerialPort(target, BRIDGE_BAUD, False, label=f"{LABEL[kind]} ({target})")
    raise TransportError("Låtsas-LocoNet öppnas inte som en port.")
