"""Classiques francophones libres de droits, servis par Open Library (Internet Archive).

Pourquoi ce module : les deux services derrière « Project Gutenberg » sont fragiles.
Gutendex (gutendex.com) est un hébergement communautaire sans garantie de
disponibilité — sa documentation conseille d'ailleurs d'auto-héberger un serveur
pour un usage sérieux — et le flux OPDS officiel de gutenberg.org est régulièrement
fermé pour maintenance (suppression annoncée pour 2027). Open Library, opéré par
Internet Archive, remplit le même rôle — des classiques libres à lire en ligne —
avec un service public stable.

Deux usages, sans clé d'API :
  - populaires()  : la liste curatée intégrée (sigb/api/amorce.py : une cinquantaine
    de classiques francophones) est « hydratée » par une recherche Open Library par
    œuvre ; chaque livre numérisé librement lisible reçoit son lien de lecture
    (archive.org, sans compte) et sa couverture ;
  - rechercher()  : recherche libre restreinte aux livres numérisés lisibles sans
    compte (critère ebook_access=public + identifiant Internet Archive).

Endpoint : https://openlibrary.org/search.json (mêmes champs que sigb/api/openlibrary.py).
Les notices produites portent source="openlibrary" et l'identifiant d'œuvre Open
Library : un livre ajouté ici ne sera pas dupliqué s'il a déjà été importé depuis
Open Library par l'écran « Chercher un livre ».
"""

from __future__ import annotations

from sigb.api import amorce
from sigb.api.common import Notice, requete_get
from sigb.api.openlibrary import URL_COUVERTURE, URL_RECHERCHE
from sigb.erreurs import ErreurReseau

CHAMPS = (
    "key,title,author_name,first_publish_year,language,ia,"
    "ebook_access,cover_i,subject,first_sentence"
)


def _lisible(doc: dict) -> bool:
    """Un document est proposé à la lecture s'il est public ET numérisé sur archive.org."""
    return doc.get("ebook_access") == "public" and bool(doc.get("ia"))


def _premiere_phrase(doc: dict) -> str | None:
    """Première phrase du livre : un avant-goût plus utile qu'un résumé absent."""
    phrases = doc.get("first_sentence")
    if not phrases:
        return None
    texte = " ".join(str(phrases[0]).split())
    if len(texte) > 220:
        texte = texte[:217].rstrip() + "…"
    return texte or None


def _couverture(doc: dict) -> str | None:
    return URL_COUVERTURE.format(cover_id=doc["cover_i"]) if doc.get("cover_i") else None


def _chercher_oeuvre(titre: str, auteur: str) -> dict | None:
    """Cherche l'œuvre exacte (titre + auteur) et renvoie le premier exemplaire
    librement lisible, sinon None. Les réponses Open Library sont classées par
    pertinence ; les trois premières couvrent les cas où l'édition la plus
    évidente est réservée aux lecteurs empêchés (printdisabled)."""
    params = {
        "q": f'title:"{titre}" author:"{auteur}"',
        "fields": CHAMPS,
        "limit": 3,
    }
    docs = requete_get(URL_RECHERCHE, params=params).json().get("docs") or []
    return next((doc for doc in docs if _lisible(doc)), None)


def _hydrater(base: Notice, doc: dict) -> Notice:
    """Fusionne la notice curatée (titre, auteur, année, genre — en français propre)
    et les données en ligne (lien de lecture, couverture, première phrase)."""
    return Notice(
        titre=base.titre,
        auteurs=base.auteurs,
        annee=base.annee or doc.get("first_publish_year"),
        isbn=None,  # numérisation libre, pas une édition commerciale
        langue="fre",
        genres=base.genres,
        resume=_premiere_phrase(doc),
        couverture_url=_couverture(doc),
        lien_numerique=f"https://archive.org/details/{doc['ia'][0]}",
        type_document="numerique",
        source="openlibrary",
        source_id=doc.get("key"),
    )


def populaires(langue: str = "fr", sujet: str | None = None, limite: int = 20) -> list[Notice]:
    """Classiques francophones avec lien de lecture réel, hydratés via Open Library.

    Si la source est injoignable dès la première œuvre, lève ErreurReseau pour que
    la cascade de sources (voir services/import_service.py) essaie la suivante.
    Si la panne survient en cours de route, les œuvres déjà hydratées sont
    renvoyées : mieux vaut un catalogue partiel qu'un échec total.
    """
    candidates = amorce.populaires(langue=langue, sujet=sujet, limite=limite)
    if not candidates:
        return []
    notices: list[Notice] = []
    for base in candidates:
        try:
            doc = _chercher_oeuvre(base.titre, base.auteurs[0] if base.auteurs else "")
        except ErreurReseau:
            if not notices:
                raise
            break
        if doc:
            notices.append(_hydrater(base, doc))
    return notices[:limite]


def _vers_notice(doc: dict) -> Notice:
    langues = doc.get("language") or []
    langue = "fre" if "fre" in langues else (langues[0] if langues else "fre")
    return Notice(
        titre=doc.get("title") or "Sans titre",
        auteurs=list(doc.get("author_name") or [])[:3],
        annee=doc.get("first_publish_year"),
        isbn=None,
        langue=langue,
        genres=[s for s in (doc.get("subject") or [])[:3]],
        resume=_premiere_phrase(doc),
        couverture_url=_couverture(doc),
        lien_numerique=f"https://archive.org/details/{doc['ia'][0]}",
        type_document="numerique",
        source="openlibrary",
        source_id=doc.get("key"),
    )


def rechercher(titre: str | None = None, auteur: str | None = None, limite: int = 10) -> list[Notice]:
    """Recherche de classiques libres : uniquement des livres lisibles en ligne sans compte.

    Le filtre ebook_access=public côté serveur exclut les livres à emprunt ; un
    second filtre local exige un identifiant Internet Archive (champ ia).
    """
    mots = " ".join(m for m in (titre, auteur) if m)
    if not mots:
        raise ValueError("Fournir un titre ou un auteur")
    params = {
        "q": mots,
        "ebook_access": "public",
        "fields": CHAMPS,
        "limit": max(limite, 12),
    }
    docs = requete_get(URL_RECHERCHE, params=params).json().get("docs") or []
    return [_vers_notice(doc) for doc in docs if _lisible(doc)][:limite]
