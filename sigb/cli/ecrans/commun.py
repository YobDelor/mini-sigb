"""Sélecteurs partagés : retrouver un lecteur ou un document sans connaître son numéro."""

from sigb.cli import ui
from sigb.erreurs import ErreurMetier
from sigb.models import db
from sigb.services import catalogue, usagers_service


def choisir_lecteur(saisie: str | None = None, proposer_inscription: bool = True):
    """Nom, prénom ou numéro de carte -> un lecteur (ligne de base). Lève Retour si abandon."""
    if saisie is None:
        saisie = ui.demander("Lecteur — nom, prénom ou n° de carte", obligatoire=True)
    trouves = usagers_service.chercher(saisie)
    if not trouves:
        ui.attention(f"Aucun lecteur ne correspond à « {saisie} ».")
        if proposer_inscription and ui.confirmer("L'inscrire maintenant ?", False):
            from sigb.cli.ecrans import lecteurs

            return lecteurs.inscrire(saisie)
        raise ui.Retour()
    if len(trouves) == 1:
        return trouves[0]
    return ui.choisir(
        f"{len(trouves)} lecteurs correspondent :",
        [(f"{ui.nom_lecteur(u):<30} {u['numero_carte']}   {u['categorie_usager']}", u) for u in trouves],
    )


def libelle_document(c: dict) -> str:
    statut = db.LIBELLES_STATUT.get(c["statut"], c["statut"])
    if c.get("emprunteur"):
        statut += f" par {c['emprunteur']}"
    return f"{c['reference']}  {c['titre'][:42]:<42}  {statut}"


def choisir_document(saisie: str | None = None) -> dict | None:
    """Numéro, titre ou auteur -> un document. Renvoie None si la saisie est vide
    (= « j'ai terminé »). Lève ErreurMetier si rien ne correspond."""
    if saisie is None:
        saisie = ui.demander("Document — n°, titre ou auteur (Entrée vide pour terminer)")
    if not saisie:
        return None
    trouves = catalogue.chercher_exemplaires(saisie)
    if not trouves:
        raise ErreurMetier(f"Aucun document ne correspond à « {saisie} ».")
    trouves = _regrouper_disponibles(trouves)
    if len(trouves) == 1:
        return trouves[0]
    return ui.choisir(f"{len(trouves)} documents correspondent :", [(libelle_document(c), c) for c in trouves])


def _regrouper_disponibles(candidats: list[dict]) -> list[dict]:
    """Deux exemplaires disponibles du même titre sont interchangeables pour l'agent :
    on n'en propose qu'un. (Les exemplaires empruntés restent distincts : emprunteurs différents.)"""
    vus, resultat = set(), []
    for c in candidats:
        if c["statut"] == db.STATUT_DISPONIBLE:
            if c["oeuvre_id"] in vus:
                continue
            vus.add(c["oeuvre_id"])
        resultat.append(c)
    return resultat
