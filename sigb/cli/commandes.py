"""Raccourcis en ligne de commande, pour aller vite ou automatiser.

Tout ce qu'ils font, le menu interactif le fait aussi : `python main.py` sans
argument ouvre le menu. Chaque raccourci appelle la MÊME couche métier (sigb.services).
"""

import argparse
from datetime import date

from sigb.cli import ui
from sigb.erreurs import ErreurMetier, ErreurReseau
from sigb.initialisation import initialiser_reference
from sigb.models import db
from sigb.services import (catalogue, circulation, import_service, lecture, pilotage,
                           reservations_service, usagers_service)


def _base() -> None:
    if not db.base_est_initialisee():
        initialiser_reference()


def cmd_recherche(a) -> int:
    lignes = catalogue.rechercher(" ".join(a.mots) or None, a.disponible, a.type, a.lisible)
    ui.tableau(["N°", "Titre", "Auteur(s)", "Année", "Disponibilité"],
               [[str(o["id"]), o["titre"][:44], (o["auteurs"] or "-")[:26], str(o["annee"] or "-"),
                 ui.disponibilite(o["nb_dispo"], o["nb_total"], bool(o["lien_numerique"]))] for o in lignes],
               titre=f"{len(lignes)} résultat(s)")
    return 0


def cmd_fiche(a) -> int:
    from sigb.cli.ecrans.catalogue import afficher_fiche

    f = catalogue.fiche_oeuvre(a.numero)
    if f is None:
        ui.erreur("Œuvre introuvable.")
        return 1
    afficher_fiche(f)
    return 0


def cmd_lire(a) -> int:
    cible = " ".join(a.livre)
    if cible.isdigit():
        oeuvre_id = int(cible)
    else:
        trouves = catalogue.rechercher(cible, lisible=True)
        if len(trouves) != 1:
            ui.tableau(["N°", "Titre"], [[str(o["id"]), o["titre"]] for o in trouves],
                       vide="Aucun livre lisible ne correspond.")
            if trouves:
                ui.info("Plusieurs livres correspondent : relancez avec le numéro (python main.py lire N°).")
            return 1
        oeuvre_id = trouves[0]["id"]
    with ui.attente("Préparation de la lecture…"):
        r = lecture.lire(oeuvre_id)
    if r["ouvert"]:
        ui.succes(f"« {r['titre']} » s'ouvre dans votre navigateur.")
    else:
        ui.attention("Aucun navigateur lancé. Ouvrez : " + r["cible"])
    return 0


def cmd_pret(a) -> int:
    ui.afficher_pret(circulation.emprunter(a.carte, a.document, acteur=ui.ACTEUR))
    return 0


def cmd_retour(a) -> int:
    ui.afficher_retour(circulation.retourner(a.document, acteur=ui.ACTEUR))
    return 0


def cmd_prolonger(a) -> int:
    r = circulation.prolonger(a.document, acteur=ui.ACTEUR)
    ui.succes(f"Prêt prolongé : à rendre avant le {ui.date_fr(str(r['nouvelle_echeance']))}.")
    return 0


def cmd_reserver(a) -> int:
    r = reservations_service.reserver(a.oeuvre, a.carte, acteur=ui.ACTEUR)
    ui.succes(f"Réservation enregistrée pour « {r['titre']} » (n°{r['rang_file']} dans la file).")
    return 0


def cmd_usager(a) -> int:
    f = usagers_service.inscription(a.nom, a.prenom, a.email, a.categorie, acteur=ui.ACTEUR)
    ui.succes(f"Lecteur inscrit : {ui.nom_lecteur(f)} — carte {f['numero_carte']}, "
              f"adhésion jusqu'au {ui.date_fr(f['expiration_adhesion'])}.")
    return 0


def cmd_exemplaire(a) -> int:
    refs = catalogue.ajouter_exemplaires(a.oeuvre, a.nombre, a.cote, a.etat, a.origine, acteur=ui.ACTEUR)
    ui.succes("Exemplaire(s) créé(s) : " + ", ".join(refs))
    return 0


def cmd_retards(a) -> int:
    lignes = pilotage.poste_guichet()["retards"]
    ui.tableau(["Document", "Titre", "Lecteur", "À rendre le", "Retard"],
               [[r["reference"], r["titre"][:34], f"{r['prenom'] or ''} {r['nom']}".strip(),
                 ui.date_fr(r["date_retour_prevue"]),
                 f"{(db.aujourd_hui() - date.fromisoformat(r['date_retour_prevue'][:10])).days} j"] for r in lignes],
               titre=f"Retards ({len(lignes)})", vide="Aucun retard.")
    return 0


def cmd_traiter(a) -> int:
    liberees = reservations_service.traiter_expirations()
    for ligne in liberees:
        ui.info(ligne)
    ui.succes(f"{len(liberees)} réservation(s) libérée(s).")
    return 0


