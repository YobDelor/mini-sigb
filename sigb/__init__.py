"""Mini-SIGB — gestion de bibliothèque en Python.

Architecture MVC :
  - M : sigb.models (persistance SQLite) + sigb.services (logique métier)
  - V : sigb.cli (menus, écrans et affichage du terminal)
  - C : sigb.cli.ecrans + sigb.cli.commandes (lisent la saisie, appellent les services)

Règle d'or : les règles métier ne vivent QUE dans sigb.services ;
les interfaces ne font que les appeler.
"""

__version__ = "1.0.0"
