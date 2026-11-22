#!/usr/bin/env python3
"""Bibliothèque (mini-SIGB) en ligne de commande.

    python main.py                  # ouvre le menu interactif (le plus simple)
    python main.py recherche verne  # ou un raccourci : python main.py --help
"""

import sys

if sys.version_info < (3, 10):
    sys.exit(f"Python 3.10 ou plus récent est nécessaire (version détectée : {sys.version.split()[0]}).")

try:
    from sigb.cli.commandes import executer
except ModuleNotFoundError as e:
    sys.exit(f"Il manque « {e.name} ». Installez les dépendances :  pip install -r requirements.txt")


def main() -> int:
    if len(sys.argv) == 1 and not sys.stdin.isatty():
        sys.argv.append("--help")  # pas de terminal interactif : on affiche l'aide plutôt que de planter
    try:
        return executer()
    except KeyboardInterrupt:
        print("\nInterrompu.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
