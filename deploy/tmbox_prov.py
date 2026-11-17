"""En låtsad TMBox över MQTT, för provet utan hårdvara (#74, BOX-24).

Boxen gör det firmware 0.9.3 gör: den säger hello med en ny session, väntar på sin första bild
och skickar livstecken, och visar raderna den får. CI kör den mot Pi-paketet med en riktig
Mosquitto; hemma går den att köra mot Pi:n bredvid de riktiga boxarna:

    python deploy/tmbox_prov.py --host trainmeet.local --box prov-1

Med --strict avslutas den med fel om ingen bild kommer inom tio sekunder.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

PREFIX = "tmbox/terminal/device/"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--box", default="prov-1", help="boxens id, 3–64 tecken")
    parser.add_argument("--seconds", type=float, default=10.0, help="hur länge boxen är med")
    parser.add_argument("--strict", action="store_true", help="fel om ingen bild kommer")
    args = parser.parse_args(argv)

    boot = secrets.token_hex(4)
    frames: list[dict[str, Any]] = []
    alive = threading.Event()
    first = threading.Event()

    def message(_client: Any, _data: Any, msg: mqtt.MQTTMessage) -> None:
        body = json.loads(msg.payload)
        if body.get("boot") != boot:
            return
        if msg.topic.endswith("/alive"):
            alive.set()
        elif msg.topic.endswith("/frame"):
            frames.append(body["frame"])
            first.set()
            print("\n".join(body["frame"]["lines"]), flush=True)
            print("-" * body["frame"]["cols"], flush=True)

    box = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=args.box,
        protocol=mqtt.MQTTv311,
        clean_session=True,
    )
    box.on_message = message
    box.connect(args.host, args.port, keepalive=10)
    box.loop_start()
    for leaf in ("alive", "frame", "ack"):
        box.subscribe(PREFIX + args.box + "/" + leaf, qos=1)
    time.sleep(0.3)
    hello = {
        "device_code": args.box,
        "model": "Låtsad TMBox",
        "firmware_version": "prov",
        "hardware_version": "prov",
        "boot": boot,
    }
    box.publish(PREFIX + args.box + "/hello", json.dumps(hello), qos=1)
    got_frame = first.wait(10)
    deadline = time.monotonic() + args.seconds
    n = 0
    while time.monotonic() < deadline:
        n += 1
        presence = {"nonce": f"{boot}-p{n}", "boot": boot}
        box.publish(PREFIX + args.box + "/presence", json.dumps(presence), qos=1)
        time.sleep(min(5.0, max(0.0, deadline - time.monotonic())))
    box.disconnect()
    box.loop_stop()
    if args.strict and not (got_frame and alive.is_set()):
        print("Ingen bild eller inget livstecken från hubben.", file=sys.stderr)
        return 1
    print(f"{len(frames)} bilder, livstecken: {'ja' if alive.is_set() else 'nej'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
