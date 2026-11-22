"""Tests du module d'import : dédoublonnage, autorités, parseurs des 3 sources."""

from sigb.api import bnf, gutenberg, openlibrary
from sigb.api.common import Notice
from sigb.models import db
from sigb.services import import_service


def _notice(isbn: str | None = "9782070413352", titre: str = "Test notice",
            source: str = "openlibrary") -> Notice:
    return Notice(
        titre=titre, auteurs=["Auteur Import"], annee=2020, isbn=isbn,
        source=source, source_id="src-1",
    )


def test_import_dedoublonne_par_isbn():
    """Dédoublonnage : importer deux fois le même ISBN ne crée qu'une œuvre,
    même si les notices viennent de deux sources différentes."""
    id1, cree1 = import_service.importer_notice(_notice(), nb_copies=1, cote="TST")
    id2, cree2 = import_service.importer_notice(
        _notice(titre="Autre intitulé éditorial", source="bnf"), nb_copies=1, cote="TST2"
    )
    assert cree1 is True and cree2 is False
    assert id1 == id2
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM oeuvre").fetchone()[0] == 1
        # aucun exemplaire supplémentaire créé par le doublon
        assert conn.execute("SELECT COUNT(*) FROM exemplaire").fetchone()[0] == 1
    finally:
        conn.close()


def test_import_dedoublonne_par_source_id_sans_isbn():
    """Cas Gutenberg : pas d'ISBN, le dédoublonnage passe par l'identifiant source."""
    notice1 = _notice(isbn=None, titre="Les Misérables", source="gutenberg")
    notice1.source_id = "135"
    id1, cree1 = import_service.importer_notice(notice1)
    notice2 = _notice(isbn=None, titre="Les Misérables (réédition)", source="gutenberg")
    notice2.source_id = "135"
    id2, cree2 = import_service.importer_notice(notice2)
    assert cree1 and not cree2 and id1 == id2


def test_import_reutilise_auteur_et_categorie():
    """Les fichiers d'autorités : un même auteur / genre n'est jamais dupliqué."""
    n1 = _notice(titre="Premier livre", isbn="1111111111111")
    n1.genres = ["Roman"]
    n2 = _notice(titre="Deuxième livre", isbn="2222222222222")
    n2.genres = ["Roman"]
    import_service.importer_notice(n1)
    import_service.importer_notice(n2)
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM auteur").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM categorie").fetchone()[0] == 1
    finally:
        conn.close()


def test_normalisation_isbn():
    assert import_service.normaliser_isbn("978-2-07-041335-2") == "9782070413352"
    assert import_service.normaliser_isbn("0-14-030676-5") == "0140306765"
    assert import_service.normaliser_isbn("  9782070612758  ") == "9782070612758"
    assert import_service.normaliser_isbn("invalide") is None
    assert import_service.normaliser_isbn(None) is None


def test_parseur_openlibrary():
    doc = {
        "key": "/works/OL12345W",
        "title": "Le Petit Prince",
        "author_name": ["Antoine de Saint-Exupéry"],
        "first_publish_year": 1943,
        "isbn": ["9782070612758", "2070612759", "x7"],
        "language": ["fre"],
        "publisher": ["Gallimard"],
        "cover_i": 10708272,
        "subject": ["Contes", "Philosophie"],
    }
    notice = openlibrary._vers_notice(doc)
    assert notice.titre == "Le Petit Prince"
    assert notice.isbn == "9782070612758"  # ISBN-13 préféré aux autres
    assert notice.langue == "fre"
    assert notice.couverture_url.endswith("10708272-M.jpg")
    assert notice.source == "openlibrary"


