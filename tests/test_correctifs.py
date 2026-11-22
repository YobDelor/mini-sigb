"""Corrections de la version retravaillée : chaque bug trouvé à la relecture
a son test, plus la saisie tolérante et la recherche sans accents."""

import pytest

from tests.helpers import creer_oeuvre, creer_usager

from sigb.erreurs import ErreurMetier
from sigb.models import db, oeuvres, usagers
from sigb.saisie import normaliser_carte, normaliser_reference, sans_accents
from sigb.services import circulation, reservations_service


def _id_usager(carte):
    conn = db.get_conn()
    try:
        return usagers.par_carte(conn, carte)["id"]
    finally:
        conn.close()


def test_premier_de_la_file_recupere_son_exemplaire_meme_si_un_autre_attend():
    """Bug : B (réservation prête) était refusé parce que C attendait derrière."""
    oid, refs = creer_oeuvre("Livre rare", nb_copies=1)
    a, b, c = creer_usager(nom="A A"), creer_usager(nom="B B"), creer_usager(nom="C C")
    circulation.emprunter(a, refs[0])
    reservations_service.reserver(oid, b)
    reservations_service.reserver(oid, c)
    circulation.retourner(refs[0])
    assert circulation.emprunter(b, refs[0])["carte"] == b
    with pytest.raises(ErreurMetier):          # et C n'a toujours pas le droit de passer devant
        circulation.emprunter(c, refs[0])


def test_un_lecteur_ne_prolonge_pas_le_pret_d_un_autre():
    _, refs = creer_oeuvre("Prêt privé", nb_copies=1)
    a, c = creer_usager(nom="A A"), creer_usager(nom="C C")
    circulation.emprunter(a, refs[0])
    with pytest.raises(ErreurMetier):
        circulation.prolonger(refs[0], usager_id=_id_usager(c))
    circulation.prolonger(refs[0], usager_id=_id_usager(a))   # le propriétaire, lui, peut


def test_un_lecteur_n_annule_pas_la_reservation_d_un_autre():
    oid, refs = creer_oeuvre("Réservé", nb_copies=1)
    a, b, c = creer_usager(nom="A A"), creer_usager(nom="B B"), creer_usager(nom="C C")
    circulation.emprunter(a, refs[0])
    reservations_service.reserver(oid, b)
    conn = db.get_conn()
    res_id = conn.execute("SELECT id FROM reservation").fetchone()["id"]
    conn.close()
    with pytest.raises(ErreurMetier):
        reservations_service.annuler(res_id, usager_id=_id_usager(c))
    reservations_service.annuler(res_id, usager_id=_id_usager(b))


def test_saisie_tolerante_carte_et_reference():
    assert normaliser_carte("1") == "US-000001"
    assert normaliser_carte(" us-12 ") == "US-000012"
    assert normaliser_reference("ex7") == "EX-000007"
    assert normaliser_reference("EX-000007") == "EX-000007"
    assert normaliser_carte("Dupont") == "Dupont"


def test_pret_avec_saisie_courte_et_par_nom():
    _, refs = creer_oeuvre("Saisie courte", nb_copies=2)
    creer_usager(nom="Zéphyrin Unique")
    r = circulation.emprunter("1", refs[0].replace("EX-0000", ""))       # « 1 » et « 1 »
    assert r["carte"] == "US-000001"
    r2 = circulation.emprunter("zephyrin", refs[1])                       # nom, sans accent
    assert "Unique" in r2["usager"]


def test_nom_ambigu_refuse_avec_la_liste():
    creer_usager(nom="Durand Un")
    creer_usager(nom="Durand Deux")
    _, refs = creer_oeuvre("Ambigu", nb_copies=1)
    with pytest.raises(ErreurMetier, match="Plusieurs lecteurs"):
        circulation.emprunter("durand", refs[0])


def test_operation_guichet_decide_pret_ou_retour():
    _, refs = creer_oeuvre("Scan", nb_copies=1)
    carte = creer_usager()
    with pytest.raises(ErreurMetier, match="carte"):
        circulation.operation_guichet("", refs[0])        # disponible sans carte
    assert circulation.operation_guichet(carte, refs[0])["operation"] == "pret"
    r = circulation.operation_guichet("", refs[0])         # emprunté : c'est un retour
    assert r["operation"] == "retour"


def test_recherche_sans_accents_multi_mots_et_disponibilite():
    oid, _ = creer_oeuvre("L'Étranger", auteur="Albert Camus", nb_copies=2)
    creer_oeuvre("La Peste", auteur="Albert Camus", nb_copies=0)
    conn = db.get_conn()
    try:
        trouve = oeuvres.recherche(conn, q="etranger camus")
        assert [o["titre"] for o in trouve] == ["L'Étranger"]
        assert trouve[0]["nb_dispo"] == 2 and trouve[0]["auteurs"] == "Albert Camus"
        assert len(oeuvres.recherche(conn, q="CAMUS")) == 2
        assert [o["titre"] for o in oeuvres.recherche(conn, q="camus", disponible=True)] == ["L'Étranger"]
    finally:
        conn.close()
    assert sans_accents("Hergé") == "herge"


def test_inscription_courriel_en_double_est_un_refus_clair():
    from sigb.services import usagers_service

    usagers_service.inscription("Un", None, "x@exemple.fr", "adulte")
    with pytest.raises(ErreurMetier, match="courriel"):
        usagers_service.inscription("Deux", None, "x@exemple.fr", "adulte")


def test_import_garde_le_type_de_document():
    from sigb.api.common import Notice
    from sigb.services import import_service

    oid, _ = import_service.importer_notice(Notice(titre="Un film", type_document="dvd"), cote="DVD x")
    conn = db.get_conn()
    try:
        assert oeuvres.par_id(conn, oid)["type_document"] == "dvd"
    finally:
        conn.close()
