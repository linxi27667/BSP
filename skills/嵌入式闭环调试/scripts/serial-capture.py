#!/usr/bin/env python3
import argparse
import datetime as _dt
import os
import sys
import time

try:
    import serial
except Exception as exc:
    print(f"pyserial import failed: {exc}", file=sys.stderr)
    print("Run inside ESP-IDF export environment or install pyserial.", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture serial logs for embedded closed-loop debugging.")
    parser.add_argument("--port", required=True, help="Serial port, e.g. COM28")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--output", default=None)
    parser.add_argument("--reset-dtr", action="store_true", help="Pulse DTR/RTS before capture when supported")
    args = parser.parse_args()

    output = args.output
    if not output:
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = os.path.join("logs", f"serial_{args.port}_{stamp}.log")
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)

    deadline = time.time() + args.seconds
    with serial.Serial(args.port, args.baud, timeout=0.2) as ser, open(output, "wb") as f:
        if args.reset_dtr:
            try:
                ser.dtr = False
                ser.rts = True
                time.sleep(0.1)
                ser.dtr = True
                ser.rts = False
                time.sleep(0.2)
            except Exception:
                pass
        print(f"[serial-capture] port={args.port} baud={args.baud} seconds={args.seconds} output={output}")
        while time.time() < deadline:
            data = ser.read(4096)
            if data:
                f.write(data)
                f.flush()
                try:
                    sys.stdout.write(data.decode("utf-8", errors="replace"))
                    sys.stdout.flush()
                except Exception:
                    pass
    print(f"\n[serial-capture] saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
