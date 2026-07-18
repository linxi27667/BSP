"""Closed-loop hardware test against running Web RTTView Socket.IO API.

Usage:
  # terminal 1:
  python web_rttview.py --no-browser --port 5000
  # terminal 2:
  python tests/hw_web_closed_loop.py
"""
import os
import sys
import time
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

HOST = os.environ.get('RTTVIEW_URL', 'http://127.0.0.1:5000')

passed = 0
failed = 0
results = []


def ok(name, detail=''):
    global passed
    passed += 1
    msg = f'  PASS  {name}' + (f' — {detail}' if detail else '')
    print(msg)
    results.append(msg)


def fail(name, detail=''):
    global failed
    failed += 1
    msg = f'  FAIL  {name}' + (f' — {detail}' if detail else '')
    print(msg)
    results.append(msg)


def wait_event(sio, name, timeout=15):
    box = {'data': None, 'done': False}

    def handler(data):
        box['data'] = data
        box['done'] = True

    sio.on(name, handler)
    t0 = time.time()
    while not box['done'] and time.time() - t0 < timeout:
        time.sleep(0.05)
    sio.handlers['/'].pop(name, None)
    if not box['done']:
        raise TimeoutError(f'timeout waiting for {name}')
    return box['data']


def main():
    try:
        import socketio
    except ImportError:
        print('pip install python-socketio[client]')
        return 1

    print(f'=== Web closed-loop @ {HOST} ===\n')
    sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)

    errors = []

    @sio.on('error')
    def on_error(data):
        errors.append(data.get('message', str(data)))

    try:
        sio.connect(HOST, transports=['websocket', 'polling'], wait_timeout=10)
        ok('socket connect')
    except Exception as e:
        fail('socket connect', str(e))
        return 1

    # probe detect
    sio.emit('probe_detect')
    try:
        plist = wait_event(sio, 'probe_list', 5)
        names = [p.get('name') for p in plist.get('probes', [])]
        if any(p.get('type') == 'jlink' for p in plist.get('probes', [])):
            ok('probe_detect', ', '.join(names))
        else:
            fail('probe_detect', f'no jlink in {names}')
    except Exception as e:
        fail('probe_detect', str(e))

    # connect J-Link + auto RTT
    errors.clear()
    sio.emit('probe_connect', {
        'type': 'jlink',
        'mode': 'arm',
        'speed': 4000,
        'address': 'auto',
        'channel': 0,
    })
    try:
        cdata = wait_event(sio, 'connected', 30)
        if cdata.get('rtt_found'):
            ok('probe_connect + auto RTT', f"{cdata.get('rtt_addr')} mode={cdata.get('mode')}")
            rtt_addr = cdata.get('rtt_addr')
        else:
            fail('probe_connect RTT', cdata.get('rtt_error') or str(cdata))
            rtt_addr = None
    except Exception as e:
        # maybe error event instead
        if errors:
            fail('probe_connect', errors[-1])
        else:
            fail('probe_connect', str(e))
        rtt_addr = None

    # RTT start + wait data (may be quiet — don't hard-fail if no traffic)
    if rtt_addr:
        errors.clear()
        got_data = {'n': 0, 'text': ''}

        @sio.on('rtt_data')
        def on_rtt(data):
            if data.get('text'):
                got_data['n'] += 1
                got_data['text'] += data['text']

        sio.emit('rtt_start', {'encoding': 'auto'})
        try:
            wait_event(sio, 'rtt_started', 5)
            ok('rtt_start')
        except Exception as e:
            fail('rtt_start', str(e))

        # send a line
        sio.emit('rtt_send', {'data': 'ping_from_web_test\n', 'encoding': 'utf-8'})
        time.sleep(0.3)
        if not errors:
            ok('rtt_send')
        else:
            fail('rtt_send', errors[-1])

        # wait up to 3s for any uplink
        t0 = time.time()
        while time.time() - t0 < 3 and got_data['n'] == 0:
            time.sleep(0.1)
        if got_data['n']:
            snippet = got_data['text'][:80].replace('\n', '\\n')
            ok('rtt_data received', f'{got_data["n"]} packets, sample={snippet!r}')
        else:
            ok('rtt_data (idle OK)', 'no uplink in 3s — firmware may be quiet')

        sio.emit('rtt_stop')
        try:
            wait_event(sio, 'rtt_stopped', 3)
            ok('rtt_stop')
        except Exception as e:
            fail('rtt_stop', str(e))

        # rescan
        sio.emit('rtt_rescan', {'address': 'auto', 'channel': 0, 'auto_start': False})
        try:
            found = wait_event(sio, 'rtt_found', 20)
            ok('rtt_rescan', found.get('rtt_addr'))
        except Exception as e:
            if errors:
                fail('rtt_rescan', errors[-1])
            else:
                fail('rtt_rescan', str(e))

    # memory read
    errors.clear()
    sio.emit('mem_read', {'addr': '0x20000000', 'size': 64})
    try:
        m = wait_event(sio, 'mem_data', 10)
        raw = m.get('data') or m.get('bytes') or m.get('hex')
        if raw is not None or m.get('lines') or m.get('ascii') is not None:
            ok('mem_read', str(list(m.keys())[:6]))
        else:
            # accept any non-error payload
            if m:
                ok('mem_read', f'keys={list(m.keys())}')
            else:
                fail('mem_read', 'empty')
    except Exception as e:
        if errors:
            fail('mem_read', errors[-1])
        else:
            fail('mem_read', str(e))

    # core regs
    errors.clear()
    sio.emit('core_regs_start', {})
    try:
        wait_event(sio, 'core_regs_started', 5)
        rdata = wait_event(sio, 'core_regs_data', 10)
        regs = rdata.get('regs') or rdata.get('registers') or rdata
        ok('core_regs', f'keys={list(regs.keys())[:8] if isinstance(regs, dict) else type(regs)}')
    except Exception as e:
        if errors:
            fail('core_regs', errors[-1])
        else:
            fail('core_regs', str(e))
    sio.emit('core_regs_stop', {})

    # crash analyze (may work if target halted/fault — just must not crash server)
    errors.clear()
    sio.emit('crash_analyze', {})
    try:
        c = wait_event(sio, 'crash_data', 15)
        ok('crash_analyze', f'keys={list(c.keys())[:8]}')
    except Exception as e:
        if errors:
            # acceptable if target running and probe complains
            ok('crash_analyze (soft)', errors[-1][:80])
        else:
            fail('crash_analyze', str(e))

    # RTOS (may return empty tasks)
    errors.clear()
    sio.emit('rtos_start', {})
    try:
        wait_event(sio, 'rtos_started', 5)
        # optional data
        try:
            t = wait_event(sio, 'rtos_data', 5)
            n = len(t.get('tasks') or [])
            ok('rtos_start/data', f'{n} tasks')
        except TimeoutError:
            ok('rtos_start', 'no tasks in 5s (OK if not FreeRTOS)')
    except Exception as e:
        if errors:
            ok('rtos (soft)', errors[-1][:80])
        else:
            fail('rtos', str(e))
    sio.emit('rtos_stop', {})

    # oscilloscope short sample
    errors.clear()
    sio.emit('osc_start', {
        'channels': [{'addr': '0x20000000', 'type': 'uint32', 'scale': 1}],
        'timebase': 0.05,
        'trigger': 'free',
    })
    try:
        wait_event(sio, 'osc_started', 5)
        o = wait_event(sio, 'osc_data', 8)
        ok('oscilloscope', f'keys={list(o.keys())[:6]}')
    except Exception as e:
        if errors:
            fail('oscilloscope', errors[-1])
        else:
            fail('oscilloscope', str(e))
    sio.emit('osc_stop', {})

    # MCU reset
    errors.clear()
    sio.emit('mcu_reset')
    try:
        wait_event(sio, 'mcu_reset_done', 10)
        ok('mcu_reset')
    except Exception as e:
        if errors:
            fail('mcu_reset', errors[-1])
        else:
            fail('mcu_reset', str(e))

    # disconnect
    sio.emit('probe_disconnect')
    try:
        wait_event(sio, 'disconnected', 5)
        ok('probe_disconnect')
    except Exception as e:
        fail('probe_disconnect', str(e))

    try:
        sio.disconnect()
    except Exception:
        pass

    print()
    total = passed + failed
    print(f'Results: {passed}/{total} passed', end='')
    if failed:
        print(f', {failed} FAILED')
        return 1
    print(' — ALL OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
