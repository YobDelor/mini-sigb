"""Source OpenLibrary (Internet Archive) — recommandation principale du cahier
des charges : API publique gratuite, sans clé, recherche par ISBN / titre /
auteur, métadonnées complètes et images de couverture.

Endpoints utilisés :
  - https://openlibrary.org/search.json  (recherche, champs limités)
  - https://covers.openlibrary.org/b/id/{id}-M.jpg (couverture)
"""

from sigb.api.common import Notice, libelle_langue, normaliser_isbn, requete_get

URL_RECHERCHE = "https://openlibrary.org/search.json"
URL_COUVERTURE = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"

CHAMPS = "key,title,author_name,first_publish_year,isbn,language,publisher,cover_i,subject,ia,ebook_access"


def _choisir_isbn(isbns: list[str] | None) -> str | None:
    """Prend de préférence un ISBN-13 (clé de dédoublonnage la plus fiable)."""
    for candidat in isbns or []:
        if len(candidat) == 13 and candidat.startswith(("978", "979")):
            return normaliser_isbn(candidat)
    for candidat in isbns or []:
        if len(candidat) == 10:
            return normaliser_isbn(candidat)
    return None


def _vers_notice(doc: dict) -> Notice:
    langue = (doc.get("language") or [None])[0] or "fre"
    # Priorité au français si la langue du doc est ambiguë
    if langue != "fre" and "fre" in (doc.get("language") or []):
        langue = "fre"
    couverture = None
    if doc.get("cover_i"):
        couverture = URL_COUVERTURE.format(cover_id=doc["cover_i"])
    lien = None
    if doc.get("ebook_access") == "public" and doc.get("ia"):
        lien = f"https://archive.org/details/{doc['ia'][0]}"  # lisible en ligne, sans compte
    return Notice(
        titre=doc.get("title") or "Sans titre",
        auteurs=list(doc.get("author_name") or [])[:3],
        editeur=(doc.get("publisher") or [None])[0],
        annee=doc.get("first_publish_year"),
        isbn=_choisir_isbn(doc.get("isbn")),
        langue=langue,
        genres=[s for s in (doc.get("subject") or [])[:3]],
        couverture_url=couverture,
        lien_numerique=lien,
        source="openlibrary",
        source_id=doc.get("key"),
    )


def rechercher(
    isbn: str | None = None, titre: str | None = None, auteur: str | None = None, limite: int = 10
) -> list[Notice]:
    """Recherche OpenLibrary : par ISBN d'abord, sinon par titre et/ou auteur."""
    params: dict = {"fields": CHAMPS, "limit": limite}
    if isbn:
        isbn = normaliser_isbn(isbn)
        if not isbn:
            raise ValueError("ISBN invalide")
        params["q"] = f"isbn:{isbn}"
    else:
        if not titre and not auteur:
            raise ValueError("Fournir un ISBN, un titre ou un auteur")
        morceaux = []
        if titre:
            morceaux.append(titre)
        if auteur:
            morceaux.append(auteur)
        params["q"] = " ".join(morceaux)
    reponse = requete_get(URL_RECHERCHE, params=params).json()
    notices = []
    for doc in reponse.get("docs", []):
        notice = _vers_notice(doc)
        # Un ISBN demandé explicitement reste la référence de l'édition trouvée
        if isbn:
            notice.isbn = isbn
        notices.append(notice)
    return notices

