"""Türkçe duyarlı arama anahtarı.

Python'un `lower()` işlevi `I` harfini `i`, `İ` harfini `i̇` yapar; Türkçede doğrusu
`I -> ı`, `İ -> i`. Arama ayrıca Türkçe karakter girmeden yazılan sorguları da
yakalasın diye katlanmış metin ASCII karşılıklarına indirgenir.
"""

_ASCII = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u"})


def tr_lower(text: str) -> str:
    return text.replace("I", "ı").replace("İ", "i").lower()


def search_key(text: str | None) -> str:
    if not text:
        return ""
    return tr_lower(text).translate(_ASCII)
