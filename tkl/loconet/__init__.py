"""LocoNet in TKL (#85, STUDIO-11, STUDIO-18, STUDIO-21, STUDIO-22, STV-11): level 3.

- messages: the messages TKL needs, encoded and decoded with their checksums (ported from
  cda-tkl's protocol.mjs and sv2.mjs).
- transports: LocoBuffer USB and BTLocoBridge, and the list of ports. The serial layer is thin:
  the pretend LocoNet takes its place in the tests.
- link: one LocoNet, a message at a time: each waits for its echo, and a switch request is a
  pulse, as JMRI sends it.
- objects: the station model's objects as the bus sees them: the address, the four states of
  Koppla in (STUDIO-17), the polarity and the switch's feedback (STUDIO-24).
- simulator: the pretend LocoNet at the message level (STUDIO-21), which Prova uses too.
- listen: Lyssna, behind Felsök: the last messages, decoded in Swedish.
- learning: Koppla in, learning by touching (STUDIO-04).
- service: the one LocoNet of a local TKL, between the bus, Koppla in and the interlocking.

LocoNet is local only: TKL in the cloud never opens a port (TKLMOLN-08). No code here names a
station (RS13).
"""
