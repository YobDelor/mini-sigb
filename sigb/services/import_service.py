"""Service d'import : alimentation du catalogue depuis les sources ouvertes.

Étapes 4 et 5 du pipeline : normalisation, dédoublonnage par ISBN
(règle n°7 : après import, la base SQLite est la seule source de vérité),
création/réutilisation des auteurs et catégories, journalisation.
"""

from sigb.api import amorce, bnf, classiques, gutenberg, openlibrary
from sigb.api.common import Notice, normaliser_isbn
from sigb.erreurs import ErreurMetier, ErreurReseau
from sigb.models import db, exemplaires, oeuvres

SOURCES_DISPONIBLES = ("openlibrary", "classiques", "gutenberg", "bnf", "auto")


def rechercher_notices(
    source: str,
    isbn: str | None = None,
    titre: str | None = None,
    auteur: str | None = None,
    limite: int = 10,
) -> list[Notice]:
    """Interroge la source choisie et renvoie des notices normalisées.

    « auto » interroge OpenLibrary puis, si rien n'est trouvé ou si la source
    est injoignable, la BnF (complémentaires pour un fonds francophone).
    """
    if source not in SOURCES_DISPONIBLES:
        raise ValueError(f"source inconnue : {source} (attendues : {', '.join(SOURCES_DISPONIBLES)})")
    criteres = dict(isbn=isbn, titre=titre, auteur=auteur, limite=limite)

    if source == "classiques":
        return classiques.rechercher(titre=titre, auteur=auteur, limite=limite)
    if source == "gutenberg":
        return gutenberg.rechercher(titre=titre, auteur=auteur, limite=limite)
    if source == "bnf":
        return bnf.rechercher(**criteres)
    if source == "openlibrary":
        return openlibrary.rechercher(**criteres)

    # auto : OpenLibrary, puis BnF en repli
    derniere_erreur = None
    try:
        notices = openlibrary.rechercher(**criteres)
        if notices:
            return notices
    except ErreurReseau as e:
        derniere_erreur = e
    try:
        return bnf.rechercher(**criteres)
    except ErreurReseau as e:
        raise ErreurReseau(
            f"Aucune source n'a répondu. Dernier échec : {derniere_erreur or e}"
        )


def rechercher_libre(texte: str, source: str = "auto", limite: int = 10) -> list[Notice]:
    """Recherche « un seul champ » : l'agent tape ce qu'il a sous la main.

    - 10 ou 13 chiffres  -> ISBN ;
    - Gutenberg + nombre -> identifiant Gutenberg ;
    - sinon              -> titre, puis auteur si le titre ne donne rien.
    """
    texte = " ".join((texte or "").split())
    if not texte:
        raise ValueError("Saisissez un titre, un auteur ou un ISBN.")
    if source in ("gutenberg", "classiques") and texte.isdigit():
        return [gutenberg.rechercher_par_id(int(texte))]
    isbn = normaliser_isbn(texte)
    if isbn:
        return rechercher_notices(source, isbn=isbn, limite=limite)
    notices = rechercher_notices(source, titre=texte, limite=limite)
    if not notices and source in ("gutenberg", "classiques", "bnf"):
        notices = rechercher_notices(source, auteur=texte, limite=limite)
    return notices


def importer_notice(
    notice: Notice,
    acteur: str = "cli",
    nb_copies: int = 1,
    cote: str | None = None,
    mode_acquisition: str = "achat",
) -> tuple[int, bool]:
    """Étapes 4-5 : normalise, dédoublonne, enregistre l'œuvre puis
    crée les exemplaires locaux (le livre devient géré par la bibliothèque).

    Retourne (id_oeuvre, creee) : creee=False signifie « notice déjà
    présente dans le catalogue » (dédoublonnage par ISBN ou source_id).
    """
    isbn = normaliser_isbn(notice.isbn)
    titre = " ".join(notice.titre.split())
    if not titre:
        raise ErreurMetier("Le titre est obligatoire.")
    if nb_copies < 0 or nb_copies > 50:
        raise ErreurMetier("Nombre d'exemplaires invalide (0 à 50).")

    with db.transaction() as conn:
        # Dédoublonnage : ISBN d'abord (empreinte unique), sinon l'identifiant
        # de la source (cas Gutenberg, qui n'a pas d'ISBN).
        existante = None
        if isbn:
            existante = oeuvres.par_isbn(conn, isbn)
        if existante is None and notice.source_id:
            existante = oeuvres.par_source_id(conn, notice.source, str(notice.source_id))
        if existante is not None:
            db.journaliser(
                conn, "import",
                f"Doublon évité : « {titre} » déjà présent (œuvre n°{existante['id']})",
                acteur,
            )
            return existante["id"], False

        oeuvre_id = oeuvres.creer(
            conn,
            titre=titre,
            auteurs=notice.auteurs,
            editeur=notice.editeur,
            annee=notice.annee,
            isbn=isbn,
            langue=notice.langue,
            type_document=notice.type_document,
            genre=(notice.genres[0] if notice.genres else None),
            resume=notice.resume,
            couverture_url=notice.couverture_url,
            lien_numerique=notice.lien_numerique,
            source=notice.source,
            source_id=str(notice.source_id) if notice.source_id else None,
            categories=notice.genres[:3],
        )

        if nb_copies > 0:
            for _ in range(nb_copies):
                exemplaires.creer(conn, oeuvre_id, cote or cote_par_defaut(notice))
            exemplaires.enregistrer_acquisition(
                conn, oeuvre_id, mode_acquisition, nb_copies, note=f"import {notice.source}"
            )

        db.journaliser(
            conn, "import",
            f"Import {notice.source} : « {titre} » (œuvre n°{oeuvre_id}), "
            f"{nb_copies} exemplaire(s), ISBN {isbn or '-'}",
            acteur,
        )
        return oeuvre_id, True


