#!/usr/bin/env python3
"""Sanity checks for WebUSB static assets and auto-entry strings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_webusb_js_present():
    js = (ROOT / 'static' / 'webusb_rtt.js').read_text(encoding='utf-8')
    assert 'class WebUsbRtt' in js or 'WebUsbRtt' in js
    assert 'CMSIS-DAP' in js or 'CmsisDap' in js
    assert 'isSecureContext' in js
    assert 'SEGGER' in js
    assert '0x20000000' in js


def test_html_has_auto_entry():
    src = (ROOT / 'web_rttview.py').read_text(encoding='utf-8')
    assert 'value="auto"' in src
    assert 'webusb_rtt.js' in src
    assert 'connectAuto' in src
    assert '--ssl' in src


def test_shim_exists():
    assert (ROOT / 'static' / 'webusb_stlink_rtt.js').is_file()


if __name__ == '__main__':
    test_webusb_js_present()
    test_html_has_auto_entry()
    test_shim_exists()
    print('OK')
