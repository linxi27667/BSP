/**
 * Compatibility shim — full implementation lives in webusb_rtt.js
 * (ST-Link + CMSIS-DAP). Kept so old <script src=webusb_stlink_rtt.js> still works.
 */
(function (g) {
  'use strict';
  if (g.WebUsbStlinkRtt && g.WebUsbRtt) return;
  // If loaded alone, pull sibling script synchronously when possible
  if (!g.WebUsbRtt) {
    try {
      var s = document.currentScript && document.currentScript.src;
      if (s) {
        var u = s.replace(/webusb_stlink_rtt\.js([\?#].*)?$/, 'webusb_rtt.js');
        // async load fallback — page should include webusb_rtt.js first
        console.warn('[WebUSB] load webusb_rtt.js before webusb_stlink_rtt.js');
      }
    } catch (e) {}
  }
})(typeof window !== 'undefined' ? window : globalThis);
