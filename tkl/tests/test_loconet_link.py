"""LocoBuffer USB and BTLocoBridge, the port list, and one message at a time (#85, STUDIO-11,
STUDIO-22).

The serial port is a pretend one: a pseudo terminal, which termios sets up as it would a
LocoBuffer, and whose other end the test reads and writes as the bus. The tests marked
"Ported" carry an old cda-tkl test's behaviour, with the old test named.
"""

from __future__ import annotations

import os
import pty
import socket
import termios
from collections.abc import Iterator

import pytest

from contracts.tkl import LoconetType
from tkl.loconet.link import Link, LinkError
from tkl.loconet.messages import (
    Output,
    hex_of,
    sensor_report,
    switch_report,
    switch_request,
)
from tkl.loconet.transports import (
    LOCOBUFFER_BAUD,
    Port,
    Rfcomm,
    SerialPort,
    TransportError,
    check_bridge,
    open_port,
    ports,
)

C, T = Output.CLOSED, Output.THROWN


@pytest.fixture
def bus() -> Iterator[tuple[int, str]]:
    """A pretend serial port: the bus's end, and the device TKL opens."""
    main, other = pty.openpty()
    try:
        yield main, os.ttyname(other)
    finally:
        os.close(main)
        os.close(other)


def written(main: int) -> bytes:
    found = b""
    while True:
        import select

        readable, _, _ = select.select([main], [], [], 0.2)
        if not readable:
            return found
        found += os.read(main, 4096)


def test_the_locobuffer_is_raw_8n1_at_its_baud_rate_with_rts_cts(bus: tuple[int, str]) -> None:
    """As cda-tkl's serial-port.py: 57600 baud, eight bits, RTS/CTS, raw, exclusive."""
    main, device = bus
    port = SerialPort(device, LOCOBUFFER_BAUD, True, label="LocoBuffer USB")
    try:
        mode = termios.tcgetattr(port._fd)
        assert mode[4] == termios.B57600 and mode[5] == termios.B57600
        assert mode[2] & termios.CS8 and mode[2] & termios.CRTSCTS
        assert mode[3] == 0, "raw: no echo, no lines"
        port.write(switch_request(7, T))
        assert hex_of(written(main)) == "B0 06 10 59"
        os.write(main, switch_report(7, T))
        assert hex_of(port.read(1.0)) == "B1 06 60 28"
        assert port.read(0.05) == b""
    finally:
        port.close()


def test_a_port_that_is_no_serial_port_is_refused(tmp_path: object) -> None:
    with pytest.raises(TransportError, match="ingen serieport"):
        SerialPort("/dev/null", LOCOBUFFER_BAUD, True, label="x")
    with pytest.raises(TransportError, match="kan inte öppnas"):
        SerialPort("/dev/finns-inte-alls", LOCOBUFFER_BAUD, True, label="x")


def test_the_ports_are_checked_before_they_are_opened() -> None:
    """Ported: connection-mode.test.mjs, "LocoBuffern sparas och prövas" and "BTLocoBridge
    väljs som anslutning, prövas …": only a device under /dev, an address AA:BB:CC:DD:EE:FF
    in versals, and a channel 1–30."""
    for wrong in ("COM3", "/dev/../etc/passwd", "ttyACM0", ""):
        with pytest.raises(TransportError, match="/dev"):
            open_port(LoconetType.LOCOBUFFER, wrong)
    with pytest.raises(TransportError, match="AA:BB:CC:DD:EE:FF"):
        check_bridge("AA:BB:CC", 1)
    with pytest.raises(TransportError, match="Kanalen är 1–30"):
        check_bridge("AA:BB:CC:DD:EE:FF", 99)
    assert check_bridge("aa:bb:cc:dd:ee:ff", 1) == "AA:BB:CC:DD:EE:FF"
    assert check_bridge("/dev/cu.BTLocoBridge-SPP", 1) == "/dev/cu.BTLocoBridge-SPP"
    with pytest.raises(TransportError):
        open_port(LoconetType.PRETEND, "latsas")


def test_the_usb_serial_ports_are_listed_with_stable_names_first() -> None:
    """Ported: connection-mode.test.mjs, "USB-serieportarna listas med stabila namn först",
    with Bluetooth's serial ports for a paired BTLocoBridge."""
    folders = {
        "/dev/serial/by-id": ["usb-RR-CirKits_LocoBuffer-USB-if00"],
        "/dev": [
            "tty",
            "ttyACM0",
            "ttyS0",
            "ttyUSB1",
            "cu.usbserial-A1",
            "null",
            "rfcomm0",
            "cu.BTLocoBridge-SPP",
            "cu.Bluetooth-Incoming-Port",
        ],
    }

    def listdir(folder: str) -> list[str]:
        if folder not in folders:
            raise FileNotFoundError(folder)
        return folders[folder]

    found = ports(listdir)
    assert [p.path for p in found if p.type == LoconetType.LOCOBUFFER] == [
        "/dev/serial/by-id/usb-RR-CirKits_LocoBuffer-USB-if00",
        "/dev/cu.usbserial-A1",
        "/dev/ttyACM0",
        "/dev/ttyUSB1",
    ]
    assert [p.path for p in found if p.type == LoconetType.BTLOCOBRIDGE] == [
        "/dev/cu.BTLocoBridge-SPP",
        "/dev/rfcomm0",
    ]
    assert ports(lambda _folder: []) == []
    assert Port(LoconetType.LOCOBUFFER, "/dev/ttyACM0", "ttyACM0").label == "ttyACM0"


