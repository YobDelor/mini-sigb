"""Erreurs partagées du mini-SIGB."""


class ErreurMetier(Exception):
    """Violation d'une règle de gestion (message en français pour l'interface)."""


class ErreurReseau(Exception):
    """Source externe injoignable ou réponse invalide."""
