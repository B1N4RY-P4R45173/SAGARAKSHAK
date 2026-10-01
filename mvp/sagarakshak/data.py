"""Data layer: gridded ocean/weather fields and sector time series, with provenance.

MVP NOTE: every field here is a *sample* generated deterministically from the issue
date. The shapes are physically motivated (upwelling pools, thermal fronts, a
monsoon-tail current, a moving thunderstorm cell) but they are NOT today's
observations. Each field records which real product it stands in for; swapping in
MOSDAC / INCOIS / IMD NetCDF only needs a loader that fills the same grids.

Every value handed to an agent carries an address (field, time index, i, j) so the
verifier can go back to this layer and re-read it independently.
"""
import datetime as dt
import math
import random

from . import geo

LAT0, LON0, STEP = 7.5, 77.5, 0.1
NLAT = NLON = 41                   # 7.5–11.5 N, 77.5–81.5 E
T_STEP_H, NT = 3, 17               # 0–48 h, 3-hourly
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

FIELDS = {
    "sst": dict(label="Sea surface temperature", unit="°C", static=True,
                stands_in_for="GHRSST L4 / MOSDAC SST (daily)"),
    "chl": dict(label="Chlorophyll-a", unit="mg/m³", static=True,
                stands_in_for="EOS-06 OCM-3 chlorophyll via MOSDAC (daily, cloud-gapped)"),
    "cu": dict(label="Surface current, east", unit="m/s", static=False,
               stands_in_for="INCOIS HOOFS ocean forecast"),
    "cv": dict(label="Surface current, north", unit="m/s", static=False,
               stands_in_for="INCOIS HOOFS ocean forecast"),
    "wu": dict(label="Wind 10 m, east", unit="m/s", static=False,
               stands_in_for="IMD / NCMRWF NWP"),
    "wv": dict(label="Wind 10 m, north", unit="m/s", static=False,
               stands_in_for="IMD / NCMRWF NWP"),
    "hs": dict(label="Significant wave height", unit="m", static=False,
               stands_in_for="INCOIS wave forecast"),
    "ts": dict(label="Thunderstorm probability", unit="0–1", static=False,
               stands_in_for="IMD nowcast / extended-range"),
}

SERIES = {
    "cpue": dict(label="Catch per boat-day", unit="kg", stands_in_for="fisher catch reports + CMFRI landings"),
    "sst_anom": dict(label="SST anomaly", unit="°C", expected=-1, stands_in_for="MOSDAC SST vs climatology"),
    "chl": dict(label="Chlorophyll-a", unit="mg/m³", expected=+1, stands_in_for="OCM-3 chlorophyll, sector mean"),
    "upwelling": dict(label="Upwelling index", unit="rel.", expected=+1, stands_in_for="Ekman transport from IMD winds"),
    "rain": dict(label="Rainfall / river run-off", unit="mm/wk", expected=-1, stands_in_for="IMD gridded rainfall"),
    "effort": dict(label="Fishing effort", unit="boat-days", expected=-1, stands_in_for="Dept. of Fisheries trip logs"),
}
SECTOR = {"name": "Palk Bay north (Kottaipattinam – Jegathapattinam)", "weeks": 52, "recent": 6}

PLACES = {
    # name: (lat, lon) of a sea point just off the place
    "kachchatheevu": (9.385, 79.52), "rameswaram": (9.36, 79.33), "mandapam": (9.35, 79.13),
    "pamban": (9.31, 79.20), "dhanushkodi": (9.21, 79.47), "nagapattinam": (10.77, 79.95),
    "tuticorin": (8.78, 78.30), "kottaipattinam": (10.00, 79.30), "jegathapattinam": (10.05, 79.36),
    "kodiyakarai": (10.22, 79.92),
}
PLACE_ALIASES = {
    "கச்சத்தீவு": "kachchatheevu", "katchatheevu": "kachchatheevu", "kachchativu": "kachchatheevu",
    "இராமேஸ்வரம்": "rameswaram", "ராமேஸ்வரம்": "rameswaram", "மண்டபம்": "mandapam",
    "பாம்பன்": "pamban", "தனுஷ்கோடி": "dhanushkodi", "நாகப்பட்டினம்": "nagapattinam",
    "தூத்துக்குடி": "tuticorin", "thoothukudi": "tuticorin", "கோட்டைப்பட்டினம்": "kottaipattinam",
    "ஜெகதாப்பட்டினம்": "jegathapattinam", "கோடியக்கரை": "kodiyakarai", "point calimere": "kodiyakarai",
    "కచ్చతీవు": "kachchatheevu", "రామేశ్వరం": "rameswaram", "మండపం": "mandapam", "పాంబన్": "pamban",
    "ధనుష్కోడి": "dhanushkodi", "నాగపట్టినం": "nagapattinam", "తూత్తుకుడి": "tuticorin",
    "కోట్టైపట్టినం": "kottaipattinam", "జగదాపట్టినం": "jegathapattinam", "కోడియక్కరై": "kodiyakarai",
}


