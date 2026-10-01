"""The orchestrator: understand -> plan -> run specialists in parallel -> verify -> compose.

The plan is a small DAG. Specialists have no dependencies on each other, so they run
concurrently; the verifier depends on all of them; the composer depends on the
verifier and may only read claims the verifier passed.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from . import lang as L
from .agents import AGENTS
from .data import PLACES, SERIES
from .geo import compass
from .verifier import verify

AGENT_LABEL = {"fish": "Fishing-zone agent", "weather": "Weather agent", "border": "Border & drift agent",
               "ocean": "Ocean-state agent", "diagnose": "Diagnosis agent"}
ORDER = ["weather", "border", "fish", "ocean", "diagnose"]


def _ms(t0):
    return round((time.perf_counter() - t0) * 1000, 1)


def handle(dl, advisory, text, lat, lon, fault=None, lang_hint=None):
    trace = []
    t0 = time.perf_counter()
    u = L.understand(text, dl.issued, lang_hint)
    lg = u["lang"]
    trace.append({"node": "understand", "label": "Language + intent", "deps": [], "ms": _ms(t0),
                  "detail": f"lang={lg} ({u['lang_reason']}); intents={u['intents'] or '—'}; window={u['window']['key']}"
                            + (f"; place={u['place']}" if u["place"] else "")})

    if u["unsupported"]:
        trace.append({"node": "plan", "label": "Planner", "deps": ["understand"], "ms": 0,
                      "detail": "No agent or dataset can support this question → refuse"})
        line = L.t(lg, "unsupported", why=L.t(lg, "unsupported_" + u["unsupported"]))
        return _response(u, trace, [], [{"agent": "refusal", "level": "blocked", "lines": [line]}], {}, {})
    if not u["intents"]:
        return _response(u, trace, [], [{"agent": "clarify", "level": "info", "lines": [L.t(lg, "clarify")]}],
                         {}, {})

    ctx = {"lat": lat, "lon": lon, "window": u["window"], "fault": fault, "advisory": advisory,
           "place": u["place"], "place_pos": PLACES.get(u["place"])}
    plan = [a for a in ORDER if a in u["intents"]]
    trace.append({"node": "plan", "label": "Planner", "deps": ["understand"], "ms": 0,
                  "detail": f"{len(plan)} specialist(s) in parallel → verifier → composer"})

    results = {}

    def run(name):
        s = time.perf_counter()
        out = AGENTS[name](dl, ctx)
        out["ms"] = _ms(s)
        return name, out

    with ThreadPoolExecutor(max_workers=len(plan)) as ex:
        for name, out in ex.map(run, plan):
            results[name] = out
            trace.append({"node": name, "label": AGENT_LABEL[name], "deps": ["plan"], "ms": out["ms"],
                          "detail": f"{len(out['claims'])} claim(s)"})

    claims = [c for a in plan for c in results[a]["claims"]]
    s = time.perf_counter()
    verify(dl, claims)
    nb = sum(1 for c in claims if c["status"] == "blocked")
    trace.append({"node": "verifier", "label": "Verifier", "deps": plan, "ms": _ms(s),
                  "detail": f"{len(claims) - nb} verified, {nb} blocked"})

    s = time.perf_counter()
    sections = [compose(a, results[a], lg, dl, u) for a in plan]
    trace.append({"node": "compose", "label": "Composer", "deps": ["verifier"], "ms": _ms(s),
                  "detail": f"answer in {L.LANG_NAME[lg]} from verified claims only"})

    mapdata = {a: _filter_map(results[a]["map"], claims) for a in plan}
    notes = {a: results[a]["notes"] for a in plan}
    return _response(u, trace, claims, sections, mapdata, notes)


def _filter_map(m, claims):
    """Blocked claims don't get drawn either."""
    ok = {c["id"] for c in claims if c["status"] == "verified"}
    out = dict(m)
    for key in ("zones", "excluded"):
        if key in m:
            out[key] = [dict(z, withheld=not all(cid in ok for cid in z["claims"])) for z in m[key]]
    return out


def _response(u, trace, claims, sections, mapdata, notes):
    lines = [ln for s in sections for ln in s["lines"]]
    return {"understood": u, "trace": trace, "claims": claims, "sections": sections,
            "speak": " ".join(lines), "map": mapdata, "notes": notes}


# ---------------------------------------------------------------- composer
def _by_role(claims):
    return {c["params"].get("role"): c for c in claims}


def _hhmm(dl, ti):
    return dl.time_of(ti).strftime("%H:%M")


