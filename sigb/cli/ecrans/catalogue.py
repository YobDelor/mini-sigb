"""Catalogue : chercher, consulter une fiche, et les actions sur un titre."""

from rich.markup import escape

from sigb.cli import ui
from sigb.cli.ecrans import commun, lecture
from sigb.cli.ecrans.circulation import traiter
from sigb.models import db
from sigb.services import catalogue, reservations_service


def chercher(q: str | None = None) -> None:
    ui.en_tete("Catalogue")
    if q is None:
        q = ui.demander("Recherche — titre, auteur, sujet ou ISBN (Entrée = tout afficher)")
    resultats = catalogue.rechercher(q or None)
    if not resultats:
        ui.attention("Rien dans votre catalogue.")
        if q and ui.confirmer(f"Chercher « {q} » sur internet pour l'ajouter ?"):
            from sigb.cli.ecrans import ajout

            ajout.chercher_en_ligne(q)
        return
    ui.tableau(
        ["N°", "Titre", "Auteur(s)", "Année", "Disponibilité"],
        [[str(o["id"]), o["titre"][:44], (o["auteurs"] or "-")[:26], str(o["annee"] or "-"),
          ui.disponibilite(o["nb_dispo"], o["nb_total"], bool(o["lien_numerique"]))] for o in resultats],
        titre=f"{len(resultats)} résultat(s)" + (" (60 premiers, précisez votre recherche)" if len(resultats) >= 60 else ""),
    )
    while True:
        try:
            oeuvre_id = ui.choisir("Ouvrir une fiche :", [
                (f"{o['titre'][:50]} — {(o['auteurs'] or 'auteur inconnu')[:24]}", o["id"]) for o in resultats])
        except ui.Retour:
            return
        fiche(oeuvre_id)


def afficher_fiche(f: dict) -> None:
    o = f["oeuvre"]
    lignes = [f"[b]{escape(o['titre'])}[/b]", f"[doux]{escape(', '.join(f['auteurs']) or 'Auteur inconnu')}[/doux]", ""]
    detail = [d for d in (o["type_document"], o["editeur"], str(o["annee"]) if o["annee"] else None,
                          f"ISBN {o['isbn']}" if o["isbn"] else None, o["langue"]) if d]
    lignes.append(escape(" · ".join(detail)))
    if f["categories"]:
        lignes.append("Sujets : " + escape(", ".join(f["categories"])))
    if o["resume"]:
        lignes += ["", escape(o["resume"][:400]) + ("…" if len(o["resume"]) > 400 else "")]
    if o["lien_numerique"]:
        lignes += ["", "[#7dcfff]● Se lit en ligne : choisissez « Lire »[/]"]
    ui.carte(f"Fiche n°{o['id']}", lignes)
    ui.tableau(["Référence", "Cote", "État", "Disponibilité"],
               [[e["reference"], e["cote"], e["etat"], ui.etat(e["statut"])] for e in f["exemplaires"]],
               vide="Aucun exemplaire papier (texte numérique ou titre sans exemplaire).")
    if f["file_attente"]:
        ui.info(f"{len(f['file_attente'])} réservation(s) en attente sur ce titre.")


def fiche(oeuvre_id: int) -> None:
    while True:
        f = catalogue.fiche_oeuvre(oeuvre_id)
        if f is None:
            ui.erreur("Œuvre introuvable.")
            return
        afficher_fiche(f)
        exemplaires = f["exemplaires"]
        prenables = [e for e in exemplaires if e["statut"] in (db.STATUT_DISPONIBLE, db.STATUT_MIS_DE_COTE)]
        retirables = [e for e in exemplaires if e["statut"] not in (db.STATUT_EMPRUNTE, db.STATUT_MIS_DE_COTE, db.STATUT_RETIRE)]
        actions = []
        if f["oeuvre"]["lien_numerique"]:
            actions.append(("Lire ce livre dans le navigateur", "lire"))
        if prenables:
            actions.append(("Prêter à un lecteur", "preter"))
        if exemplaires and not [e for e in exemplaires if e["statut"] == db.STATUT_DISPONIBLE]:
            actions.append(("Réserver pour un lecteur", "reserver"))
        actions.append(("Ajouter des exemplaires", "ajouter"))
        if retirables:
            actions.append(("Retirer un exemplaire du fonds", "retirer"))
        try:
            choix = ui.choisir("Que faire ?", actions)
        except ui.Retour:
            return
        ui.tenter({"lire": _lire, "preter": _preter, "reserver": _reserver,
                   "ajouter": _ajouter, "retirer": _retirer}[choix], f)


def _lire(f: dict) -> None:
    lecture.lire(f["oeuvre"]["id"])


def _choisir_exemplaire(f: dict, parmi: list):
    if len(parmi) == 1:
        return parmi[0]
    return ui.choisir("Quel exemplaire ?", [(f"{e['reference']}  cote {e['cote']}  —  "
                                             f"{db.LIBELLES_STATUT[e['statut']]}", e) for e in parmi])


def _preter(f: dict) -> None:
    prenables = [e for e in f["exemplaires"] if e["statut"] in (db.STATUT_DISPONIBLE, db.STATUT_MIS_DE_COTE)]
    e = _choisir_exemplaire(f, prenables)
    doc = {"reference": e["reference"], "statut": e["statut"], "titre": f["oeuvre"]["titre"],
           "emprunteur": None, "retour_prevu": None}
    traiter(doc)


def _reserver(f: dict) -> None:
    lecteur = commun.choisir_lecteur()
    r = reservations_service.reserver(f["oeuvre"]["id"], lecteur["numero_carte"], acteur=ui.ACTEUR)
    ui.succes(f"Réservation enregistrée pour {ui.nom_lecteur(lecteur)} : n°{r['rang_file']} dans la file.")


def _ajouter(f: dict) -> None:
    exemplaires = f["exemplaires"]
    nombre = ui.entier("Combien d'exemplaires ajouter ?", 1, 1, 50)
    cote = ui.demander("Cote (emplacement en rayon)", exemplaires[-1]["cote"] if exemplaires else "", obligatoire=True)
    origine = ui.choisir("Origine :", [("Achat", "achat"), ("Don", "don")], retour=None)
    refs = catalogue.ajouter_exemplaires(f["oeuvre"]["id"], nombre, cote, mode_acquisition=origine, acteur=ui.ACTEUR)
    ui.succes("Ajouté : " + ", ".join(refs))


def _retirer(f: dict) -> None:
    retirables = [e for e in f["exemplaires"]
                  if e["statut"] not in (db.STATUT_EMPRUNTE, db.STATUT_MIS_DE_COTE, db.STATUT_RETIRE)]
    e = _choisir_exemplaire(f, retirables)
    motif = ui.demander("Motif du retrait (usé, obsolète, doublon…)", obligatoire=True)
    if ui.confirmer(f"Retirer {e['reference']} du fonds ? Cette action est définitive.", False):
        catalogue.desherber(e["reference"], motif, acteur=ui.ACTEUR)
        ui.succes(f"{e['reference']} retiré du fonds (motif conservé au journal).")
