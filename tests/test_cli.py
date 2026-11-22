"""Écrans du CLI : les saisies clavier sont remplacées par des réponses scriptées,
la sortie est capturée. On vérifie la base de données ET l'affichage."""

import pytest
from rich.console import Console

from sigb.api.common import Notice
from sigb.cli import app, commandes, ui
from sigb.cli.ecrans import ajout, catalogue as ecran_catalogue, circulation as ecran_circ, lecteurs, lecture as ecran_lecture
from sigb.models import db, oeuvres, usagers
from sigb.services import import_service
from sigb.services import lecture as service_lecture
from tests.helpers import creer_oeuvre, creer_usager

RETOUR = "<retour>"


@pytest.fixture()
def clavier(monkeypatch):
    """Fournit `saisir(*reponses)` ; renvoie la sortie capturée via `sortie()`."""
    file, console = [], Console(record=True, width=130, force_terminal=False, theme=ui.THEME)
    monkeypatch.setattr(ui, "console", console)

    def suivante():
        assert file, "Le programme demande une saisie non prévue par le scénario."
        r = file.pop(0)
        if r == RETOUR:
            raise ui.Retour()
        return r

    def demander(texte, defaut="", obligatoire=False, valider=None):
        r = suivante()
        r = defaut if r is None else r
        if valider and r and valider(r) is not True:
            pytest.fail(f"saisie refusée par la validation : {r!r} ({valider(r)})")
        return r

    def choisir(texte, choix, defaut=None, retour="← Retour"):
        r = suivante()
        for libelle, valeur in choix:
            if str(r).lower() in libelle.lower():
                return valeur
        pytest.fail(f"Aucun choix ne contient {r!r} dans {[c[0] for c in choix]}")

    def cocher(texte, choix):
        r = suivante()
        return [v for lib, v in choix if any(str(m).lower() in lib.lower() for m in r)]

    monkeypatch.setattr(ui, "demander", demander)
    monkeypatch.setattr(ui, "choisir", choisir)
    monkeypatch.setattr(ui, "cocher", cocher)
    monkeypatch.setattr(ui, "entier", lambda texte, defaut, mini=0, maxi=999, **k: (lambda r: defaut if r is None else r)(suivante()))
    monkeypatch.setattr(ui, "confirmer", lambda texte, defaut=True: (lambda r: defaut if r is None else r)(suivante()))
    monkeypatch.setattr(ui, "pause", lambda: None)

    class Clavier:
        def saisir(self, *reponses):
            file.extend(reponses)

        def sortie(self):
            return console.export_text()

        def restant(self):
            return list(file)

    return Clavier()


def test_inscription_affiche_la_carte(clavier):
    clavier.saisir("Durand", "Alice", "alice@exemple.fr", "Adulte")
    lecteur = lecteurs.inscrire()
    assert lecteur["numero_carte"] == "US-000001"
    sortie = clavier.sortie()
    assert "Lecteur inscrit" in sortie and "US-000001" in sortie and "Alice Durand" in sortie


def test_guichet_pret_puis_retour_par_titre(clavier):
    _, refs = creer_oeuvre("Les Misérables", auteur="Victor Hugo", nb_copies=1)
    creer_usager(nom="Martin Zoé")
    # 1) titre -> prêt à « martin » ; 2) même titre -> retour confirmé ; 3) fin
    clavier.saisir("hugo", "martin", "miserables", True, "")
    ecran_circ.guichet()
    sortie = clavier.sortie()
    assert "Prêt enregistré" in sortie and "Zoé" in sortie and "Retour enregistré" in sortie
    assert "à remettre en rayon" in sortie and clavier.restant() == []


def test_guichet_erreur_metier_est_un_message_et_la_boucle_continue(clavier):
    creer_oeuvre("Un livre", nb_copies=1)
    clavier.saisir("introuvable-xyz", "")
    ecran_circ.guichet()
    assert "Aucun document ne correspond" in clavier.sortie()


def test_guichet_lecteur_inconnu_propose_l_inscription(clavier):
    creer_oeuvre("Livre B", nb_copies=1)
    clavier.saisir("livre b", "Inconnu", True, "Nouveau", None, None, "Adulte", "")   # inscrit puis prête
    ecran_circ.guichet()
    sortie = clavier.sortie()
    assert "Aucun lecteur ne correspond" in sortie and "Lecteur inscrit" in sortie and "Prêt enregistré" in sortie


def test_fiche_ajout_d_exemplaires(clavier):
    oid, _ = creer_oeuvre("Fiche", nb_copies=1)
    clavier.saisir("Ajouter des exemplaires", 2, "FIC x", "Achat", RETOUR)
    ecran_catalogue.fiche(oid)
    conn = db.get_conn()
    try:
        assert oeuvres.nb_exemplaires_par_statut(conn, oid)["disponible"] == 3
    finally:
        conn.close()
    assert "Ajouté" in clavier.sortie()


