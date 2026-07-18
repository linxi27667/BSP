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
    stack_base: int     # pxStack (bottom of allocated stack, lowest address)
    stack_end: int      # pxTopOfStack (current top)
    stack_used: int     # stack_end - stack_base  (high-water-mark delta)
    tcb_addr: int       # address of the TCB in MCU RAM
    stack_limit: int = 0  # top of allocation (0xA5A5A5A5 watermark boundary)

    @property
    def state_name(self) -> str:
        return STATE_NAMES.get(self.state, f"?{self.state}")

    @property
    def stack_size(self) -> int:
        """Total stack size in bytes.  Uses the 0xA5A5A5A5 watermark
        boundary if available, otherwise returns 0 (unknown)."""
        if self.stack_limit > self.stack_base:
            return self.stack_limit - self.stack_base
        return 0  # unknown total

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


_STACK_WATERMARK = 0xA5A5A5A5


def _find_end_of_stack(probe, tcb_addr: int, px_stack: int) -> int:
    """Try to read pxEndOfStack from the TCB.

    FreeRTOS stores pxEndOfStack at an offset that depends on the version
    and config options (typically after pcTaskName).  We probe a handful of
    candidate offsets and return the first value that looks sane:
    above *px_stack* and within a reasonable range (256 B – 64 KB).

    Returns 0 if no plausible value is found.
    """
    # Candidates: common offsets after pcTaskName (16-byte name assumed)
    # 0x44 (name@0x34), 0x48, 0x4C, 0x50, 0x54, 0x58
    candidates = [0x44, 0x48, 0x4C, 0x50, 0x54, 0x58, 0x5C, 0x60]
    for off in candidates:
        try:
            val = probe.read_U32(tcb_addr + off)
            # Sanity: must be above px_stack, within 256 B – 64 KB
            if px_stack < val <= px_stack + 0x10000 and val > px_stack + 0x100:
                return val
        except Exception:
            continue
    return 0


def _scan_stack_watermark(probe, stack_base: int, max_scan: int = 4096) -> int:
    """Estimate stack limit by counting the leading 0xA5 watermark.

    On Cortex-M (stack grows DOWN), FreeRTOS fills the stack with 0xA5.
    The watermark remains in the UNTOUCHED region at the low end (near
    pxStack).  We count consecutive 0xA5 words from *stack_base* upward
    and return ``stack_base + watermark_bytes``.

    This underestimates the total allocation (misses any watermark above
    the used area), but is useful as a fallback when pxEndOfStack is not
    available.
    """
    try:
        step = 64
        watermark_end = stack_base  # assume no watermark initially
        for offset in range(0, max_scan, step * 4):
            words = probe.read_mem_U32(stack_base + offset, step)
            for i, w in enumerate(words):
                if w != _STACK_WATERMARK:
                    return stack_base + offset + i * 4
            watermark_end = stack_base + offset + step * 4
        return watermark_end  # all watermark up to max_scan
    except Exception:
        return 0


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
        self._current_tcb_cache: int = 0  # resolved once in read_tasks

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
            words = self.probe.read_mem_U32(search_addr, search_len // 4)
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

        # Cache for _infer_state so it doesn't re-scan SRAM per task
        self._current_tcb_cache = current_tcb

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

            # Try to read pxEndOfStack from the TCB.  Its offset varies by
            # FreeRTOS version; scan a few candidate positions after pcTaskName.
            stack_limit = _find_end_of_stack(self.probe, tcb_addr, px_stack)

            # stack_used: on Cortex-M stack grows DOWN.
            #   pxStack = lowest address (base), pxTopOfStack = current SP.
            #   used = stack_limit - pxTopOfStack  (consumed from the top down).
            if stack_limit and stack_limit > px_top:
                stack_used = stack_limit - px_top
            else:
                # Fallback: px_top - px_stack = remaining free bytes (not used).
                # Report as negative to signal "unknown total" to the UI.
                stack_used = 0

            return TaskInfo(
                name=name,
                state=state,
                priority=ux_pri,
                stack_base=px_stack,
                stack_end=px_top,
                stack_used=stack_used,
                tcb_addr=tcb_addr,
                stack_limit=stack_limit,
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
        - If xStateListItem.pvContainer == NULL -> SUSPENDED (not in any list)
        - Fallback -> READY
        """
        try:
            # Check if this is the current TCB (cached from read_tasks)
            if self._current_tcb_cache and self._current_tcb_cache == tcb_addr:
                return TASK_STATE_RUNNING

            # Check xEventListItem.pvContainer (offset 0x18 from TCB base)
            event_item = tcb_addr + 0x18
            event_container = _read_u32(
                self.probe, event_item + LIST_ITEM_OFFSET_PV_CONTAINER
            )
            if event_container != 0:
                return TASK_STATE_BLOCKED

            # Check xStateListItem.pvContainer
            # If the task's state list item has no container, it's suspended
            # (vTaskSuspend removes the item from its list)
            state_item = tcb_addr + TCB_OFFSET_X_STATE_LIST_ITEM
            state_container = _read_u32(
                self.probe, state_item + LIST_ITEM_OFFSET_PV_CONTAINER
            )
            if state_container == 0:
                return TASK_STATE_SUSPENDED

            return TASK_STATE_READY

        except Exception:
            return TASK_STATE_READY
