"""À faire aujourd'hui : retards, réservations à remettre, dernières opérations."""

from datetime import date

from sigb.cli import ui
from sigb.cli.ecrans import lecteurs
from sigb.models import db
from sigb.services import circulation, pilotage, reservations_service


def a_faire() -> int:
    """Nombre de choses à traiter (affiché dans le menu principal)."""
    d = pilotage.poste_guichet()
    return len(d["retards"]) + len(d["reservations_pretes"])


def afficher() -> None:
    ui.en_tete("À faire aujourd'hui")
    for liberee in reservations_service.traiter_expirations():
        ui.info(f"Réservation non récupérée, libérée : {liberee}")
    d = pilotage.poste_guichet()
    aujourdhui = db.aujourd_hui()
    retards = d["retards"]
    ui.tableau(["Document", "Lecteur", "À rendre le", "Retard"],
               [[r["titre"][:40], f"{r['prenom'] or ''} {r['nom']}".strip(), ui.date_fr(r["date_retour_prevue"]),
                 f"{(aujourdhui - date.fromisoformat(r['date_retour_prevue'][:10])).days} j"] for r in retards],
               titre=f"Retards ({len(retards)})", vide="Aucun retard : tout le monde est à l'heure.")
    ui.tableau(["Document", "Pour", "À récupérer avant le"],
               [[r["titre"][:40], f"{r['prenom'] or ''} {r['nom']}".strip(), ui.date_fr(r["date_expiration"])]
                for r in d["reservations_pretes"]],
               titre=f"Documents mis de côté ({len(d['reservations_pretes'])})",
               vide="Aucune réservation en attente de retrait.")
    ui.tableau(["Quand", "Opération", "Détail"],
               [[str(j["horodatage"])[:16].replace("T", " "), j["action"], j["details"][:70]] for j in d["dernieres"]],
               titre="Dernières opérations", vide="Rien pour l'instant.")
    if not retards:
        ui.pause()
        return
    while True:
        try:
            choix = ui.choisir("Que faire ?", [("Enregistrer une relance (message au lecteur)", "relance"),
                                               ("Ouvrir le dossier d'un lecteur en retard", "dossier")])
        except ui.Retour:
            return
        r = ui.choisir("Quel retard ?", [(f"{x['titre'][:36]} — {x['prenom'] or ''} {x['nom']}", x) for x in retards])
        if choix == "relance":
            ui.tenter(lambda: ui.succes(circulation.envoyer_relance(r["pret_id"], acteur=ui.ACTEUR)))
        else:
            lecteurs.dossier(r["usager_id"])
