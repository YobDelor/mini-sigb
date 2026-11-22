"""Sources de livres libres : Gutendex puis flux OPDS officiel de Gutenberg.

Gutendex est une API communautaire pratique, mais son hébergement public n'offre
pas de garantie de disponibilité. Si elle ne répond pas, ce module interroge le
catalogue OPDS publié directement par Project Gutenberg.

Endpoints principaux :
  - https://gutendex.com/books
  - https://www.gutenberg.org/ebooks/search.opds/ (recherche OPDS officielle)
  - https://www.gutenberg.org/ebooks/{id}.opds (notice OPDS par identifiant)

Le flux OPDS XML est documenté par Project Gutenberg comme temporaire : sa
suppression est annoncée pour 2027. Gutendex reste donc prioritaire et OPDS est
un mécanisme de secours.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from sigb.api.common import Notice, extraire_annee, requete_get
from sigb.erreurs import ErreurReseau

URL_API = "https://gutendex.com/books"
URL_OPDS = "https://www.gutenberg.org/ebooks/search.opds/"
HOTE_GUTENBERG = "https://www.gutenberg.org"
MAX_PAGES_OPDS = 1  # respecter la politique OPDS : une page par recherche

_LANGUES_ISO2_ISO3 = {
    "fr": "fre", "fre": "fre", "fra": "fre",
    "en": "eng", "eng": "eng",
    "de": "ger", "ger": "ger", "deu": "ger",
    "es": "spa", "spa": "spa",
    "it": "ita", "ita": "ita",
    "pt": "por", "por": "por",
    "nl": "dut", "dut": "dut", "nld": "dut",
    "la": "lat", "lat": "lat",
}


def _nom_auteur(brut: str) -> str:
    """Gutendex/OPDS renvoient parfois « Hugo, Victor » : restitue « Victor Hugo »."""
    brut = (brut or "").strip()
    if "," in brut:
        nom, prenom = brut.split(",", 1)
        return f"{prenom.strip()} {nom.strip()}"
    return brut


def _choisir_texte(formats: dict) -> str | None:
    """Choisit un lien lisible : HTML, texte brut, puis EPUB."""
    for cle in (
        "text/html; charset=utf-8", "text/html", "application/xhtml+xml",
        "text/html; charset=iso-8859-1", "text/html; charset=us-ascii",
        "text/plain; charset=utf-8", "text/plain; charset=us-ascii",
        "text/plain", "application/epub+zip",
    ):
        if formats.get(cle):
            return formats[cle]
    # Les catalogues OPDS peuvent ne proposer que le format Kindle.
    for cle, valeur in formats.items():
        if valeur and ("epub" in cle.lower() or "mobipocket" in cle.lower()):
            return valeur
    return None


def _vers_notice(livre: dict) -> Notice:
    formats = livre.get("formats") or {}
    sujets = []
    for sujet in livre.get("subjects") or []:
        sujets.append(str(sujet).split(" -- ")[0])
    langues = livre.get("languages") or ["fre"]
    return Notice(
        titre=livre.get("title") or "Sans titre",
        auteurs=[_nom_auteur(a.get("name", "")) for a in (livre.get("authors") or [])][:3],
        isbn=None,
        langue=langues[0],
        genres=list(dict.fromkeys(sujets))[:3],
        resume=(livre.get("summaries") or [None])[0],
        couverture_url=formats.get("image/jpeg"),
        lien_numerique=_choisir_texte(formats),
        type_document="numerique",
        source="gutenberg",
        source_id=str(livre.get("id")) if livre.get("id") is not None else None,
    )


def _json_reponse(reponse, source: str) -> dict:
    try:
        donnees = reponse.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ErreurReseau(f"La source {source} a renvoyé une réponse JSON illisible.") from exc
    if not isinstance(donnees, dict):
        raise ErreurReseau(f"La source {source} a renvoyé un format de réponse inattendu.")
    return donnees


def _lancer_opds(url: str = URL_OPDS, params: dict | None = None) -> tuple[list[Notice], str | None]:
    """Télécharge et convertit une page du catalogue OPDS officiel."""
    reponse = requete_get(url, params=params)
    try:
        racine = ET.fromstring(reponse.content)
    except (ET.ParseError, AttributeError, TypeError) as exc:
        raise ErreurReseau("Le catalogue OPDS de Project Gutenberg a renvoyé un flux XML invalide.") from exc

    notices = []
    for entree in (element for element in racine.iter() if element.tag.rsplit("}", 1)[-1] == "entry"):
        notice = _entree_opds_vers_notice(entree)
        if notice is not None:
            notices.append(notice)

    suivant = None
    for lien in (element for element in racine if element.tag.rsplit("}", 1)[-1] == "link"):
        if (lien.get("rel") or "").lower() == "next" and lien.get("href"):
            suivant = urljoin(HOTE_GUTENBERG, lien.get("href"))
            break
    return notices, suivant


def _texte_enfant(element, noms: set[str]) -> list[str]:
    """Récupère les valeurs d'un champ XML sans dépendre du préfixe namespace."""
    valeurs = []
    for noeud in element.iter():
        nom_local = noeud.tag.rsplit("}", 1)[-1].lower()
        if nom_local in noms:
            texte = " ".join("".join(noeud.itertext()).split())
            if texte:
                valeurs.append(texte)
    return valeurs


