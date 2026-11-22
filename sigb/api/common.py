"""Outils communs aux trois sources ouvertes.

Le pipeline d'import en cinq étapes du cahier des charges :
  1. Recherche (par ISBN, sinon par titre/auteur) -> notices normalisées
  2. Sélection et vérification (l'agent choisit la bonne notice)
  3. Mapping (chaque source convertit vers Notice, ci-dessous)
  4. Normalisation et dédoublonnage (ISBN, auteurs, catégories)
  5. Enregistrement (sigb/services/import_service.py)
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests

from sigb import config
from sigb.erreurs import ErreurReseau


def _couper_ipv6() -> bool:
    """Restreint toutes les requêtes du programme à l'IPv4. Renvoie True si l'IPv6
    était encore actif.

    Certains réseaux annoncent de l'IPv6 (enregistrements DNS AAAA) sans le router
    réellement : la connexion à certains sites reste alors indéfiniment en attente,
    alors que d'autres répondent normalement. Forcer l'IPv4 court-circuite ce problème.
    """
    import urllib3.util.connection as _connexion

    if _connexion.HAS_IPV6:
        _connexion.HAS_IPV6 = False
        return True
    return False


if config.IPV4_SEULEMENT:
    _couper_ipv6()

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": config.USER_AGENT})


@dataclass
class Notice:
    """Notice bibliographique normalisée, quelle que soit la source."""

    titre: str
    auteurs: list[str] = field(default_factory=list)
    editeur: str | None = None
    annee: int | None = None
    isbn: str | None = None
    langue: str = config.LANGUE_DEFAUT
    genres: list[str] = field(default_factory=list)
    resume: str | None = None
    couverture_url: str | None = None
    lien_numerique: str | None = None  # version numérisée (Gutenberg, etc.)
    source: str = "saisie_manuelle"
    source_id: str | None = None
    type_document: str = "livre"  # livre | bd | dvd | periode | numerique

    def affichage(self) -> str:
        """Ligne lisible pour les listes de résultats."""
        annee = f", {self.annee}" if self.annee else ""
        isbn = f" · ISBN {self.isbn}" if self.isbn else ""
        return (
            f"{self.titre} — {' et '.join(self.auteurs) or 'auteur inconnu'}"
            f"{annee}{isbn} [{self.source}]"
        )


def _erreur_connexion(e: Exception, hote: str, ipv4_deja_tente: bool = False) -> ErreurReseau:
    """Traduit une exception requests en ErreurReseau au message exploitable."""
    if isinstance(e, requests.ConnectTimeout):
        delai = config.DELAI_RESEAU[0]
        message = f"Connexion impossible à {hote} dans le délai de {delai:g} s. "
        if ipv4_deja_tente:
            message += "Un nouvel essai en IPv4 seul a échoué de la même façon. "
        message += "Vérifiez l'accès internet, le DNS, le VPN ou le proxy, puis réessayez."
        if not ipv4_deja_tente:
            message += (
                " Certains réseaux annoncent de l'IPv6 sans le router : relancer avec"
                " SIGB_IPV4_SEULEMENT=1 force l'IPv4."
            )
        return ErreurReseau(message)
    if isinstance(e, requests.ReadTimeout):
        delai = config.DELAI_RESEAU[1]
        return ErreurReseau(
            f"Délai dépassé en consultant {hote} : la connexion a été établie, "
            f"mais le serveur n'a pas répondu dans les {delai:g} secondes. "
            "La source est peut-être lente ou temporairement surchargée. "
            "Réessayez ou utilisez une autre source."
        )
    if isinstance(e, requests.Timeout):
        return ErreurReseau(
            f"Délai dépassé en consultant {hote} (connexion ou réponse trop lente). "
            "La source n'a pas répondu dans le délai prévu. Réessayez, "
            "utilisez une autre source ou saisissez la notice à la main."
        )
    if isinstance(e, requests.ConnectionError):
        details = str(e).lower()
        erreur_dns = any(m in details for m in (
            "name or service not known", "temporary failure in name resolution",
            "name resolution", "getaddrinfo failed", "nodename nor servname",
        ))
        if erreur_dns:
            return ErreurReseau(
                f"Impossible de résoudre le nom de domaine {hote}. "
                "Vérifiez le DNS, le VPN ou le proxy de votre connexion internet."
            )
        return ErreurReseau(
            f"Source injoignable ({hote}). Vérifiez la connexion réseau, "
            "le pare-feu ou le proxy, puis réessayez."
        )
    if isinstance(e, requests.HTTPError):
        code = e.response.status_code if e.response is not None else "?"
        if code == 429:
            detail = "La source limite temporairement les requêtes. Réessayez dans quelques instants."
        elif isinstance(code, int) and code >= 500:
            detail = "Le service distant rencontre probablement une panne temporaire."
        else:
            detail = "La notice demandée est peut-être absente de cette base."
        return ErreurReseau(f"{hote} a renvoyé une erreur HTTP {code}. {detail}")
    return ErreurReseau(f"Erreur inattendue en consultant {hote} : {e}")


def _doit_retenter_en_ipv4(e: Exception) -> bool:
    """Une connexion qui expire ou un réseau « unreachable » : autant de signes
