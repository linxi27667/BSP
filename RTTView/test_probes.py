"""Smoke test for the probe system.

Verifies:
  1. All 4 probes register correctly when imported
  2. All probe classes inherit from DebugProbe
  3. create_probe() works for each probe type (construction without opening)
  4. Legacy imports (import jlink, import openocd) still work
  5. jlink.TIF.SWD == 1 still works
"""

import sys

passed = 0
failed = 0

def ok(name):
    global passed
    passed += 1
    print(f"  PASS  {name}")

def fail(name, reason=""):
    global failed
    failed += 1
    print(f"  FAIL  {name}: {reason}")


# ── 1. Import probe modules to trigger registration ──────────────

from probes.base import DebugProbe
from probes import list_probes, create_probe

from probes.jlink_probe import JLinkProbe
from probes.stlink_probe import STLinkProbe
from probes.daplink_probe import DAPLinkProbe
from probes.openocd_probe import OpenOCDProbe


# ── 2. All 4 probes registered ───────────────────────────────────

registry = list_probes()
expected = {'jlink', 'stlink', 'daplink', 'openocd'}

if set(registry.keys()) == expected:
    ok("All 4 probes registered: " + ", ".join(sorted(registry.keys())))
else:
    fail("Probe registration", f"expected {expected}, got {set(registry.keys())}")


# ── 3. All probe classes inherit from DebugProbe ─────────────────

for name in expected:
    cls = registry.get(name)
    if cls is not None and issubclass(cls, DebugProbe):
        ok(f"{name} is subclass of DebugProbe")
    else:
        fail(f"{name} inheritance", f"class={cls}")


# ── 4. create_probe() construction without opening ───────────────

for name in expected:
    try:
        probe = create_probe(name)
        if isinstance(probe, DebugProbe):
            ok(f"create_probe('{name}') -> {type(probe).__name__}")
        else:
            fail(f"create_probe('{name}')", f"not a DebugProbe: {type(probe)}")
    except Exception as e:
        fail(f"create_probe('{name}')", str(e))


# ── 5. Legacy imports still work ─────────────────────────────────

try:
    import jlink
    ok("import jlink (legacy)")
except Exception as e:
    fail("import jlink", str(e))

try:
    import openocd
    ok("import openocd (legacy)")
except Exception as e:
    fail("import openocd", str(e))


# ── 6. jlink.TIF.SWD == 1 ───────────────────────────────────────

try:
    if jlink.TIF.SWD == 1:
        ok("jlink.TIF.SWD == 1")
    else:
        fail("jlink.TIF.SWD", f"expected 1, got {jlink.TIF.SWD}")
except Exception as e:
    fail("jlink.TIF.SWD", str(e))


# ── Summary ──────────────────────────────────────────────────────

print()
total = passed + failed
print(f"Results: {passed}/{total} passed", end="")
if failed:
    print(f", {failed} FAILED")
    sys.exit(1)
else:
    print(" -- all OK")
    sys.exit(0)