def _auteurs_opds(entree) -> list[str]:
    """Extrait les auteurs sans concaténer leur URI Atom à leur nom."""
    auteurs = []
    for element in entree.iter():
        nom_local = element.tag.rsplit("}", 1)[-1].lower()
        if nom_local == "creator":  # Dublin Core : dc:creator contient directement le nom
            brut = " ".join("".join(element.itertext()).split())
        elif nom_local == "author":  # Atom : <author><name>...</name><uri>...</uri>
            enfant_nom = next(
                (enfant for enfant in element.iter()
                 if enfant is not element and enfant.tag.rsplit("}", 1)[-1].lower() == "name"),
                None,
            )
            brut = " ".join("".join(enfant_nom.itertext()).split()) if enfant_nom is not None else ""
            if not brut:
                brut = " ".join("".join(element.itertext()).split())
        else:
            continue
        nom = _nom_auteur(brut)
        if nom and nom not in auteurs:
            auteurs.append(nom)
    return auteurs[:3]


def _entree_opds_vers_notice(entree) -> Notice | None:
    """Convertit une entrée Atom/OPDS Gutenberg vers la notice interne."""
    titres = _texte_enfant(entree, {"title"})
    identifiants = _texte_enfant(entree, {"id"})
    titre = titres[0] if titres else None
    brut_id = identifiants[0] if identifiants else ""

    liens = [el for el in entree.iter() if el.tag.rsplit("}", 1)[-1] == "link"]
    if not brut_id:
        brut_id = next((l.get("href", "") for l in liens if l.get("href")), "")
    match = re.search(r"/ebooks/(\d+)(?:\.opds)?(?:[/?#]|$)", brut_id)
    if not match:
        # Certains identifiants Atom sont des tag:.../ebooks/123.
        match = re.search(r"ebooks/(\d+)", brut_id)
    if not titre or not match:
        return None  # écarte les entrées de navigation, qui ne sont pas des livres

    identifiant = match.group(1)
    formats: dict[str, str] = {}
    couverture = None
    for lien in liens:
        href = lien.get("href")
        if not href:
            continue
        href = urljoin(HOTE_GUTENBERG, href)
        mime = (lien.get("type") or "").lower().split(";", 1)[0].strip()
        rel = (lien.get("rel") or "").lower()
        if mime.startswith("image/") or "opds-spec.org/image" in rel:
            if couverture is None or "thumbnail" not in rel:
                couverture = href
        elif mime:
            # Les liens d'acquisition contiennent les vrais formats du livre.
            if ("acquisition" in rel or mime in ("text/html", "text/plain", "application/xhtml+xml")):
                formats[mime] = href

    auteurs = _auteurs_opds(entree)
    langues_brutes = _texte_enfant(entree, {"language"})
    langue = langues_brutes[0].lower() if langues_brutes else "und"
    langue = _LANGUES_ISO2_ISO3.get(langue, langue)
    sujets = _texte_enfant(entree, {"subject"})
    # L'OPDS emploie parfois Atom <category label="..."> plutôt que dc:subject.
    for categorie in (element for element in entree.iter()
                      if element.tag.rsplit("}", 1)[-1] == "category"):
        libelle = categorie.get("label") or categorie.get("term")
        if libelle:
            sujets.append(libelle)
    resumés = _texte_enfant(entree, {"summary", "content"})
    annee = extraire_annee(next(iter(_texte_enfant(entree, {"issued", "date"})), None))

    # La liseuse intégrée est plus agréable avec le HTML. Si le flux ne propose
    # qu'un texte brut ou un EPUB, on préfère l'URL HTML canonique de Gutenberg.
    formats_html = {
        mime: url for mime, url in formats.items()
        if mime.startswith(("text/html", "application/xhtml+xml"))
    }
    lien_lecture = _choisir_texte(formats_html) or f"{HOTE_GUTENBERG}/ebooks/{identifiant}.html.images"

    return Notice(
        titre=titre,
        auteurs=auteurs,
        annee=annee,
        langue=langue,
        genres=list(dict.fromkeys(sujets))[:3],
        resume=resumés[0] if resumés else None,
        couverture_url=couverture,
        lien_numerique=lien_lecture,
        type_document="numerique",
        source="gutenberg",
        source_id=identifiant,
    )



