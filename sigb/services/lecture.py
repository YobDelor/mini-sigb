"""Liseuse : lire un livre numérique dans le navigateur.

Un navigateur sait déjà afficher du HTML, du texte et du PDF : on s'en sert
comme écran de lecture, sans rien installer.

- Texte HTML ou brut (Project Gutenberg) : le livre est téléchargé UNE fois,
  mis en page (colonne étroite, police de livre, thèmes clair / sépia / sombre,
  taille réglable) et gardé en cache : les lectures suivantes marchent hors ligne.
- Tout autre lien (archive.org, PDF, epub…) : l'adresse est simplement ouverte
  dans le navigateur, qui sait la lire (ou propose de la télécharger).
"""

import hashlib
import html as _html
import re
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from sigb.api.common import requete_get
from sigb.erreurs import ErreurMetier
from sigb.models import db, oeuvres

# Formats qu'on ne remet pas en page : on laisse le navigateur s'en charger.
# (Gutenberg écrit « livre.epub.images » : l'extension n'est pas toujours en fin de lien.)
FORMATS_DIRECTS = re.compile(r"\.(epub|pdf|mobi|zip)(\.|$)")
HOTES_DIRECTS = ("archive.org",)

_STYLE = """<style id="liseuse-style">
:root{--fond:#fbfaf7;--texte:#222;--lien:#2c5282;--taille:1.15rem}
html[data-theme=sepia]{--fond:#f4ecd8;--texte:#433422;--lien:#7a4b1d}
html[data-theme=sombre]{--fond:#16181d;--texte:#d8dce3;--lien:#8ab4f8}
html,body{background:var(--fond)!important;color:var(--texte)!important}
body{max-width:40rem!important;margin:0 auto!important;padding:3.5rem 1.2rem 6rem!important;
  font:var(--taille)/1.8 Georgia,"Times New Roman",serif!important}
a{color:var(--lien)!important}
img{max-width:100%!important;height:auto!important}
pre{white-space:pre-wrap!important;font-family:inherit!important}
h1,h2,h3{line-height:1.3;text-align:center}
p.auteur{text-align:center;opacity:.7;margin-bottom:3rem}
#liseuse-barre{position:fixed;top:.6rem;right:.8rem;display:flex;gap:.4rem;z-index:9999;
  font:14px system-ui,sans-serif;opacity:.35;transition:opacity .2s}
#liseuse-barre:hover{opacity:1}
#liseuse-barre button{cursor:pointer;border:1px solid #8886;border-radius:6px;
  background:var(--fond);color:var(--texte);padding:.25rem .6rem}
</style>"""

_BARRE = """<div id="liseuse-barre">
<button id="lq-moins" title="Texte plus petit">A-</button>
<button id="lq-plus" title="Texte plus grand">A+</button>
<button id="lq-theme" title="Changer d'ambiance">Clair / sépia / sombre</button></div>
<script>(function(){var h=document.documentElement,k='sigb-liseuse',T=['clair','sepia','sombre'],
e={t:'clair',s:1.15};try{e=Object.assign(e,JSON.parse(localStorage.getItem(k)||'{}'))}catch(x){}
function a(){h.setAttribute('data-theme',e.t);h.style.setProperty('--taille',e.s+'rem');
try{localStorage.setItem(k,JSON.stringify(e))}catch(x){}}a();
document.getElementById('lq-moins').onclick=function(){e.s=Math.max(.8,e.s-.1);a()};
document.getElementById('lq-plus').onclick=function(){e.s=Math.min(2.2,e.s+.1);a()};
document.getElementById('lq-theme').onclick=function(){e.t=T[(T.indexOf(e.t)+1)%3];a()};})();</script>"""


# ------------------------------------------------------------------ mise en page


def _decoder(reponse) -> str:
    """UTF-8 d'abord (cas courant de Gutenberg) ; sinon l'encodage DÉCLARÉ par la page
    (<meta charset>) ou par l'en-tête HTTP ; en dernier recours, l'encodage deviné."""
    brut = reponse.content
    try:
        return brut.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    declare = re.search(rb"charset=[\"']?([\w\-]+)", brut[:4096], re.IGNORECASE)
    en_tete = re.search(r"charset=([\w\-]+)", reponse.headers.get("Content-Type") or "", re.IGNORECASE)
    candidats = [declare.group(1).decode("ascii") if declare else None,
                 en_tete.group(1) if en_tete else None,
                 getattr(reponse, "apparent_encoding", None), "cp1252"]
    for encodage in filter(None, candidats):
        try:
            return brut.decode(encodage)
        except (UnicodeDecodeError, LookupError):
            continue
    return brut.decode("latin-1", errors="replace")


