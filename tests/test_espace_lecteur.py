"""Espace lecteur : identification, prolongation verrouillée au compte,
réservations personnelles, profil en lecture seule, notifications.

Les garde-fous du service (`usager_id`) sont testés directement : un lecteur
ne peut prolonger ni annuler que sur SON compte.
"""

import pytest
from datetime import timedelta

from sigb.cli.ecrans import espace_lecteur
from sigb.erreurs import ErreurMetier
from sigb.models import amendes, db, usagers
from sigb.services import circulation, reservations_service
from tests.helpers import creer_oeuvre, creer_usager
from tests.test_cli import RETOUR, clavier   # noqa: F401  (fixture clavier partagée)


def _id_de(carte: str) -> int:
    conn = db.get_conn()
    try:
        return usagers.par_carte(conn, carte)["id"]
    finally:
        conn.close()


# ------------------------------------------------------------- identification


def test_identification_par_carte_puis_fermeture(clavier):
    carte = creer_usager(nom="Voyage Jules")
    clavier.saisir(carte, True, RETOUR)      # carte, « c'est bien vous ? », fermer la session
    espace_lecteur.ouvrir()
    sortie = clavier.sortie()
    assert "Espace de" in sortie and "Voyage Jules" in sortie
    assert "Compte en règle" in sortie
    assert "Réglages" not in sortie          # aucun menu de gestion dans l'espace lecteur
    assert clavier.restant() == []


def test_identification_inconnue_recommence_puis_abandon(clavier):
    clavier.saisir("inconnu-xyz", "")
    assert espace_lecteur.identifier() is None
    assert "Aucun lecteur ne correspond" in clavier.sortie()


def test_plusieurs_correspondances_choix_dans_la_liste(clavier):
    creer_usager(nom="Dubois Anne")
    creer_usager(nom="Dubois Hugo")
    clavier.saisir("dubois", "Dubois Anne", True, RETOUR)
    espace_lecteur.ouvrir()
    sortie = clavier.sortie()
    # la session s'est ouverte sur le lecteur CHOISI, pas sur son homonyme
    assert "Dubois Anne" in sortie and "Dubois Hugo" not in sortie
    assert clavier.restant() == []


# ----------------------------------------------------------------- emprunts


def test_emprunts_avec_prolongation_depuis_espace(clavier):
    _, refs = creer_oeuvre("Prolongation lecteur", nb_copies=1)
    carte = creer_usager(nom="Lea Livre")
    circulation.emprunter(carte, refs[0])
    clavier.saisir(carte, True, "Mes emprunts", True, "Prolongation", RETOUR)
    espace_lecteur.ouvrir()
    sortie = clavier.sortie()
    assert "Emprunts en cours (1)" in sortie and "prolongé : à rendre avant le" in sortie
    assert clavier.restant() == []
    conn = db.get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM pret WHERE prolonge = 1").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_bloque_affiche_le_motif_et_refuse_prolongation(clavier):
    _, refs = creer_oeuvre("Retarde lecteur", nb_copies=1)
    carte = creer_usager(nom="Bob Retard")
    circulation.emprunter(carte, refs[0])
    conn = db.get_conn()
    conn.execute("UPDATE pret SET date_retour_prevue = ?",
                 ((db.aujourd_hui() - timedelta(days=4)).isoformat(),))
    conn.close()
    clavier.saisir(carte, True, "Mes emprunts", RETOUR)
    espace_lecteur.ouvrir()
    sortie = clavier.sortie()
    assert "Carte bloquée" in sortie and "Prolongation indisponible" in sortie


def test_prolongation_verrouillee_sur_son_compte():
    _, refs = creer_oeuvre("Verrou pret", nb_copies=1)
    carte_a = creer_usager(nom="Alice Pret")
    carte_b = creer_usager(nom="Bruno Pret")
    circulation.emprunter(carte_a, refs[0])
    with pytest.raises(ErreurMetier):
        circulation.prolonger(refs[0], usager_id=_id_de(carte_b))   # pas son prêt
    r = circulation.prolonger(refs[0], usager_id=_id_de(carte_a))
    assert r["nouvelle_echeance"] > db.aujourd_hui()


# -------------------------------------------------------------- réservations


def test_reserver_puis_annuler_depuis_espace(clavier):
    _, refs = creer_oeuvre("Fleuve noir", nb_copies=1)
    carte = creer_usager(nom="File Fran")
    autre = creer_usager(nom="Autre Hugo")
    circulation.emprunter(autre, refs[0])   # plus rien de dispo : la réservation a un sens
    clavier.saisir(carte, True, "Réserver", "fleuve", "Fleuve", "Mes réservations", "Fleuve", RETOUR)
    espace_lecteur.ouvrir()
    sortie = clavier.sortie()
    assert "Réservation enregistrée" in sortie and "annulée" in sortie
    conn = db.get_conn()
    try:
        statuts = [r["statut"] for r in conn.execute("SELECT statut FROM reservation")]
    finally:
        conn.close()
    assert statuts == ["annulee"]


def test_annulation_verrouillee_sur_son_compte():
    oid, refs = creer_oeuvre("Verrou reservation", nb_copies=1)
    carte_a = creer_usager(nom="Alice Verrou")
    carte_b = creer_usager(nom="Bruno Verrou")
    circulation.emprunter(carte_a, refs[0])
    reservations_service.reserver(oid, carte_b)
    conn = db.get_conn()
    try:
        res_id = conn.execute("SELECT id FROM reservation").fetchone()["id"]
    finally:
        conn.close()
    with pytest.raises(ErreurMetier):
        reservations_service.annuler(res_id, usager_id=_id_de(carte_a))   # pas sa réservation
    reservations_service.annuler(res_id, usager_id=_id_de(carte_b))


# -------------------------------------------------------------------- profil


def test_profil_en_lecture_seule(clavier):
    _, refs = creer_oeuvre("Profil lecteur", nb_copies=1)
    carte = creer_usager(nom="Paule Profil")
    circulation.emprunter(carte, refs[0])
    clavier.saisir(carte, True, "Mon profil", RETOUR)
    espace_lecteur.ouvrir()
    sortie = clavier.sortie()
    assert "Emprunts en cours (1)" in sortie
    assert "Prêter un document" not in sortie   # aucune action de gestion dans le profil
    assert clavier.restant() == []


# -------------------------------------------------------------- notifications


def test_notification_affichee_puis_marquee_lue(clavier):
    carte = creer_usager(nom="Nino Notif")
    uid = _id_de(carte)
    conn = db.get_conn()
    amendes.notifier(conn, uid, "reservation_prete", "Votre réservation de « Essai » est disponible.")
    conn.close()
    clavier.saisir(carte, True, RETOUR)
    espace_lecteur.ouvrir()
    assert "Votre réservation de « Essai » est disponible" in clavier.sortie()
    conn = db.get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM notification WHERE lue = 0").fetchone()[0]
    finally:
        conn.close()
    assert n == 0   # affichée = lue : elle ne sera pas reposée au prochain tour


# ----------------------------------------------------------------- historique


def test_historique_du_lecteur(clavier):
    _, refs = creer_oeuvre("Historique lecteur", nb_copies=1)
    carte = creer_usager(nom="Hugo Histo")
    circulation.emprunter(carte, refs[0])
    circulation.retourner(refs[0])
    clavier.saisir(carte, True, "Historique", RETOUR)
    espace_lecteur.ouvrir()
    sortie = clavier.sortie()
    assert "Historique (30 derniers)" in sortie and "Historique lecteur" in sortie
