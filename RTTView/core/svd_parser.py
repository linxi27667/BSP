"""CMSIS-SVD parser for peripheral register definitions.

Parses .svd XML files into structured dataclasses representing
MCU devices, peripherals, registers, and bit fields.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Field:
    """A bit field within a register."""
    name: str
    description: str
    bit_offset: int
    bit_width: int
    access: str = ""

    @property
    def bit_mask(self) -> int:
        """Return the bitmask for this field (e.g. 0xFF for an 8-bit field)."""
        return ((1 << self.bit_width) - 1) << self.bit_offset

    def extract(self, reg_value: int) -> int:
        """Extract this field's value from a register value."""
        return (reg_value >> self.bit_offset) & ((1 << self.bit_width) - 1)

    def insert(self, reg_value: int, field_value: int) -> int:
        """Insert a field value into a register value, returning the new register value."""
        cleared = reg_value & ~self.bit_mask
        return cleared | ((field_value << self.bit_offset) & self.bit_mask)


@dataclass
class Register:
    """A peripheral register."""
    name: str
    description: str
    address_offset: int
    size: int  # bits
    access: str = ""
    reset_value: int = 0
    fields: List[Field] = field(default_factory=list)


@dataclass
class Peripheral:
    """A peripheral block containing registers."""
    name: str
    description: str
    base_address: int
    size: int = 32  # bits
    registers: List[Register] = field(default_factory=list)
    derived_from: Optional[str] = None

    def get_register(self, name: str) -> Optional[Register]:
        """Find a register by name (case-insensitive)."""
        name_upper = name.upper()
        for reg in self.registers:
            if reg.name.upper() == name_upper:
                return reg
        return None


@dataclass
class Device:
    """Top-level MCU device description."""
    name: str
    description: str
    cpu_name: str = ""
    address_unit_bits: int = 8
    width: int = 32
    peripherals: List[Peripheral] = field(default_factory=list)

    def get_peripheral(self, name: str) -> Optional[Peripheral]:
        """Find a peripheral by name (case-insensitive)."""
        name_upper = name.upper()
        for p in self.peripherals:
            if p.name.upper() == name_upper:
                return p
        return None

    def get_peripheral_at(self, address: int) -> Optional[Peripheral]:
        """Find the peripheral whose base_address matches the given address."""
        for p in self.peripherals:
            if p.base_address == address:
                return p
        return None


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _text(element: Optional[ET.Element], default: str = "") -> str:
    """Return stripped text content of an element, or *default* if None."""
    if element is None or element.text is None:
        return default
    return element.text.strip()


def _int(element: Optional[ET.Element], default: int = 0) -> int:
    """Parse an element's text as an integer.

    Handles: 0x-prefixed hex, bare hex digits (e.g. '00000010'), and decimal.
    """
    if element is None or element.text is None:
        return default
    text = element.text.strip()
    try:
        return int(text, 0)
    except ValueError:
        # Bare hex digits without 0x prefix
        return int(text, 16)


# ---------------------------------------------------------------------------
# Field parser
# ---------------------------------------------------------------------------

def _parse_field(el: ET.Element) -> Field:
    name = _text(el.find("name"))
    description = _text(el.find("description"))
    access = _text(el.find("access"))

    # Bit offset / width can be specified two ways:
    #   1) <bitOffset> + <bitWidth>
    #   2) <lsb> + <msb>
    bit_offset_el = el.find("bitOffset")
    bit_width_el = el.find("bitWidth")
    lsb_el = el.find("lsb")
    msb_el = el.find("msb")

    if bit_offset_el is not None and bit_width_el is not None:
        bit_offset = _int(bit_offset_el)
        bit_width = _int(bit_width_el)
    elif lsb_el is not None and msb_el is not None:
        lsb = _int(lsb_el)
        msb = _int(msb_el)
        bit_offset = lsb
        bit_width = msb - lsb + 1
    else:
        bit_offset = 0
        bit_width = 1

    return Field(
        name=name,
        description=description,
        bit_offset=bit_offset,
        bit_width=bit_width,
        access=access,
    )


# ---------------------------------------------------------------------------
# Register parser
# ---------------------------------------------------------------------------

def _parse_register(el: ET.Element) -> Register:
    name = _text(el.find("name"))
    description = _text(el.find("description"))
    address_offset = _int(el.find("addressOffset"))
    size_el = el.find("size")
    size = _int(size_el, 32)
    access = _text(el.find("access"))
    reset_value = _int(el.find("resetValue"))

    fields_el = el.find("fields")
    fields: List[Field] = []
    if fields_el is not None:
        for f_el in fields_el.findall("field"):
            fields.append(_parse_field(f_el))

    return Register(
        name=name,
        description=description,
        address_offset=address_offset,
        size=size,
        access=access,
        reset_value=reset_value,
        fields=fields,
    )


# ---------------------------------------------------------------------------
# Peripheral parser
# ---------------------------------------------------------------------------

def _parse_peripheral(el: ET.Element) -> Peripheral:
    name = _text(el.find("name"))
    description = _text(el.find("description"))
    base_address = _int(el.find("baseAddress"))
    size_el = el.find("size")
    size = _int(size_el, 32)
    derived_from = el.get("derivedFrom")

    registers_el = el.find("registers")
    registers: List[Register] = []
    if registers_el is not None:
        for r_el in registers_el.findall("register"):
            registers.append(_parse_register(r_el))

    return Peripheral(
        name=name,
        description=description,
        base_address=base_address,
        size=size,
        registers=registers,
        derived_from=derived_from,
    )


# ---------------------------------------------------------------------------
# Device parser (public API)
# ---------------------------------------------------------------------------

def parse_svd(path: str) -> Device:
    """Parse a CMSIS-SVD file and return a Device dataclass.

    Parameters
    ----------
    path : str
        File path to the .svd XML file.

    Returns
    -------
    Device
        Fully-populated device tree with peripherals, registers, and fields.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    name = _text(root.find("name"))
    description = _text(root.find("description"))

    # CPU info (optional block)
    cpu_el = root.find("cpu")
    cpu_name = _text(cpu_el.find("name")) if cpu_el is not None else ""

    address_unit_bits = _int(root.find("addressUnitBits"), 8)
    width = _int(root.find("width"), 32)

    peripherals: List[Peripheral] = []
    peripherals_el = root.find("peripherals")
    if peripherals_el is not None:
        for p_el in peripherals_el.findall("peripheral"):
            peripherals.append(_parse_peripheral(p_el))

    # Resolve derivedFrom: copy registers from parent when missing
    by_name = {p.name: p for p in peripherals}
    for p in peripherals:
        if p.derived_from and not p.registers:
            parent = by_name.get(p.derived_from)
            if parent:
                p.registers = parent.registers
                if p.size == 32:
                    p.size = parent.size

    return Device(
        name=name,
        description=description,
        cpu_name=cpu_name,
        address_unit_bits=address_unit_bits,
        width=width,
        peripherals=peripherals,
    )
