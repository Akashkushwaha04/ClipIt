"""Hinglish transliteration and font compatibility engine.

Converts Devanagari (Hindi) and Urdu into everyday Roman chat spelling (Hinglish)
and ensures text contains only glyphs supported by bold caption fonts.
"""
import re

_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e"
}
_SIGNS = {
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e"
}
_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
    "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh",
    "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
    "क़": "q", "ख़": "kh", "ग़": "gh", "ज़": "z", "फ़": "f", "ड़": "r", "ढ़": "rh", "य़": "y"
}
_NUKTA = {"क": "q", "ख": "kh", "ग": "gh", "ज": "z", "फ": "f", "ड": "r", "ढ": "rh", "य": "y"}
_VIRAMA, _NUKTA_SIGN = "्", "़"
_NASAL = {"ं": "n", "ँ": "n"}
_OTHER = {"ः": "h", "।": ".", "॥": ".", "ॐ": "om", **{chr(0x0966 + i): str(i) for i in range(10)}}

_COMMON_WORDS = {
    "में": "mein", "मैं": "main", "हैं": "hain", "है": "hai", "नहीं": "nahi", "नही": "nahi", "हूँ": "hoon",
    "हूं": "hoon", "क्या": "kya", "क्यों": "kyun", "क्यूँ": "kyun", "यह": "yeh", "वह": "woh", "और": "aur",
    "भी": "bhi", "ही": "hi", "की": "ki", "जी": "ji", "तो": "to", "हाँ": "haan", "हां": "haan", "यहाँ": "yahan",
    "यहां": "yahan", "वहाँ": "wahan", "वहां": "wahan", "कहाँ": "kahan", "कहां": "kahan", "थी": "thi",
    "रही": "rahi", "कभी": "kabhi", "अभी": "abhi", "सभी": "sabhi", "भाई": "bhai", "मुझे": "mujhe",
    "तुम": "tum", "हम": "hum", "आप": "aap", "बहुत": "bahut", "अच्छा": "accha", "ठीक": "theek", "लिए": "liye",
    "गया": "gaya", "गई": "gayi", "गए": "gaye", "था": "tha", "थे": "the", "हो": "ho", "कर": "kar", "रहा": "raha"
}

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
URDU_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
MORE_SCRIPTS = re.compile(r"[\u0370-\u03FF\u0400-\u04FF\uAC00-\uD7A3]")


def has_hindi(text: str) -> bool:
    return bool(DEVANAGARI.search(text or ""))


def needs_roman(text: str) -> bool:
    text = text or ""
    return bool(DEVANAGARI.search(text) or URDU_ARABIC.search(text) or MORE_SCRIPTS.search(text))


def drawable(text: str) -> bool:
    """True if standard Western bold fonts (Poppins/Anton) can render every character."""
    return not any(ch.isalpha() and not (ord(ch) < 0x250 or 0x1E00 <= ord(ch) <= 0x1EFF) for ch in text or "")


def transliterate_hindi_word(w: str) -> str:
    if w in _COMMON_WORDS:
        return _COMMON_WORDS[w]
    out = []
    i = 0
    n = len(w)
    while i < n:
        c = w[i]
        # Nukta check
        if i + 1 < n and w[i + 1] == _NUKTA_SIGN:
            c = _NUKTA.get(c, _CONS.get(c, c))
            i += 1
        if c in _VOWELS:
            out.append(_VOWELS[c])
        elif c in _SIGNS:
            out.append(_SIGNS[c])
        elif c in _CONS:
            cons = _CONS[c]
            # check next
            if i + 1 < n and w[i + 1] == _VIRAMA:
                out.append(cons)
                i += 1
            elif i + 1 < n and w[i + 1] in _SIGNS:
                out.append(cons)
            elif i + 1 == n:
                # final consonant usually has schwa dropped in Hindi
                out.append(cons)
            else:
                out.append(cons + "a")
        elif c in _NASAL:
            out.append(_NASAL[c])
        elif c in _OTHER:
            out.append(_OTHER[c])
        else:
            out.append(c)
        i += 1
    res = "".join(out)
    return res


def to_roman(text: str) -> str:
    """Converts mixed script text containing Hindi or Devanagari into Hinglish Roman characters."""
    if not text:
        return ""
    if not needs_roman(text):
        return text

    # Split preserving spaces/punctuation
    tokens = re.split(r"(\s+|[.,!?:;\"'()\[\]{}]+)", text)
    result = []
    for token in tokens:
        if DEVANAGARI.search(token):
            result.append(transliterate_hindi_word(token))
        else:
            result.append(token)
    return "".join(result)
