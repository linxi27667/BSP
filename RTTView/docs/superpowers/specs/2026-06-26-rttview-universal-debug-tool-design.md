# RTTView Universal Debug Tool - Design Spec

## Vision

Transform RTTView from a SEGGER RTT viewer into the world's most powerful embedded debugging tool — a single PyQt5 application that unifies RTT viewing, register inspection, oscilloscope-style waveform display, SWO/ITM trace, RTOS task awareness, memory inspection, CPU profiling, and flash programming across ALL major debug probes (J-Link, ST-Link, DAPLink, OpenOCD).

## Current State

- **Architecture**: Monolithic `RTTView.py` (1730 lines) + `xlink.py` facade + `jlink.py`/`openocd.py` backends + vendored `pyocd/`
- **Probe support**: J-Link (ctypes DLL), OpenOCD (TCP Tcl RPC), DAPLink (vendored pyocd)
- **Features**: RTT text viewing, basic waveform (4 curves), J-Scope HSS variable watching, ANSI rendering, auto-reconnect

## Target Architecture

```
RTTView.py  (UI shell — window setup, tab management, signal routing)
    │
    ├── core/
    │   ├── rtt_engine.py      — RTT protocol: scan, read, write, multi-channel
    │   ├── svd_parser.py      — SVD XML parsing (cmsis-svd)
    │   ├── elf_parser.py      — ELF/DWARF parsing (pyelftools)
    │   ├── swo_decoder.py     — SWO/ITM frame decoding
    │   ├── rtos_analyzer.py   — FreeRTOS task structure parsing
    │   └── memory_map.py      — Memory region management
    │
    ├── probes/
    │   ├── base.py            — Abstract DebugProbe interface
    │   ├── jlink_probe.py     — J-Link via pylink-square (pip)
    │   ├── stlink_probe.py    — ST-Link via pystlink (pure Python)
    │   ├── daplink_probe.py   — DAPLink via vendored pyocd
    │   └── openocd_probe.py   — OpenOCD via TCP Tcl RPC
    │
    ├── widgets/
    │   ├── rtt_console.py     — RTT text console (extracted from RTTView.py)
    │   ├── register_viewer.py — SVD-based peripheral register viewer
    │   ├── oscilloscope.py    — Enhanced waveform with trigger/timebase/cursors
    │   ├── memory_viewer.py   — Hex memory viewer/editor
    │   ├── task_viewer.py     — RTOS task state table
    │   ├── swo_console.py     — SWO/ITM trace output
    │   ├── cpu_monitor.py     — CPU load / profiling display
    │   └── crash_analyzer.py  — Post-mortem register dump + stack trace
    │
    └── utils/
        ├── theme.py           — Dark theme QSS
        └── config.py          — Settings management
```

## Feature Breakdown (15 Features)

### Phase 1: Foundation (Must Do First)

#### F1: Probe Abstraction Layer
- Replace `isinstance()` dispatch in `xlink.py` with abstract base class
- Each probe implements `DebugProbe` interface: `read_mem`, `write_mem`, `read_reg`, `write_reg`, `halt`, `go`, `step`, `reset`, `close`
- Registry pattern: probes self-register, UI auto-discovers available probes

#### F2: ST-Link Native Support
- Integrate `pystlink` for direct USB ST-Link v2/v2-1/v3 access
- No OpenOCD server needed — pure Python, zero external dependencies
- Auto-detect ST-Link probes via USB VID/PID

#### F3: J-Link via pylink-square
- Replace ctypes DLL approach with `pylink-square` library
- Gain: RTT callbacks, SWO support, memory zones, flash programming, disassembly
- Backward compatible: still supports user-specified DLL path

### Phase 2: Register & Memory Inspection

#### F4: SVD Peripheral Register Viewer
- Parse CMSIS-SVD files (standard XML format from chip vendors)
- Tree view: Chip → Peripheral → Register → Bit Field
- Live value column: read from MCU, color-highlight changed bits
- Bit field detail panel: show field name, description, access type (R/W/R0/RC/W1C)
- SVD files auto-discovered from `svd/` directory, user can browse/download
- Source: STM32, NXP, Nordic, Espressif SVD files from cmsis-svd repo

