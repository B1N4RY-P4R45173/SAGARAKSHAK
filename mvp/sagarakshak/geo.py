"""Geometry: distances, bearings, the India–Sri Lanka IMBL, and a coarse land mask.

The IMBL vertices follow the 1974 (Palk Bay) and 1976 (Gulf of Mannar / Bay of Bengal)
India–Sri Lanka agreements, rounded to ~0.1'. They are for demonstration only and
must be checked against the official chart before any operational use.
"""
import math

R_KM = 6371.0088

# (lat, lon), ordered north -> south. Latitude is monotonic along this stretch,
# which lets us express the line as lon = f(lat).
IMBL = [
    (11.2667, 82.4067),
    (11.0450, 81.9333),
    (10.6950, 81.0417),
    (10.5500, 80.7667),
    (10.1400, 80.1583),
    (10.0833, 80.0500),   # Palk Bay position 1
    (9.9500, 79.5833),
    (9.6692, 79.3767),
    (9.3633, 79.5117),
    (9.2167, 79.5333),
    (9.1000, 79.5333),    # Gulf of Mannar begins
    (8.8967, 79.4883),
    (8.6667, 79.3033),
    (8.6200, 79.2167),
    (8.5200, 79.0783),
    (8.3700, 78.9233),
    (8.2033, 78.8950),
    (7.5883, 78.7617),
    (7.3500, 78.6467),
    (6.5133, 78.2033),
]

# Coarse coastline polygons (lat, lon). Good enough to keep drift and fishing
# zones off land at 0.1° resolution; not a navigation chart.
LAND = {
    "india": [
        (8.08, 77.55), (8.20, 77.85), (8.35, 78.05), (8.50, 78.12), (8.78, 78.14),
        (9.08, 78.37), (9.17, 78.58), (9.24, 78.95), (9.27, 79.12), (9.31, 79.12),
        (9.40, 78.98), (9.48, 78.90), (9.62, 78.96), (9.74, 79.02), (9.90, 79.12),
        (10.03, 79.25), (10.20, 79.32), (10.33, 79.39), (10.35, 79.55), (10.30, 79.75),
        (10.28, 79.86), (10.40, 79.86), (10.77, 79.85), (11.10, 79.86), (11.50, 79.77),
        (12.20, 79.90), (12.20, 76.80), (8.00, 76.80), (8.08, 77.55),
    ],
    "rameswaram": [
        (9.26, 79.19), (9.31, 79.22), (9.32, 79.31), (9.26, 79.37), (9.19, 79.42),
        (9.15, 79.45), (9.17, 79.39), (9.23, 79.30), (9.24, 79.21),
    ],
    "srilanka": [
        (9.83, 80.25), (9.78, 80.05), (9.66, 79.98), (9.70, 79.87), (9.62, 79.90),
        (9.50, 80.12), (9.30, 80.10), (9.02, 80.05), (8.98, 79.92), (9.05, 79.76),
        (9.10, 79.72), (9.03, 79.70), (8.95, 79.88), (8.75, 79.93), (8.23, 79.76),
        (7.50, 79.80), (7.00, 79.85), (6.50, 80.00), (5.95, 80.50), (6.40, 81.60),
        (7.70, 81.72), (8.60, 81.22), (9.28, 80.82), (9.83, 80.25),
    ],
    "delft": [(9.55, 79.66), (9.54, 79.72), (9.49, 79.72), (9.49, 79.66)],
}


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_KM * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass(bearing):
    return COMPASS[int((bearing + 22.5) // 45) % 8]


def km_per_deg_lon(lat):
    return 111.32 * math.cos(math.radians(lat))


def boundary_lon(lat):
    """Longitude of the IMBL at a given latitude, or None outside its extent."""
    if lat > IMBL[0][0] or lat < IMBL[-1][0]:
        return None
    for (la1, lo1), (la2, lo2) in zip(IMBL, IMBL[1:]):
        if la2 <= lat <= la1:
            f = (lat - la2) / (la1 - la2) if la1 != la2 else 0
            return lo2 + f * (lo1 - lo2)
    return None


def side(lat, lon):
    """'IN' (Indian side, west of the line) or 'LK'."""
    b = boundary_lon(lat)
    if b is None:
        return "IN"
    return "IN" if lon < b else "LK"


def dist_to_imbl_km(lat, lon):
    """Shortest distance to the IMBL polyline and the nearest point on it."""
    best = (float("inf"), None)
    kx = km_per_deg_lon(lat)
    for (a_lat, a_lon), (b_lat, b_lon) in zip(IMBL, IMBL[1:]):
        ax, ay = (a_lon - lon) * kx, (a_lat - lat) * 111.32
        bx, by = (b_lon - lon) * kx, (b_lat - lat) * 111.32
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, -(ax * dx + ay * dy) / L2))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if d < best[0]:
            best = (d, (lat + py / 111.32, lon + px / kx))
    return best


def point_in_poly(lat, lon, poly):
    inside = False
    n = len(poly)
    for k in range(n):
        y1, x1 = poly[k]
        y2, x2 = poly[(k + 1) % n]
        if (y1 > lat) != (y2 > lat):
            xi = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < xi:
                inside = not inside
    return inside


def is_land(lat, lon):
    return any(point_in_poly(lat, lon, p) for p in LAND.values())


def imbl_near(lat, lon, radius_km=80):
    """IMBL vertices within a radius, padded with one vertex either side."""
    idx = [k for k, (a, b) in enumerate(IMBL) if haversine_km(lat, lon, a, b) <= radius_km]
    if not idx:
        return []
    lo, hi = max(0, min(idx) - 1), min(len(IMBL) - 1, max(idx) + 1)
    return IMBL[lo:hi + 1]


def convex_hull(points):
    """Monotone chain hull of (lat, lon) points."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]
