"""Liseuse, remplissage depuis Gutenberg, recherche de documents par titre.
Les appels réseau sont remplacés par des réponses simulées (aucun accès internet requis)."""

import pytest

from sigb.api import gutenberg
from sigb.api.common import Notice
from sigb.erreurs import ErreurMetier
from sigb.models import db, oeuvres
from sigb.services import catalogue, circulation, import_service, lecture
from tests.helpers import creer_oeuvre, creer_usager


class FausseReponse:
    def __init__(self, contenu: bytes, type_contenu="text/html; charset=utf-8", url="https://www.gutenberg.org/cache/epub/1/pg1-images.html"):
        self.content, self.headers, self.url = contenu, {"Content-Type": type_contenu}, url
        self.apparent_encoding = "utf-8"

    def json(self):
        import json
        return json.loads(self.content)


def _importer_lisible(lien, titre="Livre libre"):
    oid, _ = import_service.importer_notice(
        Notice(titre=titre, auteurs=["Auteur Libre"], lien_numerique=lien, source="gutenberg",
               source_id=titre, type_document="numerique"), nb_copies=0)
    return oid


def test_liseuse_html_mise_en_page_cache_et_ouverture(monkeypatch):
    appels, ouverts = [], []
    html = b"<html><head><meta charset='iso-8859-1'><title>X</title></head><body><h1>Chapitre</h1><p>Il \xc3\xa9tait</p></body></html>"
    monkeypatch.setattr(lecture, "requete_get", lambda url, params=None: appels.append(url) or FausseReponse(html))
    monkeypatch.setattr(lecture.webbrowser, "open", lambda cible: ouverts.append(cible) or True)
    oid = _importer_lisible("https://www.gutenberg.org/ebooks/1.html.images")

    r = lecture.lire(oid)
    assert r["mode"] == "liseuse" and r["ouvert"] and not r["depuis_cache"]
    page = next(lecture.dossier_livres().glob(f"{oid}-*.html")).read_text(encoding="utf-8")
    assert "liseuse-style" in page and "liseuse-barre" in page and "<base href=" in page
    assert page.count("charset") == 1 and "Il était" in page            # un seul charset, accents intacts
    assert ouverts[0].startswith("file://")

    r2 = lecture.lire(oid)                                              # 2e lecture : cache, pas de réseau
    assert r2["depuis_cache"] and len(appels) == 1


def test_liseuse_texte_brut_devient_paragraphes(monkeypatch):
    texte = "\ufeffPremière ligne\nsuite du paragraphe\n\nSecond <paragraphe>".encode("utf-8")
    monkeypatch.setattr(lecture, "requete_get", lambda url, params=None: FausseReponse(texte, "text/plain; charset=utf-8"))
    monkeypatch.setattr(lecture.webbrowser, "open", lambda cible: True)
    oid = _importer_lisible("https://www.gutenberg.org/cache/epub/1/pg1.txt", "Texte brut")
    lecture.lire(oid)
    page = next(lecture.dossier_livres().glob(f"{oid}-*.html")).read_text(encoding="utf-8")
    assert "<p>Première ligne suite du paragraphe</p>" in page
    assert "Second &lt;paragraphe&gt;" in page                          # le contenu est échappé


@pytest.mark.parametrize("lien", ["https://archive.org/details/x", "https://exemple.org/livre.pdf",
                                  "https://www.gutenberg.org/ebooks/1.epub.images"])
def test_liens_non_texte_ouverts_tels_quels(monkeypatch, lien):
    ouverts = []
    monkeypatch.setattr(lecture, "requete_get", lambda *a, **k: pytest.fail("pas de téléchargement"))
    monkeypatch.setattr(lecture.webbrowser, "open", lambda cible: ouverts.append(cible) or True)
    r = lecture.lire(_importer_lisible(lien, f"L {lien[-6:]}"))
    assert r["mode"] == "navigateur" and ouverts == [lien]