def parser_opds(xml_brut: bytes) -> list[Notice]:
    """Parse un flux OPDS Gutenberg (utile pour les fixtures et les imports)."""
    try:
        racine = ET.fromstring(xml_brut)
    except (ET.ParseError, TypeError) as exc:
        raise ErreurReseau("Le catalogue OPDS de Project Gutenberg a renvoyé un flux XML invalide.") from exc
    notices = []
    for entree in (element for element in racine.iter() if element.tag.rsplit("}", 1)[-1] == "entry"):
        notice = _entree_opds_vers_notice(entree)
        if notice is not None:
            notices.append(notice)
    return notices


def _rechercher_opds(mots: str, limite: int = 10) -> list[Notice]:
    """Recherche via le flux OPDS officiel de Project Gutenberg."""
    notices: list[Notice] = []
    url, params = URL_OPDS, {"query": mots}
    pages = 0
    while url and pages < MAX_PAGES_OPDS and len(notices) < limite:
        page, suivant = _lancer_opds(url, params)
        params = None  # les paramètres sont déjà portés par l'URL de pagination
        notices.extend(page)
        url = suivant
        pages += 1
    # Un même livre peut apparaître dans plusieurs pages/sections du flux.
    uniques = {}
    for notice in notices:
        uniques.setdefault(notice.source_id, notice)
    return list(uniques.values())[:limite]


def _populaires_opds(langue: str = "fr", sujet: str | None = None, limite: int = 20) -> list[Notice]:
    """Repli OPDS : populaires filtrés par langue directement dans le catalogue."""
    notices: list[Notice] = []
    code_langue = (langue or "fr").lower()
    # L'interface OPDS de Gutenberg utilise le filtre de langue `l.xx` dans
    # le paramètre `query` (par exemple `query=l.fr`). Éviter de télécharger
    # les 25 livres les plus populaires toutes langues confondues puis de les
    # filtrer localement : ils sont presque tous anglophones.
    code_langue_opds = next(
        (code for code, code3 in _LANGUES_ISO2_ISO3.items() if code3 == code_langue),
        code_langue,
    )
    requete = f"l.{code_langue_opds}"
    if sujet:
        requete += f" {sujet}"
    params = {"sort_order": "downloads", "query": requete}
    url = URL_OPDS
    pages = 0
    code_langue = (langue or "").lower()
    code_langue_alt = _LANGUES_ISO2_ISO3.get(code_langue, code_langue)
    while url and pages < MAX_PAGES_OPDS and len(notices) < limite:
        page, suivant = _lancer_opds(url, params)
        params = None
        for notice in page:
            langue_notice = (notice.langue or "").lower()
            langue_notice_alt = _LANGUES_ISO2_ISO3.get(langue_notice, langue_notice)
            if langue_notice in (code_langue, code_langue_alt) or langue_notice_alt in (code_langue, code_langue_alt):
                notices.append(notice)
        url = suivant
        pages += 1
    uniques = {}
    for notice in notices:
        uniques.setdefault(notice.source_id, notice)
    return list(uniques.values())[:limite]