#### F5: Memory Hex Viewer
- Hex dump display (like HxD/OllyDbg) with address + hex + ASCII columns
- Real-time refresh (polling) or on-demand
- Color-coded regions: Flash (blue), SRAM (green), Peripheral (yellow), Stack (red)
- Goto address, search pattern, follow pointer
- Edit bytes in-place (write back to MCU)

#### F6: Core Register Viewer
- Display all CPU registers in a clean table: R0-R12, SP, LR, PC, xPSR (ARM) or x0-x31, pc, mstatus (RISC-V)
- Decode xPSR: Exception number, ISR preemption, Thumb state
- Decode mstatus: MIE, MPIE, MPP, etc.
- One-click: copy PC address, set PC here, follow LR

### Phase 3: Oscilloscope & Waveform

#### F7: Oscilloscope Mode (Enhanced Waveform)
- **Trigger system**: Rising/Falling edge on any channel, trigger level settable
- **Timebase**: Adjustable horizontal scale (1ms/div to 10s/div)
- **Voltage scale**: Adjustable vertical scale per channel, auto-scale
- **Multiple channels**: 8 channels (up from 4), each with configurable color
- **Measurement cursors**: Horizontal (time delta) and vertical (value delta) cursors
- **Data source**: RTT comma-separated values (existing) + direct memory read (new)
- **Math channels**: Add, subtract, multiply, FFT on channels
- **XY mode**: Plot channel A vs channel B (Lissajous patterns)
- **Trigger indicator**: Show trigger point on screen, pre-trigger buffer

#### F8: Register-Based Oscilloscope
- User selects any memory address + data type (uint8/16/32, int8/16/32, float)
- Tool reads at configurable sample rate (10Hz-1kHz) via debug probe
- Plots as oscilloscope waveform — no firmware instrumentation needed
- This is the "oscilloscope based on registers" the user asked for
- Combine with SVD: click any register field → "Oscilloscope" context menu → auto-plot

### Phase 4: SWO/ITM Trace

#### F9: SWO/ITM Trace Decoder
- Decode TPIU frames from SWO pin (J-Link, ST-Link v2/v3 support ITM)
- ITM stimulus ports 0-31: printf-style output (like RTT but via hardware trace)
- DWT PC sampling: function-level profiling without code instrumentation
- DWT data watchpoints: variable change trace
- Exception trace: interrupt entry/exit with timing
- Timeline view: graphical display of events over time

#### F10: Function Profiler (orbtop-style)
- Use DWT PC sampling to build function-level CPU usage profile
- Requires ELF file for symbol resolution
- Display: function name, % CPU, call count, avg/max duration
- Real-time update, like Unix `top` command but for MCU

### Phase 5: RTOS Awareness

#### F11: FreeRTOS Task Viewer
- Parse FreeRTOS task list from MCU memory (pxCurrentTCB → linked list)
- Display: Task name, state (Running/Ready/Blocked/Suspended), priority, stack usage, stack watermark
- Color-coded: Running=green, Blocked=yellow, Suspended=red
- Stack usage bar graph (like Task Manager)
- Auto-detect RTOS: scan for known RTOS data structures
- Support: FreeRTOS (primary), RT-Thread, uC/OS, Zephyr (future)

#### F12: Heap Monitor
- Track malloc/free calls by intercepting pvPortMalloc/vPortFree
- Display: total allocated, peak usage, fragmentation, block count
- Allocation timeline: show each allocation with size and caller address
- Leak detection: allocations without matching free

### Phase 6: Advanced Debugging

#### F13: Post-Mortem Crash Analyzer
- On MCU halt (HardFault, assert, watchdog): auto-capture all registers
- Decode fault registers: CFSR, HFSR, MMFAR, BFAR, LR (EXC_RETURN)
- Stack unwinding: walk call stack using frame pointer or exception frame
- Display: fault type, fault address, call stack with function names (if ELF loaded)
- One-click: save crash dump to file for later analysis

