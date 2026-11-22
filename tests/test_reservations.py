"""Tests des réservations : file ordonnée, mise de côté au retour, délai de
récupération, déclassement automatique (règle n°6) — et du désherbage."""

from datetime import timedelta

import pytest

from tests.helpers import creer_exemplaires, creer_oeuvre, creer_usager

from sigb.erreurs import ErreurMetier
from sigb.models import amendes, db, exemplaires, reservations
from sigb.services import catalogue, circulation, reservations_service


def _id_usager(carte: str) -> int:
    conn = db.get_conn()
    try:
        return conn.execute("SELECT id FROM usager WHERE numero_carte = ?", (carte,)).fetchone()[0]
    finally:
        conn.close()


def _oeuvre_id(reference: str) -> int:
    conn = db.get_conn()
    try:
        return exemplaires.par_reference(conn, reference)["oeuvre_id"]
    finally:
        conn.close()


def _file(oeuvre_id: int):
    conn = db.get_conn()
    try:
        return reservations.file_attente(conn, oeuvre_id)
    finally:
        conn.close()


def test_reservation_refusee_si_exemplaire_disponible():
    """Règle réaliste : si un exemplaire est disponible, on l'emprunte,
    on ne réserve pas."""
    _, refs = creer_oeuvre("Roman dispo", nb_copies=1)
    carte = creer_usager("adulte", nom="Presse P")
    with pytest.raises(ErreurMetier, match="disponibl"):
        reservations_service.reserver(_oeuvre_id(refs[0]), carte)


def test_file_dattente_ordonnee_par_date():
    """Règle n°6 : la réservation est une file ordonnée par date de demande."""
    _, refs = creer_oeuvre("Roman attendu", nb_copies=1)
    carte_a = creer_usager("adulte", nom="File A")
    circulation.emprunter(carte_a, refs[0])
    oeuvre_id = _oeuvre_id(refs[0])
    carte_b = creer_usager("adulte", nom="File B")
    carte_c = creer_usager("adulte", nom="File C")
    reservations_service.reserver(oeuvre_id, carte_b)
    reservations_service.reserver(oeuvre_id, carte_c)
    assert [f["numero_carte"] for f in _file(oeuvre_id)] == [carte_b, carte_c]


def test_retour_sert_le_premier_de_la_file():
    """Au retour : mise de côté, notification, délai de récupération (règle n°6)."""
    _, refs = creer_oeuvre("Roman file 1", nb_copies=1)
    carte_a = creer_usager("adulte", nom="Retour A")
    circulation.emprunter(carte_a, refs[0])
    oeuvre_id = _oeuvre_id(refs[0])
    carte_b = creer_usager("adulte", nom="Reserv B")
    reservations_service.reserver(oeuvre_id, carte_b)

    circulation.retourner(refs[0])  # l'exemplaire revient : mis de côté pour B

    conn = db.get_conn()
    try:
        assert exemplaires.par_reference(conn, refs[0])["statut"] == db.STATUT_MIS_DE_COTE
        res = reservations.premiere_prete(conn, oeuvre_id)
        assert res is not None and res["usager_id"] == _id_usager(carte_b)
        assert res["date_expiration"] == (db.aujourd_hui() + timedelta(days=7)).isoformat()
        notifs = amendes.pour_usager(conn, _id_usager(carte_b))
        assert any("disponible" in n["message"] for n in notifs)
    finally:
        conn.close()

    # B vient récupérer sa réservation au guichet : le prêt aboutit
    resultat = circulation.emprunter(carte_b, refs[0])
    assert resultat["titre"] == "Roman file 1"
    conn = db.get_conn()
    try:
        assert reservations.par_id(conn, res["id"])["statut"] == reservations.SATISFAITE
    finally:
        conn.close()


def test_pret_refuse_si_reservation_autre_usager_en_attente():
    """Un exemplaire ajouté par l'agent ne doit pas passer devant la file :
    le prêt est refusé et la mise de côté proposée."""
    _, refs = creer_oeuvre("Roman queue", nb_copies=1)
    carte_a = creer_usager("adulte", nom="Queue A")
    circulation.emprunter(carte_a, refs[0])
    oeuvre_id = _oeuvre_id(refs[0])
    carte_b = creer_usager("adulte", nom="Queue B")
    reservations_service.reserver(oeuvre_id, carte_b)

    # l'agent ajoute un second exemplaire pendant que B attend
    refs2 = creer_exemplaires(oeuvre_id, 1, cote="TES ex2")
    carte_c = creer_usager("adulte", nom="Queue C")
    with pytest.raises(ErreurMetier, match="réservation est en attente"):
        circulation.emprunter(carte_c, refs2[0])
    # ... mais B lui-même peut l'emprunter : sa réservation est servie
    circulation.emprunter(carte_b, refs2[0])
    conn = db.get_conn()
    try:
        res = conn.execute(
            "SELECT * FROM reservation WHERE oeuvre_id = ?", (oeuvre_id,)
        ).fetchone()
        assert res["statut"] == reservations.SATISFAITE
    finally:
        conn.close()


