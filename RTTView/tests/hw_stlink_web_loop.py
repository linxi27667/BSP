"""Web closed-loop over ST-Link (CLI backend)."""
import socketio
import time
import sys

HOST = 'http://127.0.0.1:5000'
sio = socketio.Client(reconnection=False)
errs = []
got = {'n': 0, 'text': ''}


@sio.on('error')
def on_err(d):
    errs.append(d.get('message', d))
    print('ERR', d)


@sio.on('rtt_data')
def on_rtt(d):
    t = d.get('text') or ''
    if t:
        got['n'] += 1
        got['text'] += t
        if got['n'] <= 6:
            print('RTT', repr(t[:120]))


def wait(name, t=90):
    box = {'d': None, 'ok': False}

    def h(d):
        box['d'] = d
        box['ok'] = True

    sio.on(name, h)
    t0 = time.time()
    while not box['ok'] and time.time() - t0 < t:
        time.sleep(0.05)
    if not box['ok']:
        raise TimeoutError(f'{name} errs={errs[-3:]}')
    return box['d']


def main():
    sio.connect(HOST, transports=['websocket', 'polling'], wait_timeout=10)
    print('ws ok')

    sio.emit('probe_detect')
    pl = wait('probe_list', 15)
    st = None
    for p in pl.get('probes', []):
        print(' -', p.get('name'), p.get('type'))
        if p.get('type') == 'stlink' and st is None:
            st = p
    if not st:
        print('NO STLINK')
        return 2

    print('connect stlink...')
    sio.emit('probe_connect', {
        'type': 'stlink',
        'index': st.get('index', 0) or 0,
        'mode': 'arm',
        'speed': 4000,
        'address': 'auto',
        'channel': 0,
    })
    c = wait('connected', 180)
    print('connected', c)

    if not c.get('rtt_found'):
        sio.emit('rtt_rescan', {'address': 'auto', 'channel': 0})
        f = wait('rtt_found', 90)
        print('rescan', f)

    sio.emit('rtt_start', {'encoding': 'auto'})
    wait('rtt_started', 15)
    t0 = time.time()
    while time.time() - t0 < 20 and got['n'] == 0:
        time.sleep(0.2)
    print('packets', got['n'])

    sio.emit('mem_read', {'addr': '0x20000000', 'size': 64})
    try:
        m = wait('mem_data', 45)
        print('mem ok', m.get('addr'), 'lines', len(m.get('lines') or []))
    except Exception as e:
        print('mem fail', e)

    sio.emit('mcu_reset', {'halt_after': False})
    try:
        r = wait('mcu_reset_done', 90)
        print('reset', r)
    except Exception as e:
        print('reset fail', e)

    pre = got['n']
    t0 = time.time()
    while time.time() - t0 < 15 and got['n'] == pre:
        time.sleep(0.2)
    print('post-reset packets', got['n'] - pre)

    sio.emit('probe_disconnect')
    try:
        wait('disconnected', 10)
    except Exception:
        pass
    sio.disconnect()
    ok = got['n'] > 0
    print('RESULT', 'OK' if ok else 'FAIL', 'errs', errs)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
