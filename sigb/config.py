"""Configuration du mini-SIGB.

Le fichier de base SQLite est le seul état persistant du système.
La variable d'environnement SIGB_DB permet de le déplacer (utile aux tests).
"""

import os
from pathlib import Path

# Racine du projet (le dossier qui contient main.py et le paquet sigb/)
RACINE = Path(__file__).resolve().parent.parent

DOSSIER_DONNEES = Path(os.environ.get("SIGB_DATA", RACINE / "data"))
CHEMIN_BDD = Path(os.environ.get("SIGB_DB", DOSSIER_DONNEES / "sigb.db"))

# Identité du client HTTP vis-à-vis des APIs ouvertes (politesse professionnelle)
USER_AGENT = os.environ.get(
    "SIGB_USER_AGENT",
    "MiniSIGB/1.0 (projet pedagogique ; contact: bibliothecaire@exemple.fr)",
)

# Délais réseau (connexion, puis attente de la réponse), en secondes.
# Ils peuvent être ajustés sans modifier le code, notamment sur un réseau lent.
def _delai_env(nom: str, valeur_defaut: float) -> float:
    try:
        valeur = float(os.environ.get(nom, valeur_defaut))
    except (TypeError, ValueError):
        valeur = valeur_defaut
    return max(0.1, valeur)


DELAI_RESEAU = (
    _delai_env("SIGB_TIMEOUT_CONNEXION", 5),
    _delai_env("SIGB_TIMEOUT_REPONSE", 25),
)

# Certains réseaux annoncent l'IPv6 mais ne la routent pas : les connexions expirent alors
# alors que l'IPv4 fonctionne. SIGB_IPV4_SEULEMENT=1 force l'IPv4 pour toutes les requêtes.
IPV4_SEULEMENT = os.environ.get("SIGB_IPV4_SEULEMENT", "0").strip().lower() in ("1", "true", "oui", "yes")

# Langues : codes UNIMARC/OpenLibrary -> libellés français
LANGUES = {
    "fre": "français",
    "fra": "français",
    "fr": "français",
    "eng": "anglais",
    "en": "anglais",
    "ger": "allemand",
    "de": "allemand",
    "spa": "espagnol",
    "es": "espagnol",
    "ita": "italien",
    "it": "italien",
    "por": "portugais",
    "dut": "néerlandais",
    "lat": "latin",
}

# Langue par défaut du fonds (décision de cadrage : fonds francophone privilégié)
LANGUE_DEFAUT = "fre"
