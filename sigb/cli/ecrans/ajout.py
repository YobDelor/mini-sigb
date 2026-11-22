"""Ajouter des livres : recherche sur internet (OpenLibrary, BnF, Gutenberg) ou saisie manuelle."""

from sigb.api.common import Notice, normaliser_isbn
from sigb.cli import ui
from sigb.models import db
from sigb.services import import_service

TYPES = (("Livre", "livre"), ("Bande dessinée", "bd"), ("DVD", "dvd"), ("Périodique", "periode"),
         ("Ressource numérique", "numerique"))
SUJETS = (("Tous genres", ""), ("Aventure", "adventure"), ("Romans", "fiction"), ("Poésie", "poetry"),
          ("Théâtre", "drama"), ("Science-fiction", "science fiction"), ("Philosophie", "philosophy"),
          ("Histoire", "history"))


def menu() -> None:
    while True:
        try:
            choix = ui.choisir("Ajouter des livres", [
                ("Chercher un livre (titre, auteur ou ISBN)", "chercher"),
                ("Chercher un classique libre à lire en ligne", "classique"),
                ("Remplir le catalogue avec des classiques libres", "garnir"),
                ("Saisir un livre à la main", "manuel"),
            ])
        except ui.Retour:
            return
        ui.tenter({"chercher": chercher_en_ligne, "classique": lambda: chercher_en_ligne(source="classiques"),
                   "garnir": garnir, "manuel": manuel}[choix])


def libelle(n: Notice) -> str:
    auteur = (n.auteurs[0] if n.auteurs else "auteur inconnu")[:24]
    return (f"{n.titre[:46]} — {auteur}" + (f" ({n.annee})" if n.annee else "")
            + (" · à lire en ligne" if n.lien_numerique else "") + f"  [{n.source}]")


def chercher_en_ligne(q: str | None = None, source: str = "auto") -> None:
    ui.en_tete("Chercher un livre sur internet")
    q = q or ui.demander("Titre, auteur ou ISBN", obligatoire=True)
    with ui.attente("Recherche en cours…"):
        notices = import_service.rechercher_libre(q, source, limite=12)
    if not notices:
        ui.attention("Aucun résultat. Essayez un autre mot, un ISBN, ou saisissez le livre à la main.")
        return
    choisis = ui.cocher(f"{len(notices)} résultat(s) — cochez ce que vous voulez ajouter :",
                        [(libelle(n), n) for n in notices])
    if choisis:
        ajouter_notices(choisis)
    else:
        ui.info("Rien d'ajouté.")


def ajouter_notices(notices: list[Notice]) -> None:
    papier = [n for n in notices if n.type_document != "numerique"]
    copies, cote = 1, None
    if papier:
        copies = ui.entier("Combien d'exemplaires papier par livre ?", 1, 1, 50)
        if len(papier) == 1:
            cote = ui.demander("Cote (emplacement en rayon)", import_service.cote_par_defaut(papier[0]), obligatoire=True)
    lisibles = []
    for n in notices:
        oid, creee = import_service.importer_notice(
            n, acteur=ui.ACTEUR, nb_copies=0 if n.type_document == "numerique" else copies, cote=cote)
        (ui.succes if creee else ui.info)(
            f"« {n.titre} » ajouté" + (" (à lire en ligne, sans prêt)" if n.type_document == "numerique" else f" ({copies} exemplaire(s))")
            if creee else f"« {n.titre} » était déjà au catalogue.")
        if n.lien_numerique:
            lisibles.append((n.titre, oid))
    if len(lisibles) == 1 and ui.confirmer(f"Lire « {lisibles[0][0]} » maintenant ?"):
        from sigb.cli.ecrans import lecture

        lecture.lire(lisibles[0][1])


def garnir() -> None:
    ui.en_tete("Remplir le catalogue", "Des classiques francophones à lire en ligne. Les liens de lecture "
               "viennent d'Open Library (Internet Archive) ; Project Gutenberg, puis une liste intégrée "
               "hors ligne, prennent le relais si besoin.")
    nombre = ui.choisir("Combien de livres ?", [("10", 10), ("20", 20), ("30", 30)], defaut=20)
    sujet = ui.choisir("Quel genre ?", list(SUJETS))
    with ui.attente("Recherche d'une source disponible…"):
        r = import_service.garnir_catalogue(nombre, "fr", sujet or None, acteur=ui.ACTEUR)
    for source, motif in r["echecs"]:
        ui.attention(f"{source} : {motif}")
    if r["trouves"] == 0:
        ui.attention("Aucune source n'a fourni de livre. Essayez un autre genre ou « Tous genres ».")
        return
    ui.succes(f"{r['ajoutes']} livre(s) ajouté(s) depuis {r['source']}"
              + (f", {r['deja_presents']} déjà présent(s)" if r["deja_presents"] else "") + ".")
    if r["source"].startswith("liste de départ"):
        ui.info("Ces notices n'ont pas de lien de lecture : relancez plus tard pour obtenir des textes à lire en ligne.")


def manuel() -> None:
    ui.en_tete("Saisir un livre à la main")
    titre = ui.demander("Titre", obligatoire=True)
    auteurs = ui.demander("Auteur(s), séparés par des virgules")
    type_document = ui.choisir("Type de document :", list(TYPES), retour=None)
    annee = ui.demander("Année", valider=lambda v: True if v.isdigit() and 1000 <= int(v) <= 2100 else "Une année (ex. 1999).")
    isbn = ui.demander("ISBN (10 ou 13 chiffres)", valider=lambda v: True if normaliser_isbn(v) else "ISBN invalide.")
    copies = ui.entier("Nombre d'exemplaires", 1, 0, 50)
    notice = Notice(titre=titre, auteurs=[a.strip() for a in auteurs.split(",") if a.strip()],
                    annee=int(annee) if annee else None, isbn=isbn or None, type_document=type_document)
    cote = ui.demander("Cote (emplacement en rayon)", import_service.cote_par_defaut(notice), obligatoire=True)
    oid, creee = import_service.importer_notice(notice, acteur=ui.ACTEUR, nb_copies=copies, cote=cote)
    (ui.succes if creee else ui.info)(f"« {titre} » ajouté au catalogue (n°{oid})." if creee else "Ce livre était déjà au catalogue.")