def test_lire_sans_version_numerique_est_un_refus_clair():
    oid, _ = creer_oeuvre("Papier seulement")
    with pytest.raises(ErreurMetier, match="version numérique"):
        lecture.lire(oid, ouvrir_navigateur=False)
    with pytest.raises(ErreurMetier):
        lecture.lire(9999, ouvrir_navigateur=False)


def test_gutenberg_prefere_le_html_et_marque_numerique():
    livre = {"id": 135, "title": "Les Misérables", "authors": [{"name": "Hugo, Victor"}], "languages": ["fr"],
             "formats": {"text/plain; charset=utf-8": "https://x/pg135.txt",
                         "text/html": "https://x/pg135-images.html", "application/epub+zip": "https://x/e.epub"}}
    n = gutenberg._vers_notice(livre)
    assert n.lien_numerique.endswith(".html") and n.type_document == "numerique"
    assert n.auteurs == ["Victor Hugo"]


def test_garnir_depuis_gutenberg_ajoute_sans_exemplaire_et_sans_doublon(monkeypatch):
    def faux_get(url, params=None):
        livres = [{"id": i, "title": f"Classique {i}", "authors": [{"name": "Nom, Prénom"}], "languages": ["fr"],
                   "formats": {"text/html": f"https://x/{i}.html"}} for i in (1, 2, 3)]
        livres.append({"id": 4, "title": "Sans texte", "authors": [], "languages": ["fr"], "formats": {}})
        return FausseReponse(__import__("json").dumps({"results": livres, "next": None}).encode())
    monkeypatch.setattr(gutenberg, "requete_get", faux_get)
    suivi = []
    r = import_service.garnir_depuis_gutenberg(nombre=10, progression=lambda i, n, t: suivi.append(t))
    assert r == {"ajoutes": 3, "deja_presents": 0, "trouves": 3} and len(suivi) == 3   # « Sans texte » écarté
    assert import_service.garnir_depuis_gutenberg(nombre=10)["deja_presents"] == 3      # relancer = aucun doublon
    conn = db.get_conn()
    try:
        assert len(oeuvres.recherche(conn, lisible=True)) == 3
        assert all(o["nb_total"] == 0 for o in oeuvres.recherche(conn))
    finally:
        conn.close()


def test_chercher_exemplaires_par_numero_ou_par_titre():
    _, refs = creer_oeuvre("1984", auteur="George Orwell", nb_copies=2)
    carte = creer_usager()
    circulation.emprunter(carte, refs[0])
    par_numero = catalogue.chercher_exemplaires(refs[0].replace("EX-0000", ""))
    assert [c["reference"] for c in par_numero] == [refs[0]] and par_numero[0]["emprunteur"]
    par_titre = catalogue.chercher_exemplaires("orwell")
    assert {c["reference"] for c in par_titre} == set(refs)
    assert catalogue.chercher_exemplaires("1984")[0]["titre"] == "1984"   # un nombre inconnu = un titre
    assert catalogue.chercher_exemplaires("zzz") == []


def test_liseuse_respecte_l_encodage_declare_par_la_page(monkeypatch):
    page = "<html><head><meta charset='windows-1252'></head><body><p>Été, élève, cœur</p></body></html>".encode("cp1252")
    monkeypatch.setattr(lecture, "requete_get", lambda url, params=None: FausseReponse(page, "text/html"))
    monkeypatch.setattr(lecture.webbrowser, "open", lambda cible: True)
    oid = _importer_lisible("https://exemple.org/livre.html", "Latin")
    lecture.lire(oid)
    assert "Été, élève, cœur" in next(lecture.dossier_livres().glob(f"{oid}-*.html")).read_text(encoding="utf-8")


def test_liseuse_ne_met_pas_en_cache_une_page_vide(monkeypatch):
    monkeypatch.setattr(lecture, "requete_get", lambda url, params=None: FausseReponse(b"  \n"))
    oid = _importer_lisible("https://exemple.org/vide.html", "Vide")
    with pytest.raises(ErreurMetier, match="page vide"):
        lecture.lire(oid, ouvrir_navigateur=False)
    assert list(lecture.dossier_livres().glob(f"{oid}-*.html")) == []
