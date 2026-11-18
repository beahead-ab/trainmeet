"""LocoNet's messages and checksums (#85, STUDIO-11, STV-11).

The tests marked "Ported" carry an old cda-tkl test's behaviour, with the old test named. The
frames are the published fixtures and Benny's monitoring of the MGP cards (9 and 10 October
2026), word for word.
"""

from __future__ import annotations

import pytest

from tkl.loconet.messages import (
    MGP_IDENTITY,
    MGP_PRODUCTS,
    OPC_SW_STATE,
    Busy,
    FrameError,
    FrameReader,
    Identity,
    Interrogate,
    LongAck,
    Output,
    Power,
    SensorReport,
    SignalReport,
    SvCommand,
    SwitchReport,
    SwitchRequest,
    SwitchState,
    Unknown,
    decode,
    decode_sv,
    discover,
    frame,
    from_hex,
    hex_of,
    identity_reply,
    interrogation,
    long_ack,
    power,
    read_sv,
    sensor_report,
    signal_report,
    sv_message,
    switch_report,
    switch_request,
    switch_state,
)

C, T = Output.CLOSED, Output.THROWN


def test_published_byte_fixtures_decode_and_encode_independently() -> None:
    """Ported: protocol.test.mjs, "published byte fixtures decode and encode independently"."""
    cases = [
        ("B0 7A 30 05", switch_request(123, C), SwitchRequest(123, C, True)),
        ("B0 7A 10 25", switch_request(123, T), SwitchRequest(123, T, True)),
        ("B1 7A 70 44", switch_report(123, C), SwitchReport(123, C, True)),
        ("B1 7A 60 54", switch_report(123, T), SwitchReport(123, T, True)),
        ("B1 7A 00 34", switch_report(123, None), SwitchReport(123, None)),
        ("B2 3B 75 03", sensor_report(1400, True), SensorReport(1400, True)),
        ("B2 3B 65 13", sensor_report(1400, False), SensorReport(1400, False)),
        ("E4 09 06 2E 00 01 00 00 3B", signal_report(815, 0), SignalReport(815, 0)),
        ("E4 09 06 2E 00 01 12 00 29", signal_report(815, 18), SignalReport(815, 18)),
    ]
    for wire, encoded, value in cases:
        assert hex_of(encoded) == wire
        assert decode(from_hex(wire)) == value
    assert decode(from_hex("B1 7A 20 14")) == SwitchReport(123, C), "the output format, closed"
    assert decode(from_hex("B1 7A 10 24")) == SwitchReport(123, T), "the output format, thrown"


def test_bad_checksum_lengths_and_addresses_fail_closed() -> None:
    """Ported: protocol.test.mjs, "bad checksum, lengths and addresses fail closed"."""
    for text in ("B0 7A 30 04", "B0 7A 30", "B0 7A FF 05", "E4 09 00", "??"):
        with pytest.raises(FrameError):
            from_hex(text)
    with pytest.raises(FrameError, match="Fel kontrollsumma"):
        from_hex("B0 7A 30 04")
    with pytest.raises(FrameError):
        switch_request(2049, C)
    with pytest.raises(FrameError):
        sensor_report(0, True)
    assert isinstance(decode(frame([0xB1, 0, 0x40])), Unknown), "the aux input is no position"
    assert decode(frame([0xB1, 0, 0x30])) == SwitchReport(1, None)


def test_serial_chunks_and_garbage_resynchronize_without_invented_frames() -> None:
    """Ported: protocol.test.mjs, "serial chunks and garbage resynchronize without invented
    frames"."""
    errors: list[FrameError] = []
    reader = FrameReader(errors.append)
    found = reader.push(bytes([0, 5, 0xB0, 0x7A]))
    found += reader.push(bytes([0x30, 0x05, 0xB1, 0, 0xB1, 0x7A, 0x20, 0x14]))
    assert [hex_of(f) for f in found] == ["B0 7A 30 05", "B1 7A 20 14"]
    assert len(errors) == 1


MONITORED = [
    ("B0 06 10 59", SwitchRequest(7, T, True)),  # Requesting Switch at LT7 to Thrown (Output On)
    ("B1 06 60 28", SwitchReport(7, T, True)),  # Turnout LT7 Switch input is Thrown (input on)
    ("B0 06 00 49", SwitchRequest(7, T, False)),  # … to Thrown (Output Off)
    ("B0 06 30 79", SwitchRequest(7, C, True)),  # … to Closed (Output On)
    ("B1 06 70 38", SwitchReport(7, C, True)),  # Switch input is Closed (input off)
    ("B2 6C 60 41", SensorReport(218, False)),  # Sensor LS218 is Low
    ("B2 6D 40 60", SensorReport(219, False)),
    ("B2 6D 70 50", SensorReport(220, True)),  # Sensor LS220 is High
    ("B2 6E 50 73", SensorReport(221, True)),
    ("B0 72 30 0D", SwitchRequest(115, C, True)),  # a signal on LT115 (4/7) to Closed
    ("B1 72 70 4C", SwitchReport(115, C, True)),
    ("B1 72 60 5C", SwitchReport(115, T, True)),
    ("B0 01 11 5F", SwitchRequest(130, T, True)),  # LT130 (S4s) to Thrown
]


def test_bennys_frames_decode_as_jmri_reads_them() -> None:
    """Ported: benny-monitoring.test.mjs, "Bennys ramar avkodas som JMRI läser dem: B1 i
    ingångsformatet är ett växelläge, inte unsupported"."""
    for wire, expected in MONITORED:
        assert decode(from_hex(wire)) == expected, wire
    assert isinstance(decode(from_hex("B1 06 40 08")), Unknown)
    assert isinstance(decode(from_hex("B1 06 50 18")), Unknown)


