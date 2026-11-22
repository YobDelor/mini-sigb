# Bibliothèque (mini-SIGB) — en ligne de commande

Gérer une petite bibliothèque depuis le terminal : catalogue, prêts et retours, réservations,
lecteurs, règles de prêt — et **lire les livres libres dans votre navigateur**.
Python 3.10+, un fichier SQLite, aucune donnée fictive : le catalogue se remplit depuis
Open Library / Internet Archive, avec la BnF et Project Gutenberg en sources complémentaires.

## Deux profils : bibliothécaire et lecteur

Au lancement, le programme demande **qui utilise la bibliothèque** :

- **Bibliothécaire** : le poste complet du comptoir — prêts et retours, fonds, lecteurs,
  règles, retards, journal.
- **Lecteur** : un espace personnel en libre-service, limité à ses propres données.
  Le lecteur s'identifie avec son **n° de carte** (« 1 » suffit), son courriel ou son nom :
  - **Mes emprunts** : ce qu'il a en main, avec les dates, et la **prolongation en un geste**
    (une fois par prêt, refusée s'il y a un retard ou une réservation en attente) ;
  - **Lire un livre en ligne** : ouvre la liseuse dans le navigateur ;
  - **Réserver une œuvre** : utile quand tout est emprunté — il entre dans la file d'attente ;
  - **Mes réservations** : situées (en attente / mises de côté) et annulables ;
  - **Mon profil** : compte, carte bloquée ou non, amendes dues ;
  - **Historique** et ses notifications (réservation prête, relance, amende).

Le lecteur ne peut prolonger ou annuler que sur SON compte (le service verrouille chaque
action sur le compte identifié), et aucune opération de gestion n'est proposée : ce n'est
pas le guichet.

Raccourci direct, sans passer par le menu : `python main.py lecteur` (ou
`python main.py lecteur 1` pour la carte US-000001).

## Démarrer

```bash
pip install -r requirements.txt
python main.py
```

C'est tout. Au premier lancement, la bibliothèque se crée, le profil est demandé, et le
programme propose de remplir le catalogue avec de vrais classiques libres (Project
Gutenberg). Ensuite, tout se fait au clavier avec un menu : **↑↓ + Entrée** (ou une touche
**1-9**, puis Entrée), **Ctrl+C** pour revenir en arrière.

## Ce que l'on peut faire

| Menu | À quoi ça sert |
|---|---|
| **Prêt et retour** | Tapez un n° de document, **un titre ou un auteur**. Si le livre est sorti, c'est un retour ; sinon c'est un prêt et on vous demande le lecteur. Enchaînez les documents, Entrée vide pour finir. |
| **Chercher un livre** | Recherche sans accents, plusieurs mots (« etranger camus »). Fiche, prêt, réservation, ajout ou retrait d'exemplaires. |
| **Lire un livre** | Ouvre le livre dans votre navigateur, comme une liseuse (voir plus bas). |
| **Lecteurs** | Dossier d'un lecteur (recherche par nom), inscription, prolongation, perte / dégradation, règlement d'amende. |
| **Ajouter des livres** | Chercher sur internet (titre, auteur ou ISBN) et cocher ce qu'on ajoute ; remplir le catalogue avec des classiques ; ou saisir à la main. |
| **À faire aujourd'hui** | Retards, documents à mettre de côté, relances. Les réservations non récupérées sont libérées automatiquement. |
| **Réglages et suivi** | Durées et quotas par type de lecteur et de document, amendes, délais, journal, chiffres. |

Pas besoin de connaître les numéros : « Dupont » retrouve un lecteur, « 1 » suffit pour la
carte `US-000001`, et un titre retrouve son exemplaire.

## Sources en ligne et dépannage réseau

**Remplir le catalogue** et **Chercher un classique libre** essaient trois sources dans l'ordre :
1. les classiques francophones d'Open Library (Internet Archive) : chaque œuvre d'une liste
   curatée intégrée reçoit un vrai lien de lecture libre (numérisation archive.org, sans compte) ;
2. Project Gutenberg (Gutendex, puis le flux OPDS officiel) — utile quand le service est
   disponible, mais son hébergement est fragile : Gutendex est un service communautaire sans
   garantie, et le site de Gutenberg subit régulièrement des maintenances ;
3. une liste de départ d'une cinquantaine de classiques francophones intégrée au programme
   (`sigb/api/amorce.py`), qui ne demande aucune connexion. Ces notices n'ont ni ISBN ni lien
   de lecture, et reçoivent un exemplaire papier.

Open Library et la BnF restent disponibles dans « Chercher un livre » (titre, auteur ou ISBN).

Les échecs des sources précédentes sont affichés avant le résultat.

Pour les classiques, l'application interroge Open Library (une requête légère par œuvre,
quelques dixièmes de seconde). Pour Project Gutenberg, elle interroge d'abord Gutendex puis,
si cette API est lente, injoignable ou renvoie une erreur, le flux OPDS officiel. Le délai
est de 5 secondes pour établir la connexion et de 25 secondes pour recevoir la réponse.
Tu peux l'ajuster depuis le terminal si ton réseau est lent :

