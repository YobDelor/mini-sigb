"""Configuration des tests : base SQLite temporaire par test.

La variable d'environnement SIGB_DB est posée AVANT tout import de sigb :
c'est elle qui détermine le fichier de base utilisé par la configuration.
"""

import os
import shutil
import tempfile
from pathlib import Path

# Base de test unique pour la session, recréée à chaque test par la fixture
_DOSSIER_TEST = tempfile.mkdtemp(prefix="mini-sigb-tests-")
os.environ["SIGB_DB"] = str(Path(_DOSSIER_TEST) / "sigb-test.db")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def base():
    """Base neuve + référentiel (matrice, paramètres, types) pour chaque test."""
    from sigb.initialisation import initialiser_reference

    chemin = Path(os.environ["SIGB_DB"])
    for suffixe in ("", "-wal", "-shm"):
        fichier = Path(str(chemin) + suffixe)
        if fichier.exists():
            fichier.unlink()
    shutil.rmtree(chemin.parent / "livres", ignore_errors=True)   # cache de la liseuse
    initialiser_reference()
    yield
