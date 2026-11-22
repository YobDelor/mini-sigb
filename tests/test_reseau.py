"""Réseau : repli IPv4 automatique et messages d'erreur, sans accès internet."""

import pytest
import requests
import urllib3.util.connection as _u3

from sigb import config
from sigb.api import common
from sigb.erreurs import ErreurReseau


@pytest.fixture(autouse=True)
def _ipv6_active(monkeypatch):
    """Chaque test part avec l'IPv6 actif et le retrouve à la sortie."""
    monkeypatch.setattr(config, "IPV4_SEULEMENT", False)
    etat_initial = _u3.HAS_IPV6
    _u3.HAS_IPV6 = True
    yield
    _u3.HAS_IPV6 = etat_initial


class _Reponse:
    def __init__(self, code=200):
        self.status_code = code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def _brancher_session(monkeypatch, actions):
    """actions : une par appel — une exception à lever, ou une réponse à renvoyer."""
    etat = {"n": 0}

    class _FausseSession:
        headers = {}

        def get(self, url, params=None, timeout=None):
            action = actions[etat["n"]]
            etat["n"] += 1
            if isinstance(action, Exception):
                raise action
            return action

    monkeypatch.setattr(common, "_SESSION", _FausseSession())
    return etat


URL = "https://exemple.org/livres"


def test_connexion_expiree_retente_automatiquement_en_ipv4(monkeypatch):
    etat = _brancher_session(monkeypatch, [
        requests.ConnectTimeout("IPv6 muet"),
        _Reponse(200),
    ])
    reponse = common.requete_get(URL)
    assert reponse.status_code == 200
    assert etat["n"] == 2                       # deux essais : IPv6 puis IPv4
    assert _u3.HAS_IPV6 is False                # l'IPv6 reste coupé pour la session


def test_connexion_expiree_apres_repli_ipv4_message_explicite(monkeypatch):
    _brancher_session(monkeypatch, [
        requests.ConnectTimeout("IPv6 muet"),
        requests.ConnectTimeout("IPv4 muet aussi"),
    ])
    try:
        common.requete_get(URL)
        raise AssertionError("ErreurReseau attendue")
    except ErreurReseau as e:
        assert "Un nouvel essai en IPv4 seul a échoué" in str(e)
        assert "SIGB_IPV4_SEULEMENT" not in str(e)   # déjà tenté : le conseil serait inutile


def test_connexion_expiree_sans_repli_possible_conseille_ipv4(monkeypatch):
    _u3.HAS_IPV6 = False                          # IPv6 déjà coupé (ou SIGB_IPV4_SEULEMENT=1)
    etat = _brancher_session(monkeypatch, [requests.ConnectTimeout("muet")])
    try:
        common.requete_get(URL)
        raise AssertionError("ErreurReseau attendue")
    except ErreurReseau as e:
        assert "Connexion impossible à exemple.org" in str(e)
    assert etat["n"] == 1                         # aucun double essai inutile


def test_reseau_injoignable_retente_en_ipv4(monkeypatch):
    etat = _brancher_session(monkeypatch, [
        requests.ConnectionError("[Errno 101] Network is unreachable"),
        _Reponse(200),
    ])
    assert common.requete_get(URL).status_code == 200
    assert etat["n"] == 2


def test_erreur_dns_ne_retente_pas(monkeypatch):
    etat = _brancher_session(monkeypatch, [
        requests.ConnectionError("Name or service not known"),
    ])
    try:
        common.requete_get(URL)
        raise AssertionError("ErreurReseau attendue")
    except ErreurReseau as e:
        assert "résoudre le nom de domaine" in str(e)
    assert etat["n"] == 1                         # le DNS ne dépend pas de l'IPv6


def test_erreur_http_ne_declenche_aucun_repli(monkeypatch):
    etat = _brancher_session(monkeypatch, [_Reponse(503)])
    try:
        common.requete_get(URL)
        raise AssertionError("ErreurReseau attendue")
    except ErreurReseau as e:
        assert "HTTP 503" in str(e)
    assert etat["n"] == 1
    assert _u3.HAS_IPV6 is True                   # le repli IPv4 n'a pas été touché


def test_ecran_de_garnissage_survit_a_une_panne_totale(monkeypatch):
    """Le scénario vécu : Open Library muet, Gutenberg en maintenance, réseau OK."""
    from sigb.api import amorce, classiques, gutenberg

    def panne(url, params=None):
        raise ErreurReseau("Source injoignable.")
    monkeypatch.setattr(classiques, "requete_get", panne)
    monkeypatch.setattr(gutenberg, "requete_get", panne)

    from sigb.initialisation import initialiser_reference
    initialiser_reference()
    from sigb.services import import_service

    r = import_service.garnir_catalogue(nombre=10, langue="fr", acteur="test")
    assert r["source"].startswith("liste de départ") and r["ajoutes"] == 10
    assert len(r["echecs"]) == 2                  # les deux pannes sont expliquées