```bash
SIGB_TIMEOUT_CONNEXION=8 SIGB_TIMEOUT_REPONSE=40 python main.py
```

Si la connexion à une source expire, le programme **retente automatiquement une fois en
IPv4 seul** : certains réseaux annoncent de l'IPv6 (DNS AAAA) sans le router, ce qui
explique qu'un site réponde alors qu'un autre reste muet. Tu peux aussi forcer l'IPv4
dès le départ :

```bash
SIGB_IPV4_SEULEMENT=1 python main.py
```

**Open Library injoignable alors que d'autres sites répondent ?** Dans un terminal :

```bash
curl -4 -I --max-time 15 'https://openlibrary.org/search.json?q=camus'
curl -6 -I --max-time 15 'https://openlibrary.org/search.json?q=camus'
```

- `curl -4` répond mais `curl -6` (ou `curl` seul) expire : ton IPv6 est cassé —
  le repli automatique s'en charge, et `SIGB_IPV4_SEULEMENT=1` l'anticipe ;
- les deux échouent : Open Library est filtré par le VPN, le proxy, le pare-feu ou
  l'antivirus de la machine (essaie de les désactiver pour vérifier) ;
- réseau d'entreprise ou scolaire : les variables `HTTP_PROXY` / `HTTPS_PROXY` doivent
  correspondre au proxy imposé par l'établissement.

Project Gutenberg demande aux applications OPDS de fournir un User-Agent avec un véritable
moyen de contact. Remplace l'adresse d'exemple ci-dessous par une adresse qui t'appartient
avant d'utiliser régulièrement ce catalogue :

```bash
export SIGB_USER_AGENT='MiniSIGB/1.0 (contact: ton-adresse@example.com)'
python main.py
```

En cas d'échec des deux sources, vérifie séparément la résolution DNS et l'accès HTTPS
depuis le terminal :

```bash
getent hosts gutendex.com
getent hosts www.gutenberg.org
curl -I --max-time 30 'https://gutendex.com/books?ids=1342'
curl -I --max-time 30 'https://www.gutenberg.org/ebooks/search.opds/'
```

Si Gutendex échoue mais que le second `curl` répond, le projet peut tout de même importer
des livres via le catalogue officiel. Si les deux commandes `curl` échouent, le problème
est probablement lié à la connexion, au DNS, au VPN, au proxy ou au pare-feu de la machine ;
aucun service distant ne peut alors fournir de nouvelles notices.

Le flux OPDS XML officiel est limité à une page par recherche pour respecter les règles de
Project Gutenberg. Il peut donc fournir moins de résultats que Gutendex. Ce flux XML est
annoncé comme devant être retiré en 2027 ; le mécanisme de secours est centralisé dans
`sigb/api/gutenberg.py` pour faciliter son remplacement.

## Lire dans le navigateur

Un livre numérique (Project Gutenberg, ou Internet Archive pour les titres en accès libre)
s'ouvre dans votre navigateur. Pour les textes de Gutenberg, le livre est téléchargé **une
seule fois**, mis en page (colonne étroite, police de livre, thèmes clair / sépia / sombre,
taille réglable avec A- / A+) puis gardé dans `data/livres/` : les lectures suivantes
fonctionnent **sans connexion**. Les PDF et les pages d'Internet Archive s'ouvrent tels quels.

Ces textes sont libres de droits : ils se lisent, ils ne se prêtent pas (aucun exemplaire).


## Raccourcis (facultatifs, pour aller vite ou automatiser)

```bash
python main.py recherche verne --lisible
python main.py lire "tour du monde"
python main.py pret 1 12          # carte 1, document 12
python main.py retour 12
python main.py lecteur 1          # espace personnel du lecteur US-000001
python main.py import "petit prince" --choix 1
python main.py --help
```

Codes de sortie : 0 réussi · 2 règle refusée (ex. prêt impossible) · 3 source internet injoignable.

## Organisation du code

```
main.py              point d'entrée
sigb/cli/            menus (app.py), écrans (ecrans/), raccourcis (commandes.py), affichage (ui.py)
sigb/services/       TOUTES les règles métier (circulation, réservations, import, lecture, réglages…)
sigb/models/         accès SQLite
sigb/api/            clients OpenLibrary / classiques / BnF / Gutenberg
tests/               tests automatisés (règles métier, écrans du CLI, liseuse) — sans accès internet
```

Les écrans ne contiennent aucune règle : ils lisent la saisie et appellent `sigb/services/`.
Tests : `python -m pytest tests/`

## Limites

- Une seule bibliothèque, un seul poste : pas de mots de passe. L'espace lecteur s'ouvre
  sur la foi du n° de carte (ou du nom) saisi ; le journal signe chaque opération de la
  carte (« US-000001 (lecteur) ») ou de l'utilisateur de la machine côté guichet.
- Les « relances » sont enregistrées dans le dossier du lecteur ; aucun courriel n'est envoyé.
- Les amendes sont enregistrées, pas encaissées.