def cote_par_defaut(notice: Notice) -> str:
    """Cote simple par défaut : AUTEUR4 - TITRE3 (l'agent peut la corriger)."""
    nom = (notice.auteurs[0] if notice.auteurs else "ANONYME")
    nom = "".join(ch for ch in nom.split()[-1] if ch.isalnum())[:4].upper() or "ANON"
    titre = "".join(ch for ch in notice.titre.split()[:1] if ch.isalnum())[:3].lower() or "xxx"
    return f"{notice.type_document.upper()} {nom} {titre}" if notice.type_document != "livre" else f"{nom} {titre}"

def garnir_depuis_gutenberg(
    nombre: int = 20,
    langue: str = "fr",
    sujet: str | None = None,
    acteur: str = "cli",
    progression=None,
) -> dict:
    """Remplit le catalogue avec les classiques les plus populaires de Project Gutenberg.

    Ce sont de VRAIES notices (titre, auteurs, lien de lecture) : aucune donnée
    fictive. Ce sont des textes numériques libres : ils se lisent, sans exemplaire
    à prêter. `progression(i, total, titre)` est appelée à chaque notice si fournie.
    """
    notices = gutenberg.populaires(langue=langue, sujet=sujet, limite=nombre)
    ajoutes = deja = 0
    for i, notice in enumerate(notices, start=1):
        if progression:
            progression(i, len(notices), notice.titre)
        _, creee = importer_notice(notice, acteur=acteur, nb_copies=0)
        ajoutes += creee
        deja += not creee
    return {"ajoutes": ajoutes, "deja_presents": deja, "trouves": len(notices)}


# Ordre d'essai pour remplir le catalogue. La dernière source n'a pas besoin de réseau.
# « classiques » (Open Library / Internet Archive) passe d'abord : service public
# stable. Gutenberg reste en secours — il redeviendra utile à la fin de ses
# maintenances — et la liste intégrée reste le dernier recours, hors ligne.
SOURCES_REMPLISSAGE = (
    ("classiques", "Classiques francophones (Open Library · Internet Archive)", classiques.populaires),
    ("gutenberg", "Project Gutenberg", gutenberg.populaires),
    ("amorce", "liste de départ intégrée (hors ligne)", amorce.populaires),
)


def garnir_catalogue(
    nombre: int = 20,
    langue: str = "fr",
    sujet: str | None = None,
    acteur: str = "cli",
    progression=None,
) -> dict:
    """Remplit le catalogue en essayant plusieurs sources, la première qui répond gagne.

    Ordre : Project Gutenberg, puis une liste de départ intégrée qui
    ne dépend pas d'internet (Open Library n'est pas utilisé ici : son filtre de langue
    renvoie aussi des traductions, donc des livres non français). Renvoie aussi la source utilisée et les échecs
    rencontrés en chemin, pour que l'écran puisse les expliquer.
    """
    echecs: list[tuple[str, str]] = []
    notices: list[Notice] = []
    source_utilisee = ""
    for code, libelle, chercher in SOURCES_REMPLISSAGE:
        try:
            notices = chercher(langue=langue, sujet=sujet, limite=nombre)
        except ErreurReseau as e:
            echecs.append((libelle, str(e)))
            continue
        if notices:
            source_utilisee = libelle
            break
        echecs.append((libelle, "aucun livre trouvé pour ces critères."))

    ajoutes = deja = 0
    for i, notice in enumerate(notices, start=1):
        if progression:
            progression(i, len(notices), notice.titre)
        # Textes en ligne : lisibles, sans exemplaire. Notices hors ligne : 1 exemplaire papier.
        copies = 0 if notice.type_document == "numerique" else 1
        _, creee = importer_notice(notice, acteur=acteur, nb_copies=copies)
        ajoutes += creee
        deja += not creee
    return {"ajoutes": ajoutes, "deja_presents": deja, "trouves": len(notices),
            "source": source_utilisee, "echecs": echecs}
