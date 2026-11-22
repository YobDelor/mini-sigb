"""Accès aux amendes (option nord-américaine) et aux notifications."""

import sqlite3

from sigb.models import db

MOTIF_RETARD = "retard"
MOTIF_PERTE = "perte"
MOTIF_DEGRADATION = "degradation"


def creer(
    conn: sqlite3.Connection,
    usager_id: int,
    motif: str,
    montant: float,
    pret_id: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO amende (usager_id, pret_id, motif, montant, payee, date_creation) "
        "VALUES (?,?,?,?,0,?)",
        (usager_id, pret_id, motif, montant, db.maintenant()),
    )
    return cur.lastrowid


def impayees_dusager(conn: sqlite3.Connection, usager_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM amende WHERE usager_id = ? AND payee = 0 ORDER BY id",
        (usager_id,),
    ).fetchall()


def total_impayees(conn: sqlite3.Connection, usager_id: int) -> float:
    return round(
        conn.execute(
            "SELECT COALESCE(SUM(montant), 0) FROM amende WHERE usager_id = ? AND payee = 0",
            (usager_id,),
        ).fetchone()[0],
        2,
    )


def regler(conn: sqlite3.Connection, amende_id: int) -> None:
    conn.execute(
        "UPDATE amende SET payee = 1, date_reglement = ? WHERE id = ?",
        (db.maintenant(), amende_id),
    )


# ---- Notifications (liste interne du compte lecteur) ----


def notifier(
    conn: sqlite3.Connection, usager_id: int, type_notif: str, message: str
) -> None:
    conn.execute(
        "INSERT INTO notification (usager_id, type, message, cree_le, lue) "
        "VALUES (?,?,?,?,0)",
        (usager_id, type_notif, message, db.maintenant()),
    )


def pour_usager(conn: sqlite3.Connection, usager_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM notification WHERE usager_id = ? ORDER BY id DESC LIMIT 50",
        (usager_id,),
    ).fetchall()


def marquer_toutes_lues(conn: sqlite3.Connection, usager_id: int) -> None:
    conn.execute("UPDATE notification SET lue = 1 WHERE usager_id = ?", (usager_id,))
