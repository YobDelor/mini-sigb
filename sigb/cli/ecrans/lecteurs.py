"""Lecteurs : inscription, dossier, prolongations, sanctions, règlements."""

from rich.markup import escape
from rich.text import Text

from sigb.cli import ui
from sigb.cli.ecrans import commun
from sigb.cli.ecrans.circulation import traiter
from sigb.models import db, regles
from sigb.services import circulation, reservations_service, usagers_service

CATEGORIES = (("Adulte", "adulte"), ("Jeune (moins de 14 ans)", "jeune"), ("Collectivité", "collectivite"))


def menu() -> None:
    while True:
        try:
            choix = ui.choisir("Lecteurs", [
                ("Ouvrir un dossier (recherche par nom ou n° de carte)", "chercher"),
                ("Inscrire un nouveau lecteur", "inscrire"),
                ("Voir tous les lecteurs", "liste"),
            ])
        except ui.Retour:
            return
        ui.tenter({"chercher": _chercher, "inscrire": inscrire, "liste": _liste}[choix])


def _chercher() -> None:
    dossier(commun.choisir_lecteur()["id"])


def _liste() -> None:
    lecteurs = usagers_service.chercher("", limite=200)
    ui.tableau(["Carte", "Nom", "Catégorie", "Compte", "Adhésion jusqu'au"],
               [[u["numero_carte"], ui.nom_lecteur(u), u["categorie_usager"], u["statut"],
                 ui.date_fr(u["expiration_adhesion"])] for u in lecteurs],
               titre=f"{len(lecteurs)} lecteur(s)", vide="Aucun lecteur inscrit pour l'instant.")
    if lecteurs:
        dossier(ui.choisir("Ouvrir un dossier :", [(f"{ui.nom_lecteur(u)} — {u['numero_carte']}", u["id"])
                                                    for u in lecteurs]))


def inscrire(nom_propose: str = ""):
    """Formulaire d'inscription. Renvoie le lecteur créé (ligne de base)."""
    ui.en_tete("Nouveau lecteur")
    nom = ui.demander("Nom", nom_propose, obligatoire=True)
    prenom = ui.demander("Prénom (facultatif)")
    email = ui.demander("Courriel (facultatif)", valider=lambda v: True if "@" in v else "Adresse invalide.")
    categorie = ui.choisir("Catégorie :", list(CATEGORIES), retour=None)
    fiche = usagers_service.inscription(nom, prenom or None, email or None, categorie, acteur=ui.ACTEUR)
    ui.carte("Lecteur inscrit", [
        f"[b]{escape(ui.nom_lecteur(fiche))}[/b]",
        f"Carte : [b #9ece6a]{fiche['numero_carte']}[/]  (tapez simplement « {int(fiche['numero_carte'][3:])} » pour la retrouver)",
        f"Adhésion jusqu'au {ui.date_fr(fiche['expiration_adhesion'])}",
    ], "#9ece6a")
    return usagers_service.chercher(fiche["numero_carte"])[0]


# ---------------------------------------------------------------- dossier


def afficher_dossier(d: dict) -> None:
    u = d["usager"]
    etat = "[ko]Prêts bloqués : " + escape(d["motif_blocage"]) + "[/]" if d["bloque"] else "[ok]Compte en règle : prêts autorisés[/]"
    ui.carte(f"{ui.nom_lecteur(u)} — {u['numero_carte']}", [
        f"{u['categorie_usager']} · {escape(u['email'] or 'pas de courriel')} · adhésion jusqu'au {ui.date_fr(u['expiration_adhesion'])}"
        + ("" if u["statut"] == "actif" else f" · compte {u['statut']}"),
        etat,
    ], "#e0af68" if d["bloque"] else "#7aa2f7")
    aujourdhui = db.aujourd_hui().isoformat()
    ui.tableau(["Référence", "Document", "À rendre le", ""],
               [[p["reference"], p["titre"][:44], ui.date_fr(p["date_retour_prevue"]),
                 Text("en retard", style="ko") if p["date_retour_prevue"] < aujourdhui else ("prolongé" if p["prolonge"] else "")]
                for p in d["prets_en_cours"]],
               titre=f"Emprunts en cours ({len(d['prets_en_cours'])})", vide="Aucun emprunt en cours.")
    if d["reservations"]:
        ui.tableau(["Document", "Situation"],
                   [[r["titre"][:50], f"mis de côté jusqu'au {ui.date_fr(r['date_expiration'])}" if r["statut"] == "prete"
                     else "en attente d'un retour"] for r in d["reservations"]], titre="Réservations")
    if d["amendes_impayees"]:
        ui.tableau(["Motif", "Montant", "Date"],
                   [[a["motif"], f"{a['montant']:.2f} €", ui.date_fr(a["date_creation"])] for a in d["amendes_impayees"]],
                   titre=f"Sommes dues : {d['total_amendes']:.2f} €")


