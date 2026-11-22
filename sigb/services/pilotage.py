"""Service de pilotage : ce que l'on affiche sur les tableaux de bord
(guichet et administration). Lecture seule."""

from sigb.models import db, exemplaires, prets


def tableau_de_bord() -> dict:
    """Chiffres clés de l'administration."""
    conn = db.get_conn()
    try:
        def n(sql: str) -> int:
            return conn.execute(sql).fetchone()[0]

        return {
            "oeuvres": n("SELECT COUNT(*) FROM oeuvre"),
            "usagers_actifs": n("SELECT COUNT(*) FROM usager WHERE statut = 'actif'"),
            "prets_en_cours": n("SELECT COUNT(*) FROM pret WHERE date_retour_reelle IS NULL"),
            "retards": len(prets.retards(conn)),
            "reservations_attente": n("SELECT COUNT(*) FROM reservation WHERE statut = 'en_attente'"),
            "exemplaires_statut": exemplaires.compter_par_statut(conn),
            "acquisitions": exemplaires.acquisitions_recentes(conn, limite=10),
        }
    finally:
        conn.close()


def poste_guichet() -> dict:
    """Ce qu'il y a à faire aujourd'hui au guichet."""
    conn = db.get_conn()
    try:
        return {
            "retards": prets.retards(conn),
            "reservations_pretes": conn.execute(
                """SELECT r.*, o.titre, u.nom, u.prenom, u.numero_carte, u.id AS usager_id
                   FROM reservation r
                   JOIN oeuvre o ON o.id = r.oeuvre_id
                   JOIN usager u ON u.id = r.usager_id
                   WHERE r.statut = 'prete' ORDER BY r.date_expiration"""
            ).fetchall(),
            "dernieres": conn.execute(
                """SELECT * FROM journal
                   WHERE action IN ('pret','retour','prolongation','reservation','sanction')
                   ORDER BY id DESC LIMIT 8"""
            ).fetchall(),
        }
    finally:
        conn.close()


def journal(limite: int = 200) -> list:
    conn = db.get_conn()
    try:
        return conn.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
    finally:
        conn.close()
