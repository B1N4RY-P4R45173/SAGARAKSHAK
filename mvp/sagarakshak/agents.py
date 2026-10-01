"""The specialist agents. Each takes the data layer and a request context and returns
claims (numbers + the exact source cells they came from) plus map geometry.
"""
from . import geo, models
from .claims import claim
from .data import NLAT, NLON, SECTOR, SERIES

RANGE_KM = 90          # typical day-trip range for a mechanised boat
ZONE_SEP_KM = 22
ZONE_MIN_SCORE = 0.55


# ---------------------------------------------------------------- fishing zones
def regional_advisory(dl):
    """Region-wide PFZ advisory for the day, like the one INCOIS issues.

    Scores every sea cell on SST-front strength and chlorophyll, then keeps
    well-separated local maxima. Zones across the IMBL are kept but flagged.
    """
    cands = []
    for i in range(1, NLAT - 1):
        for j in range(1, NLON - 1):
            if dl.land[i][j]:
                continue
            n, s = dl.cell("sst", 0, i + 1, j), dl.cell("sst", 0, i - 1, j)
            e, w = dl.cell("sst", 0, i, j + 1), dl.cell("sst", 0, i, j - 1)
            c = dl.cell("chl", 0, i, j)
            if None in (n, s, e, w, c):
                continue
            g = models.sst_gradient(n, s, e, w, dl.lat(i))
            cands.append((models.pfz_score(g, c), i, j, g, c))
    cands.sort(reverse=True)
    zones = []
    for sc, i, j, g, c in cands:
        if sc < ZONE_MIN_SCORE:
            break
        la, lo = dl.lat(i), dl.lon(j)
        if any(geo.haversine_km(la, lo, z["lat"], z["lon"]) < ZONE_SEP_KM for z in zones):
            continue
        zones.append({"id": f"Z{len(zones) + 1}", "lat": la, "lon": lo, "i": i, "j": j,
                      "score": round(sc, 3), "grad": round(g, 4), "chl": round(c, 3),
                      "side": geo.side(la, lo), "radius_km": 8})
        if len(zones) >= 10:
            break
    return zones


def fishing_zone_agent(dl, ctx):
    lat0, lon0 = ctx["lat"], ctx["lon"]
    adv = ctx["advisory"]
    near = sorted(
        ({**z, "km": geo.haversine_km(lat0, lon0, z["lat"], z["lon"])} for z in adv),
        key=lambda z: z["km"])
    near = [z for z in near if z["km"] <= RANGE_KM]
    ours = [z for z in near if z["side"] == "IN"][:3]
    across = [z for z in near if z["side"] == "LK"]
    best_in = max((z["score"] for z in ours), default=0)
    across = [z for z in across if z["score"] > best_in][:1]

    claims, zones = [], []
    for k, z in enumerate(ours):
        i, j = z["i"], z["j"]
        refs = [dl.ref("sst", 0, i + 1, j, role="N"), dl.ref("sst", 0, i - 1, j, role="S"),
                dl.ref("sst", 0, i, j + 1, role="E"), dl.ref("sst", 0, i, j - 1, role="W"),
                dl.ref("chl", 0, i, j, role="centre")]
        grad, chl = z["grad"], z["chl"]
        if ctx.get("fault") == "pfz" and k == 0:
            # Fault injection: the agent "remembers" a greener sea than the satellite saw.
            refs[4]["value"] = round(refs[4]["value"] * 2.6, 4)
            chl = refs[4]["value"]
        score = round(models.pfz_score(grad, chl), 3)
        c1 = claim("fish", "pfz_score", {"score": score, "grad": grad, "chl": chl}, refs,
                   {"i": i, "j": j, "lat": z["lat"]}, label=f"Zone {z['id']} strength")
        brg = geo.bearing_deg(lat0, lon0, z["lat"], z["lon"])
        c2 = claim("fish", "distance", {"km": round(z["km"], 1), "bearing": round(brg)}, [],
                   {"from": [lat0, lon0], "to": [z["lat"], z["lon"]]}, label=f"Zone {z['id']} distance")
        claims += [c1, c2]
        zones.append({"id": z["id"], "lat": z["lat"], "lon": z["lon"], "radius_km": z["radius_km"],
                      "claims": [c1["id"], c2["id"]]})
    excluded = []
    for z in across:
        brg = geo.bearing_deg(lat0, lon0, z["lat"], z["lon"])
        c = claim("fish", "distance", {"km": round(z["km"], 1), "bearing": round(brg)}, [],
                  {"from": [lat0, lon0], "to": [z["lat"], z["lon"]]}, label=f"Zone {z['id']} (across IMBL)")
        claims.append(c)
        excluded.append({"id": z["id"], "lat": z["lat"], "lon": z["lon"], "radius_km": z["radius_km"],
                         "claims": [c["id"]]})
    return {"agent": "fish", "claims": claims, "map": {"zones": zones, "excluded": excluded},
            "notes": {"range_km": RANGE_KM}}


# ---------------------------------------------------------------- weather / sea state
def _window_claim(dl, agent, expr, lat, lon, slices, label, unit):
    refs, best, best_ti = [], None, None
    for ti in slices:
        if expr == "wind":
            u, ru = dl.sample("wu", lat, lon, ti)
            v, rv = dl.sample("wv", lat, lon, ti)
            val = (u * u + v * v) ** 0.5 * 3.6
            refs += ru + rv
        else:
            val, r = dl.sample(expr, lat, lon, ti)
            refs += r
        if val is not None and (best is None or val > best):
            best, best_ti = val, ti
    value = None if best is None else {"max": round(best, 2), "ti": best_ti}
    return claim(agent, "window_max", value, refs,
                 {"expr": expr, "lat": lat, "lon": lon, "slices": list(slices)}, label=label, unit=unit)