def cmd_import(a) -> int:
    from sigb.cli.ecrans import ajout

    try:
        with ui.attente("Recherche en cours…"):
            notices = import_service.rechercher_libre(" ".join(a.recherche), a.source, a.limite)
    except (ErreurReseau, ValueError, LookupError) as e:
        ui.erreur(str(e))
        return 3
    if not notices:
        ui.attention("Aucun résultat.")
        return 1
    if a.choix is None:
        ui.tableau(["N°", "Notice"], [[str(i), ajout.libelle(n)] for i, n in enumerate(notices, 1)])
        ui.info("Ajoutez-en une avec :  python main.py import … --choix N°")
        return 0
    if not 1 <= a.choix <= len(notices):
        ui.erreur(f"Choix invalide (1 à {len(notices)}).")
        return 1
    n = notices[a.choix - 1]
    oid, creee = import_service.importer_notice(
        n, acteur=ui.ACTEUR, nb_copies=0 if n.type_document == "numerique" else a.copies, cote=a.cote)
    (ui.succes if creee else ui.info)(f"« {n.titre} » ajouté (œuvre n°{oid})." if creee else "Déjà au catalogue.")
    return 0


def cmd_lecteur(a) -> int:
    """Espace lecteur : ses emprunts, ses réservations, sa lecture, son profil."""
    from sigb.cli.ecrans import espace_lecteur

    if a.carte:
        trouves = usagers_service.chercher(a.carte)
        if not trouves:
            ui.erreur(f"Aucun lecteur ne correspond à « {a.carte} ».")
            return 1
        if len(trouves) > 1:
            ui.tableau(["Carte", "Nom"], [[u["numero_carte"], ui.nom_lecteur(u)] for u in trouves],
                       titre=f"{len(trouves)} lecteurs correspondent : précisez la carte.")
            return 1
        ui.tenter(espace_lecteur.session, trouves[0])
        return 0
    ui.tenter(espace_lecteur.ouvrir)
    return 0


def construire_analyseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="main.py", add_help=False,
                                description="Bibliothèque. Sans commande : ouvre le menu interactif.")
    p.add_argument("-h", "--aide", "--help", action="help", help="affiche cette aide")
    sous = p.add_subparsers(dest="commande", title="raccourcis", metavar="")

    def cmd(nom, aide, fn):
        sp = sous.add_parser(nom, help=aide)
        sp.set_defaults(fn=fn)
        return sp

    r = cmd("recherche", "cherche dans le catalogue", cmd_recherche)
    r.add_argument("mots", nargs="*")
    r.add_argument("--disponible", action="store_true")
    r.add_argument("--lisible", action="store_true", help="seulement les livres à lire en ligne")
    r.add_argument("--type", choices=("livre", "bd", "dvd", "periode", "numerique"))
    cmd("fiche", "fiche d'une œuvre", cmd_fiche).add_argument("numero", type=int)
    cmd("lire", "ouvre un livre dans le navigateur", cmd_lire).add_argument("livre", nargs="+", help="n° ou titre")
    l = cmd("lecteur", "ouvre l'espace personnel d'un lecteur", cmd_lecteur)
    l.add_argument("carte", nargs="?", help="n° de carte (« 1 » suffit), courriel ou nom")
    pr = cmd("pret", "enregistre un prêt", cmd_pret)
    pr.add_argument("carte", help="n° de carte (« 1 » suffit) ou nom")
    pr.add_argument("document", help="n° du document (« 12 » suffit)")
    cmd("retour", "enregistre un retour", cmd_retour).add_argument("document")
    cmd("prolonger", "prolonge un prêt (une fois)", cmd_prolonger).add_argument("document")
    rs = cmd("reserver", "réserve une œuvre", cmd_reserver)
    rs.add_argument("carte")
    rs.add_argument("oeuvre", type=int)
    u = cmd("usager", "inscrit un lecteur", cmd_usager)
    u.add_argument("nom")
    u.add_argument("prenom", nargs="?")
    u.add_argument("--email")
    u.add_argument("--categorie", default="adulte", choices=("jeune", "adulte", "collectivite"))
    e = cmd("exemplaire", "ajoute des exemplaires", cmd_exemplaire)
    e.add_argument("oeuvre", type=int)
    e.add_argument("cote")
    e.add_argument("-n", "--nombre", type=int, default=1)
    e.add_argument("--etat", default="bon", choices=("neuf", "bon", "use", "repare"))
    e.add_argument("--origine", default="achat", choices=("achat", "don"))
    i = cmd("import", "cherche un livre sur internet et l'ajoute", cmd_import)
    i.add_argument("recherche", nargs="+")
    i.add_argument("--source", default="auto", choices=("auto", "openlibrary", "classiques", "bnf", "gutenberg"))
    i.add_argument("--limite", type=int, default=10)
    i.add_argument("--choix", type=int, help="n° de la notice à ajouter")
    i.add_argument("--copies", type=int, default=1)
    i.add_argument("--cote")
    cmd("retards", "liste les prêts en retard", cmd_retards)
    cmd("traiter", "libère les réservations non récupérées (tâche planifiée)", cmd_traiter)
    return p


def executer(argv=None) -> int:
    analyseur = construire_analyseur()
    args = analyseur.parse_args(argv)
    if args.commande is None:
        from sigb.cli import app

        app.lancer()
        return 0
    _base()
    try:
        return args.fn(args)
    except ErreurMetier as e:
        ui.erreur(str(e))
        return 2
    except ErreurReseau as e:
        ui.erreur(str(e))
        return 3
