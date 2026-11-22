"""Prêt et retour : l'écran de l'agent au comptoir."""

from sigb.cli import ui
from sigb.cli.ecrans import commun
from sigb.erreurs import ErreurMetier
from sigb.models import db
from sigb.services import circulation


def traiter(doc: dict, lecteur=None) -> None:
    """Un document est choisi : l'écran déduit s'il s'agit d'un retour ou d'un prêt."""
    statut = doc["statut"]
    if statut == db.STATUT_EMPRUNTE:
        ui.info(f"« {doc['titre']} » est emprunté par {doc['emprunteur']} "
                f"(retour prévu le {ui.date_fr(doc['retour_prevu'])}).")
        if ui.confirmer("Enregistrer le retour ?"):
            ui.afficher_retour(circulation.retourner(doc["reference"], acteur=ui.ACTEUR))
    elif statut in (db.STATUT_DISPONIBLE, db.STATUT_MIS_DE_COTE):
        if statut == db.STATUT_MIS_DE_COTE:
            ui.info("Ce document est réservé : seul le lecteur qui l'attend peut l'emprunter.")
        lecteur = lecteur or commun.choisir_lecteur()
        ui.afficher_pret(circulation.emprunter(lecteur["numero_carte"], doc["reference"], acteur=ui.ACTEUR))
    else:
        raise ErreurMetier(f"« {doc['titre']} » n'est pas empruntable "
                           f"({db.LIBELLES_STATUT.get(statut, statut)}).")


def guichet() -> None:
    ui.en_tete("Prêt et retour",
               "Tapez un n° de document, un titre ou un auteur. Le programme décide : retour si le "
               "livre est sorti, prêt sinon. Entrée vide pour terminer.")
    while True:
        try:
            doc = commun.choisir_document()
        except ui.Retour:
            return
        except ErreurMetier as e:
            ui.erreur(str(e))
            continue
        if doc is None:
            return
        ui.tenter(traiter, doc)
