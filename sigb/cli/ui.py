"""Tout ce qui s'affiche et se saisit dans le terminal.

Les écrans ne parlent jamais directement à `rich` ou `questionary` : ils passent
par ce module. Ainsi l'apparence (couleurs, wording des consignes) se change en un
seul endroit, et les tests peuvent remplacer les saisies par des réponses scriptées.
"""

import getpass
from datetime import datetime

import questionary
from questionary import Choice, Style
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from sigb.erreurs import ErreurMetier, ErreurReseau
from sigb.models import db

THEME = Theme({
    "ok": "bold #9ece6a", "ko": "bold #f7768e", "warn": "bold #e0af68",
    "info": "#7aa2f7", "doux": "dim", "titre": "bold #7aa2f7",
})
console = Console(theme=THEME)
ACTEUR = getpass.getuser() or "agent"   # signature des opérations dans le journal

STYLE = Style([
    ("qmark", "fg:#7aa2f7 bold"), ("question", "bold"), ("pointer", "fg:#7aa2f7 bold"),
    ("highlighted", "fg:#7aa2f7 bold"), ("selected", "fg:#9ece6a"), ("answer", "fg:#9ece6a bold"),
    ("instruction", "fg:#6b7280"), ("separator", "fg:#6b7280"),
])

COULEURS_STATUT = {
    db.STATUT_DISPONIBLE: "#9ece6a", db.STATUT_EMPRUNTE: "#e0af68", db.STATUT_MIS_DE_COTE: "#7dcfff",
    db.STATUT_EN_REPARATION: "#bb9af7", db.STATUT_PERDU: "#f7768e", db.STATUT_RETIRE: "grey50",
}


class Retour(Exception):
    """L'utilisateur revient en arrière (entrée « Retour » ou Ctrl+C)."""


# ------------------------------------------------------------------ messages


def succes(texte: str) -> None:
    console.print(f"[ok]✓[/] {escape(texte)}")


def erreur(texte: str) -> None:
    console.print(f"[ko]✗[/] {escape(texte)}")


def attention(texte: str) -> None:
    console.print(f"[warn]![/] {escape(texte)}")


def info(texte: str) -> None:
    console.print(f"[info]›[/] {escape(texte)}")


def en_tete(titre: str, sous_titre: str | None = None) -> None:
    console.print()
    console.rule(f"[titre]{escape(titre)}[/]", style="#7aa2f7", align="left")
    if sous_titre:
        console.print(f"[doux]{escape(sous_titre)}[/]")


def attente(texte: str):
    """Animation pendant un appel réseau : `with ui.attente("Recherche…"):`."""
    return console.status(f"[info]{escape(texte)}[/]", spinner="dots")


def tenter(action, *args) -> bool:
    """Exécute une action d'écran : un refus métier ou une panne réseau devient un
    message, une annulation (Ctrl+C) est silencieuse. Renvoie True si l'action a abouti."""
    try:
        action(*args)
        return True
    except Retour:
        return False
    except (ErreurMetier, ErreurReseau) as e:
        erreur(str(e))
        return False


# ------------------------------------------------------------------ formats


