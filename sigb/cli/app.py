"""Menu principal : le point d'entrée interactif (`python main.py`).

Deux profils se partagent le terminal :
  - le bibliothécaire, qui gère tout (guichet, fonds, règles, retards) ;
  - le lecteur, qui dispose d'un espace limité à ses données (emprunts,
    réservations, lecture en ligne, profil).
"""

from rich.align import Align
from rich.panel import Panel

from sigb.cli import ui
from sigb.cli.ecrans import ajout, catalogue, circulation, espace_lecteur, lecteurs, lecture, reglages, taches
from sigb.initialisation import initialiser_reference
from sigb.models import db
from sigb.services import pilotage, reservations_service


def preparer() -> None:
    """Crée la base au premier lancement et libère les réservations expirées."""
    if not db.base_est_initialisee():
        initialiser_reference()
        ui.succes("Bibliothèque créée.")
    reservations_service.traiter_expirations()


def _pluriel(n: int, mot: str) -> str:
    return f"{n} {mot}{'s' if n > 1 else ''}"


def bandeau() -> int:
    """Affiche l'en-tête avec les chiffres du jour. Renvoie le nombre d'œuvres."""
    s = pilotage.tableau_de_bord()
    ui.console.clear()
    ui.console.print(Panel(Align.center(
        "[b #7aa2f7]B I B L I O T H È Q U E[/]\n[doux]catalogue · prêts · lecture[/]\n\n"
        f"{_pluriel(s['oeuvres'], 'œuvre')}   ·   {_pluriel(s['usagers_actifs'], 'lecteur')}   ·   "
        f"{_pluriel(s['prets_en_cours'], 'prêt')} en cours   ·   "
        + (f"[ko]{_pluriel(s['retards'], 'retard')}[/]" if s["retards"] else "[ok]aucun retard[/]")),
        border_style="#7aa2f7", padding=(1, 4)))
    return s["oeuvres"]


def accueil_catalogue_vide() -> None:
    ui.carte("Bienvenue !", [
        "Votre catalogue est vide.",
        "Je peux le remplir tout de suite avec de [b]vrais classiques libres[/b] d'Open Library (Internet Archive) :",
        "vous pourrez les lire dans votre navigateur dès maintenant.",
    ])
    try:
        if ui.confirmer("Remplir le catalogue maintenant ?"):
            ui.tenter(ajout.garnir)
            ui.pause()
    except ui.Retour:
        pass   # « plus tard » : on passe au menu, sans quitter


def boucle_bibliothecaire() -> None:
    """Le menu complet de l'agent : guichet, catalogue, lecteurs, fonds, réglages."""
    # L'écran de bienvenue du premier lancement passe AVANT le bandeau : celui-ci
    # n'est imprimé que par la boucle, jamais deux fois d'affilée (c'était le
    # doublon d'en-tête constaté au premier remplissage du catalogue).
    if pilotage.tableau_de_bord()["oeuvres"] == 0:
        accueil_catalogue_vide()
    while True:
        nb = bandeau()
        n_taches = taches.a_faire()
        try:
            choix = ui.choisir("Que souhaitez-vous faire ?", [
                ("Prêt et retour", circulation.guichet),
                ("Chercher un livre", catalogue.chercher),
                ("Lire un livre", lecture.lire),
                ("Lecteurs", lecteurs.menu),
                ("Ajouter des livres", ajout.menu),
                (f"À faire aujourd'hui ({n_taches})" if n_taches else "À faire aujourd'hui", taches.afficher),
                ("Réglages et suivi", reglages.menu),
            ], retour="← Changer de profil")
        except ui.Retour:
            return
        ui.tenter(choix)


def lancer() -> None:
    try:
        preparer()
        while True:
            try:
                profil = ui.choisir("Qui utilise la bibliothèque ?", [
                    ("Bibliothécaire — guichet et gestion", boucle_bibliothecaire),
                    ("Lecteur — mon espace personnel", espace_lecteur.ouvrir),
                ], defaut=boucle_bibliothecaire, retour="Quitter")
            except ui.Retour:
                break
            ui.tenter(profil)
    except ui.Retour:
        pass
    ui.console.print("\n[doux]À bientôt.[/]")
