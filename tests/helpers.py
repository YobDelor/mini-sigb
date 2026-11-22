"""Aides de construction des tests : œuvres, exemplaires, usagers.

Passent par les services publics (jamais d'écriture directe) pour que
les tests restent fidèles au circuit réel.
"""

from sigb.models import db, oeuvres
from sigb.services import catalogue, usagers_service


def creer_oeuvre(titre: str = "Essai test", auteur: str = "Auteur Test",
                 type_document: str = "livre", isbn: str | None = None,
                 nb_copies: int = 1) -> tuple[int, list[str]]:
    """Crée une œuvre + ses exemplaires ; renvoie (id_oeuvre, références)."""
    conn = db.get_conn()
    try:
        oeuvre_id = oeuvres.creer(conn, titre=titre, auteurs=[auteur],
                                  type_document=type_document, isbn=isbn, langue="fre")
    finally:
        conn.close()
    refs = catalogue.ajouter_exemplaires(oeuvre_id, nb_copies, "TES ex") if nb_copies else []
    return oeuvre_id, refs


def creer_exemplaires(oeuvre_id: int, n: int = 1, cote: str = "TES ex") -> list[str]:
    """Ajoute des exemplaires à une œuvre existante."""
    return catalogue.ajouter_exemplaires(oeuvre_id, n, cote)


def creer_usager(categorie: str = "adulte", nom: str = "Usager Test") -> str:
    fiche = usagers_service.inscription(
        nom, "Prénom", f"{nom.lower().replace(' ', '.')}@test.fr", categorie
    )
    return fiche["numero_carte"]
