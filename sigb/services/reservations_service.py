"""Service réservations : file d'attente par œuvre, mise de côté au retour,
délai de récupération limité, déclassement automatique (règle n°6).

La réservation porte TOUJOURS sur l'œuvre, jamais sur un exemplaire précis.
"""

from datetime import timedelta

from sigb.erreurs import ErreurMetier
from sigb.models import amendes, db, exemplaires, oeuvres, regles, reservations
from sigb.services import usagers_service


def reserver(oeuvre_id: int, numero_carte: str, acteur: str = "cli") -> dict:
    """Ajoute l'usager à la file d'attente de l'œuvre.

    Règle réaliste du domaine : si un exemplaire est déjà disponible,
    il faut l'emprunter — une réservation n'a de sens que lorsque tous
    les exemplaires sont empruntés (ou mis de côté pour d'autres).
    """
    with db.transaction() as conn:
        usager = usagers_service.identifier(conn, numero_carte)
        usagers_service.verifier_compte(conn, usager)
        oeuvre = oeuvres.par_id(conn, oeuvre_id)
        if oeuvre is None:
            raise ErreurMetier("Œuvre inconnue.")

        disponibles = conn.execute(
            "SELECT COUNT(*) FROM exemplaire WHERE oeuvre_id = ? AND statut = ?",
            (oeuvre_id, db.STATUT_DISPONIBLE),
        ).fetchone()[0]
        if disponibles > 0:
            raise ErreurMetier(
                f"{disponibles} exemplaire(s) de « {oeuvre['titre']} » sont disponibles : "
                "passez au guichet pour emprunter directement."
            )
        if reservations.a_reservation_active(conn, oeuvre_id, usager["id"]):
            raise ErreurMetier(
                "Vous avez déjà une réservation active sur cette œuvre."
            )
        reservation_id = reservations.creer(conn, oeuvre_id, usager["id"])
        nb_file = len(reservations.file_attente(conn, oeuvre_id))
        db.journaliser(
            conn, "reservation",
            f"Réservation n°{reservation_id} : « {oeuvre['titre']} » par {usager['numero_carte']} "
            f"(rang dans la file : {nb_file})",
            acteur,
        )
        return {"titre": oeuvre["titre"], "rang_file": nb_file}


def annuler(reservation_id: int, acteur: str = "cli", usager_id: int | None = None) -> str:
    """Annule une réservation active ; si elle était mise de côté,
    l'exemplaire déclassé reprend son circuit normal (ou sert la suite de la file).

    `usager_id` : fourni par le compte lecteur en ligne, il garantit qu'un lecteur
    ne peut annuler que SES réservations.
    """
    with db.transaction() as conn:
        res = reservations.par_id(conn, reservation_id)
        if res is None or (usager_id is not None and res["usager_id"] != usager_id):
            raise ErreurMetier("Réservation introuvable.")
        if res["statut"] not in (reservations.EN_ATTENTE, reservations.PRETE):
            raise ErreurMetier("Réservation déjà clôturée.")
        reservations.changer_statut(conn, res["id"], reservations.ANNULEE)
        oeuvre = oeuvres.par_id(conn, res["oeuvre_id"])
        if res["statut"] == reservations.PRETE:
            _declasser_exemplaire(conn, res["oeuvre_id"], res["id"], oeuvre)
        db.journaliser(
            conn, "reservation",
            f"Réservation n°{reservation_id} annulée (« {oeuvre['titre']} »)",
            acteur,
        )
        return f"Réservation n°{reservation_id} annulée."


def traiter_expirations(acteur: str = "systeme") -> list[str]:
    """Déclassement automatique : passé le délai de récupération, la réservation
    expire et l'exemplaire sert le SUIVANT de la file (à durée renouvelée) ;
    sinon l'exemplaire reprend son circuit normal et retourne en rayon.

    À appeler périodiquement (au lancement du menu, commande « traiter »).
    """
    issues: list[str] = []
    with db.transaction() as conn:
        for res in reservations.pretes_expirees(conn, db.aujourd_hui()):
            oeuvre = oeuvres.par_id(conn, res["oeuvre_id"])
            reservations.changer_statut(conn, res["id"], reservations.EXPIREE)
            db.journaliser(
                conn, "reservation",
                f"Déclassement automatique : réservation n°{res['id']} expirée "
                f"(« {oeuvre['titre']} », délai de récupération dépassé)",
                acteur,
            )
            issue = _declasser_exemplaire(conn, res["oeuvre_id"], res["id"], oeuvre)
            issues.append(f"Réservation n°{res['id']} (« {oeuvre['titre']} ») déclassée : {issue}")
    return issues


def _declasser_exemplaire(conn, oeuvre_id: int, ancienne_reservation_id: int, oeuvre) -> str:
    """Après une mise de côté non honorée : servir la suite de la file,
    sinon remettre l'exemplaire en rayon."""
    suivant = reservations.premiere_en_attente(conn, oeuvre_id)
    delai = regles.parametre_int(conn, regles.P_DUREE_MISE_DE_COTE, 7)
    if suivant is not None:
        expiration = db.aujourd_hui() + timedelta(days=delai)
        reservations.servir(conn, suivant["id"], expiration)
        amendes.notifier(
            conn, suivant["usager_id"], "reservation_prete",
            f"Votre réservation de « {oeuvre['titre']} » est disponible "
            f"(exemplaire mis de côté jusqu'au {expiration.isoformat()}).",
        )
        issue = "exemplaire mis de côté pour la réservation suivante"
    else:
        exemplaire = conn.execute(
            "SELECT id, reference FROM exemplaire WHERE oeuvre_id = ? AND statut = ? LIMIT 1",
            (oeuvre_id, db.STATUT_MIS_DE_COTE),
        ).fetchone()
        if exemplaire is not None:
            exemplaires.changer_statut(conn, exemplaire["id"], db.STATUT_DISPONIBLE)
            issue = f"exemplaire {exemplaire['reference']} remis en rayon"
        else:
            issue = "aucun exemplaire à déclasser"
    return issue
