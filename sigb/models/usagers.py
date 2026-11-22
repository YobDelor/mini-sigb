"""Accès aux lecteurs (usagers)."""

import sqlite3

from sigb.models import db
from sigb.saisie import sans_accents

STATUT_ACTIF = "actif"
STATUT_SUSPENDU = "suspendu"
STATUT_RADIE = "radie"


def prochain_numero_carte(conn: sqlite3.Connection) -> str:
    ligne = conn.execute(
        "SELECT MAX(CAST(SUBSTR(numero_carte, 4) AS INTEGER)) AS n FROM usager"
    ).fetchone()
    n = (ligne["n"] or 0) + 1
    return f"US-{n:06d}"


def creer(
    conn: sqlite3.Connection,
    nom: str,
    prenom: str | None,
    email: str | None,
    categorie_usager: str,
    duree_adhesion_jours: int = 365,
) -> sqlite3.Row:
    """Inscription : numéro de carte + expiration d'adhésion calculée."""
    from datetime import timedelta

    numero = prochain_numero_carte(conn)
    expiration = db.aujourd_hui() + timedelta(days=duree_adhesion_jours)
    cur = conn.execute(
        """INSERT INTO usager
           (numero_carte, nom, prenom, email, categorie_usager, statut,
            date_inscription, expiration_adhesion)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            numero,
            nom,
            prenom,
            email,
            categorie_usager,
            STATUT_ACTIF,
            db.aujourd_hui().isoformat(),
            expiration.isoformat(),
        ),
    )
    return par_id(conn, cur.lastrowid)


def par_id(conn: sqlite3.Connection, usager_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM usager WHERE id = ?", (usager_id,)).fetchone()


def par_carte(conn: sqlite3.Connection, numero_carte: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM usager WHERE numero_carte = ?", (numero_carte,)
    ).fetchone()


def par_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM usager WHERE email = ?", (email,)).fetchone()


def chercher(conn: sqlite3.Connection, q: str | None = None, limite: int = 50) -> list[sqlite3.Row]:
    """Recherche de lecteurs : nom, prénom, carte ou courriel, sans accents ;
    chaque mot saisi doit se retrouver."""
    clauses, params = [], []
    for mot in sans_accents(q).split():
        motif = f"%{mot}%"
        clauses.append(
            "(sans_accents(nom) LIKE ? OR sans_accents(COALESCE(prenom,'')) LIKE ?"
            " OR lower(numero_carte) LIKE ? OR lower(COALESCE(email,'')) LIKE ?)"
        )
        params += [motif, motif, motif, motif]
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return conn.execute(
        "SELECT * FROM usager" + where + " ORDER BY nom COLLATE NOCASE, prenom COLLATE NOCASE LIMIT ?",
        params + [limite],
    ).fetchall()


def changer_statut(conn: sqlite3.Connection, usager_id: int, statut: str) -> None:
    conn.execute("UPDATE usager SET statut = ? WHERE id = ?", (statut, usager_id))


def renouveler_adhesion(conn: sqlite3.Connection, usager_id: int, duree_jours: int) -> None:
    from datetime import timedelta

    expiration = db.aujourd_hui() + timedelta(days=duree_jours)
    conn.execute(
        "UPDATE usager SET expiration_adhesion = ?, statut = ? WHERE id = ?",
        (expiration.isoformat(), STATUT_ACTIF, usager_id),
    )
