"""Réglages : règles de prêt, paramètres, journal, statistiques."""

from sigb.cli import ui
from sigb.models import regles
from sigb.services import pilotage, reglages


def menu() -> None:
    while True:
        try:
            choix = ui.choisir("Réglages et suivi", [
                ("Règles de prêt (durée et nombre de documents)", "regles"),
                ("Paramètres (amendes, délais, frais)", "parametres"),
                ("Journal des opérations", "journal"),
                ("Chiffres du fonds", "stats"),
            ])
        except ui.Retour:
            return
        ui.tenter({"regles": _regles, "parametres": _parametres, "journal": _journal, "stats": _stats}[choix])


def _libelle_regle(r) -> str:
    return f"{r['duree_jours']} j · {r['quota']} max" if r and r["autorise"] else "interdit"


def _regles() -> None:
    while True:
        d = reglages.charger()
        ui.tableau([""] + [t["libelle"] for t in d["types"]],
                   [[c["libelle"]] + [_libelle_regle(d["regles"].get((c["code"], t["code"]))) for t in d["types"]]
                    for c in d["categories"]], titre="Règles de prêt (durée · nombre de documents à la fois)")
        try:
            cat = ui.choisir("Modifier la règle de :", [(c["libelle"], c) for c in d["categories"]])
            typ = ui.choisir(f"{cat['libelle']} — pour quel type de document ?", [(t["libelle"], t) for t in d["types"]])
        except ui.Retour:
            return
        actuelle = d["regles"].get((cat["code"], typ["code"]))
        ui.tenter(_modifier_regle, cat, typ, actuelle)


def _modifier_regle(cat, typ, actuelle) -> None:
    autorise = ui.confirmer(f"Autoriser le prêt de « {typ['libelle']} » aux « {cat['libelle']} » ?",
                            bool(actuelle and actuelle["autorise"]))
    duree = quota = 0
    if autorise:
        duree = ui.entier("Durée du prêt (jours)", actuelle["duree_jours"] if actuelle else 21, 1, 365)
        quota = ui.entier("Nombre de documents à la fois", actuelle["quota"] if actuelle else 5, 1, 100)
    reglages.enregistrer_regles({(cat["code"], typ["code"]): (autorise, duree, quota)}, acteur=ui.ACTEUR)
    ui.succes("Règle enregistrée : elle s'applique dès le prochain prêt.")


def _parametres() -> None:
    while True:
        params = reglages.charger()["params"]
        lignes = [[libelle, params.get(cle, "-")] for cle, (libelle, _) in reglages.PARAMETRES_NOMBRES.items()]
        lignes.insert(0, ["Facturer une amende de retard", "oui" if params.get(regles.P_AMENDES_ACTIVEES) == "1" else "non (carte bloquée seulement)"])
        ui.tableau(["Paramètre", "Valeur"], lignes, titre="Paramètres")
        try:
            cle = ui.choisir("Modifier :", [("Facturer une amende de retard (oui/non)", regles.P_AMENDES_ACTIVEES)]
                             + [(libelle, c) for c, (libelle, _) in reglages.PARAMETRES_NOMBRES.items()])
        except ui.Retour:
            return
        ui.tenter(_modifier_parametre, cle, params)


def _modifier_parametre(cle: str, params: dict) -> None:
    amendes = params.get(regles.P_AMENDES_ACTIVEES) == "1"
    nombres = {c: params.get(c, "") for c in reglages.PARAMETRES_NOMBRES}
    if cle == regles.P_AMENDES_ACTIVEES:
        amendes = ui.confirmer("Facturer une amende pour chaque jour de retard ?", amendes)
    else:
        libelle, _ = reglages.PARAMETRES_NOMBRES[cle]
        nombres[cle] = ui.demander(libelle, nombres[cle], obligatoire=True)
    reglages.enregistrer_parametres(amendes, nombres, acteur=ui.ACTEUR)
    ui.succes("Paramètre enregistré.")


def _journal() -> None:
    lignes = pilotage.journal(40)
    ui.tableau(["Quand", "Qui", "Opération", "Détail"],
               [[str(j["horodatage"])[:16].replace("T", " "), j["acteur"], j["action"], j["details"][:80]] for j in lignes],
               titre="Journal (40 dernières opérations)", vide="Le journal est vide.")
    ui.pause()


def _stats() -> None:
    s = pilotage.tableau_de_bord()
    ui.tableau(["Indicateur", "Valeur"], [
        ["Œuvres au catalogue", str(s["oeuvres"])], ["Lecteurs actifs", str(s["usagers_actifs"])],
        ["Prêts en cours", str(s["prets_en_cours"])], ["Retards", str(s["retards"])],
        ["Réservations en attente", str(s["reservations_attente"])],
        *[[f"Exemplaires — {k}", str(v)] for k, v in s["exemplaires_statut"].items()],
    ], titre="Chiffres du fonds")
    ui.pause()
