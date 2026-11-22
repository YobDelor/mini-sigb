"""Espace lecteur : le compte personnel du lecteur, en libre-service.

Là où le bibliothécaire gère toute la bibliothèque (guichet, fonds, règles),
le lecteur dispose d'un espace limité à SES données : ses emprunts (avec
prolongation en un geste), ses réservations, ses amendes, son historique et
la lecture en ligne.

Les services de circulation acceptent un `usager_id` précisément pour ce cas :
chaque action est verrouillée sur le compte identifié à l'ouverture, il est
impossible de prolonger ou d'annuler sur un autre compte. Aucune opération de
gestion n'est proposée ici : ce n'est pas le guichet.
"""

from rich.markup import escape
from rich.text import Text

from sigb.cli import ui
from sigb.cli.ecrans import lecteurs
from sigb.cli.ecrans import lecture as ecran_lecture
from sigb.models import amendes, db
from sigb.services import catalogue, circulation, reservations_service, usagers_service


def _acteur(u) -> str:
    """Signature des opérations dans le journal : la carte du lecteur, pas un agent."""
    return f"{u['numero_carte']} (lecteur)"


def identifier():
    """« Qui êtes-vous ? » — n° de carte (« 1 » suffit), courriel ou nom.

    Renvoie le lecteur (ligne de base), ou None si abandon (Entrée vide).
    La confirmation « c'est bien votre compte ? » évite d'ouvrir celui d'un
    homonyme quand la recherche renvoie plusieurs personnes.
    """
    while True:
        saisie = ui.demander("Votre n° de carte (« 1 » suffit), courriel ou nom — Entrée vide pour revenir")
        if not saisie:
            return None
        trouves = usagers_service.chercher(saisie)
        if not trouves:
            ui.attention(f"Aucun lecteur ne correspond à « {saisie} » : vérifiez l'orthographe, "
                         "ou passez au guichet pour vous inscrire.")
            continue
        if len(trouves) == 1:
            usager = trouves[0]
        else:
            usager = ui.choisir(f"{len(trouves)} lecteurs correspondent :",
                                [(f"{ui.nom_lecteur(x)} — {x['numero_carte']}", x) for x in trouves])
        if ui.confirmer(f"Bonjour {ui.nom_lecteur(usager)} ({usager['numero_carte']}) — c'est bien votre compte ?", True):
            return usager


def ouvrir() -> None:
    """Point d'entrée depuis le choix de profil : identification puis session."""
    usager = identifier()
    if usager is None:
        return
    session(usager)


# ---------------------------------------------------------------- session


def session(usager) -> None:
    """Menu personnel du lecteur `usager` : uniquement ses données, ses actions."""
    while True:
        d = usagers_service.fiche(usager["id"])
        _afficher_espace(d)
        actions = [
            ("Mes emprunts", "emprunts"),
            ("Lire un livre en ligne", "lire"),
            ("Réserver une œuvre", "reserver"),
            ("Mes réservations", "reservations"),
            ("Mon profil — tout voir", "profil"),
            ("Historique des prêts", "historique"),
        ]
        try:
            choix = ui.choisir("Votre espace", actions, retour="Fermer ma session")
        except ui.Retour:
            return
        ecran = {"emprunts": _emprunts, "lire": _lire, "reserver": _reserver,
                 "reservations": _reservations, "profil": _profil, "historique": _historique}[choix]
        ui.tenter(ecran, d)


def _afficher_espace(d: dict) -> None:
    """Encadré personnel : identité, état du compte, messages jamais vus."""
    u = d["usager"]
    nb = len(d["prets_en_cours"])
    lignes = [
        f"{u['categorie_usager']} · adhésion jusqu'au {ui.date_fr(u['expiration_adhesion'])} · "
        f"{nb} emprunt{'s' if nb > 1 else ''} en cours"
        + (f" · {d['total_amendes']:.2f} € dus" if d["total_amendes"] else ""),
        "[ok]Compte en règle : prêts autorisés[/]" if not d["bloque"]
        else f"[ko]Carte bloquée : {escape(d['motif_blocage'])}[/]",
    ]
    nouvelles = [n for n in d["notifications"] if not n["lue"]]
    if nouvelles:
        lignes.append("")
        for n in nouvelles[:5]:
            lignes.append(f"[info]›[/] {escape(n['message'])}")
    ui.carte(f"Espace de {escape(ui.nom_lecteur(u))} — {u['numero_carte']}", lignes,
             "#e0af68" if d["bloque"] else "#7aa2f7")
    if nouvelles:
        # affiché à l'écran = lu : on ne les reposera pas à la prochaine boucle
        with db.transaction() as conn:
            amendes.marquer_toutes_lues(conn, u["id"])


