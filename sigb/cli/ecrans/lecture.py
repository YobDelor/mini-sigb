"""Lecture : ouvre un livre numérique dans le navigateur, comme une liseuse."""

from sigb.cli import ui
from sigb.services import catalogue, lecture as service


def lire(oeuvre_id: int | None = None) -> None:
    if oeuvre_id is None:
        ui.en_tete("Lire un livre", "Les textes libres de votre catalogue, lisibles dans le navigateur.")
        q = ui.demander("Rechercher (titre ou auteur, Entrée = tous)")
        livres = catalogue.rechercher(q or None, lisible=True, limite=300)
        if not livres:
            ui.attention("Aucun livre à lire en ligne dans votre catalogue.")
            if ui.confirmer("Récupérer des classiques libres depuis Project Gutenberg ?"):
                from sigb.cli.ecrans import ajout

                ajout.garnir()
            return
        oeuvre_id = ui.choisir(f"{len(livres)} livre(s) à lire :", [
            (f"{o['titre'][:55]} — {(o['auteurs'] or 'auteur inconnu')[:28]}", o["id"]) for o in livres])
    with ui.attente("Préparation de la lecture…"):
        r = service.lire(oeuvre_id)
    if r["ouvert"]:
        ui.succes(f"« {r['titre']} » s'ouvre dans votre navigateur"
                  + (" (version enregistrée : lisible sans connexion)." if r["mode"] == "liseuse" else "."))
    else:
        ui.attention("Aucun navigateur n'a pu être lancé automatiquement. Ouvrez cette adresse vous-même :")
        ui.console.print(r["cible"], soft_wrap=True, highlight=False)
    if r["mode"] == "liseuse":
        ui.info("Dans la page : A- / A+ règlent la taille du texte, le bouton de droite change l'ambiance.")
