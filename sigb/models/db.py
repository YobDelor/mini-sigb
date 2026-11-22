"""Couche de persistance unique du mini-SIGB.

Tous les accès à SQLite passent par ce module :
  - get_conn()      : connexion prête à lire (row_factory, clés étrangères)
  - transaction()   : unité indivisible d'écriture (BEGIN IMMEDIATE)
  - init_db()       : création du schéma complet
  - journaliser()   : traçabilité (règle métier n°8)

Le mode WAL est activé dès la création : il tolère mieux les accès
simultanés lecture/écriture, comme le demande le cahier des charges.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from sigb import config
from sigb.saisie import sans_accents

# Statuts d'un exemplaire (circuit de vie du document)
STATUT_DISPONIBLE = "disponible"
STATUT_EMPRUNTE = "emprunte"
STATUT_MIS_DE_COTE = "mis_de_cote"
STATUT_EN_REPARATION = "en_reparation"
STATUT_PERDU = "perdu"
STATUT_RETIRE = "retire"  # désherbage

LIBELLES_STATUT = {
    STATUT_DISPONIBLE: "disponible",
    STATUT_EMPRUNTE: "emprunté",
    STATUT_MIS_DE_COTE: "réservé pour un lecteur",
    STATUT_EN_REPARATION: "en réparation",
    STATUT_PERDU: "perdu",
    STATUT_RETIRE: "retiré du fonds",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS auteur (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    nom  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS categorie (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    libelle  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS oeuvre (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    titre           TEXT NOT NULL,
    editeur         TEXT,
    annee           INTEGER,
    isbn            TEXT UNIQUE,
    langue          TEXT NOT NULL DEFAULT 'fre',
    type_document   TEXT NOT NULL DEFAULT 'livre' REFERENCES type_document(code),
    genre           TEXT,
    resume          TEXT,
    couverture_url  TEXT,
    lien_numerique  TEXT,
    source          TEXT NOT NULL DEFAULT 'saisie_manuelle',
    source_id       TEXT,
    cree_le         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oeuvre_auteur (
    oeuvre_id  INTEGER NOT NULL REFERENCES oeuvre(id) ON DELETE CASCADE,
    auteur_id  INTEGER NOT NULL REFERENCES auteur(id),
    PRIMARY KEY (oeuvre_id, auteur_id)
);

CREATE TABLE IF NOT EXISTS oeuvre_categorie (
    oeuvre_id     INTEGER NOT NULL REFERENCES oeuvre(id) ON DELETE CASCADE,
    categorie_id  INTEGER NOT NULL REFERENCES categorie(id),
    PRIMARY KEY (oeuvre_id, categorie_id)
);

CREATE TABLE IF NOT EXISTS exemplaire (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    oeuvre_id   INTEGER NOT NULL REFERENCES oeuvre(id),
    reference   TEXT NOT NULL UNIQUE,
    cote        TEXT NOT NULL,
    etat        TEXT NOT NULL DEFAULT 'bon',
    statut      TEXT NOT NULL DEFAULT 'disponible',
    cree_le     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS acquisition (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    oeuvre_id        INTEGER NOT NULL REFERENCES oeuvre(id),
    mode             TEXT NOT NULL,          -- achat | don
    nb_exemplaires   INTEGER NOT NULL,
    date             TEXT NOT NULL,
    note             TEXT
);

CREATE TABLE IF NOT EXISTS type_document (
    code     TEXT PRIMARY KEY,
    libelle  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categorie_usager (
    code     TEXT PRIMARY KEY,
    libelle  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regle_pret (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    categorie_usager  TEXT NOT NULL REFERENCES categorie_usager(code),
    type_document     TEXT NOT NULL REFERENCES type_document(code),
    autorise          INTEGER NOT NULL DEFAULT 1,
    duree_jours       INTEGER NOT NULL DEFAULT 21,
    quota             INTEGER NOT NULL DEFAULT 10,
    UNIQUE (categorie_usager, type_document)
);

CREATE TABLE IF NOT EXISTS parametre (
    cle     TEXT PRIMARY KEY,
    valeur  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usager (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_carte         TEXT NOT NULL UNIQUE,
    nom                  TEXT NOT NULL,
    prenom               TEXT,
    email                TEXT UNIQUE,
    categorie_usager     TEXT NOT NULL REFERENCES categorie_usager(code),
    statut               TEXT NOT NULL DEFAULT 'actif',   -- actif | suspendu | radie
    date_inscription     TEXT NOT NULL,
    expiration_adhesion  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pret (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    exemplaire_id       INTEGER NOT NULL REFERENCES exemplaire(id),
    usager_id           INTEGER NOT NULL REFERENCES usager(id),
    date_pret           TEXT NOT NULL,
    date_retour_prevue  TEXT NOT NULL,
    date_retour_reelle  TEXT,
    prolonge            INTEGER NOT NULL DEFAULT 0,
    agent               TEXT
);
CREATE INDEX IF NOT EXISTS idx_pret_ouvert ON pret(exemplaire_id) WHERE date_retour_reelle IS NULL;
CREATE INDEX IF NOT EXISTS idx_pret_usager ON pret(usager_id) WHERE date_retour_reelle IS NULL;

CREATE TABLE IF NOT EXISTS reservation (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    oeuvre_id         INTEGER NOT NULL REFERENCES oeuvre(id),
    usager_id         INTEGER NOT NULL REFERENCES usager(id),
    date_demande      TEXT NOT NULL,          -- horodatage : ordonne la file d'attente
    statut            TEXT NOT NULL DEFAULT 'en_attente',  -- en_attente | prete | satisfait | expiree | annulee
    date_expiration   TEXT                    -- délai de récupération quand "prete"
);
CREATE INDEX IF NOT EXISTS idx_reservation_oeuvre ON reservation(oeuvre_id, statut);

CREATE TABLE IF NOT EXISTS amende (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usager_id       INTEGER NOT NULL REFERENCES usager(id),
    pret_id         INTEGER REFERENCES pret(id),
    motif           TEXT NOT NULL,          -- retard | perte | degradation
    montant         REAL NOT NULL DEFAULT 0,
    payee           INTEGER NOT NULL DEFAULT 0,
    date_creation   TEXT NOT NULL,
    date_reglement  TEXT
);

CREATE TABLE IF NOT EXISTS notification (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    usager_id  INTEGER NOT NULL REFERENCES usager(id),
    type       TEXT NOT NULL,               -- reservation_prete | echeance | retard | amende | compte
    message    TEXT NOT NULL,
    cree_le    TEXT NOT NULL,
    lue        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notification_usager ON notification(usager_id, lue);

CREATE TABLE IF NOT EXISTS journal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage   TEXT NOT NULL,
    acteur       TEXT NOT NULL,
    action       TEXT NOT NULL,
    details      TEXT NOT NULL
);
"""