# ---------------------------------------------------------------- écrans


def _emprunts(d: dict) -> None:
    """Ses emprunts en cours, et la prolongation en un geste (règle n°5)."""
    ui.en_tete("Mes emprunts")
    aujourdhui = db.aujourd_hui().isoformat()
    ui.tableau(["Référence", "Document", "À rendre le", ""],
               [[p["reference"], p["titre"][:44], ui.date_fr(p["date_retour_prevue"]),
                 Text("en retard", style="ko") if p["date_retour_prevue"] < aujourdhui
                 else ("prolongé" if p["prolonge"] else "")]
                for p in d["prets_en_cours"]],
               titre=f"Emprunts en cours ({len(d['prets_en_cours'])})",
               vide="Aucun emprunt en cours. Passez au guichet pour emprunter.")
    prolongables = [p for p in d["prets_en_cours"]
                    if not p["prolonge"] and p["date_retour_prevue"] >= aujourdhui]
    if prolongables and not d["bloque"]:
        if ui.confirmer("Prolonger un prêt (une seule fois par prêt) ?", False):
            p = ui.choisir("Quel prêt prolonger ?",
                           [(f"{p['reference']}  {p['titre'][:40]} — retour le {ui.date_fr(p['date_retour_prevue'])}", p)
                            for p in prolongables])
            r = circulation.prolonger(p["reference"], acteur=_acteur(d["usager"]),
                                      usager_id=d["usager"]["id"])
            ui.succes(f"« {r['titre']} » prolongé : à rendre avant le {ui.date_fr(str(r['nouvelle_echeance']))}.")
    elif d["prets_en_cours"] and d["bloque"]:
        ui.attention("Prolongation indisponible : votre carte est bloquée (voir l'encadré).")


def _lire(d: dict) -> None:
    """La lecture en ligne, comme depuis l'écran du bibliothécaire."""
    ecran_lecture.lire()


def _reserver(d: dict) -> None:
    """Réserver une œuvre : la file d'attente sert quand tout est emprunté."""
    ui.en_tete("Réserver une œuvre",
               "Quand tous les exemplaires sont empruntés, entrez dans la file : "
               "un exemplaire sera mis de côté pour vous à son retour.")
    resultats = catalogue.rechercher(ui.demander("Titre ou auteur (Entrée = tout le catalogue)"), limite=12)
    if not resultats:
        ui.attention("Aucune œuvre ne correspond.")
        return
    o = ui.choisir("Quelle œuvre ?", [
        (f"{o['titre'][:50]} — {(o['auteurs'] or '?')[:24]}  ({ui.disponibilite(o['nb_dispo'], o['nb_total'], bool(o['lien_numerique']))})", o)
        for o in resultats])
    r = reservations_service.reserver(o["id"], d["usager"]["numero_carte"], acteur=_acteur(d["usager"]))
    ui.succes(f"Réservation enregistrée pour « {r['titre']} » (n°{r['rang_file']} dans la file).")


def _reservations(d: dict) -> None:
    """Ses réservations, avec la possibilité d'annuler (que les siennes)."""
    ui.en_tete("Mes réservations")
    if not d["reservations"]:
        ui.info("Aucune réservation en cours.")
        return
    ui.tableau(["Document", "Situation"],
               [[r["titre"][:50], f"mis de côté jusqu'au {ui.date_fr(r['date_expiration'])}"
                 if r["statut"] == "prete" else "en attente d'un retour"]
                for r in d["reservations"]], titre="Réservations en cours")
    r = ui.choisir("Annuler une réservation :", [(x["titre"][:60], x) for x in d["reservations"]])
    ui.succes(reservations_service.annuler(r["id"], acteur=_acteur(d["usager"]),
                                           usager_id=d["usager"]["id"]))


def _profil(d: dict) -> None:
    """Tout le dossier, en lecture seule : pas une seule action de gestion."""
    lecteurs.afficher_dossier(d)
    ui.pause()


def _historique(d: dict) -> None:
    ui.tableau(["Document", "Prêté le", "Rendu le"],
               [[p["titre"][:50], ui.date_fr(p["date_pret"]),
                 ui.date_fr(p["date_retour_reelle"]) if p["date_retour_reelle"] else "en cours"]
                for p in d["historique"][:30]], titre="Historique (30 derniers)", vide="Aucun historique.")
    ui.pause()
