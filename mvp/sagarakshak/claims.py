"""The claim format every agent must use.

A claim is a number plus the exact inputs it was computed from. Agents never hand
back bare prose; the composer only turns *verified* claims into words.
"""
import itertools

_ids = itertools.count(1)


def claim(agent, kind, value, inputs, params=None, label="", unit=""):
    return {
        "id": f"C{next(_ids):04d}",
        "agent": agent,
        "kind": kind,          # selects the verifier's recompute rule
        "label": label,
        "value": value,
        "unit": unit,
        "inputs": inputs,      # data-layer refs: {"field",ti,i,j,value} or {"series",k,value}
        "params": params or {},
        "status": "pending",
        "reason": "",
    }
