# Legacy module — delegates to probes.jlink_probe
# Kept for backward compatibility with old code that does `import jlink`

from probes.jlink_probe import JLinkProbe as JLink

# Keep TIF class for any code that references it
class TIF:
    JTAG  = 0
    SWD   = 1
    CJTAG = 7