#### F14: Data Watchpoints (DWT)
- Configure DWT comparators to watch memory addresses/ranges
- On access (read/write/both): halt MCU or log event
- UI: set watchpoint by address, data range, access type
- Like GDB `watch` but configured from GUI

#### F15: Flash Programmer
- Flash binary/hex/ELF files to MCU via debug probe
- Erase: sector erase, mass erase
- Verify: read-back and compare
- Progress bar with estimated time
- Support: STM32, nRF, ESP32, NXP (via probe-specific algorithms)

## Data Flow

```
┌─────────────────────────────────────────────────────┐
│                    RTTView.py (UI)                   │
│  ┌──────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ Tab  │ │  Tab 2   │ │  Tab 3   │ │  Tab 4    │  │
│  │ RTT  │ │ Register │ │  Scope   │ │ Task View │  │
│  │Console│ │ Viewer   │ │  Mode   │ │           │  │
│  └──┬───┘ └────┬─────┘ └────┬─────┘ └─────┬─────┘  │
│     │          │            │              │        │
│  ┌──┴──────────┴────────────┴──────────────┴─────┐  │
│  │            DebugProbe (abstract)              │  │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌─────────────┐  │  │
│  │  │J-Link│ │ST-Link│ │DAPLink│ │   OpenOCD   │  │  │
│  │  └──────┘ └──────┘ └──────┘ └─────────────┘  │  │
│  └───────────────────────────────────────────────┘  │
│                        │                             │
│                   ┌────┴────┐                        │
│                   │  MCU    │                        │
│                   │ (SWD/   │                        │
│                   │  JTAG)  │                        │
│                   └─────────┘                        │
└─────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Tab-based UI
- Main window uses QTabWidget for different feature panels
- RTT console is the default tab (backward compatible)
- Each tab is a self-contained widget in `widgets/`
- Tabs can be detached into separate windows (QDockWidget)

### 2. Probe Plugin System
- `probes/base.py` defines `DebugProbe` ABC with all required methods
- Each probe file implements this interface
- `ProbeRegistry` auto-discovers probes at startup
- UI shows only probes whose dependencies are available

### 3. Non-intrusive Monitoring
- All register/memory reads happen via debug interface (no firmware changes)
- Oscilloscope mode reads memory directly — zero overhead on target
- SWO uses hardware trace — no CPU overhead
- RTOS task viewer reads kernel data structures passively

### 4. SVD Integration
- SVD files define the "language" of the chip's registers
- Once loaded, every peripheral register becomes human-readable
- Click any register → see bit field descriptions
- Click any bit field → read/write/toggle/watch as oscilloscope

## Dependencies

| Package | Purpose | Required |
|---------|---------|----------|
| PyQt5 | GUI framework | Yes |
| PyQtChart | Waveform display | Yes |
| pylink-square | J-Link probe driver | No (replaces ctypes) |
| pystlink | ST-Link probe driver | No (new) |
| pyelftools | ELF/DWARF parsing | Yes |
| cmsis-svd | SVD file parsing | No (new) |
| capstone | Disassembly | No (new, optional) |

## Success Criteria

1. User can connect via J-Link, ST-Link, DAPLink, or OpenOCD — one click
2. SVD register viewer shows all peripheral registers with live values
3. Register-based oscilloscope plots any memory address as waveform
4. FreeRTOS task viewer shows task states, priorities, stack usage
5. Post-mortem crash analyzer decodes HardFault automatically
6. All existing RTT functionality preserved (backward compatible)

## Implementation Order

1. **Phase 1** (Foundation): F1 → F2 → F3 — probe abstraction + ST-Link + J-Link upgrade
2. **Phase 2** (Inspection): F4 → F5 → F6 — SVD + memory viewer + core registers
3. **Phase 3** (Oscilloscope): F7 → F8 — enhanced waveform + register oscilloscope
4. **Phase 4** (Trace): F9 → F10 — SWO/ITM + function profiler
5. **Phase 5** (RTOS): F11 → F12 — task viewer + heap monitor
6. **Phase 6** (Advanced): F13 → F14 → F15 — crash analyzer + watchpoints + flash

Each phase is independently valuable and can be shipped separately.
