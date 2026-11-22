"""Source Catalogue de la BnF — notices françaises de référence,
idéales pour un fonds francophone bien sourcé.

Protocole : SRU 1.2 (https://catalogue.bnf.fr/api/SRU), réponse en
UNIMARC. C'est la source « un peu plus exigeante » du cahier des
charges : les informations vivent dans des zones codifiées.

Zones UNIMARC utilisées :
  200$a titre            200$b type de document (filtre "Texte imprimé")
  010$a ISBN             101$a langue
  210/214$c éditeur      210/214$d année (souvent « DL 2021 »)
  700/701/702 $a $b      noms de personnes (auteurs)
  330$a / 329$a résumé   608$a / 610$a sujets
  001 / 003              identifiant et ARK de la notice
"""

import re
import xml.etree.ElementTree as ET

from sigb.api.common import Notice, extraire_annee, normaliser_isbn, requete_get

URL_SRU = "https://catalogue.bnf.fr/api/SRU"

# Mots qui signalent un document non textuel (disque, film, partition...) :
# le mini-SIGB importe des monographies imprimées.
EXCLUSIONS_200B = ("enregistrement sonore", "musique imprimée", "image", "film", "document électronique")


def construire_requete(isbn: str | None = None, titre: str | None = None, auteur: str | None = None) -> str:
    """Construit une requête SRU CQL : ISBN d'abord, sinon titre ET auteur."""
    if isbn:
        isbn = normaliser_isbn(isbn)
        if not isbn:
            raise ValueError("ISBN invalide")
        return f'bib.isbn all "{isbn}"'
    morceaux = []
    if titre:
        morceaux.append(f'bib.title all "{titre}"')
    if auteur:
        morceaux.append(f'bib.author all "{auteur}"')
    if not morceaux:
        raise ValueError("Fournir un ISBN, un titre ou un auteur")
    return " and ".join(morceaux)


def _sous_champs(datafield, code: str) -> str | None:
    for sub in datafield:
        if sub.tag.endswith("subfield") and sub.get("code") == code and sub.text:
            return sub.text.strip()
    return None


def _contenu_sous_champs(datafield, code: str) -> list[str]:
    valeurs = []
    for sub in datafield:
        if sub.tag.endswith("subfield") and sub.get("code") == code and sub.text:
            valeurs.append(sub.text.strip())
    return valeurs


def parser_reponse(xml_brut: bytes) -> list[Notice]:
    """Convertit une réponse SRU en notices normalisées.

    Fonction séparée de l'appel réseau pour être testée sur un
    enregistrement XML sans dépendre du réseau.
    """
    racine = ET.fromstring(xml_brut)
    notices = {}
    for record in [el for el in racine.iter() if el.tag.endswith("record")]:
        notice = _parser_une_notice(record)
        if notice is None:
            continue
        # La SRU renvoie souvent deux fois chaque notice (variantes de
        # schéma) : le dédoublonnage par ISBN ou identifiant est obligatoire.
        cle = notice.isbn or notice.source_id
        if cle and cle in {n.isbn or n.source_id for n in notices.values()}:
            continue
        notices[cle or notice.titre] = notice
    return list(notices.values())


def _parser_une_notice(record) -> Notice | None:
    champs = [el for el in record.iter() if el.tag.endswith("datafield")]

    def zone(tag: str) -> list:
        return [df for df in champs if df.get("tag") == tag]

    # Type de document : on écarte disques, films, images...
    for df in zone("200"):
        type_doc = (_sous_champs(df, "b") or "").lower()
        if any(motif in type_doc for motif in EXCLUSIONS_200B):
            return None

    titre = None
    for df in zone("200"):
        titre = _sous_champs(df, "a")
        break
    if not titre:
        return None

    isbn = None
    for df in zone("010"):
        isbn = normaliser_isbn(_sous_champs(df, "a"))
        if isbn:
            break

    langue = "fre"
    for df in zone("101"):
        langue = (_sous_champs(df, "a") or "fre").lower()
        break

    editeur, annee_brut = None, None
    for tag in ("214", "210"):
        for df in zone(tag):
            editeur = editeur or _sous_champs(df, "c")
            annee_brut = annee_brut or _sous_champs(df, "d")
        if editeur or annee_brut:
            break

    auteurs: list[str] = []
    for tag in ("700", "701", "702"):
        for df in zone(tag):
            nom = _sous_champs(df, "a")
            prenom = _sous_champs(df, "b")
            if nom:
                auteurs.append(f"{prenom} {nom}".strip())

    resume = None
    for tag in ("330", "329"):
        for df in zone(tag):
            resume = _sous_champs(df, "a")
            if resume:
                break
        if resume:
            break

    genres: list[str] = []
    for tag in ("608", "610"):
        for df in zone(tag):
            sujet = _sous_champs(df, "a")
            if sujet:
                genres.append(sujet)

    source_id = None
    for el in record.iter():
        if el.tag.endswith("controlfield") and el.get("tag") == "001" and el.text:
            source_id = el.text.strip()
            break

    return Notice(
        titre=titre,
        auteurs=auteurs[:3],
        editeur=editeur,
        annee=extraire_annee(annee_brut),
        isbn=isbn,
        langue=langue,
        genres=genres[:3],
        resume=resume,
        source="bnf",
        source_id=source_id,
    )


def rechercher(
    isbn: str | None = None, titre: str | None = None, auteur: str | None = None,
    limite: int = 10,
) -> list[Notice]:
    """Interroge la SRU de la BnF et renvoie des notices normalisées."""
    requete = construire_requete(isbn, titre, auteur)
    reponse = requete_get(
        URL_SRU,
        params={
            "version": "1.2",
            "operation": "searchRetrieve",
            "query": requete,
            "maximumRecords": max(limite, 10),
        },
    )
    notices = parser_reponse(reponse.content)[:limite]
    if isbn:
        isbn = normaliser_isbn(isbn)
        for notice in notices:
            if not notice.isbn:
                notice.isbn = isbn
    return notices
