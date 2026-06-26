"""SWO/ITM trace decoder for ARM Cortex-M debug trace.

Decodes SWO (Serial Wire Output) data stream into structured events:
- ITM stimulus port data (debug printf output)
- DWT PC sampling (statistical profiling)
- DWT exception trace (IRQ entry/exit tracking)

SWO Packet Format (first byte):
  ITM:  bits[7:3]=port(5 bits), bits[2:1]=size(01=1B,10=2B,11=4B)
        Payload bytes are raw data (no continuation encoding).
  DWT:  bits[7:5]=001, bits[4:3]=type(00=PC,01=EXC)
        Payload uses continuation encoding: bit[0]=1 means more bytes follow.
  Sync: 0x00 repeated 5+ times, then 0x80
"""

from dataclasses import dataclass


@dataclass
class ITMFrame:
    """An ITM stimulus port packet."""
    port: int
    data: bytes
    timestamp: int = 0


@dataclass
class PCsample:
    """A DWT PC sample packet."""
    pc: int
    timestamp: int = 0


@dataclass
class ExceptionEvent:
    """A DWT exception trace packet."""
    exception_number: int
    event_type: str  # 'entry' or 'exit'
    timestamp: int = 0


class SWODecoder:
    """Stateful SWO data stream decoder.

    Usage::

        decoder = SWODecoder()
        decoder.on_itm_port(0, lambda frame: print(frame.data))
        decoder.on_pc_sample(lambda s: print(f"PC=0x{s.pc:08X}"))
        decoder.feed(raw_swo_bytes)
    """

    # SWO packet type identifiers (bits[7:5] of first byte)
    _PKT_ITM = 0b000  # ITM stimulus packet
    _PKT_DWT = 0b001  # DWT hardware packet
    _PKT_SYNC = 0b010  # Sync (not used as ID, detected by 0x00 pattern)

    def __init__(self):
        self._buffer = bytearray()
        self._itm_handlers = {}   # port -> handler(ITMFrame)
        self._pc_handler = None   # handler(PCsample)
        self._exc_handler = None  # handler(ExceptionEvent)
        self._timestamp = 0

        self.stats = {
            'itm': 0,
            'dwt_pc': 0,
            'dwt_exc': 0,
            'sync': 0,
            'unknown': 0,
            'errors': 0,
        }

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def on_itm_port(self, port: int, handler):
        """Register a callback for ITM stimulus port data.

        Parameters
        ----------
        port : int
            ITM port number (0-31).
        handler : callable
            Called with ``(ITMFrame)`` when data arrives on this port.
        """
        self._itm_handlers[port] = handler

    def on_pc_sample(self, handler):
        """Register a callback for DWT PC samples.

        Parameters
        ----------
        handler : callable
            Called with ``(PCsample)`` on each PC sample packet.
        """
        self._pc_handler = handler

    def on_exception(self, handler):
        """Register a callback for DWT exception events.

        Parameters
        ----------
        handler : callable
            Called with ``(ExceptionEvent)`` on each exception entry/exit.
        """
        self._exc_handler = handler

    # ------------------------------------------------------------------
    # Feed
    # ------------------------------------------------------------------

    def feed(self, data: bytes):
        """Feed raw SWO data bytes into the decoder.

        Parameters
        ----------
        data : bytes
            Raw bytes from the SWO pin (e.g. from ``probe.swo_read()``).
        """
        if not data:
            return
        self._buffer.extend(data)
        self._process_buffer()

    # ------------------------------------------------------------------
    # Internal: buffer processing
    # ------------------------------------------------------------------

    def _process_buffer(self):
        """Consume all complete packets from the internal buffer."""
        while len(self._buffer) > 0:
            header = self._buffer[0]

            # Skip sync bytes (0x00 padding before sync packet 0x80)
            if header == 0x00:
                self._buffer.pop(0)
                continue

            # Sync packet: 0x80 after one or more 0x00 bytes
            if header == 0x80:
                self._buffer.pop(0)
                self.stats['sync'] += 1
                continue

            pkt_type = (header >> 5) & 0x07

            if pkt_type == self._PKT_ITM:
                consumed = self._decode_itm()
                # _decode_itm handles its own buffer cleanup
            elif pkt_type == self._PKT_DWT:
                consumed = self._decode_dwt()
                if consumed > 0:
                    del self._buffer[:consumed]
            else:
                # Unknown packet type — skip one byte to avoid infinite loop
                self._buffer.pop(0)
                self.stats['unknown'] += 1
                continue

            if consumed <= 0:
                # Incomplete packet — wait for more data
                break

    # ------------------------------------------------------------------
    # Internal: ITM stimulus packet
    # ------------------------------------------------------------------

    def _decode_itm(self) -> int:
        """Decode an ITM stimulus packet from the buffer.

        Header byte: bits[7:3]=port, bits[2:1]=size, bit[0]=reserved.
        Payload bytes are raw data (not continuation-encoded).

        Returns the number of bytes consumed, or 0 if the packet is
        incomplete (not enough data in buffer).
        """
        if len(self._buffer) < 2:
            return 0

        header = self._buffer[0]
        port = (header >> 3) & 0x1F
        size_code = (header >> 1) & 0x03  # bits[2:1]: 01=1B, 10=2B, 11=4B

        if size_code == 0:
            # Reserved — skip header
            self._buffer.pop(0)
            return 1

        # Map size code to actual byte count: 1->1, 2->2, 3->4
        payload_size = {1: 1, 2: 2, 3: 4}[size_code]

        # Need: header + payload_size bytes minimum
        if len(self._buffer) < 1 + payload_size:
            return 0

        # Extract payload bytes (raw data, no continuation bit stripping)
        payload = bytes(self._buffer[1:1 + payload_size])
        consumed = 1 + payload_size

        del self._buffer[:consumed]
        self.stats['itm'] += 1

        frame = ITMFrame(port=port, data=payload, timestamp=self._timestamp)
        handler = self._itm_handlers.get(port)
        if handler:
            try:
                handler(frame)
            except Exception:
                self.stats['errors'] += 1

        return consumed

    # ------------------------------------------------------------------
    # Internal: DWT hardware packet
    # ------------------------------------------------------------------

    def _decode_dwt(self) -> int:
        """Decode a DWT hardware packet (PC sample or exception trace).

        Returns the number of bytes consumed, or 0 if incomplete.
        """
        if len(self._buffer) < 2:
            return 0

        header = self._buffer[0]
        dwt_type = (header >> 3) & 0x03

        # Read payload bytes using continuation bit protocol.
        # Start from byte index 1 (first payload byte).
        payload, consumed = self._read_payload(1)
        if consumed == 0:
            return 0  # incomplete

        try:
            if dwt_type == 0b00:
                self._handle_pc_sample(payload)
            elif dwt_type == 0b01:
                self._handle_exception(payload)
            else:
                self.stats['unknown'] += 1
        except Exception:
            self.stats['errors'] += 1

        return consumed

    def _read_payload(self, start: int):
        """Read variable-length payload using continuation bits.

        Returns ``(payload_bytes, total_bytes_consumed)`` or ``(b'', 0)``
        if the packet is incomplete.
        """
        payload = bytearray()
        idx = start
        while idx < len(self._buffer):
            byte = self._buffer[idx]
            payload.append(byte)
            idx += 1
            if (byte & 0x01) == 0:
                # Last byte — no continuation
                return bytes(payload), idx
        # Reached end of buffer without finding a terminating byte
        return b'', 0

    @staticmethod
    def _decode_varint(payload: bytes) -> int:
        """Decode a continuation-bit-encoded variable integer.

        Each byte contributes 7 data bits in bits[7:1]; bit[0] is the
        continuation flag (already consumed by ``_read_payload``).
        """
        value = 0
        for i, b in enumerate(payload[:8]):
            value |= ((b >> 1) & 0x7F) << (i * 7)
        return value

    def _handle_pc_sample(self, payload: bytes):
        """Process a DWT PC sample packet."""
        if len(payload) < 2:
            return
        # Continuation encoding: data in bits[7:1] of each byte (7 bits each).
        # Strip bit[0] then right-shift by 1 to extract the 7-bit data field.
        pc = self._decode_varint(payload)

        self.stats['dwt_pc'] += 1
        sample = PCsample(pc=pc, timestamp=self._timestamp)
        if self._pc_handler:
            try:
                self._pc_handler(sample)
            except Exception:
                self.stats['errors'] += 1

    def _handle_exception(self, payload: bytes):
        """Process a DWT exception trace packet."""
        if len(payload) < 2:
            return
        # Continuation encoding: reassemble variable-length integer
        value = self._decode_varint(payload)

        # Exception number in lower bits, event type in bit 12
        exc_num = value & 0x1FF  # 9 bits for exception number (0-511)
        event_type = 'exit' if (value >> 12) & 1 else 'entry'

        self.stats['dwt_exc'] += 1
        event = ExceptionEvent(
            exception_number=exc_num,
            event_type=event_type,
            timestamp=self._timestamp,
        )
        if self._exc_handler:
            try:
                self._exc_handler(event)
            except Exception:
                self.stats['errors'] += 1


# ------------------------------------------------------------------
# Helper: decode ITM frame to string
# ------------------------------------------------------------------

def decode_itm_string(frame: ITMFrame) -> str:
    """Convert an ITM frame's data bytes to a printable ASCII string.

    Non-printable bytes are replaced with ``'.'``.

    Parameters
    ----------
    frame : ITMFrame
        An ITM stimulus frame.

    Returns
    -------
    str
        Decoded ASCII string.
    """
    chars = []
    for b in frame.data:
        if 0x20 <= b < 0x7F:
            chars.append(chr(b))
        elif b == 0x0A:
            chars.append('\n')
        elif b == 0x0D:
            pass  # skip CR
        else:
            chars.append('.')
    return ''.join(chars)
