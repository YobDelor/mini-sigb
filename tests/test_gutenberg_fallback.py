"""Tests des replis vers le flux OPDS officiel de Project Gutenberg."""

import pytest

from sigb.api import gutenberg
from sigb.api import common
from sigb.erreurs import ErreurReseau
from sigb.services import lecture


FLUX_OPDS = '''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:dcterms="http://purl.org/dc/terms/">
  <id>https://www.gutenberg.org/ebooks/search.opds/</id>
  <title>Project Gutenberg — Popular</title>
  <entry>
    <id>https://www.gutenberg.org/ebooks/135</id>
    <title>Les Misérables</title>
    <author><name>Hugo, Victor</name></author>
    <dcterms:language>fr</dcterms:language>
    <dcterms:issued>1862</dcterms:issued>
    <dc:subject>Fiction</dc:subject>
    <category term="FICTION" label="Roman" />
    <summary>Jean Valjean et les Misérables.</summary>
    <link rel="http://opds-spec.org/image" type="image/jpeg"
          href="/cache/epub/135/pg135.cover.medium.jpg" />
    <link rel="http://opds-spec.org/acquisition/open-access" type="text/html"
          href="/ebooks/135.html.images" />
  </entry>
  <entry>
    <id>https://www.gutenberg.org/ebooks/11</id>
    <title>Alice's Adventures in Wonderland</title>
    <author><name>Carroll, Lewis</name></author>
    <dcterms:language>en</dcterms:language>
    <link rel="http://opds-spec.org/acquisition/open-access" type="text/html"
          href="/ebooks/11.html.images" />
  </entry>
</feed>'''.encode("utf-8")


class FausseReponse:
    def __init__(self, content):
        self.content = content


def test_parser_opds_convertit_une_notice_gutenberg():
    # Le parseur d'entrée s'exerce sur une entrée Atom réelle, sans réseau.
    import xml.etree.ElementTree as ET
    entree = next(e for e in ET.fromstring(FLUX_OPDS).iter() if e.tag.rsplit("}", 1)[-1] == "entry")
    notice = gutenberg._entree_opds_vers_notice(entree)
    assert notice.titre == "Les Misérables"
    assert notice.auteurs == ["Victor Hugo"]
    assert notice.langue == "fre"
    assert notice.source_id == "135"
    assert notice.annee == 1862
    assert "Roman" in notice.genres
    assert notice.resume.startswith("Jean Valjean")
    assert notice.couverture_url.endswith("pg135.cover.medium.jpg")
    assert notice.lien_numerique == "https://www.gutenberg.org/ebooks/135.html.images"



def test_parseur_opds_ignore_uri_atom_dans_le_nom_auteur():
    import xml.etree.ElementTree as ET

    xml = b"""<entry xmlns="http://www.w3.org/2005/Atom">
      <id>https://www.gutenberg.org/ebooks/42</id>
      <title>Un livre</title>
      <author><name>Verne, Jules</name><uri>https://www.gutenberg.org/author/60</uri></author>
      <link rel="http://opds-spec.org/acquisition/open-access" type="text/html"
            href="/ebooks/42.html.images" />
    </entry>"""
    entree = ET.fromstring(xml)
    notice = gutenberg._entree_opds_vers_notice(entree)
    assert notice.auteurs == ["Jules Verne"]


def test_populaires_bascule_sur_opds_si_gutendex_est_indisponible(monkeypatch):
    appels = []

    def faux_get(url, params=None):
        appels.append((url, params))
        if url == gutenberg.URL_API:
            raise ErreurReseau("Gutendex ne répond pas")
        assert url == gutenberg.URL_OPDS
        assert params == {"sort_order": "downloads", "query": "l.fr"}
        return FausseReponse(FLUX_OPDS)

    monkeypatch.setattr(gutenberg, "requete_get", faux_get)
    notices = gutenberg.populaires(langue="fr", limite=10)

    assert len(appels) == 2
    assert appels[0][0] == gutenberg.URL_API
    assert appels[1][0] == gutenberg.URL_OPDS
    assert [n.titre for n in notices] == ["Les Misérables"]
    assert notices[0].source_id == "135"


def test_recherche_bascule_sur_opds_si_gutendex_est_indisponible(monkeypatch):
    def faux_get(url, params=None):
        if url == gutenberg.URL_API:
            raise ErreurReseau("Gutendex ne répond pas")
        assert params == {"query": "miserables"}
        return FausseReponse(FLUX_OPDS)

    monkeypatch.setattr(gutenberg, "requete_get", faux_get)
    notices = gutenberg.rechercher(titre="miserables", limite=5)
    assert [n.titre for n in notices] == ["Les Misérables", "Alice's Adventures in Wonderland"]


def test_identifiant_gutenberg_essaie_le_endpoint_opds_direct(monkeypatch):
    appels = []

    def faux_get(url, params=None):
        appels.append(url)
        if url == gutenberg.URL_API:
            raise ErreurReseau("Gutendex ne répond pas")
        assert url.endswith("/ebooks/135.opds")
        return FausseReponse(FLUX_OPDS)

    monkeypatch.setattr(gutenberg, "requete_get", faux_get)
    notice = gutenberg.rechercher_par_id(135)
    assert notice.source_id == "135"
    assert len(appels) == 2


