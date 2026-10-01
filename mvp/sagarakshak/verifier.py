"""The verifier: nothing reaches the fisher unless it can be reproduced from source data.

For every claim it runs three gates, in order:
  1. Provenance — each input the agent cites is re-read from the data layer. A value
     that doesn't match what the source holds is treated as fabricated.
  2. Coverage — if a needed observation is missing (cloud gap, off-grid), the claim is
     withheld rather than filled in.
  3. Reproduction — the claimed number is recomputed from the verifier's *own* reads
     (not the agent's copies) and must match within tolerance.
A claim kind with no recompute rule is unverifiable and blocked by default.
"""
import math

from . import geo, models


def _close(a, b, tol=1e-3):
    if isinstance(a, dict) and isinstance(b, dict):
        return all(k in b and _close(a[k], b[k], tol) for k in a)
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return abs(a - b) <= tol + tol * abs(b)


def _src(dl, r):
    if "series" in r:
        return dl.series[r["series"]][r["k"]]
    return dl.cell(r["field"], r["ti"], r["i"], r["j"])


def _where(r):
    if "series" in r:
        return f"{r['series']}[week {r['k']}]"
    return f"{r['field']} cell ({r['lat']:.1f}°N, {r['lon']:.1f}°E, t{r['ti']})"


# ---------------------------------------------------------------- recompute rules
def _pfz(dl, c):
    i, j = c["params"]["i"], c["params"]["j"]
    n, s = dl.cell("sst", 0, i + 1, j), dl.cell("sst", 0, i - 1, j)
    e, w = dl.cell("sst", 0, i, j + 1), dl.cell("sst", 0, i, j - 1)
    chl = dl.cell("chl", 0, i, j)
    g = models.sst_gradient(n, s, e, w, dl.lat(i))
    return ({"score": round(models.pfz_score(g, chl), 3), "grad": round(g, 4), "chl": round(chl, 3)},
            "Re-read 4 SST cells + 1 chlorophyll cell; recomputed front gradient and zone score")


def _distance(dl, c):
    (a, b), (x, y) = c["params"]["from"], c["params"]["to"]
    return ({"km": round(geo.haversine_km(a, b, x, y), 1), "bearing": round(geo.bearing_deg(a, b, x, y))},
            "Recomputed great-circle distance and bearing")


def _imbl(dl, c):
    lat, lon = c["params"]["lat"], c["params"]["lon"]
    km, near = geo.dist_to_imbl_km(lat, lon)
    return ({"km": round(km, 2), "away_bearing": round(geo.bearing_deg(near[0], near[1], lat, lon)),
             "side": geo.side(lat, lon)},
            "Recomputed shortest distance to the IMBL polyline")


def _point(dl, c):
    p = c["params"]
    v, _ = dl.sample(p["field"], p["lat"], p["lon"], p["ti"])
    return (None if v is None else round(v, 3), "Re-sampled the grid bilinearly at the point")


def _window(dl, c):
    p = c["params"]
    best, bti = None, None
    for ti in p["slices"]:
        if p["expr"] == "wind":
            u, _ = dl.sample("wu", p["lat"], p["lon"], ti)
            v, _ = dl.sample("wv", p["lat"], p["lon"], ti)
            val = math.hypot(u, v) * 3.6
        else:
            val, _ = dl.sample(p["expr"], p["lat"], p["lon"], ti)
        if val is not None and (best is None or val > best):
            best, bti = val, ti
    return (None if best is None else {"max": round(best, 2), "ti": bti},
            f"Re-sampled {len(p['slices'])} forecast slices; recomputed the window maximum")


def _drift(dl, c):
    p = c["params"]
    ens = models.drift_ensemble(dl, p["lat"], p["lon"], p["t0"], p["hours"], p["n"], p["seed"])
    return ens["stats"], f"Re-ran the {p['n']}-member RK4 drift ensemble from the same seed"


def _series_change(dl, c):
    p = c["params"]
    return ({"pct": round(models.pct_change(dl.series[p["series"]], p["recent"]), 1)},
            "Recomputed recent-vs-baseline change from the raw weekly series")


def _driver(dl, c):
    p = c["params"]
    x, y = dl.series[p["series"]], dl.series["cpue"]
    return ({"z": round(models.recent_z(x, p["recent"]), 2), "r": round(models.pearson(x, y), 2)},
            "Recomputed anomaly z-score and correlation with catch from raw series")


RULES = {"pfz_score": _pfz, "distance": _distance, "imbl_distance": _imbl, "point": _point,
         "window_max": _window, "drift": _drift, "series_change": _series_change, "driver": _driver}


def verify_one(dl, c):
    # 1. provenance
    for r in c["inputs"]:
        truth = _src(dl, r)
        if not _close(r["value"], truth, 1e-6):
            c.update(status="blocked", gate="provenance",
                     reason=f"cited {r['value']} for {_where(r)}, but the source holds {truth}")
            return c
    # 2. coverage
    missing = [r for r in c["inputs"] if r["value"] is None]
    if missing or c["value"] is None:
        c.update(status="blocked", gate="coverage",
                 reason=f"no valid observation in {len(missing) or 'required'} source cell(s) — "
                        f"likely cloud cover; refusing to fill the gap")
        return c
    # 3. reproduction
    rule = RULES.get(c["kind"])
    if rule is None:
        c.update(status="blocked", gate="reproduction", reason="no recompute rule — claim is unverifiable")
        return c
    got, how = rule(dl, c)
    c["check"] = how
    c["recomputed"] = got
    if not _close(c["value"], got):
        c.update(status="blocked", gate="reproduction", reason=f"recomputed {got}, agent claimed {c['value']}")
        return c
    c.update(status="verified", gate="passed")
    return c


def verify(dl, claims):
    return [verify_one(dl, c) for c in claims]
