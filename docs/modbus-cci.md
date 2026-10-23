# Modbus TCP interoperability — CCI Wally A+

## Hardware and scope

Target: Waveshare **ESP32-S3-POE-ETH-8DI-8DO**, SKU **32108** (not 8DI-8RO).
The device offers eight opto-isolated digital inputs, eight transistor outputs,
W5500 Ethernet, and an isolated RS485 interface.

This first change exposes **local** digital I/O as standard Modbus TCP bit
objects. Modbus RTU master polling already exists upstream, but its received
registers are **not yet bridged** into the TCP server register map.
Do not assume the current firmware is a complete multi-inverter RTU/TCP gateway.

## Connection

- Transport: Ethernet TCP, port **502**.
- Modbus TCP Unit Identifier: currently echoed but **not filtered**; use **1**
  for the CCI configuration. No device-specific Unit ID routing is implemented.
- Ethernet configuration: DHCP by default or static through the firmware UI.
  Set the static IP/mask/gateway for the actual CCI subnet; do not duplicate an
  existing IP address.

## Local Modbus map

**All addresses below are zero-based protocol offsets**, not printed Modbus
reference numbers. The first coil / discrete input has offset `0`.

| Modbus function | Offset | Count | Value | Access |
| --- | ---: | ---: | --- | --- |
| FC02 Read Discrete Inputs | 0..7 | 1..8 | DI1..DI8, one bit each | Read only |
| FC01 Read Coils | 0..7 | 1..8 | DO1..DO8 logical states | Read only |
| FC03 Read Holding Registers | 0 | 1 | DI bitmap (bit 0 = DI1) | Read |
| FC03 Read Holding Registers | 1 | 1 | DO bitmap (bit 0 = DO1) | Read |
| FC03 Read Holding Registers | 2..7 | 6 | Upstream diagnostic values | Read |
| FC04 Read Input Registers | 0..127 | up to 60 | Legacy alias of holding registers | Read |
| FC06/FC16 Write Holding Registers | 1 | 1 | DO bitmask | Write |

FC01/FC02 responses pack the first requested bit into bit 0 of the first
data byte (Modbus convention). Invalid DI/DO address ranges return exception
code `02` (illegal data address). The existing holding-register map and write
behavior are preserved from upstream for compatibility: **upstream also permits
writes to other holding addresses**. Do not expose port 502 to untrusted
networks, and do not write during initial read-only commissioning.

For CCI Wally A+ **Stati Impianto**, configure:

- `SINGLE_DISCRETE_IN` (FC02), offset `0` for DI1 through `7` for DI8.
- For a single bit, the logical mask is `0x0001`.
- Alternative: `UINT16_HOLDING` (FC03) at offset `0`, then extract bits 0..7.

The `diInv` firmware setting applies inversion to **all** eight inputs.
The interpretation of a real dry contact / active input needs to be checked
on the physical device before assigning meaning to open/closed states.

## Field commissioning (not yet performed)

1. Flash the firmware via USB with Arduino IDE, ensuring the correct ESP32-S3
   board profile, flash settings, and selected serial interface.
2. Configure Ethernet and verify the assigned IP. Enable Modbus TCP Server.
3. With all DI disconnected, record FC02 offsets 0..7 and FC03 offset 0.
4. Actuate one wired test DI at a time: verify the corresponding FC02 bit and
   FC03 bitmask. Check polarity and physical wiring.
5. Poll the device repeatedly **on the same TCP connection** and test a
   client disconnect/reconnect. Verify no unexplained timeouts.
6. Run `python tools/modbus_tcp_probe.py <device-ip>` from a PC on the
   Ethernet network. It performs *read-only* requests.
7. Configure CCI `SINGLE_DISCRETE_IN`, offset 0..7, and verify each status.
8. With RS485 later enabled, separately test RTU response time, timeout/fault
   handling, and exporting valid/fresh inverter values to TCP registers.

### Known limits inherited from upstream

- Modbus TCP currently serves **one active client at a time**.
- The RTU master implementation only polls holding registers (FC03), and
  its polling is synchronous; RTU timeouts can delay the main loop.
- No stale-data indication or RTU-to-TCP register allocation has been
  implemented yet.
- CAN GPIO defaults and the safe physical output behavior must be verified
  against the hardware documentation before enabling those features.

Hardware documentation:
https://docs.waveshare.com/ESP32-S3-POE-ETH-8DI-8DO

Original project:
https://github.com/logictechs/waveshare_lct_industrial_server

The original project is GPL-3.0; retain upstream notices and license.
