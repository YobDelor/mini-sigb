"""Matrice des règles de prêt (catégorie d'usager × type de document)
et paramètres de configuration.

C'est la pièce de configuration centrale du système : aucune durée,
aucun quota, aucune autorisation n'est écrite en dur ailleurs
(règle métier n°3). Changer de type de bibliothèque = changer
les valeurs de cette matrice, pas réécrire le code.
"""

import sqlite3

from sigb.models import db

# Clés de paramètres (table parametre)
P_AMENDES_ACTIVEES = "amendes_activees"        # "0" blocage à la française (défaut), "1" amendes
P_MONTANT_AMENDE = "montant_amende_journalier"  # € par jour de retard
P_DUREE_MISE_DE_COTE = "duree_mise_de_cote_jours"
P_DUREE_ADHESION = "duree_adhesion_jours"
P_FRAIS_PERTE = "frais_perte"
P_FRAIS_DEGRADATION = "frais_degradation"


def types_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM type_document ORDER BY code").fetchall()


def categories_usager(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM categorie_usager ORDER BY code").fetchall()


def matrice(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r.*, cu.libelle AS cat_libelle, td.libelle AS type_libelle
           FROM regle_pret r
           JOIN categorie_usager cu ON cu.code = r.categorie_usager
           JOIN type_document td ON td.code = r.type_document
           ORDER BY cu.code, td.code"""
    ).fetchall()


def regle(
    conn: sqlite3.Connection, categorie_usager: str, type_document: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM regle_pret WHERE categorie_usager = ? AND type_document = ?",
        (categorie_usager, type_document),
    ).fetchone()


def definir_regle(
    conn: sqlite3.Connection,
    categorie_usager: str,
    type_document: str,
    autorise: bool,
    duree_jours: int,
    quota: int,
) -> None:
    conn.execute(
        """INSERT INTO regle_pret (categorie_usager, type_document, autorise, duree_jours, quota)
           VALUES (?,?,?,?,?)
           ON CONFLICT (categorie_usager, type_document)
           DO UPDATE SET autorise = excluded.autorise,
                        duree_jours = excluded.duree_jours,
                        quota = excluded.quota""",
        (categorie_usager, type_document, 1 if autorise else 0, duree_jours, quota),
    )


# ---- Paramètres ----


def parametre(conn: sqlite3.Connection, cle: str, defaut: str) -> str:
    ligne = conn.execute("SELECT valeur FROM parametre WHERE cle = ?", (cle,)).fetchone()
    return ligne["valeur"] if ligne else defaut


def parametre_bool(conn: sqlite3.Connection, cle: str, defaut: bool) -> bool:
    return parametre(conn, cle, "1" if defaut else "0") == "1"


def parametre_float(conn: sqlite3.Connection, cle: str, defaut: float) -> float:
    try:
        return float(parametre(conn, cle, str(defaut)))
    except (TypeError, ValueError):
        return defaut


def parametre_int(conn: sqlite3.Connection, cle: str, defaut: int) -> int:
    try:
        return int(parametre(conn, cle, str(defaut)))
    except (TypeError, ValueError):
        return defaut


def definir_parametre(conn: sqlite3.Connection, cle: str, valeur: str) -> None:
    conn.execute(
        "INSERT INTO parametre (cle, valeur) VALUES (?,?) "
        "ON CONFLICT (cle) DO UPDATE SET valeur = excluded.valeur",
        (cle, valeur),
    )


def parametres_tous(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM parametre ORDER BY cle").fetchall()