def chemin_bdd() -> Path:
    return Path(config.CHEMIN_BDD)


def get_conn() -> sqlite3.Connection:
    """Ouvre une connexion de lecture/écriture simple (autocommit)."""
    chemin_bdd().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(chemin_bdd(), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # Recherche insensible aux accents et à la casse (« etranger » = « Étranger »)
    conn.create_function("sans_accents", 1, sans_accents, deterministic=True)
    return conn


@contextmanager
def transaction():
    """Unité indivisible : vérifier puis appliquer sans insertion concurrente.

    BEGIN IMMEDIATE sérialise les écritures : c'est ce qui garantit la règle
    n°2 (un exemplaire ne peut pas être prêté deux fois) même si deux
    demandes arrivent en même temps — une seule gagne, proprement.
    """
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Crée le schéma complet et active le mode WAL."""
    chemin_bdd().parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def base_est_initialisee() -> bool:
    if not chemin_bdd().exists():
        return False
    conn = get_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='oeuvre'"
        ).fetchone()[0]
        return n > 0
    finally:
        conn.close()


def maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


def aujourd_hui() -> date:
    return date.today()


def journaliser(
    conn: sqlite3.Connection,
    action: str,
    details: str,
    acteur: str = "cli",
) -> None:
    """Règle n°8 : chaque opération est datée et tracée."""
    conn.execute(
        "INSERT INTO journal (horodatage, acteur, action, details) VALUES (?,?,?,?)",
        (maintenant(), acteur, action, details),
    )
