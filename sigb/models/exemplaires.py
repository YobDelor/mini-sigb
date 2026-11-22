"""Accès aux exemplaires (objets physiques) et aux acquisitions."""

import sqlite3

from sigb.models import db


def par_id(conn: sqlite3.Connection, exemplaire_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM exemplaire WHERE id = ?", (exemplaire_id,)
    ).fetchone()


def par_reference(conn: sqlite3.Connection, reference: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM exemplaire WHERE reference = ?", (reference,)
    ).fetchone()


def de_loeuvre(conn: sqlite3.Connection, oeuvre_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM exemplaire WHERE oeuvre_id = ? ORDER BY reference",
        (oeuvre_id,),
    ).fetchall()


def prochaine_reference(conn: sqlite3.Connection) -> str:
    """Référence unique (équivalent du code-barres) : EX-000001, EX-000002..."""
    ligne = conn.execute(
        "SELECT MAX(CAST(SUBSTR(reference, 4) AS INTEGER)) AS n FROM exemplaire"
    ).fetchone()
    n = (ligne["n"] or 0) + 1
    return f"EX-{n:06d}"


def creer(
    conn: sqlite3.Connection,
    oeuvre_id: int,
    cote: str,
    etat: str = "bon",
    reference: str | None = None,
) -> str:
    if reference is None:
        reference = prochaine_reference(conn)
    elif par_reference(conn, reference):
        raise ValueError(f"la référence {reference} existe déjà")
    conn.execute(
        "INSERT INTO exemplaire (oeuvre_id, reference, cote, etat, statut, cree_le) "
        "VALUES (?,?,?,?,?,?)",
        (oeuvre_id, reference, cote, etat, db.STATUT_DISPONIBLE, db.maintenant()),
    )
    return reference


def changer_statut(conn: sqlite3.Connection, exemplaire_id: int, statut: str) -> None:
    conn.execute(
        "UPDATE exemplaire SET statut = ? WHERE id = ?", (statut, exemplaire_id)
    )


def compter_par_statut(conn: sqlite3.Connection) -> dict[str, int]:
    lignes = conn.execute(
        "SELECT statut, COUNT(*) AS n FROM exemplaire GROUP BY statut"
    ).fetchall()
    return {l["statut"]: l["n"] for l in lignes}


# ---- Acquisitions (gestion du fonds : entrées) ----

def enregistrer_acquisition(
    conn: sqlite3.Connection,
    oeuvre_id: int,
    mode: str,
    nb_exemplaires: int,
    note: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO acquisition (oeuvre_id, mode, nb_exemplaires, date, note) "
        "VALUES (?,?,?,?,?)",
        (oeuvre_id, mode, nb_exemplaires, db.aujourd_hui().isoformat(), note),
    )


def acquisitions_recentes(conn: sqlite3.Connection, limite: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT ac.*, o.titre FROM acquisition ac JOIN oeuvre o ON o.id = ac.oeuvre_id "
        "ORDER BY ac.id DESC LIMIT ?",
        (limite,),
    ).fetchall()
