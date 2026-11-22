"""Catalogue de départ hors ligne : dernier recours quand aucune source en ligne ne répond.

Ce sont de vraies œuvres du patrimoine francophone (titre, auteur, année de première
publication), écrites en dur : aucun réseau n'est nécessaire. Elles n'ont ni ISBN ni
lien de lecture, car une édition précise n'est pas connue ; l'agent peut compléter
la notice plus tard (par exemple en cherchant l'œuvre sur Open Library ou la BnF).
"""

from __future__ import annotations

import re
import unicodedata

from sigb.api.common import Notice

# (titre, auteur, année, sujet) — les sujets reprennent ceux de l'écran « Remplir le catalogue ».
_OEUVRES = (
    ("Les Misérables", "Victor Hugo", 1862, "fiction"),
    ("Le Comte de Monte-Cristo", "Alexandre Dumas", 1844, "adventure"),
    ("Vingt mille lieues sous les mers", "Jules Verne", 1870, "science fiction"),
    ("Madame Bovary", "Gustave Flaubert", 1857, "fiction"),
    ("Les Fleurs du mal", "Charles Baudelaire", 1857, "poetry"),
    ("Le Misanthrope", "Molière", 1666, "drama"),
    ("Candide", "Voltaire", 1759, "philosophy"),
    ("Histoire de la Révolution française", "Jules Michelet", 1847, "history"),
    ("Le Rouge et le Noir", "Stendhal", 1830, "fiction"),
    ("Les Trois Mousquetaires", "Alexandre Dumas", 1844, "adventure"),
    ("Voyage au centre de la Terre", "Jules Verne", 1864, "science fiction"),
    ("Cyrano de Bergerac", "Edmond Rostand", 1897, "drama"),
    ("Discours de la méthode", "René Descartes", 1637, "philosophy"),
    ("Fables", "Jean de La Fontaine", 1668, "poetry"),
    ("Germinal", "Émile Zola", 1885, "fiction"),
    ("Le Tour du monde en quatre-vingts jours", "Jules Verne", 1872, "adventure"),
    ("Notre-Dame de Paris", "Victor Hugo", 1831, "fiction"),
    ("Tartuffe", "Molière", 1664, "drama"),
    ("Pensées", "Blaise Pascal", 1670, "philosophy"),
    ("Mémoires d'outre-tombe", "François-René de Chateaubriand", 1849, "history"),
    ("Le Père Goriot", "Honoré de Balzac", 1835, "fiction"),
    ("Arsène Lupin, gentleman-cambrioleur", "Maurice Leblanc", 1907, "adventure"),
    ("Poèmes saturniens", "Paul Verlaine", 1866, "poetry"),
    ("Phèdre", "Jean Racine", 1677, "drama"),
    ("Du contrat social", "Jean-Jacques Rousseau", 1762, "philosophy"),
    ("L'Île mystérieuse", "Jules Verne", 1875, "adventure"),
    ("Bel-Ami", "Guy de Maupassant", 1885, "fiction"),
    ("Alcools", "Guillaume Apollinaire", 1913, "poetry"),
    ("Le Cid", "Pierre Corneille", 1637, "drama"),
    ("Essais", "Michel de Montaigne", 1580, "philosophy"),
    ("La Princesse de Clèves", "Madame de La Fayette", 1678, "fiction"),
    ("Le Fantôme de l'Opéra", "Gaston Leroux", 1910, "fiction"),
    ("Sans famille", "Hector Malot", 1878, "adventure"),
    ("Les Contemplations", "Victor Hugo", 1856, "poetry"),
    ("L'Avare", "Molière", 1668, "drama"),
    ("Les Confessions", "Jean-Jacques Rousseau", 1782, "philosophy"),
    ("Le Capitaine Fracasse", "Théophile Gautier", 1863, "adventure"),
    ("La Chartreuse de Parme", "Stendhal", 1839, "fiction"),
    ("Le Spleen de Paris", "Charles Baudelaire", 1869, "poetry"),
    ("Le Grand Meaulnes", "Alain-Fournier", 1913, "fiction"),
    ("Eugénie Grandet", "Honoré de Balzac", 1833, "fiction"),
    ("L'Assommoir", "Émile Zola", 1877, "fiction"),
    ("Le Horla", "Guy de Maupassant", 1887, "fiction"),
    ("Manon Lescaut", "Abbé Prévost", 1731, "fiction"),
    ("Les Liaisons dangereuses", "Pierre Choderlos de Laclos", 1782, "fiction"),
    ("Carmen", "Prosper Mérimée", 1845, "fiction"),
    ("Gargantua", "François Rabelais", 1534, "fiction"),
    ("Le Mystère de la chambre jaune", "Gaston Leroux", 1907, "fiction"),
)


def _identifiant(titre: str, auteur: str) -> str:
    """Identifiant stable (sert au dédoublonnage : relancer ne crée pas de doublon)."""
    brut = unicodedata.normalize("NFKD", f"{auteur} {titre}").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", brut.lower()).strip("-")


def _vers_notice(titre: str, auteur: str, annee: int, sujet: str) -> Notice:
    return Notice(
        titre=titre,
        auteurs=[auteur],
        annee=annee,
        langue="fre",
        genres=[sujet.capitalize()],
        source="amorce",
        source_id=_identifiant(titre, auteur),
        type_document="livre",
    )


def populaires(langue: str = "fr", sujet: str | None = None, limite: int = 20) -> list[Notice]:
    """Renvoie des classiques francophones sans aucun appel réseau.

    La liste ne contient que du français. Si un genre est demandé mais ne donne rien,
    la liste complète est utilisée plutôt que de ne rien renvoyer.
    """
    if (langue or "fr").lower() not in ("fr", "fre", "fra"):
        return []
    choisies = [o for o in _OEUVRES if not sujet or o[3] == sujet.lower()] or list(_OEUVRES)
    return [_vers_notice(*o) for o in choisies[:limite]]
