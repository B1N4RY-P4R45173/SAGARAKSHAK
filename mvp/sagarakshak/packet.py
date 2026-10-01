"""Offline safety packet: what the phone keeps when the signal drops.

The packet carries a small current/wind subgrid, the nearby IMBL, the day's zones and
a 3-hourly sea-state strip, so the phone can keep integrating drift and warning on its
own. In production it rides the GEMINI/GAGAN broadcast; here it is fetched while
"online". It is signed with Ed25519 so a phone can reject a spoofed or altered packet.

The signature covers the exact body string, so no JSON re-serialisation is needed to
verify it on the phone.
"""
import json
import math
import os

from . import ed25519, geo
from .data import NLAT, NLON

HALF = 5          # subgrid is (2*HALF+1)^2 cells at 0.1°  ->  ~110 km square
SLICES = 5        # 0–12 h at 3-hourly


def load_key(path):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(os.urandom(32))
    with open(path, "rb") as f:
        seed = f.read()
    return seed, ed25519.public_key(seed)


def build(dl, advisory, lat, lon, seed):
    ci, cj = dl.corners(lat, lon)[0][:2]
    n = 2 * HALF + 1
    i0 = max(0, min(NLAT - n, ci - HALF + 1))
    j0 = max(0, min(NLON - n, cj - HALF + 1))

    def sub(f, ti):
        # integers: currents in cm/s, wind in dm/s (see "scale") — roughly halves the payload
        k = 100 if f in ("cu", "cv") else 10
        return [round((dl.cell(f, ti, i, j) or 0.0) * k) for i in range(i0, i0 + n) for j in range(j0, j0 + n)]

    wx = []
    for ti in range(SLICES):
        hs, _ = dl.sample("hs", lat, lon, ti)
        u, _ = dl.sample("wu", lat, lon, ti)
        v, _ = dl.sample("wv", lat, lon, ti)
        ts, _ = dl.sample("ts", lat, lon, ti)
        wx.append([dl.time_of(ti).strftime("%H:%M"), round(hs or 0, 1), round(math.hypot(u, v) * 3.6),
                   round((ts or 0) * 100)])
    body = {
        "v": 1,
        "issued": dl.issued.isoformat(),
        "valid_h": 12,
        "mode": "SAMPLE",
        "boat": [round(lat, 4), round(lon, 4)],
        "grid": {"lat0": dl.lat(i0), "lon0": dl.lon(j0), "step": 0.1, "n": n, "t_step": 3,
                 "scale": {"cu": 0.01, "cv": 0.01, "wu": 0.1, "wv": 0.1},
                 "cu": [sub("cu", t) for t in range(SLICES)], "cv": [sub("cv", t) for t in range(SLICES)],
                 "wu": [sub("wu", t) for t in range(SLICES)], "wv": [sub("wv", t) for t in range(SLICES)]},
        "imbl": [[round(a, 4), round(b, 4)] for a, b in geo.imbl_near(lat, lon, 150)],
        "zones": [[z["id"], z["lat"], z["lon"], z["radius_km"]] for z in advisory
                  if z["side"] == "IN" and geo.haversine_km(lat, lon, z["lat"], z["lon"]) < 90][:4],
        "wx": wx,
        "alert_km": {"warn": 5, "crit": 2},
        "leeway": 0.03,
    }
    text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    sig = ed25519.sign(seed, text.encode("utf-8"))
    return {"body": text, "sig": sig.hex(), "pub": ed25519.public_key(seed).hex(), "bytes": len(text.encode())}