def test_dossier_lecteur_pret_et_prolongation(clavier):
    _, refs = creer_oeuvre("Dossier", nb_copies=2)
    carte = creer_usager(nom="Petit Léa")
    conn = db.get_conn()
    uid = usagers.par_carte(conn, carte)["id"]
    conn.close()
    clavier.saisir("Prêter un document", "dossier", "Prolonger un prêt", "Dossier", RETOUR)
    lecteurs.dossier(uid)
    sortie = clavier.sortie()
    assert "Prêt enregistré" in sortie and "Prêt prolongé" in sortie and "Emprunts en cours (1)" in sortie


def test_ajout_en_ligne_coche_et_importe(clavier, monkeypatch):
    notices = [Notice(titre="Premier", auteurs=["A"], isbn="9782070612758", source="openlibrary"),
               Notice(titre="Second", auteurs=["B"], source="gutenberg", source_id="9", type_document="numerique",
                      lien_numerique="https://x/9.html")]
    monkeypatch.setattr(import_service, "rechercher_libre", lambda q, s="auto", limite=10: notices)
    clavier.saisir("petit", ["Premier", "Second"], 2, None, False)   # 2 exemplaires, cote par défaut, pas de lecture
    ajout.chercher_en_ligne()
    conn = db.get_conn()
    try:
        tous = {o["titre"]: o for o in oeuvres.recherche(conn)}
    finally:
        conn.close()
    assert tous["Premier"]["nb_total"] == 2 and tous["Second"]["nb_total"] == 0     # numérique : pas d'exemplaire
    assert "à lire en ligne" in clavier.sortie()


def test_ecran_lire_ouvre_la_liseuse(clavier, monkeypatch):
    oid, _ = import_service.importer_notice(Notice(titre="Texte libre", lien_numerique="https://x/t.html",
                                                    source="gutenberg", source_id="1", type_document="numerique"), nb_copies=0)
    ouverts = []
    monkeypatch.setattr(service_lecture, "lire", lambda i: ouverts.append(i) or
                        {"titre": "Texte libre", "mode": "liseuse", "cible": "file:///x", "ouvert": True, "depuis_cache": False})
    clavier.saisir("", "Texte libre")
    ecran_lecture.lire()
    assert ouverts == [oid] and "s'ouvre dans votre navigateur" in clavier.sortie()


def test_ecran_lire_sans_livre_numerique_propose_gutenberg(clavier, monkeypatch):
    appels = []
    monkeypatch.setattr(ajout, "garnir", lambda: appels.append(1))
    clavier.saisir("", True)
    ecran_lecture.lire()
    assert appels == [1] and "Aucun livre à lire en ligne" in clavier.sortie()


def test_premier_lancement_catalogue_vide_propose_de_garnir(clavier, monkeypatch):
    appels = []
    monkeypatch.setattr(ajout, "garnir", lambda: appels.append(1))
    clavier.saisir(True)
    app.accueil_catalogue_vide()
    assert appels == [1] and "Votre catalogue est vide" in clavier.sortie()


def test_menu_principal_quitter(clavier, monkeypatch):
    monkeypatch.setattr(ui.console, "clear", lambda: None)
    # 1) profil bibliothécaire  2) « plus tard » à l'écran de bienvenue  3) quitter le menu  4) Quitter
    clavier.saisir("guichet", RETOUR, RETOUR, RETOUR)
    app.lancer()
    sortie = clavier.sortie()
    assert "À bientôt" in sortie and clavier.restant() == []
    # premier lancement : le bandeau ne doit apparaître qu'une fois (jamais deux d'affilée)
    assert sortie.count("B I B L I O T H È Q U E") == 1


def test_menu_principal_catalogue_plein_bandeau_affiche_une_seule_fois(clavier, monkeypatch):
    creer_oeuvre("Présent", nb_copies=1)
    monkeypatch.setattr(ui.console, "clear", lambda: None)
    clavier.saisir("guichet", RETOUR, RETOUR)   # bibliothécaire, quitter le menu, Quitter
    app.lancer()
    assert clavier.sortie().count("B I B L I O T H È Q U E") == 1


def test_menu_principal_ouvre_un_ecran_puis_quitte(clavier, monkeypatch):
    creer_oeuvre("Présent", nb_copies=1)                       # catalogue non vide : pas de bienvenue
    monkeypatch.setattr(ui.console, "clear", lambda: None)
    # bibliothécaire, ouvre la recherche, quitte la liste, quitte le menu, Quitter
    clavier.saisir("guichet", "Chercher un livre", "present", RETOUR, RETOUR, RETOUR)
    app.lancer()
    sortie = clavier.sortie()
    assert "1 œuvre" in sortie and "Présent" in sortie and "À bientôt" in sortie


def test_menu_principal_profil_lecteur_ouvre_espace(clavier, monkeypatch):
    creer_usager(nom="Zola Emilie")
    monkeypatch.setattr(ui.console, "clear", lambda: None)
    # profil Lecteur, identification par carte, confirmation, fermer la session, Quitter
    clavier.saisir("lecteur", "1", True, RETOUR, RETOUR)
    app.lancer()
    sortie = clavier.sortie()
    assert "Espace de" in sortie and "Zola Emilie" in sortie
    assert "À bientôt" in sortie and clavier.restant() == []


