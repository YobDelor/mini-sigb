"""Remplissage du catalogue : cascade classiques (Open Library) → Gutenberg → liste intégrée.

La source « classiques » passe en premier : elle repose sur Open Library
(Internet Archive), service public stable. Gutenberg reste en secours et la
liste intégrée hors ligne reste le dernier recours. Tous les tests restent
sans accès réseau.
"""

from sigb.api import amorce, classiques, gutenberg
from sigb.api.common import Notice
from sigb.erreurs import ErreurReseau
from sigb.models import db, oeuvres
from sigb.services import import_service


def _en_panne(monkeypatch, *modules):
    """Simule l'indisponibilité des sources données (classiques, gutenberg…)."""
    def panne(url, params=None):
        raise ErreurReseau("503")
    for module in modules:
        monkeypatch.setattr(module, "requete_get", panne)


def _classiques_branche(monkeypatch, notices):
    """La source « classiques » répond avec les notices données."""
    monkeypatch.setattr(classiques, "requete_get", lambda url, params=None: _Rep(notices))


class _Rep:
    def __init__(self, docs):
        self._docs = docs

    def json(self):
        return {"docs": self._docs, "numFound": len(self._docs)}


def _doc_classique(titre="Germinal", key="OL1W", ia="germinal00zola"):
    return {"key": key, "title": titre, "author_name": ["Auteur"], "language": ["fre"],
            "ia": [ia], "ebook_access": "public", "first_publish_year": 1885}


def test_classiques_en_tete_de_cascade_gutenberg_en_panne(monkeypatch):
    _en_panne(monkeypatch, gutenberg)
    _classiques_branche(monkeypatch, [_doc_classique()])
    r = import_service.garnir_catalogue(nombre=5)
    assert r["source"] == "Classiques francophones (Open Library · Internet Archive)"
    assert r["ajoutes"] == 1 and r["echecs"] == []
    conn = db.get_conn()
    try:
        oeuvre = oeuvres.recherche(conn)[0]
        assert oeuvre["type_document"] == "numerique"
        assert oeuvre["lien_numerique"] == f"https://archive.org/details/germinal00zola"
    finally:
        conn.close()


def test_tout_est_en_panne_la_liste_integree_fonctionne_sans_reseau(monkeypatch):
    _en_panne(monkeypatch, classiques, gutenberg)
    r = import_service.garnir_catalogue(nombre=10)
    assert r["source"].startswith("liste de départ")
    assert r["ajoutes"] == 10
    assert [e[0] for e in r["echecs"]] == ["Classiques francophones (Open Library · Internet Archive)",
                                           "Project Gutenberg"]
    assert import_service.garnir_catalogue(nombre=10)["deja_presents"] == 10   # pas de doublon


def test_classiques_vides_gutenberg_prend_le_relais(monkeypatch):
    _classiques_branche(monkeypatch, [])          # Open Library répond, mais rien de lisible
    livres = [{"id": 1, "title": "Classique", "authors": [{"name": "Nom, Prénom"}], "languages": ["fr"],
               "formats": {"text/html": "https://x/1.html"}}]

    class Rep:
        def json(self):
            return {"results": livres, "next": None}
    monkeypatch.setattr(gutenberg, "requete_get", lambda url, params=None: Rep())
    r = import_service.garnir_catalogue(nombre=5)
    assert r["source"] == "Project Gutenberg" and r["ajoutes"] == 1
    assert r["echecs"] == [("Classiques francophones (Open Library · Internet Archive)",
                            "aucun livre trouvé pour ces critères.")]


def test_liste_integree_filtre_par_genre(monkeypatch):
    _en_panne(monkeypatch, classiques, gutenberg)
    import_service.garnir_catalogue(nombre=30, sujet="poetry")
    conn = db.get_conn()
    try:
        livres = oeuvres.recherche(conn)
        assert livres and all("Poetry" in (o["genre"] or "") for o in livres)
    finally:
        conn.close()


def test_gutenberg_ok_la_liste_integree_n_est_pas_utilisee(monkeypatch):
    _en_panne(monkeypatch, classiques)            # la source prioritaire est injoignable
    livres = [{"id": 1, "title": "Classique", "authors": [{"name": "Nom, Prénom"}], "languages": ["fr"],
               "formats": {"text/html": "https://x/1.html"}}]

    class Rep:
        def json(self):
            return {"results": livres, "next": None}
    monkeypatch.setattr(gutenberg, "requete_get", lambda url, params=None: Rep())
    r = import_service.garnir_catalogue(nombre=5)
    assert r["source"] == "Project Gutenberg" and r["ajoutes"] == 1
    assert [e[0] for e in r["echecs"]] == ["Classiques francophones (Open Library · Internet Archive)"]


def test_amorce_langue_non_francaise_est_vide():
    assert amorce.populaires(langue="en") == []