def rechercher_par_id(gutenberg_id: int) -> Notice:
    """Récupère une notice par identifiant, avec repli OPDS en cas de panne ou d'absence."""
    erreur_gutendex = None
    try:
        reponse = _json_reponse(requete_get(URL_API, params={"ids": gutenberg_id}), "Gutendex")
        resultats = reponse.get("results") or []
        if resultats:
            return _vers_notice(resultats[0])
        erreur_gutendex = ErreurReseau(
            f"Gutendex n'a pas trouvé de notice pour l'identifiant {gutenberg_id}."
        )
    except ErreurReseau as exc:
        erreur_gutendex = exc

    try:
        notices, _ = _lancer_opds(f"{HOTE_GUTENBERG}/ebooks/{gutenberg_id}.opds")
        if notices:
            return notices[0]
    except ErreurReseau as erreur_opds:
        raise ErreurReseau(
            f"Gutendex est indisponible ({erreur_gutendex}). Le catalogue officiel de "
            f"Project Gutenberg est également inaccessible ({erreur_opds}). "
            "Vérifiez votre connexion ou réessayez plus tard."
        ) from erreur_opds
    raise ErreurReseau(
        f"Aucune notice trouvée pour le livre n°{gutenberg_id}. "
        f"Gutendex : {erreur_gutendex} ; Project Gutenberg : aucun résultat OPDS."
    ) from erreur_gutendex


def rechercher(titre: str | None = None, auteur: str | None = None, limite: int = 10) -> list[Notice]:
    """Recherche plein-texte : Gutendex en priorité, OPDS officiel en secours."""
    mots = " ".join(m for m in (titre, auteur) if m)
    if not mots:
        raise ValueError("Fournir un titre ou un auteur")
    try:
        reponse = _json_reponse(
            requete_get(URL_API, params={"search": mots, "languages": "fr", "page": 1}),
            "Gutendex",
        )
        notices = [_vers_notice(livre) for livre in (reponse.get("results") or [])[:limite]]
        if not notices:
            # Deuxième essai sans filtre de langue : certains livres ont d'autres codes.
            reponse = _json_reponse(requete_get(URL_API, params={"search": mots, "page": 1}), "Gutendex")
            notices = [_vers_notice(livre) for livre in (reponse.get("results") or [])[:limite]]
        if notices:
            return notices
        erreur_gutendex = ErreurReseau("Gutendex n'a renvoyé aucun résultat pour cette recherche.")
        return _rechercher_opds_avec_diagnostic(mots, limite, erreur_gutendex)
    except ErreurReseau as erreur_gutendex:
        return _rechercher_opds_avec_diagnostic(mots, limite, erreur_gutendex)


def _rechercher_opds_avec_diagnostic(mots: str, limite: int, erreur_gutendex: ErreurReseau) -> list[Notice]:
    try:
        return _rechercher_opds(mots, limite)
    except ErreurReseau as erreur_opds:
        raise ErreurReseau(
            f"Gutendex est indisponible ({erreur_gutendex}). Le catalogue officiel de "
            f"Project Gutenberg est également inaccessible ({erreur_opds}). "
            "Vérifiez votre connexion ou réessayez plus tard."
        ) from erreur_opds


def populaires(langue: str = "fr", sujet: str | None = None, limite: int = 20) -> list[Notice]:
    """Classiques les plus téléchargés, avec repli sur le flux OPDS officiel."""
    notices: list[Notice] = []
    try:
        for page in range(1, 5):
            params = {"languages": langue, "page": page}
            if sujet:
                params["topic"] = sujet
            reponse = _json_reponse(requete_get(URL_API, params=params), "Gutendex")
            for livre in reponse.get("results") or []:
                if _choisir_texte(livre.get("formats") or {}):
                    notices.append(_vers_notice(livre))
            if len(notices) >= limite or not reponse.get("next"):
                break
        if notices:
            return notices[:limite]
        erreur_gutendex = ErreurReseau("Gutendex n'a renvoyé aucun livre pour ces critères.")
        return _populaires_opds_avec_diagnostic(langue, sujet, limite, erreur_gutendex)
    except ErreurReseau as erreur_gutendex:
        return _populaires_opds_avec_diagnostic(langue, sujet, limite, erreur_gutendex)


def _populaires_opds_avec_diagnostic(langue: str, sujet: str | None, limite: int,
                                     erreur_gutendex: ErreurReseau) -> list[Notice]:
    try:
        return _populaires_opds(langue=langue, sujet=sujet, limite=limite)
    except ErreurReseau as erreur_opds:
        raise ErreurReseau(
            f"Gutendex est indisponible ({erreur_gutendex}). Le catalogue officiel de "
            f"Project Gutenberg est également inaccessible ({erreur_opds}). "
            "Vérifiez votre connexion ou réessayez plus tard."
        ) from erreur_opds
