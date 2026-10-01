"""The reply envelope: fisher catch reports scored against the advisory they fished under.

Two numbers go back to the scientists:
  * PFZ skill — catch rate inside advised zones vs outside (lift) and hit share.
  * SST check — boat-measured water temperature vs the satellite value at that point
    (bias and RMSE), i.e. free in-situ validation.

Storage is a JSON file for the MVP; seeded reports are clearly marked as seed data.
"""
import datetime as dt
import json
import math
import os
import random
import threading

from . import geo

INSIDE_KM = 10
_lock = threading.Lock()


class FeedbackStore:
    def __init__(self, path, dl, advisory):
        self.path, self.dl, self.advisory = path, dl, advisory
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._write(self._seed())
        self.reports = self._read()

    def _read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, reports):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(reports, f, ensure_ascii=False, indent=1)

    def _seed(self):
        rng = random.Random(26176)
        zones = [z for z in self.advisory if z["side"] == "IN"]
        out = []
        for k in range(48):
            inside = rng.random() < 0.55
            if inside:
                z = rng.choice(zones)
                r, b = rng.uniform(0, 8), rng.uniform(0, 360)
            else:
                z = {"lat": 9.6 + rng.uniform(-0.5, 0.4), "lon": 79.1 + rng.uniform(-0.4, 0.2)}
                r, b = 0, 0
            lat = z["lat"] + r * math.cos(math.radians(b)) / 111.32
            lon = z["lon"] + r * math.sin(math.radians(b)) / geo.km_per_deg_lon(z["lat"])
            if geo.is_land(lat, lon) or geo.side(lat, lon) != "IN" or not self.dl.in_bounds(lat, lon):
                continue
            hours = round(rng.uniform(5, 10), 1)
            cpue = max(1.0, rng.gauss(8.5 if inside else 5.2, 1.6))
            sat, _ = self.dl.sample("sst", lat, lon, 0)
            temp = round(sat + rng.gauss(0.15, 0.35), 1) if sat is not None and rng.random() < 0.7 else None
            when = self.dl.issued - dt.timedelta(hours=rng.uniform(6, 240))
            out.append({"seed": True, "time": when.isoformat(), "lat": round(lat, 4), "lon": round(lon, 4),
                        "kg": round(cpue * hours), "hours": hours, "species": rng.choice(
                            ["sardine", "mackerel", "prawn", "squid", "trevally"]), "water_temp": temp})
        return out

    # ------------------------------------------------------------------
    def evaluate(self, r):
        best = min(((geo.haversine_km(r["lat"], r["lon"], z["lat"], z["lon"]), z)
                    for z in self.advisory if z["side"] == "IN"), key=lambda x: x[0])
        sat, _ = self.dl.sample("sst", r["lat"], r["lon"], 0)
        ev = {"nearest_zone": best[1]["id"], "zone_km": round(best[0], 1), "inside": best[0] <= INSIDE_KM,
              "cpue": round(r["kg"] / r["hours"], 2), "sat_sst": None if sat is None else round(sat, 2)}
        if r.get("water_temp") is not None and sat is not None:
            ev["sst_diff"] = round(r["water_temp"] - sat, 2)
        return ev

    def add(self, r):
        with _lock:
            r = {"seed": False, "time": dt.datetime.now(self.dl.issued.tzinfo).isoformat(), **r}
            self.reports.append(r)
            self._write(self.reports)
        return self.evaluate(r)

    def scorecard(self):
        ev = [(r, self.evaluate(r)) for r in self.reports]
        ins = [e["cpue"] for _, e in ev if e["inside"]]
        out = [e["cpue"] for _, e in ev if not e["inside"]]
        diffs = [e["sst_diff"] for _, e in ev if "sst_diff" in e]
        mean = (lambda xs: sum(xs) / len(xs) if xs else None)
        mi, mo = mean(ins), mean(out)
        recent = sorted(ev, key=lambda x: x[0]["time"], reverse=True)[:8]
        return {
            "n": len(ev), "n_live": sum(1 for r, _ in ev if not r["seed"]),
            "hit_share": round(len(ins) / len(ev), 2) if ev else None,
            "cpue_inside": mi and round(mi, 2), "cpue_outside": mo and round(mo, 2),
            "lift": round(mi / mo, 2) if mi and mo else None,
            "sst": {"n": len(diffs), "bias": diffs and round(mean(diffs), 2),
                    "rmse": diffs and round(math.sqrt(mean([x * x for x in diffs])), 2)},
            "recent": [{**r, **e} for r, e in recent],
            "points": [[r["lat"], r["lon"], e["inside"], r["seed"]] for r, e in ev],
        }