def test_declassement_automatique_sert_la_file():
    """Règle n°6 : délai dépassé -> la réservation expire, l'exemplaire est
    remis de côté pour le suivant de la file."""
    _, refs = creer_oeuvre("Roman expire", nb_copies=1)
    carte_a = creer_usager("adulte", nom="Exp A")
    circulation.emprunter(carte_a, refs[0])
    oeuvre_id = _oeuvre_id(refs[0])
    carte_b = creer_usager("adulte", nom="Exp B")
    carte_c = creer_usager("adulte", nom="Exp C")
    reservations_service.reserver(oeuvre_id, carte_b)
    reservations_service.reserver(oeuvre_id, carte_c)
    circulation.retourner(refs[0])  # mise de côté pour B

    # B ne récupère pas : le délai expire
    with db.transaction() as txn:
        txn.execute(
            "UPDATE reservation SET date_expiration = '2000-01-01' WHERE oeuvre_id = ?",
            (oeuvre_id,),
        )
    issues = reservations_service.traiter_expirations()
    assert len(issues) == 1

    conn = db.get_conn()
    try:
        res_b = conn.execute(
            "SELECT * FROM reservation WHERE usager_id = ?", (_id_usager(carte_b),)
        ).fetchone()
        assert res_b["statut"] == reservations.EXPIREE
        res_c = reservations.premiere_prete(conn, oeuvre_id)
        assert res_c is not None and res_c["usager_id"] == _id_usager(carte_c)
        assert exemplaires.par_reference(conn, refs[0])["statut"] == db.STATUT_MIS_DE_COTE
    finally:
        conn.close()


def test_declassement_sans_suivant_remet_en_rayon():
    """Sans file restante, l'exemplaire déclassé retourne en rayon."""
    _, refs = creer_oeuvre("Roman expire seul", nb_copies=1)
    carte_a = creer_usager("adulte", nom="ExpS A")
    circulation.emprunter(carte_a, refs[0])
    oeuvre_id = _oeuvre_id(refs[0])
    carte_b = creer_usager("adulte", nom="ExpS B")
    reservations_service.reserver(oeuvre_id, carte_b)
    circulation.retourner(refs[0])
    with db.transaction() as txn:
        txn.execute(
            "UPDATE reservation SET date_expiration = '2000-01-01' WHERE oeuvre_id = ?",
            (oeuvre_id,),
        )
    reservations_service.traiter_expirations()
    conn = db.get_conn()
    try:
        assert exemplaires.par_reference(conn, refs[0])["statut"] == db.STATUT_DISPONIBLE
    finally:
        conn.close()


def test_annulation_de_la_mise_de_cote_remet_en_circuit():
    _, refs = creer_oeuvre("Roman annule", nb_copies=1)
    carte_a = creer_usager("adulte", nom="Ann A")
    circulation.emprunter(carte_a, refs[0])
    oeuvre_id = _oeuvre_id(refs[0])
    carte_b = creer_usager("adulte", nom="Ann B")
    reservations_service.reserver(oeuvre_id, carte_b)
    circulation.retourner(refs[0])
    conn = db.get_conn()
    try:
        res_id = reservations.premiere_prete(conn, oeuvre_id)["id"]
    finally:
        conn.close()
    reservations_service.annuler(res_id)
    conn = db.get_conn()
    try:
        assert exemplaires.par_reference(conn, refs[0])["statut"] == db.STATUT_DISPONIBLE
    finally:
        conn.close()


def test_desherbage_motif_obligatoire_et_trace():
    """Gestion du fonds : le désherbage est un retrait MOTIVE et documenté."""
    _, refs = creer_oeuvre("Roman à désherber", nb_copies=2)
    # motif trop court -> refus
    with pytest.raises(ErreurMetier, match="motif"):
        catalogue.desherber(refs[0], "usé")
    # exemplaire emprunté -> refus
    carte = creer_usager("adulte", nom="Desh D")
    circulation.emprunter(carte, refs[1])
    with pytest.raises(ErreurMetier, match="pas en rayon"):
        catalogue.desherber(refs[1], "usure avancée, pages manquantes")
    # cas nominal : statut retiré + motif conservé dans le journal (règle n°8)
    catalogue.desherber(refs[0], "usure avancée, pages manquantes")
    conn = db.get_conn()
    try:
        assert exemplaires.par_reference(conn, refs[0])["statut"] == db.STATUT_RETIRE
        journal = conn.execute(
            "SELECT details FROM journal WHERE action = 'desherbage' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert "usure avancée" in journal["details"]
    finally:
        conn.close()