def compose(agent, res, lg, dl, u):
    cl = res["claims"]
    blocked = [c for c in cl if c["status"] != "verified"]
    lines, level = [], "info"

    if agent == "weather":
        r = _by_role(cl)
        core = [r["hs"], r["wind"], r["ts"]]
        if any(c["status"] != "verified" for c in core):
            bad = next(c for c in core if c["status"] != "verified")
            return {"agent": agent, "level": "blocked",
                    "lines": [L.t(lg, "withheld", what=L.t(lg, "w_weather"), why=L.why(lg, bad))]}
        hs, wind, ts = r["hs"]["value"]["max"], r["wind"]["value"]["max"], r["ts"]["value"]["max"]
        level = ("crit" if hs >= 2.5 or wind >= 45 or ts >= 0.6 else
                 "warn" if hs >= 1.5 or wind >= 30 or ts >= 0.3 else "ok")
        lines.append(L.t(lg, "weather_" + level, when=L.WHEN[lg][u["window"]["key"]],
                         hs=f"{hs:.1f}", wind=round(wind), ts=round(ts * 100)))
        lt, lh = r.get("later_ts"), r.get("later_hs")
        if lt and lh and lt["status"] == lh["status"] == "verified":
            lts, lhs = lt["value"], lh["value"]
            if lts["max"] >= 0.3 or lhs["max"] >= 1.5:
                ti = lts["ti"] if lts["max"] >= 0.3 else lhs["ti"]
                lines.append(L.t(lg, "weather_later", time=_hhmm(dl, ti), ts=round(lts["max"] * 100),
                                 hs=f"{lhs['max']:.1f}", back=_hhmm(dl, max(0, ti - 1))))
                if level == "ok":
                    level = "warn"

    elif agent == "border":
        d, dr = cl[0], cl[1]
        if d["status"] == "verified":
            v = d["value"]
            cmp = L.COMPASS[lg][compass(v["away_bearing"])]
            if v["side"] == "LK":
                return {"agent": agent, "level": "crit",
                        "lines": [L.t(lg, "border_other", bearing=f"{v['away_bearing']:03d}", compass=cmp)]}
            if dr["status"] == "verified":
                s, p = dr["value"], dr["params"]
                if s["p_cross"] > 0:
                    lines.append(L.t(lg, "border_risk", km=f"{v['km']:.1f}", p=round(s["p_cross"] * 100),
                                     n=p["n"], h=p["hours"], t10=f"{s['t10']:.1f}", t90=f"{s['t90']:.1f}"))
                    level = "crit" if s["p_cross_3h"] >= 0.2 or v["km"] < 2 else "warn"
                    lines.append(L.t(lg, "border_head", bearing=f"{v['away_bearing']:03d}", compass=cmp))
                else:
                    lines.append(L.t(lg, "border_far", km=f"{v['km']:.1f}", n=p["n"], h=p["hours"]))
                    level = "warn" if v["km"] < 5 else "ok"
            else:
                lines.append(L.t(lg, "withheld", what=L.t(lg, "w_border"), why=L.why(lg, dr)))
                level = "blocked"

    elif agent == "fish":
        ok = {c["id"]: c for c in cl if c["status"] == "verified"}
        zones = res["map"]["zones"]
        shown = 0
        if zones:
            lines.append(L.t(lg, "fish_intro"))
        for z in zones:
            sc, dc = (next(c for c in cl if c["id"] == cid) for cid in z["claims"])
            if sc["id"] in ok and dc["id"] in ok:
                v, dv = sc["value"], dc["value"]
                lines.append(L.t(lg, "fish_zone", id=z["id"], km=f"{dv['km']:.0f}", bearing=f"{dv['bearing']:03d}",
                                 compass=L.COMPASS[lg][compass(dv["bearing"])], grad=f"{v['grad']:.3f}",
                                 chl=f"{v['chl']:.2f}"))
                shown += 1
            else:
                bad = sc if sc["status"] != "verified" else dc
                lines.append(L.t(lg, "withheld", what=L.t(lg, "w_zone", id=z["id"]), why=L.why(lg, bad)))
        for z in res["map"]["excluded"]:
            c = ok.get(z["claims"][0])
            if c:
                lines.append(L.t(lg, "fish_excluded", km=f"{c['value']['km']:.0f}",
                                 compass=L.COMPASS[lg][compass(c["value"]["bearing"])]))
        if not zones:
            lines.append(L.t(lg, "fish_none", range=res["notes"]["range_km"]))
        level = "ok" if shown else "blocked" if blocked else "info"

    elif agent == "ocean":
        name = L.place_name(u["place"], lg)
        for c in cl:
            f = c["params"]["field"]
            if c["status"] == "verified":
                lines.append(L.t(lg, "ocean_" + f, place=name, v=f"{c['value']:.2f}"))
            else:
                lines.append(L.t(lg, "withheld", what=f"{name} · {L.t(lg, 'w_' + f)}", why=L.why(lg, c)))
        level = "blocked" if blocked else "info"

    elif agent == "diagnose":
        n = res["notes"]
        ch = cl[0]
        if ch["status"] != "verified":
            return {"agent": agent, "level": "blocked",
                    "lines": [L.t(lg, "withheld", what=L.t(lg, "w_diag"), why=L.why(lg, ch))]}
        pct = ch["value"]["pct"]
        lines.append(L.t(lg, "diag_intro", sector=L.sector_name(lg, n["sector"]), k=n["recent_weeks"], pct=f"{abs(pct):.0f}",
                         dir=L.t(lg, "down" if pct < 0 else "up")))
        ver = {c["id"]: c for c in cl if c["status"] == "verified"}
        rank = [r for r in n["ranking"] if r["claim"] in ver and r["impact"] < -0.5 and r["physical"]]
        for k, r in enumerate(rank[:3], 1):
            v = ver[r["claim"]]["value"]
            lines.append(L.t(lg, "diag_item", rank=k, label=L.DRIVER_LABEL[lg][r["driver"]],
                             updown=L.t(lg, "higher" if v["z"] > 0 else "lower"), z=f"{v['z']:+.1f}",
                             r=f"{v['r']:.2f}", link=L.t(lg, "with" if v["r"] > 0 else "against")))
        top = {r["driver"] for r in rank[:3]}
        if {"upwelling", "chl"} <= top:
            lines.append(L.t(lg, "diag_chain"))
        if "effort" not in top:
            lines.append(L.t(lg, "diag_effort"))
        lines.append(L.t(lg, "diag_caveat"))
        level = "warn"
        res["notes"]["labels"] = {d: SERIES[d]["label"] for d in SERIES}

    return {"agent": agent, "level": level, "lines": lines}