def test_the_btlocobridge_by_address_is_an_rfcomm_socket() -> None:
    """As cda-tkl's bluetooth-port.py: a stream to the paired card's address and channel."""
    mine, theirs = socket.socketpair()
    asked: list[tuple[str, int]] = []

    def connect(address: str, channel: int) -> socket.socket:
        asked.append((address, channel))
        return mine

    bridge = Rfcomm("AA:BB:CC:DD:EE:FF", 3, connect=connect)
    try:
        assert asked == [("AA:BB:CC:DD:EE:FF", 3)]
        assert bridge.label == "BTLocoBridge (AA:BB:CC:DD:EE:FF)"
        bridge.write(switch_request(7, C))
        assert hex_of(theirs.recv(64)) == "B0 06 30 79"
        theirs.sendall(sensor_report(220, True))
        assert hex_of(bridge.read(1.0)) == "B2 6D 70 50"
        theirs.close()
        with pytest.raises(TransportError, match="bröts"):
            bridge.read(1.0)
    finally:
        bridge.close()

    def refused(address: str, channel: int) -> socket.socket:
        raise OSError("Host is down")

    with pytest.raises(TransportError, match="parad"):
        Rfcomm("AA:BB:CC:DD:EE:FF", 1, connect=refused)


class Bench:
    """The bus at the other end of a link: what TKL wrote, and what the bus sends back."""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.incoming = b""
        self.closed = False
        self.label = "bänken"

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def read(self, timeout: float) -> bytes:
        data, self.incoming = self.incoming, b""
        return data

    def close(self) -> None:
        self.closed = True


def test_only_the_complete_echo_acknowledges_an_order() -> None:
    """Ported: serial-gateway.test.mjs, "only a matching complete serial echo acknowledges an
    order, after RECEIVE and separately from B1"."""
    now = [0.0]
    bench = Bench()
    link = Link(bench, clock=lambda: now[0])
    order, report = switch_request(123, C), switch_report(123, C)
    link.send(order)
    link.send(switch_request(124, C))
    assert bench.written == [order], "the next waits for the echo"
    bench.incoming = report + order[:2]
    assert link.receive() == [report], "a report is passed on and acknowledges nothing"
    assert len(bench.written) == 1
    bench.incoming = order[2:]
    assert link.receive() == [], "the echo is TKL's own"
    assert len(bench.written) == 2


def test_a_bad_echo_cannot_acknowledge_and_the_timeout_fails_without_a_resend() -> None:
    """Ported: serial-gateway.test.mjs, "invalid frames cannot acknowledge an order, and timeout
    closes the serial writer without replay"."""
    now = [0.0]
    bench = Bench()
    link = Link(bench, clock=lambda: now[0])
    order = switch_request(2, T)
    link.send(order)
    bad = bytearray(order)
    bad[3] ^= 1
    bench.incoming = bytes(bad)
    assert link.receive() == []
    now[0] = 2.5
    with pytest.raises(LinkError, match="skickade inte tillbaka"):
        link.tick()
    assert bench.written == [order], "never sent again"


def test_a_switch_request_is_a_pulse_on_then_off() -> None:
    """Ported: benny-monitoring.test.mjs, "transporten pulsar: ON följt av OFF, som JMRI och
    Bennys monitorering"."""
    now = [0.0]
    bench = Bench()
    link = Link(bench, clock=lambda: now[0])
    link.send(switch_request(7, T))
    bench.incoming = bench.written[-1]
    link.receive()
    now[0] = 0.1
    link.tick()
    assert [hex_of(w) for w in bench.written] == ["B0 06 10 59"]
    now[0] = 0.25
    link.tick()
    assert [hex_of(w) for w in bench.written] == ["B0 06 10 59", "B0 06 00 49"]
    assert not link.idle
    bench.incoming = bench.written[-1]
    link.receive()
    assert link.idle


def test_a_queue_that_overflows_and_a_closed_link_refuse() -> None:
    now = [0.0]
    bench = Bench()
    link = Link(bench, clock=lambda: now[0])
    for _ in range(201):  # one on its way and two hundred waiting
        link.send(sensor_report(1, True))
    with pytest.raises(LinkError, match="för många"):
        link.send(sensor_report(1, True))
    link.close()
    assert bench.closed
    with pytest.raises(LinkError, match="inte anslutet"):
        link.send(sensor_report(1, True))


def test_a_port_that_fails_fails_the_link() -> None:
    class Gone(Bench):
        def read(self, timeout: float) -> bytes:
            raise TransportError("Serieporten försvann: är sladden urdragen?")

    link = Link(Gone())
    with pytest.raises(LinkError, match="sladden"):
        link.receive()
