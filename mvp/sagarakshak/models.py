"""Pure science functions shared by agents and the verifier.

Agents call these with values they fetched; the verifier calls them again with
values it re-reads from the data layer itself. Same maths, independent inputs.
"""
import math
import random

from . import geo
from .data import STEP

# ---------------------------------------------------------------- fishing zones
GRAD_REF = 0.03     # °C/km: a sharp front for this region at 0.1° resolution
CHL_REF = 0.2       # mg/m³: oligotrophic background


def sst_gradient(n, s, e, w, lat):
    """Central-difference |∇SST| in °C/km from the four neighbouring cells."""
    dy = (n - s) / (2 * STEP * 111.32)
    dx = (e - w) / (2 * STEP * geo.km_per_deg_lon(lat))
    return math.hypot(dx, dy)


def pfz_score(grad, chl):
    """INCOIS-style PFZ logic: fish gather where thermal fronts meet productive water."""
    g = min(1.0, grad / GRAD_REF)
    c = max(0.0, min(1.0, math.log10(chl / CHL_REF)))
    return 0.55 * g + 0.45 * c


# ---------------------------------------------------------------- drift (RK4 ensemble)
def _rot(u, v, deg):
    r = math.radians(deg)
    return u * math.cos(r) - v * math.sin(r), u * math.sin(r) + v * math.cos(r)


def _members(n, seed):
    rng = random.Random(seed)
    out = [dict(sc=1.0, rc=0.0, lw=0.03, rw=0.0)]  # member 0 = best estimate
    for _ in range(n - 1):
        out.append(dict(sc=rng.uniform(0.75, 1.25), rc=rng.uniform(-20, 20),
                        lw=rng.uniform(0.02, 0.045), rw=rng.uniform(-15, 15)))
    return out


def _velocity(dl, lat, lon, t, m):
    cu, cv = _rot(dl.fast("cu", lat, lon, t), dl.fast("cv", lat, lon, t), m["rc"])
    wu, wv = _rot(dl.fast("wu", lat, lon, t), dl.fast("wv", lat, lon, t), m["rw"])
    return m["sc"] * cu + m["lw"] * wu, m["sc"] * cv + m["lw"] * wv


def _deriv(dl, lat, lon, t, m):
    u, v = _velocity(dl, lat, lon, t, m)            # m/s
    return v * 3.6 / 111.32, u * 3.6 / geo.km_per_deg_lon(lat)   # deg/h


def rk4_track(dl, lat, lon, t0, hours, m, dt=1 / 6):
    """Fourth-order Runge–Kutta through the time-varying current + wind-leeway field."""
    track, cross_t, beached = [(lat, lon)], None, False
    steps_per_h = int(round(1 / dt))
    t = t0
    for h in range(hours):
        for _ in range(steps_per_h):
            if not beached:
                k1 = _deriv(dl, lat, lon, t, m)
                k2 = _deriv(dl, lat + dt / 2 * k1[0], lon + dt / 2 * k1[1], t + dt / 2, m)
                k3 = _deriv(dl, lat + dt / 2 * k2[0], lon + dt / 2 * k2[1], t + dt / 2, m)
                k4 = _deriv(dl, lat + dt * k3[0], lon + dt * k3[1], t + dt, m)
                nlat = lat + dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
                nlon = lon + dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
                if geo.is_land(nlat, nlon):
                    beached = True
                else:
                    lat, lon = nlat, nlon
            t += dt
            if cross_t is None and geo.side(lat, lon) == "LK":
                cross_t = round(t - t0, 2)
        track.append((round(lat, 5), round(lon, 5)))
    return track, cross_t


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(math.ceil(q * len(xs))) - 1))
    return xs[k]


def drift_ensemble(dl, lat, lon, t0=0.0, hours=8, n=40, seed=7):
    tracks, crosses = [], []
    for m in _members(n, seed):
        tr, ct = rk4_track(dl, lat, lon, t0, hours, m)
        tracks.append(tr)
        crosses.append(ct)
    hit = [c for c in crosses if c is not None]
    stats = {
        "p_cross": round(len(hit) / n, 2),
        "p_cross_3h": round(sum(1 for c in hit if c <= 3) / n, 2),
        "t10": pct(hit, 0.1), "t50": pct(hit, 0.5), "t90": pct(hit, 0.9),
    }
    return {"tracks": tracks, "crosses": crosses, "stats": stats}


# ---------------------------------------------------------------- statistics
def mean(xs):
    return sum(xs) / len(xs)


def std(xs):
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def pearson(a, b):
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def recent_z(xs, k):
    base, rec = xs[:-k], xs[-k:]
    return (mean(rec) - mean(base)) / std(base)


def pct_change(xs, k):
    base, rec = xs[:-k], xs[-k:]
    return (mean(rec) / mean(base) - 1) * 100
