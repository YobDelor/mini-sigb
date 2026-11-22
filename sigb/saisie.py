"""Saisie tolérante : ce que tape l'agent est nettoyé avant d'être cherché.

Objectif : « 1 », « us-1 » ou « US-000001 » désignent la même carte ;
« ex12 » ou « 12 » la même référence ; « etranger » trouve « L'Étranger ».
"""

import re
import unicodedata


def sans_accents(texte) -> str:
    """Minuscules, sans accents : sert aux recherches (« Hergé » = « herge »)."""
    if texte is None:
        return ""
    decompose = unicodedata.normalize("NFKD", str(texte))
    return "".join(c for c in decompose if not unicodedata.combining(c)).lower()


def _numero(saisie: str, prefixe: str) -> str | None:
    m = re.fullmatch(rf"(?:{prefixe})?[\s\-_]*0*(\d{{1,9}})", saisie.strip(), re.IGNORECASE)
    return f"{prefixe}-{int(m.group(1)):06d}" if m else None


def normaliser_carte(saisie: str) -> str:
    """« 1 » ou « us1 » -> « US-000001 ». Toute autre saisie est rendue telle quelle."""
    saisie = (saisie or "").strip()
    return _numero(saisie, "US") or saisie


def normaliser_reference(saisie: str) -> str:
    """« 12 » ou « ex12 » -> « EX-000012 ». Toute autre saisie est rendue telle quelle."""
    saisie = (saisie or "").strip()
    return _numero(saisie, "EX") or saisie
