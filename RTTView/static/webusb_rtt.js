/**
 * Browser WebUSB SEGGER RTT — ST-Link V2 + CMSIS-DAP (MIT).
 * One click → OS USB picker → multi-region RTT scan → live log.
 * Requires secure context (https or localhost). Windows often needs WinUSB (Zadig).
 * J-Link is not WebUSB here — use 本机 USB / 远程代理 (pylink).
 */
(function (global) {
  'use strict';

  // ─── helpers ────────────────────────────────────────────────────────────
  function le32(n) {
    const b = new Uint8Array(4);
    new DataView(b.buffer).setUint32(0, n >>> 0, true);
    return b;
  }
  function u32(dv, off) {
    return dv.getUint32(off, true) >>> 0;
  }
  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }
  function toHex(n) {
    return '0x' + (n >>> 0).toString(16);
  }

  const RTT_REGIONS = [
    [0x20000000, 0x10000],
    [0x20000000, 0x40000],
    [0x20000000, 0x80000],
    [0x24000000, 0x20000],
    [0x30000000, 0x20000],
    [0x10000000, 0x10000],
    [0x20200000, 0x20000],
  ];
  const NEEDLE = [0x53, 0x45, 0x47, 0x47, 0x45, 0x52, 0x20, 0x52, 0x54, 0x54]; // SEGGER RTT

  // ─── ST-Link backend ────────────────────────────────────────────────────
  const ST_VID = 0x0483;
  const ST_PIDS = [0x3748, 0x374b, 0x3752, 0x374e, 0x374f, 0x3753, 0x3754];
  const ST = {
    CMD: 0xf2,
    GET_VERSION: 0xf1,
    GET_MODE: 0xf5,
    DFU: 0xf3,
    EXIT: 0x21,
    ENTER_V2: 0x30,
    ENTER_SWD: 0xa3,
    RUN: 0x09,
    FORCEDEBUG: 0x02,
    RESETSYS: 0x03,
    RMEM32: 0x07,
    WMEM32: 0x08,
    RMEM8: 0x0c,
    WMEM8: 0x0d,
    READCOREID: 0x22,
  };

  class StlinkBackend {
    constructor(device) {
      this.device = device;
      this.epIn = 0x81;
      this.epOut = 0x01;
      this.iface = 0;
      this.name = 'ST-Link';
    }

    static filters() {
      return ST_PIDS.map((productId) => ({ vendorId: ST_VID, productId }));
    }

    static matches(dev) {
      return dev.vendorId === ST_VID && ST_PIDS.indexOf(dev.productId) >= 0;
    }

    async open() {
      await this.device.open();
      if (this.device.configuration === null) {
        await this.device.selectConfiguration(1);
      }
      let claimed = false;
      for (const conf of this.device.configurations) {
        for (const iface of conf.interfaces) {
          for (const alt of iface.alternates) {
            const bulkIn = alt.endpoints.find((e) => e.direction === 'in' && e.type === 'bulk');
            const bulkOut = alt.endpoints.find((e) => e.direction === 'out' && e.type === 'bulk');
            if (!bulkIn || !bulkOut) continue;
            try {
              if (this.device.configuration.configurationValue !== conf.configurationValue) {
                await this.device.selectConfiguration(conf.configurationValue);
              }
              await this.device.claimInterface(iface.interfaceNumber);
              await this.device.selectAlternateInterface(iface.interfaceNumber, alt.alternateSetting);
              this.epIn = bulkIn.endpointNumber;
              this.epOut = bulkOut.endpointNumber;
              this.iface = iface.interfaceNumber;
              claimed = true;
              break;
            } catch (e) {
              /* try next */
            }
          }
          if (claimed) break;
        }
        if (claimed) break;
      }
      if (!claimed) {
        await this.device.claimInterface(0);
        this.epIn = 1;
        this.epOut = 1;
      }
      await this._initSwd();
    }

    async close() {
      try {
        await this._cmd([ST.CMD, ST.EXIT], 2);
      } catch (e) {}
      try {
        await this.device.close();
      } catch (e) {}
    }

    async _cmd(bytes, rxLen) {
      const pkt = new Uint8Array(16);
      for (let i = 0; i < bytes.length && i < 16; i++) pkt[i] = bytes[i] & 0xff;
      await this.device.transferOut(this.epOut, pkt);
      if (!rxLen) return null;
      const r = await this.device.transferIn(this.epIn, rxLen);
      return new Uint8Array(r.data.buffer);
    }

    async _cmdWrite(bytes, data) {
      const pkt = new Uint8Array(16);
      for (let i = 0; i < bytes.length && i < 16; i++) pkt[i] = bytes[i] & 0xff;
      await this.device.transferOut(this.epOut, pkt);
      await this.device.transferOut(this.epOut, data);
      try {
        await this.device.transferIn(this.epIn, 2);
      } catch (e) {}
    }

    async _initSwd() {
      try {
        await this._cmd([ST.GET_VERSION], 6);
      } catch (e) {}
      try {
        const m = await this._cmd([ST.GET_MODE], 2);
        if (m && m[0] === 0) await this._cmd([ST.DFU, 0x07], 0);
      } catch (e) {}
      try {
        await this._cmd([ST.CMD, ST.EXIT], 2);
      } catch (e) {}
      await this._cmd([ST.CMD, ST.ENTER_V2, ST.ENTER_SWD], 2);
      try {
        await this._cmd([ST.CMD, ST.FORCEDEBUG], 2);
      } catch (e) {}
      try {
        await this._cmd([ST.CMD, ST.READCOREID], 4);
      } catch (e) {}
      try {
        await this._cmd([ST.CMD, ST.RUN], 2);
      } catch (e) {}
    }

    async readMem8(addr, count) {
      const out = new Uint8Array(count);
      let off = 0;
      while (off < count) {
        const n = Math.min(64, count - off);
        const a = (addr + off) >>> 0;
        const cmd = new Uint8Array(16);
        cmd[0] = ST.CMD;
        cmd[1] = ST.RMEM8;
        cmd[2] = n & 0xff;
        cmd[3] = 0;
        cmd[4] = a & 0xff;
        cmd[5] = (a >> 8) & 0xff;
        cmd[6] = (a >> 16) & 0xff;
        cmd[7] = (a >> 24) & 0xff;
        await this.device.transferOut(this.epOut, cmd);
        const r = await this.device.transferIn(this.epIn, n);
        const chunk = new Uint8Array(r.data.buffer);
        out.set(chunk.subarray(0, n), off);
        off += n;
      }
      return out;
    }

    async writeU32(addr, val) {
      const a = addr >>> 0;
      const cmd = new Uint8Array(16);
      cmd[0] = ST.CMD;
      cmd[1] = ST.WMEM32;
      cmd[2] = 4;
      cmd[3] = 0;
      cmd[4] = a & 0xff;
      cmd[5] = (a >> 8) & 0xff;
      cmd[6] = (a >> 16) & 0xff;
      cmd[7] = (a >> 24) & 0xff;
      await this._cmdWrite(cmd, le32(val));
    }

    async writeMem8(addr, data) {
      let off = 0;
      while (off < data.length) {
        const n = Math.min(64, data.length - off);
        const a = (addr + off) >>> 0;
        const cmd = new Uint8Array(16);
        cmd[0] = ST.CMD;
        cmd[1] = ST.WMEM8;
        cmd[2] = n & 0xff;
        cmd[3] = 0;
        cmd[4] = a & 0xff;
        cmd[5] = (a >> 8) & 0xff;
        cmd[6] = (a >> 16) & 0xff;
        cmd[7] = (a >> 24) & 0xff;
        await this._cmdWrite(cmd, data.subarray(off, off + n));
        off += n;
      }
    }

    async reset() {
      try {
        await this._cmd([ST.CMD, ST.RESETSYS], 2);
      } catch (e) {}
      try {
        await this._cmd([ST.CMD, ST.RUN], 2);
      } catch (e) {}
      await sleep(120);
    }
  }

  // ─── CMSIS-DAP backend (bulk / HID) ─────────────────────────────────────
  // Minimal SWD + AHB-AP mem R/W for RTT. Compatible with many DAPLink / HS probes.
  const DAP_VID_PIDS = [
    // ARM / DAPLink common
    { vendorId: 0x0d28, productId: 0x0204 },
    // Raspberry Pi / pico probe style often 0x2e8a
    { vendorId: 0x2e8a, productId: 0x000c },
    { vendorId: 0x2e8a, productId: 0x0004 },
    // NXP LPC-Link / MCU-Link
    { vendorId: 0x1fc9, productId: 0x0090 },
    { vendorId: 0x1fc9, productId: 0x0143 },
    // STM32 CMSIS-DAP clones sometimes 0x0483 other PIDs — still match class later
    { vendorId: 0xc251, productId: 0xf001 },
    { vendorId: 0xc251, productId: 0xf002 },
    // WCH-Link as CMSIS-DAP mode
    { vendorId: 0x1a86, productId: 0x8011 },
    // generic catch: user can still pick any device if we widen filters below
  ];

  const DAP = {
    INFO: 0x00,
    CONNECT: 0x02,
    DISCONNECT: 0x03,
    TRANSFER_CONFIGURE: 0x04,
    TRANSFER: 0x05,
    TRANSFER_BLOCK: 0x06,
    SWJ_CLOCK: 0x11,
    SWJ_SEQUENCE: 0x12,
    SWD_CONFIGURE: 0x13,
    TRANSFER_ABORT: 0x07,
  };

  // DP / AP
  const DP_IDCODE = 0x00;
  const DP_CTRLSTAT = 0x04;
  const DP_SELECT = 0x08;
  const DP_RDBUFF = 0x0c;
  const AP_CSW = 0x00;
  const AP_TAR = 0x04;
  const AP_DRW = 0x0c;

  class CmsisDapBackend {
    constructor(device) {
      this.device = device;
      this.epIn = 0x81;
      this.epOut = 0x01;
      this.iface = 0;
      this.packetSize = 64;
      this.mode = 'bulk'; // bulk | hid
      this.name = 'CMSIS-DAP';
      this._select = 0xffffffff;
    }

    static filters() {
      // Broad filter: any CMSIS-DAP-ish VID/PID + class-less catch via empty filters fallback
      return DAP_VID_PIDS.slice();
    }

    static matches(dev) {
      return DAP_VID_PIDS.some((f) => f.vendorId === dev.vendorId && f.productId === dev.productId);
    }

    async open() {
      await this.device.open();
      if (this.device.configuration === null) {
        await this.device.selectConfiguration(1);
      }
      let claimed = false;
      for (const conf of this.device.configurations) {
        for (const iface of conf.interfaces) {
          for (const alt of iface.alternates) {
            const bulkIn = alt.endpoints.find((e) => e.direction === 'in' && e.type === 'bulk');
            const bulkOut = alt.endpoints.find((e) => e.direction === 'out' && e.type === 'bulk');
            const intIn = alt.endpoints.find((e) => e.direction === 'in' && e.type === 'interrupt');
            const intOut = alt.endpoints.find((e) => e.direction === 'out' && e.type === 'interrupt');
            const useIn = bulkIn || intIn;
            const useOut = bulkOut || intOut;
            if (!useIn || !useOut) continue;
            try {
              if (this.device.configuration.configurationValue !== conf.configurationValue) {
                await this.device.selectConfiguration(conf.configurationValue);
              }
              await this.device.claimInterface(iface.interfaceNumber);
              await this.device.selectAlternateInterface(iface.interfaceNumber, alt.alternateSetting);
              this.epIn = useIn.endpointNumber;
              this.epOut = useOut.endpointNumber;
              this.iface = iface.interfaceNumber;
              this.packetSize = useIn.packetSize || 64;
              this.mode = bulkIn ? 'bulk' : 'hid';
              claimed = true;
              break;
            } catch (e) {
              /* next */
            }
          }
          if (claimed) break;
        }
        if (claimed) break;
      }
      if (!claimed) throw new Error('无法 claim CMSIS-DAP 接口（可能被系统占用，Windows 可试 Zadig WinUSB）');

      // Identify
      try {
        const info = await this._cmd(new Uint8Array([DAP.INFO, 0x01])); // vendor
        if (info && info[1] > 0) {
          const s = String.fromCharCode.apply(null, Array.from(info.subarray(2, 2 + info[1])));
          if (s) this.name = 'CMSIS-DAP · ' + s.trim();
        }
      } catch (e) {}

      await this._swdConnect();
    }

    async close() {
      try {
        await this._cmd(new Uint8Array([DAP.DISCONNECT]));
      } catch (e) {}
      try {
        await this.device.close();
      } catch (e) {}
    }

    async _cmd(req) {
      const pkt = new Uint8Array(this.packetSize);
      pkt.set(req.subarray(0, Math.min(req.length, this.packetSize)));
      await this.device.transferOut(this.epOut, pkt);
      const r = await this.device.transferIn(this.epIn, this.packetSize);
      return new Uint8Array(r.data.buffer);
    }

    async _swdConnect() {
      // clock ~1MHz
      const clk = new Uint8Array(5);
      clk[0] = DAP.SWJ_CLOCK;
      new DataView(clk.buffer).setUint32(1, 1000000, true);
      await this._cmd(clk);
      await this._cmd(new Uint8Array([DAP.SWD_CONFIGURE, 0x00]));
      // line reset + JTAG→SWD
      const seq = new Uint8Array(1 + 1 + 8);
      seq[0] = DAP.SWJ_SEQUENCE;
      seq[1] = 51; // bits
      // 50+ clocks high then 0xE79E
      seq[2] = 0xff;
      seq[3] = 0xff;
      seq[4] = 0xff;
      seq[5] = 0xff;
      seq[6] = 0xff;
      seq[7] = 0xff;
      seq[8] = 0x7b; // partial — enough for many probes; transfer will re-sync
      try {
        await this._cmd(seq);
      } catch (e) {}
      const conn = await this._cmd(new Uint8Array([DAP.CONNECT, 1])); // SWD
      if (conn[1] === 0) throw new Error('CMSIS-DAP 无法进入 SWD');
      await this._cmd(new Uint8Array([DAP.TRANSFER_CONFIGURE, 0, 64, 0, 0]));
      // power up debug
      await this._writeDp(DP_CTRLSTAT, 0x50000000);
      await sleep(10);
      await this._writeDp(DP_CTRLSTAT, 0x50000000);
      // CSW 32-bit
      await this._writeAp(AP_CSW, 0x23000002);
    }

    async _transfer(reqBytes) {
      // reqBytes: [DAP_Transfer, dap_index, count, ...req]
      const rsp = await this._cmd(reqBytes);
      // rsp: cmd, count, response status, data...
      if (rsp[2] & 0x08) throw new Error('DAP transfer FAULT');
      if (!(rsp[2] & 0x01)) throw new Error('DAP transfer no ACK');
      return rsp;
    }

    async _writeDp(reg, val) {
      // request: A[3:2] | RnW=0 | APnDP=0
      const req = 0x00 | ((reg & 0x0c) >> 2);
      const pkt = new Uint8Array(8);
      pkt[0] = DAP.TRANSFER;
      pkt[1] = 0;
      pkt[2] = 1;
      pkt[3] = req;
      new DataView(pkt.buffer).setUint32(4, val >>> 0, true);
      await this._transfer(pkt);
    }

    async _readDp(reg) {
      const req = 0x02 | ((reg & 0x0c) >> 2); // RnW
      const pkt = new Uint8Array(4);
      pkt[0] = DAP.TRANSFER;
      pkt[1] = 0;
      pkt[2] = 1;
      pkt[3] = req;
      const rsp = await this._transfer(pkt);
      return u32(new DataView(rsp.buffer, rsp.byteOffset, rsp.byteLength), 3);
    }

    async _selectAp(apSel, bank) {
      const v = ((apSel & 0xff) << 24) | ((bank & 0xf) << 4);
      if (v === this._select) return;
      await this._writeDp(DP_SELECT, v);
      this._select = v;
    }

    async _writeAp(reg, val) {
      await this._selectAp(0, (reg >> 4) & 0xf);
      const req = 0x01 | ((reg & 0x0c) >> 2); // APnDP=1 write
      const pkt = new Uint8Array(8);
      pkt[0] = DAP.TRANSFER;
      pkt[1] = 0;
      pkt[2] = 1;
      pkt[3] = req;
      new DataView(pkt.buffer).setUint32(4, val >>> 0, true);
      await this._transfer(pkt);
    }

    async _readAp(reg) {
      await this._selectAp(0, (reg >> 4) & 0xf);
      const req = 0x03 | ((reg & 0x0c) >> 2); // AP read
      const pkt = new Uint8Array(4);
      pkt[0] = DAP.TRANSFER;
      pkt[1] = 0;
      pkt[2] = 1;
      pkt[3] = req;
      await this._transfer(pkt);
      // posted — read RDBUFF
      return await this._readDp(DP_RDBUFF);
    }

    async readMem8(addr, count) {
      // Use 32-bit aligned reads when possible for speed
      const out = new Uint8Array(count);
      let off = 0;
      // unaligned head
      while (off < count && ((addr + off) & 3) !== 0) {
        await this._writeAp(AP_CSW, 0x23000000); // 8-bit
        await this._writeAp(AP_TAR, (addr + off) >>> 0);
        const w = await this._readAp(AP_DRW);
        out[off] = (w >>> (8 * ((addr + off) & 3))) & 0xff;
        off++;
      }
      await this._writeAp(AP_CSW, 0x23000002); // 32-bit
      while (off + 4 <= count) {
        await this._writeAp(AP_TAR, (addr + off) >>> 0);
        const w = await this._readAp(AP_DRW);
        out[off] = w & 0xff;
        out[off + 1] = (w >> 8) & 0xff;
        out[off + 2] = (w >> 16) & 0xff;
        out[off + 3] = (w >> 24) & 0xff;
        off += 4;
      }
      while (off < count) {
        await this._writeAp(AP_CSW, 0x23000000);
        await this._writeAp(AP_TAR, (addr + off) >>> 0);
        const w = await this._readAp(AP_DRW);
        out[off] = (w >>> (8 * ((addr + off) & 3))) & 0xff;
        off++;
      }
      await this._writeAp(AP_CSW, 0x23000002);
      return out;
    }

    async writeU32(addr, val) {
      await this._writeAp(AP_CSW, 0x23000002);
      await this._writeAp(AP_TAR, addr >>> 0);
      await this._writeAp(AP_DRW, val >>> 0);
    }

    async writeMem8(addr, data) {
      for (let i = 0; i < data.length; i++) {
        const a = (addr + i) >>> 0;
        await this._writeAp(AP_CSW, 0x23000000);
        await this._writeAp(AP_TAR, a);
        const shift = (a & 3) * 8;
        await this._writeAp(AP_DRW, (data[i] & 0xff) << shift);
      }
      await this._writeAp(AP_CSW, 0x23000002);
    }

    async reset() {
      // NVIC AIRCR sysreset via mem
      try {
        await this.writeU32(0xe000ed0c, 0x05fa0004);
      } catch (e) {}
      await sleep(150);
      try {
        await this._swdConnect();
      } catch (e) {}
    }
  }

  // ─── High-level RTT client ──────────────────────────────────────────────
  class WebUsbRtt {
    constructor() {
      this.backend = null;
      this.device = null;
      this.running = false;
      this.cb = 0;
      this.aUp = 0;
      this.aDown = 0;
      this.channel = 0;
      this.onData = null;
      this.onStatus = null;
      this.kind = '';
    }

    supported() {
      return !!(navigator.usb && navigator.usb.requestDevice && window.isSecureContext);
    }

    unsupportedReason() {
      if (typeof navigator === 'undefined') return '非浏览器环境';
      if (!window.isSecureContext) {
        return (
          '当前页面不是安全上下文（远程 http 会禁用 WebUSB）。' +
          '请用 https://服务器 打开（启动加 --ssl），或本机 http://127.0.0.1'
        );
      }
      if (!navigator.usb || !navigator.usb.requestDevice) {
        return '当前浏览器不支持 WebUSB（请用 Chrome / Edge）';
      }
      return '';
    }

    _status(msg) {
      if (this.onStatus) this.onStatus(msg);
    }

    static allFilters() {
      // ST-Link + CMSIS-DAP. Also empty filter option via extra common PIDs.
      return StlinkBackend.filters().concat(CmsisDapBackend.filters());
    }

    async connect(opts) {
      opts = opts || {};
      const why = this.unsupportedReason();
      if (why) throw new Error(why);

      const filters = opts.filters || WebUsbRtt.allFilters();
      this._status('请选择调试器（ST-Link / CMSIS-DAP）…');
      let device;
      try {
        device = await navigator.usb.requestDevice({ filters: filters });
      } catch (e) {
        // user cancelled or no match — retry with no filter so user can pick any
        if (e && e.name === 'NotFoundError') {
          device = await navigator.usb.requestDevice({ filters: [] });
        } else {
          throw e;
        }
      }
      this.device = device;

      let Backend = null;
      if (StlinkBackend.matches(device)) Backend = StlinkBackend;
      else if (CmsisDapBackend.matches(device)) Backend = CmsisDapBackend;
      else if (device.vendorId === ST_VID) Backend = StlinkBackend;
      else Backend = CmsisDapBackend; // try DAP protocol for unknown CMSIS probes

      this.backend = new Backend(device);
      this.kind = Backend === StlinkBackend ? 'stlink' : 'daplink';
      await this.backend.open();
      this._status(this.backend.name + ' 已连接 (WebUSB)');
    }

    async disconnect() {
      this.running = false;
      if (this.backend) {
        try {
          await this.backend.close();
        } catch (e) {}
      }
      this.backend = null;
      this.device = null;
      this._status('已断开 WebUSB');
    }

    async findRtt(regions) {
      const list =
        regions ||
        RTT_REGIONS.map(function (r) {
          return { base: r[0], size: r[1] };
        });
      // Prefer smaller first-region scan already ordered
      for (let ri = 0; ri < list.length; ri++) {
        const base = list[ri].base >>> 0;
        const size = list[ri].size || 0x10000;
        this._status('扫描 RTT @ ' + toHex(base) + ' +' + toHex(size) + ' …');
        const step = 1024;
        for (let off = 0; off < size; off += step) {
          const n = Math.min(step + 16, size - off + 16);
          let chunk;
          try {
            chunk = await this.backend.readMem8(base + off, n);
          } catch (e) {
            break; // region not mapped — next region
          }
          for (let i = 0; i + 10 <= chunk.length; i++) {
            let ok = true;
            for (let k = 0; k < 10; k++) {
              if (chunk[i + k] !== NEEDLE[k]) {
                ok = false;
                break;
              }
            }
            if (ok) {
              this.cb = (base + off + i) >>> 0;
              // aUp[ch] after acID[16]+MaxUp+MaxDown = 24, each ring 24 bytes
              const ch = this.channel || 0;
              this.aUp = (this.cb + 24 + 24 * ch) >>> 0;
              // MaxNumUpBuffers at +16 — read for down offset
              try {
                const hdr = await this.backend.readMem8(this.cb + 16, 8);
                const dv = new DataView(hdr.buffer, hdr.byteOffset, hdr.byteLength);
                const maxUp = u32(dv, 0) || 3;
                const maxDown = u32(dv, 4) || 3;
                this.aDown = (this.cb + 24 + 24 * maxUp + 24 * ch) >>> 0;
                if (ch >= maxUp) throw new Error('channel ' + ch + ' >= MaxUp ' + maxUp);
              } catch (e) {
                this.aDown = (this.cb + 24 + 24 * 3 + 24 * ch) >>> 0;
              }
              return this.cb;
            }
          }
        }
      }
      throw new Error('未找到 SEGGER RTT 控制块（已扫常见 SRAM 区）');
    }

    async pollOnce() {
      const desc = await this.backend.readMem8(this.aUp, 24);
      const dv = new DataView(desc.buffer, desc.byteOffset, desc.byteLength);
      const pBuffer = u32(dv, 4);
      const size = u32(dv, 8);
      const wr = u32(dv, 12);
      const rd = u32(dv, 16);
      if (!(size > 0 && size <= 1024 * 1024 && wr < size && rd < size && pBuffer)) {
        throw new Error('RTT ring invalid');
      }
      if (rd === wr) return new Uint8Array(0);
      let cnt;
      if (rd < wr) cnt = wr - rd;
      else cnt = size - rd; // first segment only; next poll gets wrap
      cnt = Math.min(cnt, 1024);
      const payload = await this.backend.readMem8((pBuffer + rd) >>> 0, cnt);
      const newRd = (rd + cnt) % size;
      await this.backend.writeU32((this.aUp + 16) >>> 0, newRd);
      return payload;
    }

    async write(data) {
      if (!this.aDown) throw new Error('no down buffer');
      const u8 = typeof data === 'string' ? new TextEncoder().encode(data) : data;
      if (!u8 || !u8.length) return 0;
      const desc = await this.backend.readMem8(this.aDown, 24);
      const dv = new DataView(desc.buffer, desc.byteOffset, desc.byteLength);
      const pBuffer = u32(dv, 4);
      const size = u32(dv, 8);
      let wr = u32(dv, 12);
      const rd = u32(dv, 16);
      if (!(size > 0 && wr < size && rd < size && pBuffer)) throw new Error('down ring invalid');
      let written = 0;
      while (written < u8.length) {
        const free = rd > wr ? rd - wr - 1 : size - wr + rd - 1;
        if (free <= 0) break;
        const n = Math.min(free, u8.length - written, size - wr);
        await this.backend.writeMem8((pBuffer + wr) >>> 0, u8.subarray(written, written + n));
        wr = (wr + n) % size;
        written += n;
        await this.backend.writeU32((this.aDown + 12) >>> 0, wr);
      }
      return written;
    }

    async startRtt(opts) {
      opts = opts || {};
      if (!this.backend) await this.connect(opts);
      this.channel = opts.channel || 0;
      this._status('扫描 RTT …');
      if (opts.base != null) {
        await this.findRtt([{ base: opts.base, size: opts.size || 0x10000 }]);
      } else {
        await this.findRtt();
      }
      this._status('RTT @ ' + toHex(this.cb) + ' (' + this.kind + ')');
      this.running = true;
      const self = this;
      const tick = async () => {
        while (self.running) {
          try {
            const data = await self.pollOnce();
            if (data && data.length && self.onData) self.onData(data);
          } catch (e) {
            self._status('RTT 错误: ' + (e.message || e));
            await sleep(200);
          }
          await sleep(15);
        }
      };
      this._loop = tick();
    }

    stopRtt() {
      this.running = false;
    }

    async reset() {
      if (!this.backend) return;
      await this.backend.reset();
      await sleep(100);
      await this.findRtt();
    }
  }

  // Back-compat alias used by older pages
  class WebUsbStlinkRtt extends WebUsbRtt {
    async connect(opts) {
      opts = opts || {};
      opts.filters = opts.filters || StlinkBackend.filters();
      return super.connect(opts);
    }
  }

  global.WebUsbRtt = WebUsbRtt;
  global.WebUsbStlinkRtt = WebUsbStlinkRtt;
})(typeof window !== 'undefined' ? window : globalThis);
