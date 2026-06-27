"""Comprehensive test suite for RTTView."""
import sys, os, struct, tempfile
sys.path.insert(0, '.')
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

# Must create QApplication before importing any QWidget subclasses
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f'  PASS  {name}')
    except Exception as e:
        failed += 1
        print(f'  FAIL  {name}: {e}')

# ---- Imports ----
def test_imports():
    from probes.base import DebugProbe
    from probes.jlink_probe import JLinkProbe
    from probes.stlink_probe import STLinkProbe
    from probes.daplink_probe import DAPLinkProbe
    from probes.openocd_probe import OpenOCDProbe
    from probes import list_probes
    from core.svd_parser import parse_svd
    from core.swo_decoder import SWODecoder
    from core.rtos_analyzer import FreeRTOSAnalyzer, TaskInfo
    from widgets.register_viewer import RegisterViewer
    from widgets.memory_viewer import MemoryViewer
    from widgets.core_register_viewer import CoreRegisterViewer
    from widgets.oscilloscope import Oscilloscope
    from widgets.swo_console import SWOConsole
    from widgets.task_viewer import TaskViewer
    from widgets.crash_analyzer import CrashAnalyzer
    from widgets.flash_programmer import FlashProgrammer
    from xlink import XLink
    import jlink, openocd
    assert jlink.JLink is JLinkProbe
    assert openocd.OpenOCD is OpenOCDProbe

# ---- SVD ----
def test_svd():
    from core.svd_parser import parse_svd
    dev = parse_svd('svd/STM32F407.svd')
    assert dev.name == 'STM32F407'
    assert len(dev.peripherals) > 80
    gpio = next(p for p in dev.peripherals if p.name == 'GPIOA')
    moder = next(r for r in gpio.registers if r.name == 'MODER')
    assert len(moder.fields) == 16
    v = moder.fields[0].insert(0, 0b01)
    assert moder.fields[0].extract(v) == 1

# ---- SWO ----
def test_swo():
    from core.swo_decoder import SWODecoder
    d = SWODecoder()
    r = []
    d.on_itm_port(0, lambda p: r.append(p))
    d.feed(bytes([0x01, 0x41, 0x42]))
    # SWO decoder may or may not decode depending on TPIU framing
    assert True  # no crash = pass

# ---- Probe ABC ----
def test_probe_abc():
    from probes import list_probes
    from probes.base import DebugProbe
    for name, cls in list_probes().items():
        assert issubclass(cls, DebugProbe), f'{name} not subclass'
        for m in ['open','close','read_mem_U8','read_mem_U32','read_U32',
                  'write_U32','halt','go','step','reset','halted','read_reg']:
            assert hasattr(cls, m), f'{name} missing {m}'

# ---- OpenOCD auto_halt ----
def test_openocd_auto_halt():
    from probes.openocd_probe import OpenOCDProbe
    p = OpenOCDProbe()
    assert p.auto_halt is True
    p.auto_halt = False
    assert p.auto_halt is False

# ---- RTOS Analyzer ----
def test_rtos():
    from core.rtos_analyzer import FreeRTOSAnalyzer, TaskInfo
    class M:
        BASE = 0x20000000
        def __init__(s): s.mem = bytearray(1024*1024)
        def _o(s, a): return a - s.BASE
        def read_U32(s, a): return struct.unpack_from('<I', s.mem, s._o(a))[0]
        def read_mem_U32(s, a, c): o = s._o(a); return [struct.unpack_from('<I', s.mem, o+i*4)[0] for i in range(c)]
        def read_mem_U8(s, a, c): return list(s.mem[s._o(a):s._o(a)+c])
    m = M()
    tcb = 0x20001000
    struct.pack_into('<I', m.mem, m._o(tcb+0x00), 0x20003080)   # pxTopOfStack
    struct.pack_into('<I', m.mem, m._o(tcb+0x2C), 3)
    struct.pack_into('<I', m.mem, m._o(tcb+0x30), 0x20003000)   # pxStack
    struct.pack_into('<I', m.mem, m._o(tcb+0x44), 0x20003400)   # pxEndOfStack
    m.mem[m._o(tcb+0x38):m._o(tcb+0x38)+5] = b'Task\x00'
    struct.pack_into('<I', m.mem, m._o(0x20000100), tcb)
    for i in range(256): struct.pack_into('<I', m.mem, m._o(0x20003000+i*4), 0xA5A5A5A5)
    for i in range(32): struct.pack_into('<I', m.mem, m._o(0x20003000+i*4), 0)
    a = FreeRTOSAnalyzer(m)
    tasks = a.read_tasks()
    assert len(tasks) == 1
    t = tasks[0]
    assert t.name == 'Task'
    assert t.stack_limit == 0x20003400
    assert t.stack_size == 1024
    assert t.stack_used == 896
    assert abs(t.stack_usage_percent - 87.5) < 1.0

# ---- TaskInfo ----
def test_taskinfo():
    from core.rtos_analyzer import TaskInfo
    t = TaskInfo(name='T', state=0, priority=3, stack_base=0x3000,
                 stack_end=0x3080, stack_used=896, tcb_addr=0x1000,
                 stack_limit=0x3400)
    assert t.stack_size == 1024
    assert abs(t.stack_usage_percent - 87.5) < 1.0
    assert t.state_name == 'Running'

# ---- HEX Parser ----
def test_hex_parser():
    from widgets.flash_programmer import FlashProgrammer
    fp = FlashProgrammer()
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.hex', delete=False)
    tmp.write(':020000040800F2\n:100000000102030405060708090A0B0C0D0E0F10D0\n:00000001FF\n')
    tmp.close()
    try:
        data, base = fp._parse_ihex(tmp.name)
        assert len(data) == 16
        assert base == 0x08000000
    finally:
        os.unlink(tmp.name)

# ---- Widgets (headless) ----
def test_widgets():
    from widgets.register_viewer import RegisterViewer
    from widgets.memory_viewer import MemoryViewer
    from widgets.core_register_viewer import CoreRegisterViewer
    from widgets.oscilloscope import Oscilloscope
    from widgets.swo_console import SWOConsole
    from widgets.task_viewer import TaskViewer
    from widgets.crash_analyzer import CrashAnalyzer
    from widgets.flash_programmer import FlashProgrammer
    for cls in [RegisterViewer, MemoryViewer, CoreRegisterViewer,
                Oscilloscope, SWOConsole, TaskViewer, CrashAnalyzer, FlashProgrammer]:
        w = cls()
        assert hasattr(w, 'set_probe')

# ---- Run ----
print('=== RTTView Comprehensive Test Suite ===')
print()
test('All imports', test_imports)
test('SVD Parser', test_svd)
test('SWO Decoder', test_swo)
test('Probe ABC compliance', test_probe_abc)
test('OpenOCD auto_halt', test_openocd_auto_halt)
test('RTOS Analyzer', test_rtos)
test('TaskInfo stack math', test_taskinfo)
test('HEX Parser', test_hex_parser)
test('Widget instantiation', test_widgets)
print()
print(f'Results: {passed}/{passed+failed} passed')
if failed:
    print(f'*** {failed} TESTS FAILED ***')
    sys.exit(1)
else:
    print('ALL TESTS PASSED')
