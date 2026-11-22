"""Accès aux prêts (transactions de circulation)."""

import sqlite3

from sigb.models import db


def creer(
    conn: sqlite3.Connection,
    exemplaire_id: int,
    usager_id: int,
    date_retour_prevue,
    agent: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO pret (exemplaire_id, usager_id, date_pret, date_retour_prevue, agent) "
        "VALUES (?,?,?,?,?)",
        (
            exemplaire_id,
            usager_id,
            db.maintenant(),
            date_retour_prevue.isoformat(),
            agent,
        ),
    )
    return cur.lastrowid


def par_id(conn: sqlite3.Connection, pret_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM pret WHERE id = ?", (pret_id,)).fetchone()


def pret_ouvert_dun_exemplaire(
    conn: sqlite3.Connection, exemplaire_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM pret WHERE exemplaire_id = ? AND date_retour_reelle IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (exemplaire_id,),
    ).fetchone()


def cloturer(conn: sqlite3.Connection, pret_id: int, date_retour) -> None:
    conn.execute(
        "UPDATE pret SET date_retour_reelle = ? WHERE id = ?",
        (date_retour.isoformat(), pret_id),
    )


def marquer_prolonge(conn: sqlite3.Connection, pret_id: int, nouvelle_echeance) -> None:
    conn.execute(
        "UPDATE pret SET prolonge = 1, date_retour_prevue = ? WHERE id = ?",
        (nouvelle_echeance.isoformat(), pret_id),
    )


def nb_prets_en_cours(
    conn: sqlite3.Connection, usager_id: int, type_document: str | None = None
) -> int:
    """Compte les prêts actifs, éventuellement filtrés par type de document."""
    sql = (
        "SELECT COUNT(*) FROM pret p "
        "JOIN exemplaire e ON e.id = p.exemplaire_id "
        "JOIN oeuvre o ON o.id = e.oeuvre_id "
        "WHERE p.usager_id = ? AND p.date_retour_reelle IS NULL"
    )
    params = [usager_id]
    if type_document:
        sql += " AND o.type_document = ?"
        params.append(type_document)
    return conn.execute(sql, params).fetchone()[0]


def prets_en_cours_dusager(conn: sqlite3.Connection, usager_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT p.*, e.reference, e.cote, e.oeuvre_id, o.titre, o.type_document
           FROM pret p
           JOIN exemplaire e ON e.id = p.exemplaire_id
           JOIN oeuvre o ON o.id = e.oeuvre_id
           WHERE p.usager_id = ? AND p.date_retour_reelle IS NULL
           ORDER BY p.date_retour_prevue""",
        (usager_id,),
    ).fetchall()


def historique_dusager(conn: sqlite3.Connection, usager_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT p.*, e.reference, o.titre
           FROM pret p
           JOIN exemplaire e ON e.id = p.exemplaire_id
           JOIN oeuvre o ON o.id = e.oeuvre_id
           WHERE p.usager_id = ?
           ORDER BY p.id DESC LIMIT 100""",
        (usager_id,),
    ).fetchall()


def retards(conn: sqlite3.Connection, aujourdhui=None) -> list[sqlite3.Row]:
    """Prêts dont l'échéance est dépassée et non rendus."""
    aujourdhui = aujourdhui or db.aujourd_hui()
    return conn.execute(
        """SELECT p.id AS pret_id, p.*, e.reference, e.id AS exemplaire_id,
                  o.titre, o.type_document,
                  u.id AS usager_id, u.nom, u.prenom, u.numero_carte, u.categorie_usager
           FROM pret p
           JOIN exemplaire e ON e.id = p.exemplaire_id
           JOIN oeuvre o ON o.id = e.oeuvre_id
           JOIN usager u ON u.id = p.usager_id
           WHERE p.date_retour_reelle IS NULL AND p.date_retour_prevue < ?
           ORDER BY p.date_retour_prevue""",
        (aujourdhui.isoformat(),),
    ).fetchall()


def a_un_retard(conn: sqlite3.Connection, usager_id: int) -> bool:
    return conn.execute(
        """SELECT COUNT(*) FROM pret
           WHERE usager_id = ? AND date_retour_reelle IS NULL
             AND date_retour_prevue < ?""",
        (usager_id, db.aujourd_hui().isoformat()),
    ).fetchone()[0] > 0
