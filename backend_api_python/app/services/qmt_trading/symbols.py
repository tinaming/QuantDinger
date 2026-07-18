"""
Symbol Mapping and Conversion for QMT (迅投 miniQMT).

Handles A-share (China A-Stock) symbol normalization for the QMT/xtquant
trading interface.

QMT stock codes are suffixed with the exchange identifier:
  - 600000.SH   (Shanghai Main Board / STAR Market)
  - 000001.SZ   (Shenzhen Main Board / ChiNext)
  - 830899.BJ   (Beijing Stock Exchange)

The caller can pass a bare 6-digit code (e.g. "600000") and the correct
exchange suffix will be auto-detected from the code prefix.
"""

from typing import Tuple


# Exchange suffixes used by QMT/xtquant for A-shares.
SH_SUFFIX = ".SH"   # Shanghai Stock Exchange (SSE)
SZ_SUFFIX = ".SZ"   # Shenzhen Stock Exchange (SZSE)
BJ_SUFFIX = ".BJ"   # Beijing Stock Exchange (BSE)

CN_SUFFIXES = {SH_SUFFIX, SZ_SUFFIX, BJ_SUFFIX}


def _detect_exchange(code: str) -> str:
    """
    Auto-detect the exchange from a 6-digit A-share code prefix.

    Shanghai (SH):
      - 60xxxx  Main Board
      - 688xxx  STAR Market (科创板)
      - 689xxx  STAR Market (CDR)
      - 11xxxx  Convertible bonds (可转债)
      - 13xxxx  State bonds / repos
      - 50xxxx  Funds / ETFs

    Shenzhen (SZ):
      - 00xxxx  Main Board
      - 002xxx  SME Board (中小板, merged into Main Board)
      - 30xxxx  ChiNext (创业板)
      - 12xxxx  Convertible bonds

    Beijing (BJ):
      - 83xxxx, 87xxxx, 92xxxx, 43xxxx, 88xxxx, 920xxx
      - 4xxxxx  Old NEEQ

    Returns the suffix ".SH" / ".SZ" / ".BJ".
    Defaults to ".SH" if detection fails.
    """
    c = code.strip()
    if not c or not c[0].isdigit():
        return SH_SUFFIX

    # Take first 3 digits for prefix matching
    prefix = c[:3]

    sh_prefixes = {"600", "601", "603", "605", "688", "689",
                   "110", "113", "118", "130", "500", "501", "502", "510",
                   "511", "512", "513", "515", "516", "517", "518", "520",
                   "522", "523", "525", "526", "588"}
    sz_prefixes = {"000", "001", "002", "003", "300", "301",
                   "120", "123", "125", "128", "159", "150", "151",
                   "152", "153", "154", "155", "159", "184", "185", "188"}
    bj_prefixes = {"430", "830", "831", "832", "833", "834", "835",
                   "836", "837", "838", "839", "870", "871", "872", "873",
                   "874", "875", "876", "877", "878", "879", "880", "889",
                   "920"}

    if prefix in sh_prefixes:
        return SH_SUFFIX
    if prefix in sz_prefixes:
        return SZ_SUFFIX
    if prefix in bj_prefixes:
        return BJ_SUFFIX

    # Fallback: 688/689 → SH, 300/301 → SZ, else default SH
    if c.startswith("6"):
        return SH_SUFFIX
    if c.startswith("0") or c.startswith("3"):
        return SZ_SUFFIX
    if c.startswith("8") or c.startswith("4") or c.startswith("9"):
        return BJ_SUFFIX
    return SH_SUFFIX


def normalize_symbol(symbol: str, suffix: str = "") -> str:
    """
    Normalize an A-share stock symbol to QMT format.

    Accepts various input formats:
      - "600000"       → "600000.SH"  (auto-detected)
      - "600000.SH"    → "600000.SH"  (unchanged)
      - "SH600000"     → "600000.SH"  (prefix-removed)
      - "sz000001"     → "000001.SZ"  (prefix-removed)
      - "600000.SS"    → "600000.SH"  (SS alias → SH)
      - "600000.XSHG"  → "600000.SH"  (XSHG alias → SH)

    Args:
        symbol: Raw symbol string.
        suffix: Optional explicit exchange suffix override.

    Returns:
        Normalized QMT symbol, e.g. ``"600000.SH"``.
    """
    s = (symbol or "").strip().upper()
    if not s:
        return ""

    # Remove common separators / whitespace
    s = s.replace(" ", "").replace("-", "").replace("_", "").replace("/", "")

    # Handle prefix-style codes: SH600000, SZ000001, BJ830899
    for pfx, sfx in (("SH", SH_SUFFIX), ("SZ", SZ_SUFFIX), ("BJ", BJ_SUFFIX),
                      ("SS", SH_SUFFIX)):  # SS is sometimes used for Shanghai
        if s.startswith(pfx) and len(s) > len(pfx):
            rest = s[len(pfx):]
            # Only strip prefix if the rest is a digit string
            if rest and rest[0].isdigit():
                s = rest + sfx
                break

    # Handle long-form aliases: XSHG → SH, XSHE → SZ
    for alias, real in ((".XSHG", SH_SUFFIX), (".XSHE", SZ_SUFFIX),
                         (".SS", SH_SUFFIX), (".SZ", SZ_SUFFIX),
                         (".SH", SH_SUFFIX), (".BJ", BJ_SUFFIX)):
        if s.endswith(alias):
            s = s[: -len(alias)] + real
            break

    # If the symbol already ends with a known CN suffix, keep it
    for sfx in CN_SUFFIXES:
        if s.endswith(sfx):
            return s

    # If there's a dot, check if the tail is a known suffix
    if "." in s:
        tail = s[s.rfind("."):]
        if tail.upper() in CN_SUFFIXES:
            return s
        # Unknown suffix — strip it and proceed to auto-detect
        s = s[: s.rfind(".")]

    # Auto-detect exchange from code prefix (or use explicit suffix)
    if suffix:
        sfx = suffix.strip().upper()
        if not sfx.startswith("."):
            sfx = "." + sfx
    else:
        sfx = _detect_exchange(s)

    return s + sfx


def parse_symbol(symbol: str) -> Tuple[str, str]:
    """
    Parse a QMT symbol and extract the clean code plus market type.

    Args:
        symbol: QMT symbol, e.g. ``"600000.SH"``.

    Returns:
        ``(clean_code, market_type)`` where ``market_type`` is always
        ``"CNStock"`` for symbols routed through this module.
    """
    clean = (symbol or "").strip().upper()
    for sfx in CN_SUFFIXES:
        if clean.endswith(sfx):
            clean = clean[: -len(sfx)]
            break
    return clean, "CNStock"