def date_fr(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return "-"


def etat(statut: str) -> Text:
    return Text(f"● {db.LIBELLES_STATUT.get(statut, statut)}", style=COULEURS_STATUT.get(statut, ""))


def disponibilite(nb_dispo: int, nb_total: int, lisible: bool = False) -> Text:
    if nb_total == 0:
        return Text("● à lire en ligne", style="#7dcfff") if lisible else Text("● pas d'exemplaire", style="grey50")
    if nb_dispo > 0:
        return Text(f"● {nb_dispo}/{nb_total} disponible{'s' if nb_dispo > 1 else ''}", style="#9ece6a")
    return Text(f"● tout est emprunté (0/{nb_total})", style="#e0af68")


def nom_lecteur(u) -> str:
    return f"{u['prenom'] or ''} {u['nom']}".strip()


# ------------------------------------------------------------------ tableaux et cartes


def tableau(colonnes: list, lignes: list[list], titre: str | None = None, vide: str = "Aucun résultat.") -> None:
    """colonnes : noms, ou (nom, {options rich}) ; lignes : listes de textes ou renderables."""
    if not lignes:
        console.print(f"[doux]{escape(vide)}[/]")
        return
    t = Table(title=titre, title_justify="left", box=box.ROUNDED, header_style="titre",
              border_style="grey37", row_styles=["", "dim"] if len(lignes) > 12 else None)
    for c in colonnes:
        nom, options = c if isinstance(c, tuple) else (c, {})
        t.add_column(nom, **options)
    for ligne in lignes:
        t.add_row(*[c if not isinstance(c, str) else escape(c) for c in ligne])
    console.print(t)


def carte(titre: str, lignes: list[str], couleur: str = "#7aa2f7") -> None:
    """Encadré. Les lignes acceptent le balisage rich ([b]gras[/b])."""
    console.print(Panel("\n".join(lignes), title=f"[b]{escape(titre)}[/b]", title_align="left",
                        border_style=couleur, padding=(1, 2)))


def afficher_pret(r: dict) -> None:
    carte("Prêt enregistré", [
        f"[b]{escape(r['titre'])}[/b]",
        f"Lecteur : {escape(r['usager'])} ([doux]{r['carte']}[/doux])",
        f"À rendre avant le [b]{date_fr(str(r['date_retour_prevue']))}[/b]",
    ], "#9ece6a")


def afficher_retour(r: dict) -> None:
    lignes = [f"[b]{escape(r['titre'])}[/b]", f"Suite : [b]{escape(r['issue'])}[/b]"]
    couleur = "#9ece6a"
    if r.get("retard_jours"):
        couleur = "#e0af68"
        ligne = f"Rendu avec {r['retard_jours']} jour(s) de retard"
        lignes.append(ligne + (f" — amende de {r['amende']:.2f} €" if r.get("amende") else ""))
    carte("Retour enregistré", lignes, couleur)


# ------------------------------------------------------------------ saisies


def _poser(question):
    try:
        return question.unsafe_ask()
    except (KeyboardInterrupt, EOFError):
        raise Retour()


def demander(texte: str, defaut: str = "", obligatoire: bool = False, valider=None) -> str:
    """Saisie libre. `valider(texte)` renvoie True ou un message d'erreur."""
    def verifier(valeur: str):
        if not valeur.strip():
            return "Ce champ est obligatoire." if obligatoire else True
        return valider(valeur) if valider else True

    return _poser(questionary.text(texte, default=defaut, validate=verifier, style=STYLE, qmark="›")).strip()


def entier(texte: str, defaut: int, minimum: int = 0, maximum: int = 999) -> int:
    def valide(v: str):
        return True if v.strip().isdigit() and minimum <= int(v) <= maximum else f"Un nombre entre {minimum} et {maximum}."
    return int(demander(texte, str(defaut), obligatoire=True, valider=valide))


def choisir(texte: str, choix: list[tuple[str, object]], defaut=None, retour: str | None = "← Retour"):
    """Menu à flèches (et touches 1-9 pour les petits menus, filtre au clavier pour les longs).
    Renvoie la valeur choisie ; `retour` ajoute une entrée de sortie qui lève Retour."""
    entrees = [Choice(titre, value=valeur) for titre, valeur in choix]
    sortie = object()
    if retour:
        entrees.append(Choice(retour, value=sortie))
    long = len(entrees) > 9
    defaut_choice = next((e for e in entrees if e.value == defaut), None) if defaut is not None else None
    valeur = _poser(questionary.select(
        texte, choices=entrees, style=STYLE, qmark="›", default=defaut_choice,
        use_shortcuts=not long, use_search_filter=long, use_jk_keys=False,
        instruction="(↑↓ ou tapez pour filtrer, puis Entrée)" if long else "(↑↓ ou touche 1-9, puis Entrée)",
    ))
    if valeur is sortie:
        raise Retour()
    return valeur


def cocher(texte: str, choix: list[tuple[str, object]]) -> list:
    return _poser(questionary.checkbox(
        texte, choices=[Choice(t, value=v) for t, v in choix], style=STYLE, qmark="›",
        instruction="(Espace pour cocher, a = tout, Entrée pour valider)"))


def confirmer(texte: str, defaut: bool = True) -> bool:
    return choisir(texte, [("Oui", True), ("Non", False)], defaut=defaut, retour=None)


def pause() -> None:
    """Attend Entrée. Ctrl+C ici n'est jamais une demande de sortie : on continue."""
    try:
        console.input("[doux]Entrée pour continuer…[/]")
    except (KeyboardInterrupt, EOFError):
        console.print()
