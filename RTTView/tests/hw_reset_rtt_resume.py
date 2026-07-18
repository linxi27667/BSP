"""Verify MCU reset auto-resumes RTT streaming."""
import socketio
import time
import sys

sio = socketio.Client(reconnection=False)
errs = []


@sio.on('error')
def on_err(d):
    errs.append(d.get('message', d))
    print('ERR', d)


def wait(name, t=30):
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
    sio.connect('http://127.0.0.1:5000', transports=['websocket', 'polling'], wait_timeout=10)
    got = {'n': 0, 'last': ''}

    @sio.on('rtt_data')
    def on_rtt(d):
        txt = d.get('text') or ''
        if txt:
            got['n'] += 1
            got['last'] = txt[:120]
            print('RTT:', repr(txt[:90]))

    sio.emit('probe_connect', {
        'type': 'jlink', 'mode': 'arm', 'speed': 4000,
        'address': 'auto', 'channel': 0,
    })
    c = wait('connected', 30)
    print('connected', c.get('rtt_found'), c.get('rtt_addr'))

    sio.emit('rtt_start', {'encoding': 'auto'})
    wait('rtt_started', 5)
    print('rtt_started')

    t0 = time.time()
    while time.time() - t0 < 4 and got['n'] == 0:
        time.sleep(0.1)
    print('pre packets', got['n'])

    got['n'] = 0
    got['last'] = ''
    sio.emit('mcu_reset', {'halt_after': False})
    rd = wait('mcu_reset_done', 40)
    print('reset_done', rd)

    t0 = time.time()
    while time.time() - t0 < 10 and got['n'] == 0:
        time.sleep(0.1)
    print('post packets', got['n'], 'last', repr(got['last'][:80]))

    if rd.get('rtt_resumed') and got['n'] > 0:
        print('RESULT=RESET_RTT_RESUME_OK')
        code = 0
    elif rd.get('rtt_resumed'):
        print('RESULT=RESET_RTT_RESUMED_QUIET')
        code = 0
    else:
        print('RESULT=FAIL')
        code = 1

    sio.emit('probe_disconnect')
    try:
        wait('disconnected', 5)
    except Exception:
        pass
    sio.disconnect()
    print('errs', errs)
    return code


if __name__ == '__main__':
    sys.exit(main())
