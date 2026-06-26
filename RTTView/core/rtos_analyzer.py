"""FreeRTOS task list analyzer via debug probe memory reads.

Walks the FreeRTOS kernel linked list (v10.x / Cortex-M) to extract
task name, state, priority, stack usage, and TCB address.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


# ------------------------------------------------------------------ #
#  FreeRTOS v10.x TCB field offsets (Cortex-M, configUSE_TRACE_FACILITY=1)
# ------------------------------------------------------------------ #
# TCB layout (simplified, 32-bit):
#   0x00  pxTopOfStack        (pointer)
#   0x04  xStateListItem      (ListItem_t, 20 bytes)
#   0x18  xEventListItem      (ListItem_t, 20 bytes)
#   0x2C  uxPriority          (UBaseType_t)
#   0x30  pxStack             (pointer)
#   0x38  pcTaskName[16]      (char[16])
#   ...

TCB_OFFSET_PX_TOP_OF_STACK = 0x00
TCB_OFFSET_X_STATE_LIST_ITEM = 0x04
TCB_OFFSET_UX_PRIORITY = 0x2C      # 44
TCB_OFFSET_PX_STACK = 0x30         # 48
TCB_OFFSET_PC_TASK_NAME = 0x38     # 56

# MiniListItem / ListItem_t offsets (each item is 20 bytes on 32-bit)
LIST_ITEM_OFFSET_X_ITEM_VALUE = 0x00   # TickType_t (4 bytes)
LIST_ITEM_OFFSET_PX_NEXT = 0x04        # pointer
LIST_ITEM_OFFSET_PX_PREVIOUS = 0x08    # pointer
LIST_ITEM_OFFSET_PV_OWNER = 0x0C       # pointer (-> TCB)
LIST_ITEM_OFFSET_PV_CONTAINER = 0x10   # pointer (-> List)

LIST_ITEM_SIZE = 20

# Task states (matches FreeRTOS eTaskState enum)
TASK_STATE_RUNNING = 0
TASK_STATE_READY = 1
TASK_STATE_BLOCKED = 2
TASK_STATE_SUSPENDED = 3
TASK_STATE_DELETED = 4

STATE_NAMES = {
    TASK_STATE_RUNNING: "Running",
    TASK_STATE_READY: "Ready",
    TASK_STATE_BLOCKED: "Blocked",
    TASK_STATE_SUSPENDED: "Suspended",
    TASK_STATE_DELETED: "Deleted",
}

# Sanity limits to avoid infinite loops
MAX_TASKS = 64
MAX_LIST_WALK = 128


@dataclass
class TaskInfo:
    """Snapshot of one FreeRTOS task."""
    name: str
    state: int          # 0=Running, 1=Ready, 2=Blocked, 3=Suspended, 4=Deleted
    priority: int
    stack_base: int     # pxStack (bottom of allocated stack)
    stack_end: int      # pxTopOfStack (current top)
    stack_used: int     # stack_base - pxTopOfStack  (high-water-mark delta)
    tcb_addr: int       # address of the TCB in MCU RAM

    @property
    def state_name(self) -> str:
        return STATE_NAMES.get(self.state, f"?{self.state}")

    @property
    def stack_size(self) -> int:
        """Total stack size in bytes (requires pxEndOfStack which we
        don't always have; return high-water-mark usage as fallback)."""
        return self.stack_used  # caller may override if pxEndOfStack known

    @property
    def stack_usage_percent(self) -> float:
        """Stack usage as percentage.  Returns 0.0 if size unknown."""
        size = self.stack_size
        if size <= 0:
            return 0.0
        return (self.stack_used / size) * 100.0


# ------------------------------------------------------------------ #
#  Helper: read a null-terminated ASCII string from MCU memory
# ------------------------------------------------------------------ #
def _read_cstr(probe, addr: int, max_len: int = 16) -> str:
    """Read a C string from MCU memory (up to *max_len* bytes)."""
    raw = probe.read_mem_U8(addr, max_len)
    chars = []
    for b in raw:
        if b == 0:
            break
        if 0x20 <= b < 0x7F:
            chars.append(chr(b))
        else:
            chars.append('?')  # non-printable
    return ''.join(chars)


def _read_u32(probe, addr: int) -> int:
    """Read a single 32-bit little-endian word."""
    return probe.read_U32(addr)


# ------------------------------------------------------------------ #
#  FreeRTOSAnalyzer
# ------------------------------------------------------------------ #
class FreeRTOSAnalyzer:
    """Reads FreeRTOS kernel data structures from MCU RAM.

    Parameters
    ----------
    probe : DebugProbe
        An open, connected probe with read_U32 / read_mem_U8.
    mode : str
        'arm' (default) for Cortex-M 32-bit pointers.
    """

    def __init__(self, probe, mode: str = 'arm'):
        self.probe = probe
        self.mode = mode

    # ------------------------------------------------------------------ #
    #  Locate pxCurrentTCB
    # ------------------------------------------------------------------ #
    def find_current_tcb(
        self,
        search_addr: int = 0x20000000,
        search_len: int = 0x40000,
    ) -> Optional[int]:
        """Brute-force search for the pxCurrentTCB pointer in SRAM.

        Algorithm:
        1. Read a block of SRAM as 32-bit words.
        2. For each word that looks like a valid SRAM pointer
           (0x20000000..0x20FFFFFF), treat it as a candidate TCB address.
        3. Read 4 bytes at candidate + TCB_OFFSET_PC_TASK_NAME and check
           that the first byte is a printable ASCII character (a-z, A-Z).
        4. Return the **address of the pointer** (i.e. &pxCurrentTCB),
           which contains the TCB address.

        Returns the address of pxCurrentTCB in SRAM, or None.
        """
        try:
            words = probe = self.probe.read_mem_U32(search_addr, search_len // 4)
        except Exception:
            return None

        for i, val in enumerate(words):
            # Candidate: looks like a pointer into SRAM
            if not (0x20000000 <= val < 0x30000000):
                continue

            # Read first byte of pcTaskName inside the candidate TCB
            try:
                name_bytes = self.probe.read_mem_U8(
                    val + TCB_OFFSET_PC_TASK_NAME, 1
                )
            except Exception:
                continue

            if not name_bytes:
                continue

            ch = name_bytes[0]
            # Accept printable ASCII (space ~ tilde)
            if 0x20 <= ch < 0x7F:
                # Double-check: read a few more bytes to be sure
                try:
                    name_bytes2 = self.probe.read_mem_U8(
                        val + TCB_OFFSET_PC_TASK_NAME, 4
                    )
                except Exception:
                    continue
                # Reject if all zeros or looks corrupt
                if all(b == 0 for b in name_bytes2):
                    continue
                # Found it - return the address of the pointer
                return search_addr + i * 4

        return None

    # ------------------------------------------------------------------ #
    #  Walk task list from pxCurrentTCB
    # ------------------------------------------------------------------ #
    def read_tasks(self) -> List[TaskInfo]:
        """Walk the FreeRTOS ready-list / all-task list from pxCurrentTCB.

        FreeRTOS stores tasks in a circular linked list via
        xStateListItem.  The ``pvContainer`` field of the list item
        points back to the List_t that owns it, and we use ``pxNext``
        to walk.

        Returns a list of TaskInfo, or empty list on failure.
        """
        tcb_ptr_addr = self.find_current_tcb()
        if tcb_ptr_addr is None:
            return []

        current_tcb = _read_u32(self.probe, tcb_ptr_addr)
        if current_tcb == 0:
            return []

        tasks: List[TaskInfo] = []
        visited: set[int] = set()
        addr = current_tcb

        for _ in range(MAX_TASKS):
            if addr in visited or addr == 0:
                break
            visited.add(addr)

            task = self._parse_tcb(addr)
            if task is None:
                break
            tasks.append(task)

            # Follow xStateListItem.pxNext -> next list item -> pvOwner -> next TCB
            state_item_addr = addr + TCB_OFFSET_X_STATE_LIST_ITEM
            next_item = _read_u32(self.probe, state_item_addr + LIST_ITEM_OFFSET_PX_NEXT)
            if next_item == 0 or next_item == state_item_addr:
                break  # end of list (points to itself or NULL)

            # pvOwner of the next list item is the next TCB
            next_tcb = _read_u32(self.probe, next_item + LIST_ITEM_OFFSET_PV_OWNER)
            if next_tcb == 0:
                break

            # Detect full loop back to start
            if next_tcb == current_tcb:
                break

            addr = next_tcb

        return tasks

    # ------------------------------------------------------------------ #
    #  Parse a single TCB
    # ------------------------------------------------------------------ #
    def _parse_tcb(self, tcb_addr: int) -> Optional[TaskInfo]:
        """Read fields from one TCB and return a TaskInfo."""
        try:
            px_top = _read_u32(self.probe, tcb_addr + TCB_OFFSET_PX_TOP_OF_STACK)
            ux_pri = _read_u32(self.probe, tcb_addr + TCB_OFFSET_UX_PRIORITY)
            px_stack = _read_u32(self.probe, tcb_addr + TCB_OFFSET_PX_STACK)
            name = _read_cstr(self.probe, tcb_addr + TCB_OFFSET_PC_TASK_NAME, 16)

            if not name or all(c == '?' for c in name):
                return None

            # Derive state from xStateListItem.pvContainer
            # FreeRTOS maintains separate lists for each state.
            # We can infer state from the list pointer, but a simpler
            # heuristic: if tcb matches pxCurrentTCB -> Running,
            # otherwise Blocked/Ready/Suspended needs the container list.
            # For now, read xEventListItem to detect blocked/suspended.
            state = self._infer_state(tcb_addr)

            # Stack usage: pxStack is bottom, pxTopOfStack is current top.
            # On Cortex-M stack grows DOWN, so usage = pxStack - pxTopOfStack
            # (positive when stack has been used).
            stack_used = max(0, px_stack - px_top) if px_stack > px_top else 0

            return TaskInfo(
                name=name,
                state=state,
                priority=ux_pri,
                stack_base=px_stack,
                stack_end=px_top,
                stack_used=stack_used,
                tcb_addr=tcb_addr,
            )
        except Exception:
            return None

    def _infer_state(self, tcb_addr: int) -> int:
        """Best-effort state inference.

        FreeRTOS maintains separate List_t for each state.  The
        xStateListItem.pvContainer field points to the owning list.
        Without knowing the list addresses, we use a heuristic:

        - If tcb is the current TCB -> RUNNING
        - If xEventListItem.pvContainer != NULL -> BLOCKED (waiting on event)
        - If uxTopReadyPriority bit is set for this task -> READY
        - Fallback -> READY
        """
        try:
            # Check if this is the current TCB
            tcb_ptr_addr = self.find_current_tcb()
            if tcb_ptr_addr is not None:
                current_tcb = _read_u32(self.probe, tcb_ptr_addr)
                if current_tcb == tcb_addr:
                    return TASK_STATE_RUNNING

            # Check xEventListItem.pvContainer
            # xEventListItem is at offset 0x18 from TCB base
            event_item = tcb_addr + 0x18
            event_container = _read_u32(
                self.probe, event_item + LIST_ITEM_OFFSET_PV_CONTAINER
            )
            if event_container != 0:
                return TASK_STATE_BLOCKED

            # Check uxTopReadyPriority at offset 0x24 (varies by config)
            # This is fragile; default to READY
            return TASK_STATE_READY

        except Exception:
            return TASK_STATE_READY
