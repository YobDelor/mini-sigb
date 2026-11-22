"""Accès aux réservations (file d'attente par œuvre)."""

import sqlite3

from sigb.models import db

EN_ATTENTE = "en_attente"
PRETE = "prete"            # mise de côté faite, en attente de récupération
SATISFAITE = "satisfait"   # récupérée (empruntée par l'usager)
EXPIREE = "expiree"        # délai dépassé, déclassée
ANNULEE = "annulee"


def creer(conn: sqlite3.Connection, oeuvre_id: int, usager_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO reservation (oeuvre_id, usager_id, date_demande, statut) "
        "VALUES (?,?,?,?)",
        (oeuvre_id, usager_id, db.maintenant(), EN_ATTENTE),
    )
    return cur.lastrowid


def par_id(conn: sqlite3.Connection, reservation_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM reservation WHERE id = ?", (reservation_id,)
    ).fetchone()


def premiere_en_attente(conn: sqlite3.Connection, oeuvre_id: int) -> sqlite3.Row | None:
    """Premier de la file : la réservation en attente la plus ancienne."""
    return conn.execute(
        "SELECT * FROM reservation WHERE oeuvre_id = ? AND statut = ? "
        "ORDER BY date_demande, id LIMIT 1",
        (oeuvre_id, EN_ATTENTE),
    ).fetchone()


def premiere_prete(conn: sqlite3.Connection, oeuvre_id: int) -> sqlite3.Row | None:
    """La réservation actuellement servie par une mise de côté."""
    return conn.execute(
        "SELECT * FROM reservation WHERE oeuvre_id = ? AND statut = ? "
        "ORDER BY date_demande, id LIMIT 1",
        (oeuvre_id, PRETE),
    ).fetchone()


def prete_de_usager(conn: sqlite3.Connection, oeuvre_id: int, usager_id: int) -> sqlite3.Row | None:
    """La réservation mise de côté pour CET usager sur cette œuvre.

    La réservation porte sur l'œuvre (règle n°1) : n'importe quel exemplaire
    mis de côté peut servir celui à qui une réservation est « prête »."""
    return conn.execute(
        "SELECT * FROM reservation WHERE oeuvre_id = ? AND usager_id = ? AND statut = ? "
        "ORDER BY date_demande, id LIMIT 1",
        (oeuvre_id, usager_id, PRETE),
    ).fetchone()


def file_attente(conn: sqlite3.Connection, oeuvre_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r.*, u.nom, u.prenom, u.numero_carte
           FROM reservation r JOIN usager u ON u.id = r.usager_id
           WHERE r.oeuvre_id = ? AND r.statut = ?
           ORDER BY r.date_demande, r.id""",
        (oeuvre_id, EN_ATTENTE),
    ).fetchall()


def reservations_actives_dusager(
    conn: sqlite3.Connection, usager_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r.*, o.titre, o.type_document
           FROM reservation r JOIN oeuvre o ON o.id = r.oeuvre_id
           WHERE r.usager_id = ? AND r.statut IN (?, ?)
           ORDER BY r.date_demande""",
        (usager_id, EN_ATTENTE, PRETE),
    ).fetchall()


def pretes_expirees(conn: sqlite3.Connection, aujourdhui) -> list[sqlite3.Row]:
    """Réservations mises de côté dont le délai de récupération est dépassé."""
    return conn.execute(
        "SELECT * FROM reservation WHERE statut = ? AND date_expiration < ?",
        (PRETE, aujourdhui.isoformat()),
    ).fetchall()


def a_reservation_active(conn: sqlite3.Connection, oeuvre_id: int, usager_id: int) -> bool:
    return conn.execute(
        "SELECT COUNT(*) FROM reservation WHERE oeuvre_id = ? AND usager_id = ? "
        "AND statut IN (?, ?)",
        (oeuvre_id, usager_id, EN_ATTENTE, PRETE),
    ).fetchone()[0] > 0


def changer_statut(conn: sqlite3.Connection, reservation_id: int, statut: str) -> None:
    conn.execute(
        "UPDATE reservation SET statut = ? WHERE id = ?", (statut, reservation_id)
    )


def servir(conn: sqlite3.Connection, reservation_id: int, date_expiration) -> None:
    """Mise de côté : l'exemplaire attend l'usager pendant le délai fixé."""
    conn.execute(
        "UPDATE reservation SET statut = ?, date_expiration = ? WHERE id = ?",
        (PRETE, date_expiration.isoformat(), reservation_id),
    )