def weather_agent(dl, ctx):
    lat, lon = ctx["lat"], ctx["lon"]
    t0, t1 = ctx["window"]["t0"], ctx["window"]["t1"]
    win = list(range(dl.ti_for(t0), dl.ti_for(t1) + 1))
    later = list(range(win[-1] + 1, min(win[-1] + 5, 17)))
    claims = [
        _window_claim(dl, "weather", "hs", lat, lon, win, "Max wave height in window", "m"),
        _window_claim(dl, "weather", "wind", lat, lon, win, "Max wind in window", "km/h"),
        _window_claim(dl, "weather", "ts", lat, lon, win, "Max thunderstorm chance in window", "0–1"),
    ]
    if later:
        claims += [
            _window_claim(dl, "weather", "ts", lat, lon, later, "Thunderstorm chance, 12 h after", "0–1"),
            _window_claim(dl, "weather", "hs", lat, lon, later, "Wave height, 12 h after", "m"),
        ]
    for c, role in zip(claims, ["hs", "wind", "ts", "later_ts", "later_hs"]):
        c["params"]["role"] = role
    return {"agent": "weather", "claims": claims, "map": {}, "notes": {"slices": win, "later": later}}


# ---------------------------------------------------------------- border / drift
DRIFT_HOURS, DRIFT_N = 8, 40


def border_agent(dl, ctx):
    lat, lon = ctx["lat"], ctx["lon"]
    km, near = geo.dist_to_imbl_km(lat, lon)
    away = geo.bearing_deg(near[0], near[1], lat, lon)
    c1 = claim("border", "imbl_distance",
               {"km": round(km, 2), "away_bearing": round(away), "side": geo.side(lat, lon)}, [],
               {"lat": lat, "lon": lon}, label="Distance to IMBL")
    seed = int(abs(lat * 1000) + abs(lon * 1000)) % 100000
    ens = models.drift_ensemble(dl, lat, lon, 0.0, DRIFT_HOURS, DRIFT_N, seed)
    refs = []
    for f in ("cu", "cv", "wu", "wv"):
        refs += dl.sample(f, lat, lon, 0)[1]
    c2 = claim("border", "drift", ens["stats"], refs,
               {"lat": lat, "lon": lon, "t0": 0.0, "hours": DRIFT_HOURS, "n": DRIFT_N, "seed": seed},
               label="Engine-off drift, RK4 ensemble")
    pts = [(lat, lon)] + [p for tr in ens["tracks"] for p in tr]
    iso = {}
    for h in (2, 4, 6, 8):
        iso[h] = geo.convex_hull([tr[h] for tr in ens["tracks"]])
    return {"agent": "border", "claims": [c1, c2],
            "map": {"cone": geo.convex_hull(pts), "center": ens["tracks"][0], "iso": iso,
                    "nearest": near, "crossing_members": sum(1 for c in ens["crosses"] if c is not None),
                    "imbl": geo.imbl_near(lat, lon, 150)},
            "notes": {}}


# ---------------------------------------------------------------- point ocean state
def ocean_agent(dl, ctx):
    lat, lon = ctx.get("place_pos") or (ctx["lat"], ctx["lon"])
    claims = []
    for f, unit in (("sst", "°C"), ("chl", "mg/m³")):
        v, refs = dl.sample(f, lat, lon, 0)
        claims.append(claim("ocean", "point", None if v is None else round(v, 3), refs,
                            {"field": f, "lat": lat, "lon": lon, "ti": 0},
                            label=f"{f.upper()} at {ctx.get('place') or 'boat'}", unit=unit))
    return {"agent": "ocean", "claims": claims, "map": {"point": [lat, lon]}, "notes": {}}


# ---------------------------------------------------------------- diagnosis
DRIVERS = ["upwelling", "chl", "sst_anom", "rain", "effort"]


def diagnosis_agent(dl, ctx):
    k = SECTOR["recent"]
    s = dl.series
    cp_refs = [{"series": "cpue", "k": n, "value": v} for n, v in enumerate(s["cpue"])]
    c0 = claim("diagnose", "series_change", {"pct": round(models.pct_change(s["cpue"], k), 1)}, cp_refs,
               {"series": "cpue", "recent": k}, label="Change in catch per boat-day")
    claims, ranking = [c0], []
    for d in DRIVERS:
        z = models.recent_z(s[d], k)
        r = models.pearson(s[d], s["cpue"])
        refs = [{"series": d, "k": n, "value": v} for n, v in enumerate(s[d])]
        c = claim("diagnose", "driver", {"z": round(z, 2), "r": round(r, 2)}, refs + cp_refs,
                  {"series": d, "recent": k}, label=f"Driver: {SERIES[d]['label']}")
        claims.append(c)
        # A driver explains a *fall* in catch when its anomaly × its link to catch is negative.
        impact = z * r
        physical = (r > 0) == (SERIES[d]["expected"] > 0)
        ranking.append({"driver": d, "claim": c["id"], "impact": round(impact, 2), "physical": physical})
    ranking.sort(key=lambda x: x["impact"])
    return {"agent": "diagnose", "claims": claims, "map": {},
            "notes": {"ranking": ranking, "sector": SECTOR["name"], "recent_weeks": k,
                      "series": s, "weeks": SECTOR["weeks"]}}


AGENTS = {"fish": fishing_zone_agent, "weather": weather_agent, "border": border_agent,
          "ocean": ocean_agent, "diagnose": diagnosis_agent}
