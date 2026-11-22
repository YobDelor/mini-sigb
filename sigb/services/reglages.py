"""Service réglages : règles de prêt (catégorie × type) et paramètres.

C'est la pièce de configuration centrale (règle n°3) : toute valeur est
validée ici, jamais dans l'interface.
"""

from sigb.erreurs import ErreurMetier
from sigb.models import db, regles

# (clé, libellé, minimum) pour les paramètres numériques
PARAMETRES_NOMBRES = {
    regles.P_MONTANT_AMENDE: ("Montant de l'amende par jour", 0.0),
    regles.P_DUREE_MISE_DE_COTE: ("Délai de récupération d'une réservation", 1),
    regles.P_DUREE_ADHESION: ("Durée d'adhésion", 30),
    regles.P_FRAIS_PERTE: ("Frais de perte", 0.0),
    regles.P_FRAIS_DEGRADATION: ("Frais de dégradation", 0.0),
}


def charger() -> dict:
    """Tout ce qu'il faut pour afficher la page des réglages."""
    conn = db.get_conn()
    try:
        return {
            "categories": regles.categories_usager(conn),
            "types": regles.types_documents(conn),
            "regles": {(r["categorie_usager"], r["type_document"]): r for r in regles.matrice(conn)},
            "params": {p["cle"]: p["valeur"] for p in regles.parametres_tous(conn)},
        }
    finally:
        conn.close()


def enregistrer_regles(valeurs: dict, acteur: str = "cli") -> None:
    """valeurs : {(categorie, type): (autorise, duree_jours, quota)}."""
    with db.transaction() as conn:
        for (categorie, typ), (autorise, duree, quota) in valeurs.items():
            if autorise and (duree <= 0 or quota <= 0):
                raise ErreurMetier(
                    f"Règle {categorie} / {typ} : la durée et le quota doivent être supérieurs à 0 "
                    "(ou décochez « autorisé »)."
                )
            regles.definir_regle(conn, categorie, typ, autorise, max(duree, 0), max(quota, 0))
        db.journaliser(conn, "administration", "Règles de prêt mises à jour", acteur)


def enregistrer_parametres(amendes_activees: bool, nombres: dict, acteur: str = "cli") -> None:
    """nombres : {clé: texte saisi}. Rien n'est enregistré si une valeur est invalide."""
    a_ecrire = {}
    for cle, texte in nombres.items():
        if cle not in PARAMETRES_NOMBRES:
            continue
        libelle, minimum = PARAMETRES_NOMBRES[cle]
        try:
            valeur = float(str(texte).replace(",", "."))
        except ValueError:
            raise ErreurMetier(f"{libelle} : « {texte} » n'est pas un nombre.")
        if valeur < minimum:
            raise ErreurMetier(f"{libelle} : la valeur doit être au moins {minimum}.")
        entier = isinstance(minimum, int)
        a_ecrire[cle] = str(int(valeur)) if entier else f"{valeur:.2f}"
    with db.transaction() as conn:
        regles.definir_parametre(conn, regles.P_AMENDES_ACTIVEES, "1" if amendes_activees else "0")
        for cle, valeur in a_ecrire.items():
            regles.definir_parametre(conn, cle, valeur)
        db.journaliser(conn, "administration", "Paramètres mis à jour", acteur)