def test_our_orders_and_reports_are_byte_for_byte_as_on_bennys_layout() -> None:
    """Ported: benny-monitoring.test.mjs, "våra order och rapporter är byte för byte som på
    Bennys bana"."""
    assert hex_of(switch_request(7, T)) == "B0 06 10 59"
    assert hex_of(switch_request(7, T, on=False)) == "B0 06 00 49"
    assert hex_of(switch_request(115, C)) == "B0 72 30 0D"
    assert hex_of(switch_request(115, C, on=False)) == "B0 72 20 1D"
    assert hex_of(sensor_report(218, False)) == "B2 6C 60 41"
    assert hex_of(sensor_report(220, True)) == "B2 6D 70 50"
    assert hex_of(switch_report(7, T)) == "B1 06 60 28"
    assert hex_of(switch_report(7, C)) == "B1 06 70 38"
    assert hex_of(read_sv(6, 21)) == "E5 10 01 02 02 10 06 00 15 00 10 00 00 00 00 18"
    write = sv_message(cmd=SvCommand.WRITE, src=1, dst=6, sv=178, data=[0])
    assert hex_of(write) == "E5 10 01 01 02 14 06 00 32 00 10 00 00 00 00 38"
    reply = decode_sv(from_hex("E5 10 01 42 02 10 06 00 15 00 10 06 00 00 12 4C"))
    assert reply is not None
    assert (reply.reply, reply.dst, reply.sv, reply.data[0]) == (True, 6, 21, 6)


def test_the_interrogation_is_jmris_eight_frames_and_not_an_order() -> None:
    """Ported: benny-monitoring.test.mjs, "JMRI:s avfrågning vid uppstart är en avfrågning,
    inte en order, och TKL bygger samma åtta ramar"."""
    jmri = [
        "B0 78 27 10",
        "B0 79 27 11",
        "B0 7A 27 12",
        "B0 7B 27 13",
        "B0 78 07 30",
        "B0 79 07 31",
        "B0 7A 07 32",
        "B0 7B 07 33",
    ]
    assert [hex_of(f) for f in interrogation()] == jmri
    assert [decode(from_hex(f)) for f in jmri] == [Interrogate(g) for g in (4, 5, 6, 7, 0, 1, 2, 3)]
    assert isinstance(decode(switch_request(1017, C)), SwitchRequest)
    assert isinstance(decode(switch_request(7, C, on=False)), SwitchRequest)
    answers = [("B2 71 50 6C", 227, True), ("B2 70 60 5D", 226, False), ("B2 6B 70 56", 216, True)]
    for wire, address, active in answers:
        assert decode(from_hex(wire)) == SensorReport(address, active)


def test_discover_replies_carry_the_cards_identity() -> None:
    """Ported: benny-monitoring.test.mjs, "MGP-appen: Discover-svaren bär kortens identitet,
    och svaret behåller frågarens agentnummer i SRC"."""
    assert hex_of(discover(0)) == "E5 10 00 07 02 10 00 00 00 00 10 00 00 00 00 0F"
    cards = [
        ("E5 10 00 47 02 10 12 00 7E 01 14 05 00 12 00 31", 18, 5, 146),
        ("E5 10 00 47 02 10 06 00 7E 01 14 09 00 38 00 03", 6, 9, 184),
        ("E5 10 00 47 02 10 6E 00 7E 01 14 06 00 17 02 49", 110, 6, 663),
    ]
    for wire, address, product, serial in cards:
        reply = decode_sv(from_hex(wire))
        assert reply is not None and reply.src == 0 and reply.card == address
        assert reply.identity == Identity(*MGP_IDENTITY, product, serial)
    assert MGP_PRODUCTS[6] == "Signal10 SE"
    assert Identity(*MGP_IDENTITY, 6, 663).name == "MGP Signal10 SE"
    assert Identity(*MGP_IDENTITY, 5, 146).name == "produkt 5"
    read = decode_sv(from_hex("E5 10 00 06 02 10 6E 00 26 01 10 00 00 00 00 47"))
    assert read is not None and (read.cmd, read.dst, read.sv) == (SvCommand.READ4, 110, 294)
    data = decode_sv(from_hex("E5 10 00 46 02 10 6E 00 26 01 14 0E 00 30 0E 33"))
    assert data is not None and data.data == (14, 0, 176, 14)
    request = decode_sv(discover(1))
    assert request is not None
    again = decode_sv(identity_reply(request, 110, Identity(*MGP_IDENTITY, 6, 663)))
    assert again is not None and again.card == 110 and again.identity is not None
    assert again.name == "Svar Discover"


def test_switch_state_long_ack_and_power_are_read() -> None:
    """OPC_SW_STATE gets a long acknowledge with closed in bit 5, as JMRI reads it; a refused
    switch request is B4 30 00; power on and off are only named, TKL never sends them."""
    assert decode(switch_state(123)) == SwitchState(123)
    closed = decode(long_ack(OPC_SW_STATE, 0x20))
    assert isinstance(closed, LongAck) and closed.closed is True
    thrown = decode(long_ack(OPC_SW_STATE, 0))
    assert isinstance(thrown, LongAck) and thrown.closed is False
    assert decode(from_hex("B4 30 00 7B")) == LongAck(0x30, 0)
    assert decode(power(True)) == Power(True)
    assert decode(power(False)) == Power(False)
    assert decode(frame([0x81])) == Busy()