def test_parseur_gutendex():
    """Le client Gutenberg est testé sur un enregistrement au format Gutendex
    (l'API gutendex.com était injoignable depuis l'environnement de test :
    blocage 403 des IP de datacenter)."""
    livre = {
        "id": 135,
        "title": "Les Misérables",
        "authors": [{"name": "Hugo, Victor", "birth_year": 1802, "death_year": 1885}],
        "languages": ["fr"],
        "subjects": ["Historical fiction -- France -- Paris", "Paris (France) -- Fiction"],
        "formats": {
            "text/plain; charset=utf-8": "https://www.gutenberg.org/ebooks/135.txt.utf-8",
            "image/jpeg": "https://www.gutenberg.org/cache/epub/135/pg135.cover.medium.jpg",
        },
    }
    notice = gutenberg._vers_notice(livre)
    assert notice.titre == "Les Misérables"
    assert notice.auteurs == ["Victor Hugo"]  # « Hugo, Victor » remis dans l'ordre
    assert notice.lien_numerique == "https://www.gutenberg.org/ebooks/135.txt.utf-8"
    assert notice.source_id == "135"
    assert notice.genres[0] == "Historical fiction"


# Enregistrement UNIMARC réduit d'une réponse réelle de la SRU BnF
UNIMARC_EXTRAIT = """<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
 <numberOfRecords>1</numberOfRecords>
 <records><record>
  <recordData><record xmlns="http://www.loc.gov/MARC21/slim">
   <controlfield tag="001">FRBNF38012762</controlfield>
   <datafield tag="010" ind1=" " ind2=" ">
     <subfield code="a">978-2-264-08521-4</subfield></datafield>
   <datafield tag="101" ind1=" " ind2=" "><subfield code="a">fre</subfield></datafield>
   <datafield tag="200" ind1=" " ind2=" ">
     <subfield code="a">L'ile mysterieuse</subfield>
     <subfield code="b">Texte imprimé</subfield></datafield>
   <datafield tag="210" ind1=" " ind2=" ">
     <subfield code="c">10/18</subfield><subfield code="d">DL 2025</subfield></datafield>
   <datafield tag="700" ind1=" " ind2=" ">
     <subfield code="a">Verne</subfield><subfield code="b">Jules</subfield></datafield>
   <datafield tag="330" ind1=" " ind2=" ">
     <subfield code="a">Un nouveau voyage extraordinaire.</subfield></datafield>
   <datafield tag="608" ind1=" " ind2=" "><subfield code="a">Romans d'aventures</subfield></datafield>
  </record></recordData>
 </record></records>
</searchRetrieveResponse>""".encode("utf-8")


def test_parseur_bnf_sru():
    notices = bnf.parser_reponse(UNIMARC_EXTRAIT)
    assert len(notices) == 1
    n = notices[0]
    assert n.titre == "L'ile mysterieuse"
    assert n.isbn == "9782264085214"
    assert n.auteurs == ["Jules Verne"]
    assert n.editeur == "10/18"
    assert n.annee == 2025
    assert n.langue == "fre"
    assert n.resume.startswith("Un nouveau voyage")
    assert n.source == "bnf"


def test_parseur_bnf_dedoublonne_les_variantes():
    """La SRU BnF renvoie chaque notice en double (variantes de schéma) :
    le parseur doit ne garder qu'une notice par ISBN."""
    xml_double = UNIMARC_EXTRAIT.replace(
        b"</records>",
        UNIMARC_EXTRAIT.split(b"<records>", 1)[1].rsplit(b"</records>", 1)[0] + b"</records>",
    )
    assert len(bnf.parser_reponse(xml_double)) == 1


def test_parseur_bnf_ecarte_les_disques():
    """Filtre métier : la SRU renvoie aussi disques et films — on les écarte."""
    xml_disque = UNIMARC_EXTRAIT.replace("Texte imprimé".encode(), "Enregistrement sonore".encode())
    assert bnf.parser_reponse(xml_disque) == []


def test_import_manuel_sans_isbn():
    """La saisie manuelle reste possible même sans ISBN ni source."""
    notice = _notice(isbn=None, titre="Notice saisie à la main", source="saisie_manuelle")
    notice.source_id = None
    oeuvre_id, creee = import_service.importer_notice(notice, nb_copies=2, cote="MAIN 1")
    assert creee
    conn = db.get_conn()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM exemplaire WHERE oeuvre_id = ?", (oeuvre_id,)
        ).fetchone()[0] == 2
    finally:
        conn.close()
