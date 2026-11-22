"""Source « classiques » : hydratation Open Library de la liste curatée, sans accès réseau."""

import json

from sigb.api import classiques
from sigb.erreurs import ErreurReseau


def _doc(key="OL1W", titre="Germinal", annee=1885, ia=("germinal00zola",),
         acces="public", cover=123, langue=("fre",), phrase=("Un soir de mars...",)):
    return {
        "key": key, "title": titre, "author_name": ["Émile Zola"],
        "first_publish_year": annee, "language": list(langue), "ia": list(ia),
        "ebook_access": acces, "cover_i": cover, "subject": ["Fiction"],
        "first_sentence": list(phrase) if phrase else [],
    }


class _Reponse:
    def __init__(self, docs):
        self._docs = docs

    def json(self):
        return {"docs": self._docs, "numFound": len(self._docs)}


def _brancher(monkeypatch, docs_par_requete):
    """docs_par_requete : liste de listes de documents, une par requête HTTP."""
    appels = iter(docs_par_requete)
    monkeypatch.setattr(classiques, "requete_get",
                        lambda url, params=None: _Reponse(next(appels)))


def test_populaires_hydrate_les_classiques_avec_un_lien_archive(monkeypatch):
    _brancher(monkeypatch, [[_doc()]])
    notices = classiques.populaires(langue="fr", limite=1)
    assert len(notices) == 1
    n = notices[0]
    # Le titre, l'auteur et l'année curatés priment (typographie française propre) ;
    # le lien, la couverture et la première phrase viennent d'Open Library.
    assert n.titre == "Les Misérables" and n.auteurs == ["Victor Hugo"] and n.annee == 1862
    assert n.lien_numerique == "https://archive.org/details/germinal00zola"
    assert n.couverture_url.endswith("123-M.jpg")
    assert n.type_document == "numerique" and n.source == "openlibrary" and n.source_id == "OL1W"
    assert n.resume == "Un soir de mars..."


def test_populaires_passe_les_editions_non_lisibles(monkeypatch):
    # 1re requête : la meilleure réponse est réservée (printdisabled), la 2e est libre.
    _brancher(monkeypatch, [
        [_doc(ia=(), acces="printdisabled"), _doc(key="OL2W", ia=("autre00zola",))],
    ])
    notices = classiques.populaires(langue="fr", limite=1)
    assert len(notices) == 1 and notices[0].source_id == "OL2W"


def test_populaires_saute_les_oeuvres_sans_exemplaire_lisible(monkeypatch):
    _brancher(monkeypatch, [
        [_doc(ia=(), acces="printdisabled"), _doc(ia=(), acces="borrowable")],  # rien de lisible
        [_doc(key="OL9W", titre="Candide")],                                    # œuvre suivante lisible
    ])
    notices = classiques.populaires(langue="fr", limite=2)
    assert [n.source_id for n in notices] == ["OL9W"]


def test_populaires_source_injoignable_des_le_debut_leve_l_erreur(monkeypatch):
    def panne(url, params=None):
        raise ErreurReseau("injoignable")
    monkeypatch.setattr(classiques, "requete_get", panne)
    try:
        classiques.populaires(langue="fr", limite=5)
        raise AssertionError("ErreurReseau attendue")
    except ErreurReseau:
        pass


def test_populaires_panne_en_cours_de_route_garde_les_hydratees(monkeypatch):
    reponses = [_Reponse([_doc()]), _Reponse([_doc(key="OL2W")])]
    etat = {"n": 0}

    def alternee(url, params=None):
        if etat["n"] >= 2:
            raise ErreurReseau("panne réseau")
        reponse = reponses[etat["n"]]
        etat["n"] += 1
        return reponse

    monkeypatch.setattr(classiques, "requete_get", alternee)
    notices = classiques.populaires(langue="fr", limite=3)
    assert [n.source_id for n in notices] == ["OL1W", "OL2W"]


def test_populaires_respecte_langue_genre_et_limite(monkeypatch):
    appels = []

    def reponse(url, params=None):
        appels.append(params)
        return _Reponse([_doc(titre="Fables")])

    monkeypatch.setattr(classiques, "requete_get", reponse)
    assert classiques.populaires(langue="en", limite=5) == []          # liste curatée : français seulement
    assert appels == []                                                # aucune requête réseau inutile
    classiques.populaires(langue="fr", sujet="poetry", limite=3)
    assert len(appels) == 3                                            # seulement les œuvres du genre
    assert appels[0]["q"].startswith('title:"') and 'author:"' in appels[0]["q"]


def test_rechercher_ne_garde_que_les_livres_lisibles(monkeypatch):
    capturés = {}

    def reponse(url, params=None):
        capturés.update(params)
        return _Reponse([_doc(), _doc(ia=(), acces="borrowable"), _doc(key="OL3W")])

    monkeypatch.setattr(classiques, "requete_get", reponse)
    notices = classiques.rechercher(titre="zola", limite=10)
    assert [n.source_id for n in notices] == ["OL1W", "OL3W"]
    assert capturés["ebook_access"] == "public"                        # filtre côté serveur
    assert all(n.type_document == "numerique" and n.lien_numerique for n in notices)


def test_rechercher_sans_critere_refuse(monkeypatch):
    try:
        classiques.rechercher()
        raise AssertionError("ValueError attendue")
    except ValueError:
        pass
