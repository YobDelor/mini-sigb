"""Service catalogue : recherche, fiche, exemplaires,
désherbage (sorties du fonds avec motif).

Le désherbage est un retrait MOTIVE : pas de motif, pas de retrait
(journal n°8 appliqué à la gestion du fonds).
"""

from sigb.models import db, exemplaires, oeuvres, prets, usagers
from sigb.erreurs import ErreurMetier
from sigb.saisie import normaliser_reference


def rechercher(
    q: str | None = None,
    disponible: bool = False,
    type_document: str | None = None,
    lisible: bool = False,
    limite: int = 60,
) -> list:
    """Recherche dans le catalogue. Chaque ligne porte déjà auteurs, nb_total, nb_dispo."""
    conn = db.get_conn()
    try:
        return oeuvres.recherche(conn, q=q, disponible=disponible, type_document=type_document,
                                 lisible=lisible, limite=limite)
    finally:
        conn.close()


def chercher_exemplaires(saisie: str, limite_oeuvres: int = 8) -> list[dict]:
    """Retrouve des documents à partir de ce que l'agent tape : un numéro
    (« 12 », « EX-000012 ») OU un titre / un auteur. Un nombre qui ne correspond
    à aucun document est traité comme un titre (« 1984 »).

    Chaque résultat indique l'emprunteur éventuel, pour que l'agent sache
    immédiatement s'il s'agit d'un prêt ou d'un retour.
    """
    saisie = (saisie or "").strip()
    if not saisie:
        return []
    conn = db.get_conn()
    try:
        trouves = []
        ref = normaliser_reference(saisie)
        exemplaire = exemplaires.par_reference(conn, ref) if ref.upper().startswith("EX-") else None
        if exemplaire is not None:
            trouves = [(exemplaire, oeuvres.par_id(conn, exemplaire["oeuvre_id"]))]
        else:
            for o in oeuvres.recherche(conn, q=saisie, limite=limite_oeuvres):
                trouves += [(e, o) for e in exemplaires.de_loeuvre(conn, o["id"])]
        resultat = []
        for e, o in trouves:
            emprunteur = retour_prevu = None
            if e["statut"] == db.STATUT_EMPRUNTE:
                pret = prets.pret_ouvert_dun_exemplaire(conn, e["id"])
                if pret is not None:
                    u = usagers.par_id(conn, pret["usager_id"])
                    emprunteur = f"{u['prenom'] or ''} {u['nom']}".strip()
                    retour_prevu = pret["date_retour_prevue"]
            resultat.append({
                "reference": e["reference"], "cote": e["cote"], "statut": e["statut"],
                "oeuvre_id": o["id"], "titre": o["titre"], "emprunteur": emprunteur,
                "retour_prevu": retour_prevu,
            })
        return resultat
    finally:
        conn.close()


def fiche_oeuvre(oeuvre_id: int) -> dict | None:
    """Fiche complète : œuvre + auteurs + catégories + exemplaires + file d'attente."""
    from sigb.models import reservations

    conn = db.get_conn()
    try:
        row = oeuvres.par_id(conn, oeuvre_id)
        if row is None:
            return None
        return {
            "oeuvre": row,
            "auteurs": oeuvres.auteurs_de(conn, oeuvre_id),
            "categories": oeuvres.categories_de(conn, oeuvre_id),
            "exemplaires": exemplaires.de_loeuvre(conn, oeuvre_id),
            "compteurs": oeuvres.nb_exemplaires_par_statut(conn, oeuvre_id),
            "file_attente": reservations.file_attente(conn, oeuvre_id),
        }
    finally:
        conn.close()


def ajouter_exemplaires(
    oeuvre_id: int,
    nb_copies: int,
    cote: str,
    etat: str = "bon",
    mode_acquisition: str = "achat",
    acteur: str = "cli",
) -> list[str]:
    """Crée des exemplaires locaux (références uniques, cote = adresse physique)."""
    if nb_copies < 1:
        raise ErreurMetier("Il faut au moins un exemplaire.")
    cote = cote.strip()
    if not cote:
        raise ErreurMetier("La cote (adresse physique dans le bâtiment) est obligatoire.")
    references = []
    with db.transaction() as conn:
        if oeuvres.par_id(conn, oeuvre_id) is None:
            raise ErreurMetier(f"Œuvre n°{oeuvre_id} inconnue.")
        for _ in range(nb_copies):
            references.append(exemplaires.creer(conn, oeuvre_id, cote, etat))
        exemplaires.enregistrer_acquisition(conn, oeuvre_id, mode_acquisition, nb_copies)
        db.journaliser(
            conn, "catalogage",
            f"{nb_copies} exemplaire(s) créé(s) pour l'œuvre n°{oeuvre_id} "
            f"(cote {cote}, état {etat}, {mode_acquisition}) : {', '.join(references)}",
            acteur,
        )
    return references


def desherber(reference: str, motif: str, acteur: str = "cli") -> None:
    """Retrait raisonné et MOTIVE d'un exemplaire du fonds."""
    motif = motif.strip()
    if len(motif) < 5:
        raise ErreurMetier(
            "Le motif du désherbage est obligatoire et doit être explicite "
            "(usure, obsolescence, jamais emprunté, doublon...)."
        )
    with db.transaction() as conn:
        reference = normaliser_reference(reference)
        exemplaire = exemplaires.par_reference(conn, reference)
        if exemplaire is None:
            raise ErreurMetier(f"Document {reference} inconnu.")
        if exemplaire["statut"] in (db.STATUT_EMPRUNTE, db.STATUT_MIS_DE_COTE):
            raise ErreurMetier(
                "Cet exemplaire n'est pas en rayon (emprunté ou mis de côté) : "
                "il ne peut pas être désherbé maintenant."
            )
        exemplaires.changer_statut(conn, exemplaire["id"], db.STATUT_RETIRE)
        db.journaliser(
            conn, "desherbage",
            f"Exemplaire {reference} retiré du fonds (œuvre n°{exemplaire['oeuvre_id']}). "
            f"Motif : {motif}",
            acteur,
        )