def test_deux_sources_indisponibles_donnent_un_message_clair(monkeypatch):
    def faux_get(url, params=None):
        raise ErreurReseau(f"{url} indisponible")

    monkeypatch.setattr(gutenberg, "requete_get", faux_get)
    with pytest.raises(ErreurReseau, match="Gutendex.*catalogue officiel"):
        gutenberg.populaires(langue="fr")


def test_page_catalogue_gutenberg_est_ouverte_directement():
    assert lecture._ouvrir_directement("https://www.gutenberg.org/ebooks/135")
    # Une vraie page de lecture HTML reste traitée par la liseuse.
    assert not lecture._ouvrir_directement("https://www.gutenberg.org/ebooks/135.html.images")


def test_erreur_dns_est_distinguee_du_delai_depasse(monkeypatch):
    import requests

    def dns_ko(*args, **kwargs):
        raise requests.ConnectionError("Temporary failure in name resolution")

    monkeypatch.setattr(common._SESSION, "get", dns_ko)
    with pytest.raises(ErreurReseau, match="résoudre le nom de domaine"):
        common.requete_get("https://gutendex.com/books")


def test_delai_reseau_a_un_message_diagnostic(monkeypatch):
    import requests

    def timeout(*args, **kwargs):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(common._SESSION, "get", timeout)
    with pytest.raises(ErreurReseau, match="Délai dépassé.*gutendex.com"):
        common.requete_get("https://gutendex.com/books")


def test_delai_de_connexion_est_distingue_du_delai_de_lecture(monkeypatch):
    import requests

    def connect_timeout(*args, **kwargs):
        raise requests.ConnectTimeout("connect timed out")

    monkeypatch.setattr(common._SESSION, "get", connect_timeout)
    with pytest.raises(ErreurReseau, match="Connexion impossible à gutendex.com.*5 s"):
        common.requete_get("https://gutendex.com/books")

    def read_timeout(*args, **kwargs):
        raise requests.ReadTimeout("read timed out")

    monkeypatch.setattr(common._SESSION, "get", read_timeout)
    with pytest.raises(ErreurReseau, match="connexion a été établie.*25 secondes"):
        common.requete_get("https://gutendex.com/books")


def test_delais_reseau_peuvent_etre_configures_depuis_lenvironnement(monkeypatch):
    from sigb import config

    monkeypatch.setenv("SIGB_TIMEOUT_CONNEXION", "8")
    monkeypatch.setenv("SIGB_TIMEOUT_REPONSE", "40")
    assert config._delai_env("SIGB_TIMEOUT_CONNEXION", 5) == 8.0
    assert config._delai_env("SIGB_TIMEOUT_REPONSE", 25) == 40.0


def test_catalogue_opds_filtre_la_langue_et_conserve_le_genre(monkeypatch):
    recu = []

    def faux_get(url, params=None):
        recu.append(params)
        return FausseReponse(FLUX_OPDS)

    monkeypatch.setattr(gutenberg, "requete_get", faux_get)
    notices = gutenberg._populaires_opds(langue="fre", sujet="poetry", limite=10)

    assert recu == [{"sort_order": "downloads", "query": "l.fr poetry"}]
    assert notices == [notices[0]]
    assert notices[0].source_id == "135"


def test_recherche_vide_bascule_aussi_sur_opds(monkeypatch):
    class ReponseJsonVide(FausseReponse):
        def json(self):
            return {"results": [], "next": None}

    appels_opds = []

    def faux_get(url, params=None):
        if url == gutenberg.URL_API:
            return ReponseJsonVide(b"")
        appels_opds.append((url, params))
        return FausseReponse(FLUX_OPDS)

    monkeypatch.setattr(gutenberg, "requete_get", faux_get)
    notices = gutenberg.rechercher(titre="miserables", limite=5)

    assert appels_opds == [(gutenberg.URL_OPDS, {"query": "miserables"})]
    assert notices[0].source_id == "135"


def test_catalogue_vide_bascule_aussi_sur_opds(monkeypatch):
    class ReponseJsonVide(FausseReponse):
        def json(self):
            return {"results": [], "next": None}

    def faux_get(url, params=None):
        if url == gutenberg.URL_API:
            return ReponseJsonVide(b"")
        assert url == gutenberg.URL_OPDS
        assert params == {"sort_order": "downloads", "query": "l.fr"}
        return FausseReponse(FLUX_OPDS)

    monkeypatch.setattr(gutenberg, "requete_get", faux_get)
    notices = gutenberg.populaires(langue="fr", limite=5)
    assert [notice.source_id for notice in notices] == ["135"]


def test_identifiant_absent_de_gutendex_est_cherche_dans_opds(monkeypatch):
    class ReponseJsonVide(FausseReponse):
        def json(self):
            return {"results": []}

    def faux_get(url, params=None):
        if url == gutenberg.URL_API:
            return ReponseJsonVide(b"")
        assert url.endswith("/ebooks/135.opds")
        return FausseReponse(FLUX_OPDS)

    monkeypatch.setattr(gutenberg, "requete_get", faux_get)
    notice = gutenberg.rechercher_par_id(135)
    assert notice.source_id == "135"
