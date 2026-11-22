"""Service usagers : inscription, dossier, état du compte.

États du compte :
  - « actif / suspendu / radié » : enregistrés dans la table usager
  - « expiré » : dérivé (adhésion passée)
  - « bloqué » : dérivé (retard en cours ou amende impayée)
La règle n°4 est absolue : aucun prêt sans compte ACTIF au sens large.
"""

import sqlite3
from datetime import timedelta


from sigb.models import db, regles, usagers
from sigb.erreurs import ErreurMetier
from sigb.saisie import normaliser_carte

CATEGORIES_AUTORISEES = ("jeune", "adulte", "collectivite")


def inscription(
    nom: str,
    prenom: str | None,
    email: str | None,
    categorie_usager: str,
    acteur: str = "cli",
) -> dict:
    """Inscrit un usager : numéro de carte, adhésion d'un an, droits = catégorie."""
    nom = nom.strip()
    if len(nom) < 2:
        raise ErreurMetier("Le nom est obligatoire.")
    if categorie_usager not in CATEGORIES_AUTORISEES:
        raise ErreurMetier(
            "Catégorie invalide (attendues : jeune, adulte, collectivite)."
        )
    email = email.strip() if email else None
    if email and "@" not in email:
        raise ErreurMetier("Adresse courriel invalide.")
    with db.transaction() as conn:
        duree = regles.parametre_int(conn, regles.P_DUREE_ADHESION, 365)
        try:
            row = usagers.creer(
                conn, nom, prenom, email, categorie_usager, duree
            )
        except sqlite3.IntegrityError:
            raise ErreurMetier("Ce courriel est déjà utilisé par un autre lecteur.")
        db.journaliser(
            conn, "inscription",
            f"Inscription de {prenom or ''} {nom} ({row['numero_carte']}), "
            f"catégorie {categorie_usager}, adhésion jusqu'au {row['expiration_adhesion']}",
            acteur,
        )
        return dict(row)


def identifier(conn, saisie: str):
    """Retrouve un lecteur à partir de ce que l'agent a tapé :
    numéro de carte (« 1 », « us-1 »...), courriel, ou nom si un seul lecteur correspond."""
    saisie = (saisie or "").strip()
    if not saisie:
        raise ErreurMetier("Indiquez la carte du lecteur (ou son nom).")
    usager = usagers.par_carte(conn, normaliser_carte(saisie))
    if usager is None and "@" in saisie:
        usager = usagers.par_email(conn, saisie)
    if usager is not None:
        return usager
    trouves = usagers.chercher(conn, saisie, limite=6)
    if len(trouves) == 1:
        return trouves[0]
    if not trouves:
        raise ErreurMetier(f"Aucun lecteur ne correspond à « {saisie} ».")
    noms = ", ".join(f"{u['prenom'] or ''} {u['nom']} ({u['numero_carte']})".strip() for u in trouves[:5])
    raise ErreurMetier(f"Plusieurs lecteurs correspondent à « {saisie} » : {noms}. Précisez le numéro de carte.")


def verifier_compte(conn, usager) -> None:
    """Règle n°4 : vérifie tout ce qui peut interdire le prêt (levé une à une)."""
    if usager is None:
        raise ErreurMetier("Usager inconnu.")
    if usager["statut"] == usagers.STATUT_SUSPENDU:
        raise ErreurMetier("Le compte est suspendu : voir un agent.")
    if usager["statut"] == usagers.STATUT_RADIE:
        raise ErreurMetier("Le compte est radié.")
    if usager["expiration_adhesion"] < db.aujourd_hui().isoformat():
        raise ErreurMetier(
            f"L'adhésion a expiré le {usager['expiration_adhesion']} : renouvellement nécessaire."
        )
    from sigb.models import amendes, prets

    if prets.a_un_retard(conn, usager["id"]):
        raise ErreurMetier(
            "La carte est bloquée : un document est en retard (retour ou régularisation nécessaire)."
        )
    total = amendes.total_impayees(conn, usager["id"])
    if total > 0:
        raise ErreurMetier(
            f"La carte est bloquée jusqu'au règlement des amendes ({total:.2f} € dus)."
        )


def dossier(conn, usager_id: int) -> dict:
    """Dossier usager : compte, prêts en cours, historique, réservations, amendes."""
    from sigb.models import amendes, prets, reservations

    usager = usagers.par_id(conn, usager_id)
    if usager is None:
        raise ErreurMetier("Usager inconnu.")
    bloque = False
    motif_blocage = None
    try:
        verifier_compte(conn, usager)
    except ErreurMetier as e:
        bloque = True
        motif_blocage = str(e)
    return {
        "usager": usager,
        "bloque": bloque,
        "motif_blocage": motif_blocage,
        "prets_en_cours": prets.prets_en_cours_dusager(conn, usager_id),
        "retards": [p for p in prets.prets_en_cours_dusager(conn, usager_id)
                    if p["date_retour_prevue"] < db.aujourd_hui().isoformat()],
        "historique": prets.historique_dusager(conn, usager_id),
        "reservations": reservations.reservations_actives_dusager(conn, usager_id),
        "amendes_impayees": amendes.impayees_dusager(conn, usager_id),
        "total_amendes": amendes.total_impayees(conn, usager_id),
        "notifications": amendes.pour_usager(conn, usager_id),
    }


def changer_statut_compte(usager_id: int, statut: str, acteur: str = "cli") -> None:
    if statut not in (usagers.STATUT_ACTIF, usagers.STATUT_SUSPENDU, usagers.STATUT_RADIE):
        raise ErreurMetier("Statut de compte invalide.")
    with db.transaction() as conn:
        usagers.changer_statut(conn, usager_id, statut)
        db.journaliser(conn, "gestion_public", f"Compte usager n°{usager_id} : {statut}", acteur)


def renouveler(usager_id: int, acteur: str = "cli") -> None:
    with db.transaction() as conn:
        duree = regles.parametre_int(conn, regles.P_DUREE_ADHESION, 365)
        usagers.renouveler_adhesion(conn, usager_id, duree)
        db.journaliser(conn, "gestion_public", f"Adhésion renouvelée pour usager n°{usager_id}", acteur)


def regler_amende(usager_id: int, amende_id: int, acteur: str = "cli") -> float:
    """Enregistre le règlement d'une amende (le paiement lui-même se fait au guichet)."""
    from sigb.models import amendes

    with db.transaction() as conn:
        ligne = conn.execute(
            "SELECT * FROM amende WHERE id = ? AND usager_id = ?", (amende_id, usager_id)
        ).fetchone()
        if ligne is None:
            raise ErreurMetier("Amende introuvable pour ce lecteur.")
        if ligne["payee"]:
            raise ErreurMetier("Cette amende est déjà réglée.")
        amendes.regler(conn, amende_id)
        db.journaliser(
            conn, "sanction",
            f"Amende n°{amende_id} ({ligne['montant']:.2f} €) réglée pour l'usager n°{usager_id}",
            acteur,
        )
        return ligne["montant"]


def chercher(saisie: str, limite: int = 30) -> list:
    """Lecteurs correspondant à une saisie libre (nom, prénom, carte, courriel)."""
    conn = db.get_conn()
    try:
        exact = usagers.par_carte(conn, normaliser_carte(saisie)) if (saisie or "").strip() else None
        return [exact] if exact is not None else usagers.chercher(conn, saisie, limite=limite)
    finally:
        conn.close()


def fiche(usager_id: int) -> dict:
    """Dossier complet d'un lecteur (ouvre sa propre connexion)."""
    conn = db.get_conn()
    try:
        return dossier(conn, usager_id)
    finally:
        conn.close()