def test_raccourcis_recherche_pret_retour_et_codes_de_sortie(clavier):
    _, refs = creer_oeuvre("Raccourci", auteur="Jules Verne", nb_copies=1)
    creer_usager(nom="Verne Fan")
    assert commandes.executer(["recherche", "verne"]) == 0 and "Raccourci" in clavier.sortie()
    assert commandes.executer(["pret", "1", "1"]) == 0 and "Prêt enregistré" in clavier.sortie()
    assert commandes.executer(["pret", "1", "1"]) == 2                              # refus métier -> code 2
    assert "n'est pas disponible" in clavier.sortie()
    assert commandes.executer(["retour", "1"]) == 0
    assert commandes.executer(["retards"]) == 0
    assert commandes.executer(["usager", "Nouveau", "Test", "--email", "n@x.fr"]) == 0


def test_raccourci_import_erreur_reseau_code_3(clavier, monkeypatch):
    from sigb.erreurs import ErreurReseau

    def panne(*a, **k):
        raise ErreurReseau("Source injoignable (exemple).")
    monkeypatch.setattr(import_service, "rechercher_libre", panne)
    assert commandes.executer(["import", "petit prince"]) == 3
    assert "Source injoignable" in clavier.sortie()


def test_affichage_ne_casse_pas_sur_des_crochets_et_colore_le_retard(clavier):
    """Un titre « [gras] » ne doit pas être interprété comme du balisage, et « en retard » reste coloré."""
    from datetime import timedelta

    oid, refs = creer_oeuvre("[b]Titre[/b] [piège]", auteur="A [x]", nb_copies=1)
    carte = creer_usager(nom="Retard Er")
    from sigb.services import circulation as service_circ, usagers_service

    service_circ.emprunter(carte, refs[0])
    conn = db.get_conn()
    conn.execute("UPDATE pret SET date_retour_prevue = ?", ((db.aujourd_hui() - timedelta(days=3)).isoformat(),))
    uid = usagers.par_carte(conn, carte)["id"]
    conn.close()
    ecran_catalogue.afficher_fiche(__import__("sigb.services.catalogue", fromlist=["x"]).fiche_oeuvre(oid))
    lecteurs.afficher_dossier(usagers_service.fiche(uid))
    sortie = clavier.sortie()
    assert "[b]Titre[/b] [piège]" in sortie and "en retard" in sortie and "[ko]" not in sortie


def test_ecran_a_faire_retards_relance_et_dossier(clavier):
    from datetime import timedelta

    from sigb.cli.ecrans import taches
    from sigb.services import circulation as service_circ

    _, refs = creer_oeuvre("En retard", nb_copies=1)
    carte = creer_usager(nom="Tardif Tom")
    service_circ.emprunter(carte, refs[0])
    conn = db.get_conn()
    conn.execute("UPDATE pret SET date_retour_prevue = ?", ((db.aujourd_hui() - timedelta(days=5)).isoformat(),))
    conn.close()
    assert taches.a_faire() == 1
    clavier.saisir("relance", "En retard", "Ouvrir le dossier", "En retard", RETOUR, RETOUR)
    taches.afficher()
    sortie = clavier.sortie()
    assert "Retards (1)" in sortie and "5 j" in sortie and "Relance enregistrée" in sortie and "Tardif Tom" in sortie


def test_ecran_a_faire_sans_retard(clavier):
    from sigb.cli.ecrans import taches

    taches.afficher()
    assert "tout le monde est à l'heure" in clavier.sortie()


def test_reglages_modifier_une_regle_et_un_parametre(clavier):
    from sigb.cli.ecrans import reglages as ecran
    from sigb.models import regles
    from sigb.services import reglages as service

    clavier.saisir("Adulte", "Livre", True, 28, 7, RETOUR)          # règle : adulte × livre -> 28 j, 7 max
    ecran._regles()
    d = service.charger()
    assert d["regles"][("adulte", "livre")]["duree_jours"] == 28 and d["regles"][("adulte", "livre")]["quota"] == 7

    clavier.saisir("Amende par jour", "0,40", RETOUR)               # paramètre numérique
    ecran._parametres()
    assert service.charger()["params"][regles.P_MONTANT_AMENDE] == "0.40"

    clavier.saisir("Amende par jour", "abc", RETOUR)                # valeur invalide : message, rien de cassé
    ecran._parametres()
    assert "n'est pas un nombre" in clavier.sortie()
    assert service.charger()["params"][regles.P_MONTANT_AMENDE] == "0.40"


def test_reglages_journal_et_stats(clavier):
    from sigb.cli.ecrans import reglages as ecran

    creer_oeuvre("Pour le journal", nb_copies=1)
    ecran._journal()
    ecran._stats()
    sortie = clavier.sortie()
    assert "Journal" in sortie and "Œuvres au catalogue" in sortie
