from .base import DebugProbe

# Registry: populated by probe modules on import
_PROBES = {}

def register_probe(name, probe_class):
    _PROBES[name] = probe_class

def get_probe(name):
    return _PROBES.get(name)

def list_probes():
    return dict(_PROBES)

def create_probe(name, **kwargs):
    cls = _PROBES.get(name)
    if cls is None:
        raise ValueError(f"Unknown probe: {name}")
    return cls(**kwargs)
