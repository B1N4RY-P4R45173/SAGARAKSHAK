"""Minimal Ed25519 (RFC 8032) in pure Python, so the server needs no crypto dependency.

Slow (tens of ms per signature) but we sign one packet per request. Tested against
the RFC 8032 test vectors in tests/test_core.py.
"""
import hashlib

p = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
d = -121665 * pow(121666, p - 2, p) % p
I = pow(2, (p - 1) // 4, p)


def _h(m):
    return hashlib.sha512(m).digest()


def _inv(x):
    return pow(x, p - 2, p)


def _xrecover(y):
    xx = (y * y - 1) * _inv(d * y * y + 1)
    x = pow(xx, (p + 3) // 8, p)
    if (x * x - xx) % p != 0:
        x = x * I % p
    if x % 2:
        x = p - x
    return x


_By = 4 * _inv(5) % p
_Bx = _xrecover(_By)
B = (_Bx, _By, 1, _Bx * _By % p)


def _add(P, Q):
    X1, Y1, Z1, T1 = P
    X2, Y2, Z2, T2 = Q
    A = (Y1 - X1) * (Y2 - X2) % p
    Bv = (Y1 + X1) * (Y2 + X2) % p
    C = T1 * 2 * d * T2 % p
    D = Z1 * 2 * Z2 % p
    E, F, G, H = Bv - A, D - C, D + C, Bv + A
    return (E * F % p, G * H % p, F * G % p, E * H % p)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _enc(P):
    X, Y, Z, _ = P
    zi = _inv(Z)
    x, y = X * zi % p, Y * zi % p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _dec(s):
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _xrecover(y)
    if (x & 1) != sign:
        x = p - x
    return (x, y, 1, x * y % p)


def _expand(seed):
    h = _h(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    a, _ = _expand(seed)
    return _enc(_mul(a, B))


def sign(seed, msg):
    a, prefix = _expand(seed)
    A = _enc(_mul(a, B))
    r = int.from_bytes(_h(prefix + msg), "little") % L
    R = _enc(_mul(r, B))
    k = int.from_bytes(_h(R + A + msg), "little") % L
    return R + int.to_bytes((r + k * a) % L, 32, "little")


def verify(pub, msg, sig):
    try:
        A, R = _dec(pub), _dec(sig[:32])
    except Exception:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= L:
        return False
    k = int.from_bytes(_h(sig[:32] + pub + msg), "little") % L
    return _enc(_mul(s, B)) == _enc(_add(R, _mul(k, A)))
