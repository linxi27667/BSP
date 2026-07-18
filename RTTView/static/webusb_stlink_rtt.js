/**
 * Browser WebUSB ST-Link V2 + SEGGER RTT (MIT, self-contained).
 * Click → OS USB picker → RTT logs. Probe must be on THIS PC (browser machine).
 * Windows: ST-Link needs WinUSB (Zadig) for WebUSB; stock ST driver blocks it.
 */
(function (global) {
  'use strict';

  const VID = 0x0483;
  const PIDS = [0x3748, 0x374b, 0x3752, 0x374e, 0x374f, 0x3753, 0x3754];
  const CMD = 0xF2;
  const GET_VERSION = 0xF1;
  const GET_MODE = 0xF5;
  const DFU = 0xF3;
  const EXIT = 0x21;
  const ENTER_V2 = 0x30;
  const ENTER_SWD = 0xA3;
  const RUN = 0x09;
  const FORCEDEBUG = 0x02;
  const RESETSYS = 0x03;
  const RMEM32 = 0x07;
  const WMEM32 = 0x08;
  const RMEM8 = 0x0C;
  const WMEM8 = 0x0D;
  const READCOREID = 0x22;
  const OK = 0x80;

  function le32(n) {
    const b = new Uint8Array(4);
    new DataView(b.buffer).setUint32(0, n >>> 0, true);
    return b;
  }
  function u32(dv, off) {
    return dv.getUint32(off, true) >>> 0;
  }
  function concat(a, b) {
    const o = new Uint8Array(a.length + b.length);
    o.set(a, 0);
    o.set(b, a.length);
    return o;
  }

  class WebUsbStlinkRtt {
    constructor() {
      this.device = null;
      this.epIn = 0x81;
      this.epOut = 0x01;
      this.running = false;
      this._loop = null;
      this.cb = 0;
      this.aUp = 0;
      this.onData = null;
      this.onStatus = null;
    }

    supported() {
      return !!(navigator.usb && navigator.usb.requestDevice && window.isSecureContext);
    }

    /** Why WebUSB is unavailable — empty string if OK. */
    unsupportedReason() {
      if (typeof navigator === 'undefined') return '非浏览器环境';
      if (!window.isSecureContext) {
        return (
          '当前页面不是安全上下文（http 远程 IP 会禁用 WebUSB）。' +
          '请用 https://服务器地址 打开，或本机用 http://127.0.0.1；' +
          '服务器加参数 --ssl'
        );
      }
      if (!navigator.usb || !navigator.usb.requestDevice) {
        return '当前浏览器不支持 WebUSB（请用 Chrome / Edge，不要用 iframe 无权限页）';
      }
      return '';
    }

    _status(msg) {
      if (this.onStatus) this.onStatus(msg);
    }

    async connect() {
      const why = this.unsupportedReason();
      if (why) throw new Error(why);
      const filters = PIDS.map((productId) => ({ vendorId: VID, productId }));
      this.device = await navigator.usb.requestDevice({ filters });
      await this.device.open();
      if (this.device.configuration === null) {
        await this.device.selectConfiguration(1);
      }
      // ST-Link/V2 often interface 0; V2-1 may use interface 0 bulk
      let claimed = false;
      for (const conf of this.device.configurations) {
        for (const iface of conf.interfaces) {
          for (const alt of iface.alternates) {
            const bulkIn = alt.endpoints.find((e) => e.direction === 'in' && e.type === 'bulk');
            const bulkOut = alt.endpoints.find((e) => e.direction === 'out' && e.type === 'bulk');
            if (bulkIn && bulkOut) {
              try {
                if (this.device.configuration.configurationValue !== conf.configurationValue) {
                  await this.device.selectConfiguration(conf.configurationValue);
                }
                await this.device.claimInterface(iface.interfaceNumber);
                await this.device.selectAlternateInterface(iface.interfaceNumber, alt.alternateSetting);
                this.epIn = bulkIn.endpointNumber;
                this.epOut = bulkOut.endpointNumber;
                claimed = true;
                break;
              } catch (e) {
                /* try next */
              }
            }
          }
          if (claimed) break;
        }
        if (claimed) break;
      }
      if (!claimed) {
        // fallback classic
        await this.device.claimInterface(0);
        this.epIn = 1;
        this.epOut = 1;
      }
      await this._initSwd();
      this._status('WebUSB ST-Link 已连接');
    }

    async disconnect() {
      this.running = false;
      if (this.device) {
        try {
          await this._cmd([CMD, EXIT], 2);
        } catch (e) {}
        try {
          await this.device.close();
        } catch (e) {}
      }
      this.device = null;
      this._status('已断开 WebUSB');
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
        await this._cmd([GET_VERSION], 6);
      } catch (e) {}
      try {
        const m = await this._cmd([GET_MODE], 2);
        if (m && m[0] === 0) {
          await this._cmd([DFU, 0x07], 0);
        }
      } catch (e) {}
      try {
        await this._cmd([CMD, EXIT], 2);
      } catch (e) {}
      await this._cmd([CMD, ENTER_V2, ENTER_SWD], 2);
      try {
        await this._cmd([CMD, FORCEDEBUG], 2);
      } catch (e) {}
      try {
        await this._cmd([CMD, READCOREID], 4);
      } catch (e) {}
      // leave core running for RTT
      try {
        await this._cmd([CMD, RUN], 2);
      } catch (e) {}
    }

    async readMem8(addr, count) {
      const out = new Uint8Array(count);
      let off = 0;
      while (off < count) {
        const n = Math.min(64, count - off);
        const a = (addr + off) >>> 0;
        const cmd = new Uint8Array(16);
        cmd[0] = CMD;
        cmd[1] = RMEM8;
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
      cmd[0] = CMD;
      cmd[1] = WMEM32;
      cmd[2] = 4;
      cmd[3] = 0;
      cmd[4] = a & 0xff;
      cmd[5] = (a >> 8) & 0xff;
      cmd[6] = (a >> 16) & 0xff;
      cmd[7] = (a >> 24) & 0xff;
      await this._cmdWrite(cmd, le32(val));
    }

    async findRtt(base, size) {
      base = (base >>> 0) || 0x20000000;
      size = size || 0x10000;
      const step = 1024;
      const needle = [0x53, 0x45, 0x47, 0x47, 0x45, 0x52, 0x20, 0x52, 0x54, 0x54]; // SEGGER RTT
      for (let off = 0; off < size; off += step) {
        const chunk = await this.readMem8(base + off, Math.min(step + 16, size - off + 16));
        for (let i = 0; i + 10 <= chunk.length; i++) {
          let ok = true;
          for (let k = 0; k < 10; k++) {
            if (chunk[i + k] !== needle[k]) {
              ok = false;
              break;
            }
          }
          if (ok) {
            this.cb = (base + off + i) >>> 0;
            // aUp[0] starts after acID[16] + MaxUp + MaxDown = 24
            this.aUp = (this.cb + 24) >>> 0;
            return this.cb;
          }
        }
      }
      throw new Error('未找到 SEGGER RTT 控制块');
    }

    async pollOnce() {
      // RingBuffer: sName,pBuffer,Size,WrOff,RdOff,Flags — 24 bytes
      const desc = await this.readMem8(this.aUp, 24);
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
      let wrap = false;
      if (rd < wr) {
        cnt = wr - rd;
      } else {
        cnt = size - rd;
        wrap = true;
      }
      cnt = Math.min(cnt, 1024);
      const payload = await this.readMem8((pBuffer + rd) >>> 0, cnt);
      let newRd = (rd + cnt) % size;
      await this.writeU32((this.aUp + 16) >>> 0, newRd);
      return payload;
    }

    async startRtt(opts) {
      opts = opts || {};
      if (!this.device) await this.connect();
      this._status('扫描 RTT ...');
      const base = opts.base != null ? opts.base : 0x20000000;
      const size = opts.size != null ? opts.size : 0x10000;
      const cb = await this.findRtt(base, size);
      this._status('RTT @ 0x' + cb.toString(16));
      this.running = true;
      const self = this;
      const tick = async () => {
        while (self.running) {
          try {
            const data = await self.pollOnce();
            if (data && data.length && self.onData) self.onData(data);
          } catch (e) {
            self._status('RTT 错误: ' + e.message);
            await new Promise((r) => setTimeout(r, 200));
          }
          await new Promise((r) => setTimeout(r, 20));
        }
      };
      this._loop = tick();
    }

    stopRtt() {
      this.running = false;
    }

    async reset() {
      try {
        await this._cmd([CMD, RESETSYS], 2);
      } catch (e) {}
      try {
        await this._cmd([CMD, RUN], 2);
      } catch (e) {}
      await new Promise((r) => setTimeout(r, 100));
      await this.findRtt(0x20000000, 0x10000);
    }
  }

  global.WebUsbStlinkRtt = WebUsbStlinkRtt;
})(typeof window !== 'undefined' ? window : globalThis);