def dossier(usager_id: int) -> None:
    while True:
        d = usagers_service.fiche(usager_id)
        afficher_dossier(d)
        actions = [("Prêter un document", "preter")]
        if d["prets_en_cours"]:
            actions += [("Enregistrer un retour", "retour"), ("Prolonger un prêt", "prolonger"),
                        ("Signaler un document perdu ou abîmé", "sanction")]
        if d["reservations"]:
            actions.append(("Annuler une réservation", "annuler"))
        if d["amendes_impayees"]:
            actions.append(("Enregistrer le règlement d'une amende", "amende"))
        actions += [("Renouveler l'adhésion", "renouveler"), ("Changer le statut du compte", "statut"),
                    ("Historique des prêts", "historique")]
        try:
            choix = ui.choisir("Que faire ?", actions)
        except ui.Retour:
            return
        ui.tenter({"preter": _preter, "retour": _retour, "prolonger": _prolonger, "sanction": _sanction,
                   "annuler": _annuler, "amende": _amende, "renouveler": _renouveler,
                   "statut": _statut, "historique": _historique}[choix], d)


def _choisir_pret(d: dict, texte: str):
    return ui.choisir(texte, [(f"{p['reference']}  {p['titre'][:44]}  (retour le {ui.date_fr(p['date_retour_prevue'])})", p)
                              for p in d["prets_en_cours"]])


def _preter(d: dict) -> None:
    doc = commun.choisir_document()
    if doc is not None:
        traiter(doc, lecteur=d["usager"])


def _retour(d: dict) -> None:
    p = _choisir_pret(d, "Quel document est rendu ?")
    ui.afficher_retour(circulation.retourner(p["reference"], acteur=ui.ACTEUR))


def _prolonger(d: dict) -> None:
    p = _choisir_pret(d, "Quel prêt prolonger ?")
    r = circulation.prolonger(p["reference"], acteur=ui.ACTEUR)
    ui.succes(f"Prêt prolongé : à rendre avant le {ui.date_fr(str(r['nouvelle_echeance']))}.")


def _sanction(d: dict) -> None:
    p = _choisir_pret(d, "Quel document ?")
    nature = ui.choisir("Que s'est-il passé ?", [("Perdu", "perte"), ("Abîmé", "degradation")])
    if not ui.confirmer(f"Déclarer « {p['titre']} » {'perdu' if nature == 'perte' else 'abîmé'} ? Des frais seront facturés.", False):
        return
    action = circulation.declarer_perte if nature == "perte" else circulation.declarer_degradation
    r = action(p["reference"], acteur=ui.ACTEUR)
    ui.succes(f"Enregistré : {r['frais']:.2f} € de frais. La carte reste bloquée jusqu'au règlement.")


def _annuler(d: dict) -> None:
    r = ui.choisir("Quelle réservation annuler ?", [(x["titre"][:60], x) for x in d["reservations"]])
    ui.succes(reservations_service.annuler(r["id"], acteur=ui.ACTEUR))


def _amende(d: dict) -> None:
    a = ui.choisir("Quelle amende a été réglée ?", [(f"{x['montant']:.2f} €  {x['motif']}", x) for x in d["amendes_impayees"]])
    if ui.confirmer(f"Confirmer l'encaissement de {a['montant']:.2f} € ?"):
        usagers_service.regler_amende(d["usager"]["id"], a["id"], acteur=ui.ACTEUR)
        ui.succes("Règlement enregistré.")


def _renouveler(d: dict) -> None:
    usagers_service.renouveler(d["usager"]["id"], acteur=ui.ACTEUR)
    ui.succes("Adhésion renouvelée.")


def _statut(d: dict) -> None:
    nouveau = ui.choisir("Nouveau statut :", [("Actif", "actif"), ("Suspendu", "suspendu"), ("Radié", "radie")],
                         defaut=d["usager"]["statut"])
    usagers_service.changer_statut_compte(d["usager"]["id"], nouveau, acteur=ui.ACTEUR)
    ui.succes("Statut mis à jour.")


def _historique(d: dict) -> None:
    ui.tableau(["Document", "Prêté le", "Rendu le"],
               [[p["titre"][:50], ui.date_fr(p["date_pret"]), ui.date_fr(p["date_retour_reelle"]) if p["date_retour_reelle"] else "en cours"]
                for p in d["historique"][:30]], titre="Historique (30 derniers)", vide="Aucun historique.")
    ui.pause()