def _g(lat, lon, clat, clon, s):
    return math.exp(-((lat - clat) ** 2 + (lon - clon) ** 2) / (2 * s * s))


class DataLayer:
    def __init__(self, issued=None):
        now = issued or dt.datetime.now(IST)
        self.issued = now.replace(minute=0, second=0, microsecond=0, hour=now.hour - now.hour % T_STEP_H)
        self.seed = int(self.issued.strftime("%Y%m%d"))
        rng = random.Random(self.seed)
        # smooth "weather noise": a few low-wavenumber sinusoids with random phase
        self._waves = [(rng.uniform(1.5, 4), rng.uniform(1.5, 4), rng.uniform(0, 6.28)) for _ in range(4)]
        tomorrow_15 = (self.issued + dt.timedelta(days=1)).replace(hour=15)
        self.storm_peak_h = (tomorrow_15 - self.issued).total_seconds() / 3600
        self.land = [[geo.is_land(self.lat(i), self.lon(j)) for j in range(NLON)] for i in range(NLAT)]
        self.grids = {f: self._build(f) for f in FIELDS}
        self.series = self._build_series(rng)

    # ---- grid geometry -------------------------------------------------
    @staticmethod
    def lat(i):
        return round(LAT0 + i * STEP, 4)

    @staticmethod
    def lon(j):
        return round(LON0 + j * STEP, 4)

    def time_of(self, ti):
        return self.issued + dt.timedelta(hours=ti * T_STEP_H)

    def ti_for(self, hours):
        return max(0, min(NT - 1, int(round(hours / T_STEP_H))))

    def in_bounds(self, lat, lon):
        return LAT0 <= lat <= LAT0 + (NLAT - 1) * STEP and LON0 <= lon <= LON0 + (NLON - 1) * STEP

    # ---- field synthesis ----------------------------------------------
    def _noise(self, lat, lon, amp):
        return amp * sum(math.sin(a * lat + b * lon + p) for a, b, p in self._waves) / len(self._waves)

    def _storm(self, lat, lon, t):
        env = math.exp(-((t - self.storm_peak_h) / 3.5) ** 2)
        clat = 9.3 + 0.03 * (t - self.storm_peak_h)
        clon = 79.3 + 0.03 * (t - self.storm_peak_h)
        return env * _g(lat, lon, clat, clon, 0.35)

    def _value(self, f, lat, lon, t):
        if f == "sst":
            return (28.9 + 0.12 * (lat - 9.5)
                    - 1.1 * _g(lat, lon, 8.85, 78.6, 0.30)       # Gulf of Mannar upwelling pool
                    - 0.75 * _g(lat, lon, 9.86, 79.30, 0.13)     # Palk Bay cool eddy
                    - 0.65 * _g(lat, lon, 9.78, 79.80, 0.10)     # feature across the IMBL
                    + self._noise(lat, lon, 0.12))
        if f == "chl":
            if _g(lat, lon, 9.385, 79.52, 0.07) > 0.35 or _g(lat, lon, 10.7, 80.8, 0.22) > 0.4:
                return None                                       # cloud gap: no retrieval
            c = (0.22 + 1.6 * _g(lat, lon, 8.85, 78.6, 0.28) + 1.3 * _g(lat, lon, 9.86, 79.30, 0.12)
                 + 1.5 * _g(lat, lon, 9.78, 79.80, 0.09) + self._noise(lat, lon, 0.08))
            return max(0.05, c)
        tide = 0.12 * math.cos(2 * math.pi * t / 12.42 + 0.7)
        if f == "cu":
            return 0.17 + tide * math.sin(math.radians(60)) + self._noise(lat, lon, 0.04) \
                - 0.08 * (lat - 9.86) / 0.3 * _g(lat, lon, 9.86, 79.30, 0.25)
        if f == "cv":
            return 0.04 + tide * math.cos(math.radians(60)) + self._noise(lon, lat, 0.04) \
                + 0.08 * (lon - 79.30) / 0.3 * _g(lat, lon, 9.86, 79.30, 0.25)
        diurnal = math.sin(2 * math.pi * ((self.issued.hour + t) % 24 - 9) / 24)
        s = self._storm(lat, lon, t)
        if f == "wu":
            return 5.2 + 1.0 * diurnal + 7 * s + self._noise(lat, lon, 0.6)
        if f == "wv":
            return 2.2 + 0.5 * diurnal + 4 * s + self._noise(lon, lat, 0.6)
        if f == "hs":
            w = math.hypot(self._value("wu", lat, lon, t), self._value("wv", lat, lon, t))
            shelter = -0.25 if (9.3 < lat < 10.3 and 78.9 < lon < 79.9) else 0.0
            exposed = 0.45 if (lat > 10.2 and lon > 80.0) or lat < 8.4 else 0.0
            return max(0.2, 0.35 + 0.075 * w + 1.9 * s + shelter + exposed)
        if f == "ts":
            return min(1.0, 0.03 + 0.9 * self._storm(lat, lon, t))
        raise KeyError(f)

    def _build(self, f):
        slices = 1 if FIELDS[f]["static"] else NT
        out = []
        for ti in range(slices):
            t = ti * T_STEP_H
            grid = []
            for i in range(NLAT):
                row = []
                for j in range(NLON):
                    if self.land[i][j]:
                        row.append(0.0 if f in ("cu", "cv", "wu", "wv", "ts") else None)
                    else:
                        v = self._value(f, self.lat(i), self.lon(j), t)
                        row.append(None if v is None else round(v, 4))
                grid.append(row)
            out.append(grid)
        return out

    def _build_series(self, rng):
        n, k = SECTOR["weeks"], SECTOR["recent"]
        s = {name: [] for name in SERIES}
        for w in range(n):
            seas = math.sin(2 * math.pi * w / 52)
            recent = w >= n - k
            up = 1.0 + 0.5 * seas + rng.gauss(0, 0.15) - (0.85 if recent else 0)
            sst_a = -0.45 * (up - 1) + rng.gauss(0, 0.12)
            chl = max(0.1, 0.9 + 0.45 * (up - 1) - 0.15 * sst_a + rng.gauss(0, 0.07))
            rain = max(0.0, 18 + 14 * max(0, -seas) + rng.gauss(0, 5))
            effort = 100 + rng.gauss(0, 7) + (11 if recent else 0)
            cpue = max(2.0, 31 + 19 * (chl - 0.9) - 0.06 * (effort - 100) + rng.gauss(0, 1.8))
            for name, v in (("cpue", cpue), ("sst_anom", sst_a), ("chl", chl), ("upwelling", up),
                            ("rain", rain), ("effort", effort)):
                s[name].append(round(v, 3))
        return s

    # ---- read API (what agents and the verifier use) ------------------
    def cell(self, f, ti, i, j):
        g = self.grids[f]
        return g[0 if FIELDS[f]["static"] else ti][i][j]

    def ref(self, f, ti, i, j, **extra):
        ti = 0 if FIELDS[f]["static"] else ti
        r = {"field": f, "ti": ti, "i": i, "j": j, "lat": self.lat(i), "lon": self.lon(j),
             "value": self.cell(f, ti, i, j)}
        r.update(extra)
        return r

    def corners(self, lat, lon):
        """Bilinear corner indices and weights for a point."""
        x = (lon - LON0) / STEP
        y = (lat - LAT0) / STEP
        j0 = max(0, min(NLON - 2, int(math.floor(x))))
        i0 = max(0, min(NLAT - 2, int(math.floor(y))))
        fx, fy = x - j0, y - i0
        return [(i0, j0, (1 - fx) * (1 - fy)), (i0, j0 + 1, fx * (1 - fy)),
                (i0 + 1, j0, (1 - fx) * fy), (i0 + 1, j0 + 1, fx * fy)]

    def sample(self, f, lat, lon, ti=0):
        """Bilinear value + the four source refs. None if any corner has no data."""
        refs = [self.ref(f, ti, i, j, w=round(w, 6)) for i, j, w in self.corners(lat, lon)]
        if any(r["value"] is None for r in refs):
            return None, refs
        return sum(r["value"] * r["w"] for r in refs), refs

    def fast(self, f, lat, lon, t_hours=0.0):
        """Unrecorded bilinear read, interpolating in time too. Used inside the drift integrator."""
        if not self.in_bounds(lat, lon):
            return 0.0
        tf = max(0.0, min((NT - 1) * T_STEP_H, t_hours)) / T_STEP_H
        t0 = min(NT - 2, int(tf))
        a = tf - t0
        out = 0.0
        for ti, wt in ((t0, 1 - a), (t0 + 1, a)):
            if wt == 0:
                continue
            for i, j, w in self.corners(lat, lon):
                v = self.cell(f, ti, i, j)
                out += wt * w * (v or 0.0)
        return out

    def provenance(self, f):
        meta = FIELDS.get(f) or SERIES.get(f)
        return {"field": f, "label": meta["label"], "unit": meta["unit"],
                "stands_in_for": meta["stands_in_for"], "mode": "SAMPLE",
                "issued": self.issued.isoformat()}