d'un IPv6 annoncé mais non routé — un nouvel essai en IPv4 seul se justifie."""
    if isinstance(e, requests.ConnectTimeout):
        return True
    return isinstance(e, requests.ConnectionError) and "unreachable" in str(e).lower()


def requete_get(url: str, params: dict | None = None) -> requests.Response:
    """Appel GET avec délais séparés, repli IPv4 automatique et messages clairs.

    Une source injoignable ne doit jamais faire planter l'application :
    l'agent reçoit un message clair et peut toujours saisir la notice à la main.
    Si la connexion expire, l'IPv6 défaillant est le suspect habituel : la requête
    est automatiquement retentée une fois en IPv4 seul avant d'abandonner.
    """
    hote = urlsplit(url).hostname or "source inconnue"
    try:
        reponse = _SESSION.get(url, params=params, timeout=config.DELAI_RESEAU)
        reponse.raise_for_status()
        return reponse
    except (requests.ConnectTimeout, requests.ConnectionError) as e:
        if not _doit_retenter_en_ipv4(e) or config.IPV4_SEULEMENT or not _couper_ipv6():
            raise _erreur_connexion(e, hote) from e
        # IPv6 coupé pour le reste de la session : on retente une fois, proprement.
        try:
            reponse = _SESSION.get(url, params=params, timeout=config.DELAI_RESEAU)
            reponse.raise_for_status()
            return reponse
        except requests.RequestException as second_e:
            raise _erreur_connexion(second_e, hote, ipv4_deja_tente=True) from second_e
    except requests.RequestException as e:
        raise _erreur_connexion(e, hote) from e


def normaliser_isbn(isbn: str | None) -> str | None:
    """Normalise un ISBN : sans tirets ni espaces, X majuscule.

    L'ISBN est la clé de dédoublonnage des imports : importer deux fois
    le même livre ne doit pas créer deux œuvres.
    """
    if not isbn:
        return None
    isbn = re.sub(r"[\s\-.]", "", str(isbn)).upper()
    if isbn and len(isbn) in (10, 13) and re.fullmatch(r"[0-9]+[0-9X]?", isbn):
        return isbn
    return None


def extraire_annee(texte: str | None) -> int | None:
    """Extrait une année plausible (ex. « DL 2021 » -> 2021)."""
    if not texte:
        return None
    m = re.search(r"(1[89]\d{2}|20\d{2})", str(texte))
    return int(m.group(1)) if m else None


def libelle_langue(code: str | None) -> str:
    return config.LANGUES.get((code or "").lower(), code or "inconnue")
