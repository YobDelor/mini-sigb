"""Initialisation de la base : schéma et référentiel (types de documents,
catégories de lecteurs, règles de prêt par défaut, paramètres).

Aucune donnée fictive : le catalogue se remplit depuis les sources réelles
(OpenLibrary, BnF, Project Gutenberg) via sigb.services.import_service.
"""

from sigb.models import db, regles


def initialiser_reference() -> None:
    """Crée le schéma et le référentiel. Peut être rappelée sans créer de doublon."""
    db.init_db()
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")

        for code, libelle in (
            ("livre", "Livre (monographie)"),
            ("bd", "Bande dessinée"),
            ("dvd", "DVD"),
            ("periode", "Périodique"),
            ("numerique", "Ressource numérique"),
        ):
            conn.execute(
                "INSERT OR IGNORE INTO type_document (code, libelle) VALUES (?,?)",
                (code, libelle),
            )

        for code, libelle in (
            ("jeune", "Jeune (moins de 14 ans)"),
            ("adulte", "Adulte"),
            ("collectivite", "Collectivité"),
        ):
            conn.execute(
                "INSERT OR IGNORE INTO categorie_usager (code, libelle) VALUES (?,?)",
                (code, libelle),
            )

        # Matrice par défaut (médiathèque publique) — Tableau 5 du cahier des charges
        matrice_defaut = {
            # (catégorie, type) : (autorisé, durée jours, quota)
            ("jeune", "livre"): (1, 21, 5),
            ("jeune", "bd"): (1, 21, 5),
            ("jeune", "dvd"): (0, 0, 0),        # DVD refusés
            ("adulte", "livre"): (1, 21, 10),
            ("adulte", "bd"): (1, 21, 10),
            ("adulte", "dvd"): (1, 7, 2),       # 7 jours, 2 DVD maximum
            ("collectivite", "livre"): (1, 60, 30),
            ("collectivite", "bd"): (1, 60, 30),
            ("collectivite", "dvd"): (0, 0, 0),  # DVD refusés
        }
        for (cat, typ), (aut, duree, quota) in matrice_defaut.items():
            regles.definir_regle(conn, cat, typ, bool(aut), duree, quota)

        parametres_defaut = {
            regles.P_AMENDES_ACTIVEES: "0",        # blocage à la française par défaut
            regles.P_MONTANT_AMENDE: "0.25",
            regles.P_DUREE_MISE_DE_COTE: "7",      # délai de récupération d'une réservation
            regles.P_DUREE_ADHESION: "365",
            regles.P_FRAIS_PERTE: "15.00",
            regles.P_FRAIS_DEGRADATION: "10.00",
        }
        for cle, valeur in parametres_defaut.items():
            conn.execute(
                "INSERT OR IGNORE INTO parametre (cle, valeur) VALUES (?,?)",
                (cle, valeur),
            )

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    conn = db.get_conn()
    try:
        db.journaliser(conn, "administration", "Initialisation : schéma et référentiel chargés", "systeme")
    finally:
        conn.close()
