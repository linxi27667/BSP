"""Smoke new debug features against running web_rttview on :5000."""
import time
import socketio

HOST = 'http://127.0.0.1:5000'
sio = socketio.Client(reconnection=False)
errs = []


@sio.on('error')
def on_err(d):
    errs.append(d.get('message', d))


def wait(name, t=20):
    box = {'d': None, 'ok': False}

    def h(d):
        box['d'] = d
        box['ok'] = True

    sio.on(name, h)
    t0 = time.time()
    while not box['ok'] and time.time() - t0 < t:
        time.sleep(0.05)
    if not box['ok']:
        raise TimeoutError(name + ' errs=' + str(errs[-3:]))
    return box['d']


def main():
    sio.connect(HOST, transports=['websocket', 'polling'], wait_timeout=10)
    print('socket ok')
    sio.emit('probe_connect', {
        'type': 'jlink', 'mode': 'arm', 'speed': 4000,
        'address': 'auto', 'channel': 0,
    })
    c = wait('connected', 30)
    print('connected', c.get('rtt_found'), c.get('rtt_addr'))

    sio.emit('target_info')
    info = wait('target_info', 10)
    print('target', info.get('core_type'), 'pc', info.get('pc'),
          'halted', info.get('halted'))

    sio.emit('cpu_halt')
    print('halt', wait('cpu_state', 5))
    sio.emit('cpu_step')
    print('step', wait('cpu_state', 5))

    addr = info.get('pc') or '0x0'
    sio.emit('disasm', {'addr': addr, 'count': 8})
    d = wait('disasm_data', 8)
    print('disasm', len(d.get('lines') or []), (d.get('lines') or [None])[0])

    sio.emit('mem_write', {'addr': '0x20001000', 'width': 32, 'value': '0xA5A5A5A5'})
    print('mem_write', wait('mem_write_done', 5))

    sio.emit('watch_start', {'items': [{'name': 'w', 'addr': '0x20001000', 'type': 'u32'}]})
    print('watch_started', wait('watch_started', 5))
    print('watch_data', wait('watch_data', 5))
    sio.emit('watch_stop')

    sio.emit('rtt_list_channels')
    try:
        ch = wait('rtt_channels', 10)
        print('up channels', ch.get('channels', {}).get('up'))
    except Exception as e:
        print('channels fail', e)

    sio.emit('cpu_go')
    print('go', wait('cpu_state', 5))
    sio.emit('probe_disconnect')
    wait('disconnected', 5)
    sio.disconnect()
    print('ALL_FEATURE_SMOKE_OK errors=', errs)
    return 0 if not errs else 1


if __name__ == '__main__':
    raise SystemExit(main())
