"""Accès aux œuvres, auteurs et catégories (fichiers d'autorités)."""

import sqlite3

from sigb.models import db
from sigb.saisie import sans_accents

SOURCES = ("openlibrary", "gutenberg", "bnf", "saisie_manuelle")


# ---- Auteurs (autorité : un même nom = une seule ligne) ----

def trouver_ou_creer_auteur(conn: sqlite3.Connection, nom: str) -> int:
    nom = " ".join(nom.split())  # normalisation : espaces propres
    if not nom:
        raise ValueError("nom d'auteur vide")
    ligne = conn.execute("SELECT id FROM auteur WHERE nom = ?", (nom,)).fetchone()
    if ligne:
        return ligne["id"]
    cur = conn.execute("INSERT INTO auteur (nom) VALUES (?)", (nom,))
    return cur.lastrowid


def auteurs_de(conn: sqlite3.Connection, oeuvre_id: int) -> list[str]:
    lignes = conn.execute(
        "SELECT a.nom FROM oeuvre_auteur oa JOIN auteur a ON a.id = oa.auteur_id "
        "WHERE oa.oeuvre_id = ? ORDER BY a.nom",
        (oeuvre_id,),
    ).fetchall()
    return [l["nom"] for l in lignes]


# ---- Catégories (genres / sujets) ----

def trouver_ou_creer_categorie(conn: sqlite3.Connection, libelle: str) -> int:
    libelle = " ".join(libelle.split())
    if not libelle:
        raise ValueError("libellé de catégorie vide")
    ligne = conn.execute(
        "SELECT id FROM categorie WHERE libelle = ?", (libelle,)
    ).fetchone()
    if ligne:
        return ligne["id"]
    cur = conn.execute("INSERT INTO categorie (libelle) VALUES (?)", (libelle,))
    return cur.lastrowid


def categories_de(conn: sqlite3.Connection, oeuvre_id: int) -> list[str]:
    lignes = conn.execute(
        "SELECT c.libelle FROM oeuvre_categorie oc JOIN categorie c ON c.id = oc.categorie_id "
        "WHERE oc.oeuvre_id = ? ORDER BY c.libelle",
        (oeuvre_id,),
    ).fetchall()
    return [l["libelle"] for l in lignes]


# ---- Œuvres ----

def par_id(conn: sqlite3.Connection, oeuvre_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM oeuvre WHERE id = ?", (oeuvre_id,)).fetchone()


def par_isbn(conn: sqlite3.Connection, isbn: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM oeuvre WHERE isbn = ?", (isbn,)).fetchone()


def par_source_id(conn: sqlite3.Connection, source: str, source_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM oeuvre WHERE source = ? AND source_id = ?", (source, source_id)
    ).fetchone()


def creer(
    conn: sqlite3.Connection,
    titre: str,
    auteurs: list[str],
    editeur: str | None = None,
    annee: int | None = None,
    isbn: str | None = None,
    langue: str = "fre",
    type_document: str = "livre",
    genre: str | None = None,
    resume: str | None = None,
    couverture_url: str | None = None,
    lien_numerique: str | None = None,
    source: str = "saisie_manuelle",
    source_id: str | None = None,
    categories: list[str] | None = None,
) -> int:
    """Crée l'œuvre, rattache auteurs et catégories (réutilisation des autorités).

    Les auteurs et catégories existants sont réutilisés, jamais dupliqués :
    c'est le principe des fichiers d'autorités du domaine.
    """
    cur = conn.execute(
        """INSERT INTO oeuvre
           (titre, editeur, annee, isbn, langue, type_document, genre, resume,
            couverture_url, lien_numerique, source, source_id, cree_le)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            titre,
            editeur,
            annee,
            isbn,
            langue,
            type_document,
            genre,
            resume,
            couverture_url,
            lien_numerique,
            source,
            source_id,
            db.maintenant(),
        ),
    )
    oeuvre_id = cur.lastrowid
    for nom in auteurs:
        auteur_id = trouver_ou_creer_auteur(conn, nom)
        conn.execute(
            "INSERT OR IGNORE INTO oeuvre_auteur (oeuvre_id, auteur_id) VALUES (?,?)",
            (oeuvre_id, auteur_id),
        )
    for libelle in categories or []:
        if libelle:
            cat_id = trouver_ou_creer_categorie(conn, libelle)
            conn.execute(
                "INSERT OR IGNORE INTO oeuvre_categorie (oeuvre_id, categorie_id) VALUES (?,?)",
                (oeuvre_id, cat_id),
            )
    return oeuvre_id


def recherche(
    conn: sqlite3.Connection,
    q: str | None = None,
    disponible: bool = False,
    type_document: str | None = None,
    limite: int = 60,
    lisible: bool = False,
) -> list[sqlite3.Row]:
    """Recherche dans le catalogue en UNE requête.

    - chaque mot saisi doit se retrouver (titre, auteur, genre, sujet ou ISBN) ;
    - insensible aux accents et à la casse ;
    - renvoie aussi auteurs, nb_total et nb_dispo (pas de requête par résultat).
    """
    clauses, params = [], []
    for mot in sans_accents(q).split():
        motif = f"%{mot}%"
        clauses.append(
            "(sans_accents(o.titre) LIKE ? OR sans_accents(COALESCE(o.genre,'')) LIKE ?"
            " OR COALESCE(o.isbn,'') LIKE ?"
            " OR EXISTS (SELECT 1 FROM oeuvre_auteur oa JOIN auteur a ON a.id = oa.auteur_id"
            "            WHERE oa.oeuvre_id = o.id AND sans_accents(a.nom) LIKE ?)"
            " OR EXISTS (SELECT 1 FROM oeuvre_categorie oc JOIN categorie c ON c.id = oc.categorie_id"
            "            WHERE oc.oeuvre_id = o.id AND sans_accents(c.libelle) LIKE ?))"
        )
        params += [motif, motif, motif, motif, motif]
    if type_document:
        clauses.append("o.type_document = ?")
        params.append(type_document)
    if lisible:
        clauses.append("COALESCE(o.lien_numerique, '') <> ''")
    if disponible:
        clauses.append(
            "EXISTS (SELECT 1 FROM exemplaire e WHERE e.oeuvre_id = o.id AND e.statut = 'disponible')"
        )
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = (
        "SELECT o.*,"
        " (SELECT GROUP_CONCAT(a.nom, ', ') FROM oeuvre_auteur oa JOIN auteur a ON a.id = oa.auteur_id"
        "   WHERE oa.oeuvre_id = o.id) AS auteurs,"
        " (SELECT COUNT(*) FROM exemplaire e WHERE e.oeuvre_id = o.id"
        "   AND e.statut NOT IN ('retire','perdu')) AS nb_total,"
        " (SELECT COUNT(*) FROM exemplaire e WHERE e.oeuvre_id = o.id"
        "   AND e.statut = 'disponible') AS nb_dispo"
        " FROM oeuvre o" + where + " ORDER BY o.titre COLLATE NOCASE LIMIT ?"
    )
    params.append(limite)
    return conn.execute(sql, params).fetchall()


def nb_exemplaires_par_statut(conn: sqlite3.Connection, oeuvre_id: int) -> dict[str, int]:
    lignes = conn.execute(
        "SELECT statut, COUNT(*) AS n FROM exemplaire WHERE oeuvre_id = ? GROUP BY statut",
        (oeuvre_id,),
    ).fetchall()
    return {l["statut"]: l["n"] for l in lignes}
