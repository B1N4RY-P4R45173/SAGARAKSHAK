"""SAGARAKSHAK MVP server. Standard library only:  python server.py  ->  http://localhost:8000"""
import json
import mimetypes
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import time

from sagarakshak import geo, lang, packet, tts
from sagarakshak.agents import regional_advisory
from sagarakshak.data import FIELDS, LAT0, LON0, NLAT, NLON, PLACES, STEP, DataLayer, IST
from sagarakshak.feedback import FeedbackStore
from sagarakshak.orchestrator import handle

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
DATA = os.path.join(ROOT, "data")


class State:
    lock = threading.Lock()

    def __init__(self):
        self.key, self.pub = packet.load_key(os.path.join(DATA, "packet_key.bin"))
        self.refresh(force=True)

    def refresh(self, force=False):
        """Rebuild the data layer when a new 3-hourly issue is due."""
        import datetime as dt
        with self.lock:
            now = dt.datetime.now(IST)
            if force or (now - self.dl.issued).total_seconds() >= 3 * 3600:
                self.dl = DataLayer()
                self.advisory = regional_advisory(self.dl)
                self.feedback = FeedbackStore(os.path.join(DATA, "catches.json"), self.dl, self.advisory)


S = State()


def meta():
    dl = S.dl
    return {
        "issued": dl.issued.isoformat(), "storm_peak_h": dl.storm_peak_h,
        "bounds": [[LAT0, LON0], [LAT0 + (NLAT - 1) * STEP, LON0 + (NLON - 1) * STEP]],
        "grid": {"lat0": LAT0, "lon0": LON0, "step": STEP, "nlat": NLAT, "nlon": NLON},
        "fields": {f: dl.provenance(f) for f in FIELDS},
        "imbl": geo.IMBL, "land": geo.LAND, "places": PLACES,
        "advisory": [{k: z[k] for k in ("id", "lat", "lon", "score", "side", "radius_km")} for z in S.advisory],
        "pubkey": S.pub.hex(), "mode": "SAMPLE",
        "lang_markers": {**lang.MARKERS, "weak": sorted(lang.WEAK)},
    }


def layer(q):
    f = q.get("field", ["sst"])[0]
    ti = int(q.get("t", ["0"])[0])
    if f == "wind":
        g = [[None if S.dl.land[i][j] else round((S.dl.cell("wu", ti, i, j) ** 2 + S.dl.cell("wv", ti, i, j) ** 2) ** .5 * 3.6, 1)
              for j in range(NLON)] for i in range(NLAT)]
    elif f == "currents":
        g = [[[S.dl.cell("cu", ti, i, j), S.dl.cell("cv", ti, i, j)] for j in range(NLON)] for i in range(NLAT)]
        return {"field": f, "ti": ti, "time": S.dl.time_of(ti).isoformat(), "vectors": g,
                "land": S.dl.land}
    else:
        g = S.dl.grids[f][0 if FIELDS[f]["static"] else ti]
    vals = [v for row in g for v in row if v is not None]
    return {"field": f, "ti": ti, "time": S.dl.time_of(ti).isoformat(), "grid": g,
            "min": min(vals), "max": max(vals), "land": S.dl.land}


_voices = {"t": 0, "v": []}


def host_voices():
    """Windows voices on this host, re-checked every 30 s so a newly installed voice shows up."""
    if time.time() - _voices["t"] > 30:
        _voices.update(t=time.time(), v=tts.voices())
    langs = {loc.split("-")[0] for loc, _ in _voices["v"]}
    return {"available": tts.available(), "voices": _voices["v"], **{k: k in langs for k in ("en", "ta", "te")}}


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  %s %s\n" % (self.command, self.path))

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        S.refresh()
        try:
            if u.path == "/api/meta":
                return self._json(meta())
            if u.path == "/api/layer":
                return self._json(layer(q))
            if u.path == "/api/packet":
                lat, lon = float(q["lat"][0]), float(q["lon"][0])
                return self._json(packet.build(S.dl, S.advisory, lat, lon, S.key))
            if u.path == "/api/scorecard":
                return self._json(S.feedback.scorecard())
            if u.path == "/api/voices":
                return self._json(host_voices())
        except (KeyError, ValueError) as e:
            return self._json({"error": f"bad request: {e}"}, 400)
        return self._static(u.path)

    def do_POST(self):
        u = urlparse(self.path)
        S.refresh()
        try:
            b = self._body()
            if u.path == "/api/ask":
                lat, lon = float(b["lat"]), float(b["lon"])
                if not S.dl.in_bounds(lat, lon):
                    return self._json({"error": "Position is outside the demo region (7.5–11.5°N, 77.5–81.5°E)."}, 400)
                if geo.is_land(lat, lon):
                    return self._json({"error": "That position is on land. Drag the boat onto the sea."}, 400)
                return self._json(handle(S.dl, S.advisory, str(b.get("text", ""))[:500], lat, lon, b.get("fault"),
                                         b.get("lang")))
            if u.path == "/api/tts":
                return self._tts(str(b.get("text", ""))[:2000], b.get("lang") if b.get("lang") in ("ta", "te") else "en")
            if u.path == "/api/catch":
                r = {"lat": float(b["lat"]), "lon": float(b["lon"]), "kg": float(b["kg"]),
                     "hours": max(0.5, float(b["hours"])), "species": str(b.get("species", ""))[:40],
                     "water_temp": None if b.get("water_temp") in (None, "") else float(b["water_temp"])}
                ev = S.feedback.add(r)
                return self._json({"evaluation": ev, "scorecard": S.feedback.scorecard()})
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            return self._json({"error": f"bad request: {e}"}, 400)
        self._json({"error": "not found"}, 404)

    def _tts(self, text, lang):
        if not text.strip():
            return self._json({"error": "empty text"}, 400)
        try:
            wav = tts.synth(text, lang)
        except tts.NoVoice as e:
            return self._json({"error": str(e), "novoice": True}, 404)
        except Exception as e:  # PowerShell / WinRT failure: report, don't crash the server
            return self._json({"error": f"speech synthesis failed: {e}"}, 500)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav)))
        self.end_headers()
        self.wfile.write(wav)

    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8000))
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    print(f"SAGARAKSHAK MVP  ·  data issued {S.dl.issued:%Y-%m-%d %H:%M} IST (SAMPLE data)")
    print(f"open  http://localhost:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    mimetypes.add_type("text/javascript", ".js")
    main()
