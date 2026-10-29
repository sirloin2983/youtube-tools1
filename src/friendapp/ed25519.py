"""Ed25519 の署名と確かめ(RFC 8032 の 6 章の参照の形・純 Python。安全面の直し 1・10-29)。
友人の PC は更新の latest.json の署名を確かめるだけ(1 KB を 1 回 = 遅さは問題にならない)。署名はユーザーの PC の道具(dev/signing_key.py・build_friend_zip)が作る。
外の部品(cryptography)を友人の zip に増やさないための物。定数時間ではない = 秘密鍵を持つのはユーザーの PC だけ"""
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493   # 群の位数


def _sha512(b):
    return hashlib.sha512(b).digest()


def _inv(x):
    return pow(x, P - 2, P)


D = -121665 * _inv(121666) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A = (y1 - x1) * (y2 - x2) % P
    B = (y1 + x1) * (y2 + x2) % P
    C = 2 * t1 * t2 * D % P
    Dd = 2 * z1 * z2 % P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def _mul(s, pt):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _equal(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * _inv(5) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def _compress(pt):
    zi = _inv(pt[2])
    x, y = pt[0] * zi % P, pt[1] * zi % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(b):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _expand(seed):
    h = _sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _hmod(b):
    return int.from_bytes(_sha512(b), "little") % L


def public_key(seed):
    """秘密鍵(32 バイトの種)-> 公開鍵(32 バイト)"""
    if not isinstance(seed, bytes) or len(seed) != 32:
        raise ValueError("秘密鍵は 32 バイト")
    return _compress(_mul(_expand(seed)[0], G))


def sign(seed, msg):
    """-> 署名(64 バイト)"""
    a, prefix = _expand(seed)
    pub = _compress(_mul(a, G))
    r = _hmod(prefix + msg)
    rs = _compress(_mul(r, G))
    s = (r + _hmod(rs + pub + msg) * a) % L
    return rs + int.to_bytes(s, 32, "little")


def verify(pub, msg, sig):
    """署名が合うか(形の違う物も False)"""
    if not (isinstance(pub, bytes) and isinstance(sig, bytes) and isinstance(msg, bytes)) or len(pub) != 32 or len(sig) != 64:
        return False
    a = _decompress(pub)
    r = _decompress(sig[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= L:
        return False
    h = _hmod(sig[:32] + pub + msg)
    return _equal(_mul(s, G), _add(r, _mul(h, a)))
