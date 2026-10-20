"""A small, dependency-free AES-128-CBC decryptor (N10).

FreeDM only needs AES-128 to decrypt HLS segments, and the project does not
want a heavy dependency for that. If `cryptography` happens to be installed it
is used (it is much faster); otherwise this pure-Python implementation does
the job.

The implementation is verified against a reference implementation in
``tests/test_n10.py``.
"""
from __future__ import annotations

# --- the tables ------------------------------------------------------------


def _gf_mul(a: int, b: int) -> int:
    """Multiply two numbers in GF(2^8) (the AES polynomial 0x11B)."""
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


def _gf_pow(base: int, exponent: int) -> int:
    """base ** exponent in GF(2^8)."""
    result = 1
    while exponent:
        if exponent & 1:
            result = _gf_mul(result, base)
        base = _gf_mul(base, base)
        exponent >>= 1
    return result


def _rotl8(value: int, bits: int) -> int:
    """Rotate a byte left."""
    return ((value << bits) | (value >> (8 - bits))) & 0xFF


def _build_tables():
    """The AES S-box and its inverse, computed once at import time."""
    inverse = [0] * 256
    for value in range(1, 256):
        inverse[value] = _gf_pow(value, 254)
    sbox = [0] * 256
    for value in range(256):
        b = inverse[value]
        sbox[value] = (b ^ _rotl8(b, 1) ^ _rotl8(b, 2) ^ _rotl8(b, 3)
                       ^ _rotl8(b, 4) ^ 0x63)
    inv_sbox = [0] * 256
    for index, value in enumerate(sbox):
        inv_sbox[value] = index
    return sbox, inv_sbox


def _xtime(value: int) -> int:
    """Multiply by x in GF(2^8)."""
    value <<= 1
    if value & 0x100:
        value = (value ^ 0x1B) & 0xFF
    return value


SBOX, INV_SBOX = _build_tables()
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _mul(a: int, b: int) -> int:
    """Multiply two numbers in GF(2^8)."""
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


def _expand_key(key: bytes) -> list[list[int]]:
    """The AES-128 key schedule: 11 round keys of 16 bytes."""
    if len(key) != 16:
        raise ValueError("AES-128 needs a 16 byte key")
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    for index in range(4, 44):
        temp = list(words[index - 1])
        if index % 4 == 0:
            temp = temp[1:] + temp[:1]                 # RotWord
            temp = [SBOX[b] for b in temp]              # SubWord
            temp[0] ^= RCON[index // 4 - 1]
        words.append([words[index - 4][i] ^ temp[i] for i in range(4)])
    return [sum(words[r * 4:r * 4 + 4], []) for r in range(11)]


def _add_round_key(state: list[int], round_key: list[int]) -> list[int]:
    return [state[i] ^ round_key[i] for i in range(16)]


def _inv_shift_rows(state: list[int]) -> list[int]:
    """Undo the row shift: every row moves to the right by its row number.

    In flat (column-major) indices that means the element at row r, column c
    comes from row r, column (c - r)."""
    out = list(state)
    for row in range(1, 4):
        for column in range(4):
            out[column * 4 + row] = state[((column - row) % 4) * 4 + row]
    return out


def _inv_sub_bytes(state: list[int]) -> list[int]:
    return [INV_SBOX[b] for b in state]


def _inv_mix_columns(state: list[int]) -> list[int]:
    out = [0] * 16
    for column in range(4):
        a = state[column * 4:column * 4 + 4]
        out[column * 4 + 0] = _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9)
        out[column * 4 + 1] = _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13)
        out[column * 4 + 2] = _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11)
        out[column * 4 + 3] = _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)
    return out


def decrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    """Decrypt one 16-byte block with AES-128."""
    state = list(block)
    state = _add_round_key(state, round_keys[10])
    for rnd in range(9, -1, -1):
        state = _inv_shift_rows(state)
        state = _inv_sub_bytes(state)
        state = _add_round_key(state, round_keys[rnd])
        if rnd != 0:
            state = _inv_mix_columns(state)
    return bytes(state)


def decrypt_cbc(data: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt AES-128-CBC data (with PKCS#7 padding removed)."""
    if len(data) % 16:
        raise ValueError("the encrypted data is not a multiple of 16 bytes")
    round_keys = _expand_key(key)
    previous = bytearray(iv)
    out = bytearray()
    for offset in range(0, len(data), 16):
        block = data[offset:offset + 16]
        plain = decrypt_block(block, round_keys)
        out.extend(bytes(a ^ b for a, b in zip(plain, previous)))
        previous = bytearray(block)
    if out:
        padding = out[-1]
        if 1 <= padding <= 16 and out[-padding:] == bytes([padding]) * padding:
            out = out[:-padding]
    return bytes(out)