def habiller_html(contenu: str, url: str) -> str:
    """Injecte la mise en page de la liseuse dans une page HTML existante.

    <base> garde les images et les liens relatifs fonctionnels (ils pointent
    vers le site d'origine) même quand la page est lue depuis le cache local.
    """
    contenu = re.sub(r"<meta[^>]*charset[^>]*>", "", contenu, flags=re.IGNORECASE)
    entete = f'<meta charset="utf-8"><base href="{_html.escape(url, quote=True)}">{_STYLE}'
    if re.search(r"<head[^>]*>", contenu, re.IGNORECASE):
        contenu = re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + entete, contenu, count=1, flags=re.IGNORECASE)
    elif re.search(r"<html[^>]*>", contenu, re.IGNORECASE):
        contenu = re.sub(r"(<html[^>]*>)", lambda m: m.group(1) + f"<head>{entete}</head>", contenu,
                         count=1, flags=re.IGNORECASE)
    else:
        contenu = f"<head>{entete}</head>{contenu}"
    if re.search(r"<body[^>]*>", contenu, re.IGNORECASE):
        return re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + _BARRE, contenu, count=1, flags=re.IGNORECASE)
    return contenu + _BARRE


def construire_page_texte(titre: str, auteurs: str, texte: str) -> str:
    """Texte brut (lignes coupées à 70 colonnes) -> page HTML en vrais paragraphes."""
    texte = texte.lstrip("\ufeff").replace("\r\n", "\n")
    paragraphes = [" ".join(p.split()) for p in re.split(r"\n\s*\n", texte)]
    corps = "".join(f"<p>{_html.escape(p)}</p>" for p in paragraphes if p)
    return (
        f'<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        f"<title>{_html.escape(titre)}</title>{_STYLE}</head><body>{_BARRE}"
        f'<h1>{_html.escape(titre)}</h1><p class="auteur">{_html.escape(auteurs)}</p>{corps}</body></html>'
    )


# ------------------------------------------------------------------ lecture


def dossier_livres() -> Path:
    """Cache des livres mis en page, à côté de la base."""
    dossier = db.chemin_bdd().parent / "livres"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def _ouvrir_directement(lien: str) -> bool:
    chemin = urlsplit(lien)
    # Le catalogue officiel de secours fournit la page canonique /ebooks/<id>
    # plutôt qu'un lien direct vers un fichier HTML/texte.
    page_catalogue_gutenberg = (
        chemin.netloc.lower() in ("gutenberg.org", "www.gutenberg.org")
        and re.fullmatch(r"/ebooks/\d+/?", chemin.path) is not None
    )
    return (bool(FORMATS_DIRECTS.search(chemin.path.lower()))
            or any(h in chemin.netloc for h in HOTES_DIRECTS)
            or page_catalogue_gutenberg)


def _telecharger_et_habiller(oeuvre, auteurs: str, lien: str) -> str | None:
    """Renvoie la page prête à lire, ou None si le format n'est pas du texte."""
    reponse = requete_get(lien)
    type_contenu = (reponse.headers.get("Content-Type") or "").lower()
    texte = _decoder(reponse)
    if not texte.strip():
        raise ErreurMetier("La source a renvoyé une page vide : réessayez plus tard.")
    if "html" in type_contenu or re.match(r"\s*(<!doctype html|<html)", texte, re.IGNORECASE):
        return habiller_html(texte, getattr(reponse, "url", lien) or lien)
    if "text/plain" in type_contenu:
        return construire_page_texte(oeuvre["titre"], auteurs, texte)
    return None


def lire(oeuvre_id: int, ouvrir_navigateur: bool = True) -> dict:
    """Prépare la lecture d'une œuvre et l'ouvre dans le navigateur.

    Renvoie {titre, mode: 'liseuse'|'navigateur', cible, ouvert, depuis_cache}.
    `ouvert` vaut False si aucun navigateur n'a pu être lancé (serveur sans écran,
    par exemple) : l'appelant affiche alors `cible` pour que l'on puisse l'ouvrir à la main.
    """
    conn = db.get_conn()
    try:
        oeuvre = oeuvres.par_id(conn, oeuvre_id)
        if oeuvre is None:
            raise ErreurMetier("Œuvre introuvable.")
        auteurs = ", ".join(oeuvres.auteurs_de(conn, oeuvre_id))
    finally:
        conn.close()
    lien = oeuvre["lien_numerique"]
    if not lien:
        raise ErreurMetier(
            f"« {oeuvre['titre']} » n'a pas de version numérique à lire. "
            "Seuls les textes libres (Project Gutenberg, Internet Archive) se lisent."
        )

    mode, cible, depuis_cache = "navigateur", lien, False
    if not _ouvrir_directement(lien):
        # Le nom contient l'empreinte du lien : un autre livre ne peut jamais en reprendre le cache.
        empreinte = hashlib.sha1(lien.encode("utf-8")).hexdigest()[:10]
        fichier = dossier_livres() / f"{oeuvre_id}-{empreinte}.html"
        depuis_cache = fichier.exists()
        if not depuis_cache:
            page = _telecharger_et_habiller(oeuvre, auteurs, lien)
            if page is not None:
                fichier.write_text(page, encoding="utf-8")
        if fichier.exists():
            mode, cible = "liseuse", fichier.as_uri()

    ouvert = bool(webbrowser.open(cible)) if ouvrir_navigateur else False
    return {"titre": oeuvre["titre"], "mode": mode, "cible": cible, "ouvert": ouvert,
            "depuis_cache": depuis_cache}
