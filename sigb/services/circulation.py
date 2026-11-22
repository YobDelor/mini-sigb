"""Service circulation : prêt, retour, prolongation, retards et sanctions.

Le guichet ne calcule jamais rien : tout découle de la matrice
catégorie × type (règle n°3) et des vérifications systématiques
(règles n°2 et n°4). Les écritures sont des unités indivisibles :
transaction BEGIN IMMEDIATE de la vérification à l'application.
"""

from datetime import date, timedelta

from sigb.erreurs import ErreurMetier
from sigb.models import amendes, db, exemplaires, oeuvres, prets, regles, reservations, usagers
from sigb.saisie import normaliser_reference
from sigb.services import usagers_service


def _regle_ou_echec(conn, categorie_usager: str, type_document: str):
    regle = regles.regle(conn, categorie_usager, type_document)
    if regle is None:
        raise ErreurMetier(
            f"Aucune règle de prêt n'est configurée pour la catégorie "
            f"« {categorie_usager} » et le type « {type_document} » : "
            "à définir dans l'administration."
        )
    if not regle["autorise"]:
        raise ErreurMetier(
            f"Prêt refusé par la matrice de règles : les usagers « {categorie_usager} » "
            f"ne peuvent pas emprunter de « {type_document} »."
        )
    return regle


def emprunter(numero_carte: str, reference_exemplaire: str, acteur: str = "cli") -> dict:
    """Le cœur du guichet : toutes les vérifications, puis le prêt en une unité.

    - la carte peut être saisie « 1 », « us-1 », un courriel ou un nom unique ;
    - un exemplaire réservé n'est prêtable qu'au lecteur dont la réservation est prête ;
    - si une réservation attend et qu'elle appartient à UN AUTRE lecteur, le prêt
      est refusé (l'exemplaire servira cette réservation à son retour).
    """
    with db.transaction() as conn:
        usager = usagers_service.identifier(conn, numero_carte)
        usagers_service.verifier_compte(conn, usager)

        reference = normaliser_reference(reference_exemplaire)
        exemplaire = exemplaires.par_reference(conn, reference)
        if exemplaire is None:
            raise ErreurMetier(f"Document {reference or '(vide)'} inconnu.")
        oeuvre = oeuvres.par_id(conn, exemplaire["oeuvre_id"])
        if oeuvre is None:
            raise ErreurMetier("Œuvre introuvable : base incohérente.")

        regle = _regle_ou_echec(conn, usager["categorie_usager"], oeuvre["type_document"])

        # Disponible en rayon, ou mis de côté pour CE lecteur (retrait d'une réservation).
        res_servie = None
        if exemplaire["statut"] == db.STATUT_DISPONIBLE:
            pass
        elif exemplaire["statut"] == db.STATUT_MIS_DE_COTE:
            res_servie = reservations.prete_de_usager(conn, oeuvre["id"], usager["id"])
            if res_servie is None:
                raise ErreurMetier(
                    f"Prêt refusé : {reference} est mis de côté pour un autre lecteur "
                    "(réservation en cours de récupération)."
                )
        else:
            raise ErreurMetier(
                f"Prêt refusé : {reference} n'est pas disponible "
                f"(statut : {db.LIBELLES_STATUT.get(exemplaire['statut'], exemplaire['statut'])})."
            )

        res_en_attente = None
        if res_servie is None:
            res_en_attente = reservations.premiere_en_attente(conn, oeuvre["id"])
            if res_en_attente is not None and res_en_attente["usager_id"] != usager["id"]:
                raise ErreurMetier(
                    "Prêt refusé : une réservation est en attente sur cette œuvre. "
                    "L'exemplaire sera mis de côté pour elle à son prochain retour."
                )

        nb = prets.nb_prets_en_cours(conn, usager["id"], oeuvre["type_document"])
        if nb >= regle["quota"]:
            raise ErreurMetier(
                f"Prêt refusé : quota atteint ({nb}/{regle['quota']} document(s) de type "
                f"« {oeuvre['type_document']} » en cours)."
            )

        date_retour_prevue = db.aujourd_hui() + timedelta(days=regle["duree_jours"])
        pret_id = prets.creer(conn, exemplaire["id"], usager["id"], date_retour_prevue, acteur)
        exemplaires.changer_statut(conn, exemplaire["id"], db.STATUT_EMPRUNTE)

        message_reservation = ""
        if res_servie is not None:
            reservations.changer_statut(conn, res_servie["id"], reservations.SATISFAITE)
            message_reservation = " (réservation récupérée)"
        elif res_en_attente is not None:
            reservations.changer_statut(conn, res_en_attente["id"], reservations.SATISFAITE)
            message_reservation = " (réservation servie par cet emprunt)"

        db.journaliser(
            conn, "pret",
            f"Prêt n°{pret_id} : {reference} « {oeuvre['titre']} » à "
            f"{usager['numero_carte']} ({usager['nom']}), retour prévu le {date_retour_prevue}"
            f"{message_reservation}",
            acteur,
        )
        return {
            "pret_id": pret_id,
            "titre": oeuvre["titre"],
            "usager": f"{usager['prenom'] or ''} {usager['nom']}".strip(),
            "carte": usager["numero_carte"],
            "date_retour_prevue": date_retour_prevue,
        }


def retourner(reference_exemplaire: str, acteur: str = "cli") -> dict:
    """Le retour déclenche le plus de règles automatiques :
    retard + sanction, réservation servie (mise de côté), remise en circuit.
    """
    with db.transaction() as conn:
        reference_exemplaire = normaliser_reference(reference_exemplaire)
        exemplaire = exemplaires.par_reference(conn, reference_exemplaire)
        if exemplaire is None:
            raise ErreurMetier(f"Document {reference_exemplaire or '(vide)'} inconnu.")
        pret = prets.pret_ouvert_dun_exemplaire(conn, exemplaire["id"])
        if pret is None:
            raise ErreurMetier(
                f"Aucun prêt en cours sur {reference_exemplaire} : rien à retourner."
            )
        oeuvre = oeuvres.par_id(conn, exemplaire["oeuvre_id"])
        usager = usagers.par_id(conn, pret["usager_id"])
        aujourdhui = db.aujourd_hui()
        echeance = date.fromisoformat(pret["date_retour_prevue"])
        jours_retard = max((aujourdhui - echeance).days, 0)

        prets.cloturer(conn, pret["id"], aujourdhui)

        details_retard = ""
        montant_amende = 0.0
        if jours_retard > 0:
            details_retard = f", RETARD de {jours_retard} jour(s)"
            db.journaliser(
                conn, "retard",
                f"Retour en retard : {reference_exemplaire} par {usager['numero_carte']} "
                f"({jours_retard} jour(s) de retard)",
                acteur,
            )
            if regles.parametre_bool(conn, regles.P_AMENDES_ACTIVEES, False):
                montant_par_jour = regles.parametre_float(conn, regles.P_MONTANT_AMENDE, 0.25)
                montant = round(jours_retard * montant_par_jour, 2)
                amendes.creer(conn, usager["id"], amendes.MOTIF_RETARD, montant, pret["id"])
                amendes.notifier(
                    conn, usager["id"], "amende",
                    f"Amende de retard : {jours_retard} jour(s) × {montant_par_jour:.2f} € "
                    f"= {montant:.2f} € pour « {oeuvre['titre']} ».",
                )
                montant_amende = montant
                details_retard += f", amende de {montant:.2f} €"

        # Une réservation attend-elle cette œuvre ?
        res = reservations.premiere_en_attente(conn, oeuvre["id"])
        if res is not None:
            delai = regles.parametre_int(conn, regles.P_DUREE_MISE_DE_COTE, 7)
            expiration = aujourdhui + timedelta(days=delai)
            exemplaires.changer_statut(conn, exemplaire["id"], db.STATUT_MIS_DE_COTE)
            reservations.servir(conn, res["id"], expiration)
            amendes.notifier(
                conn, res["usager_id"], "reservation_prete",
                f"Votre réservation de « {oeuvre['titre']} » est disponible. "
                f"L'exemplaire est mis de côté pour vous jusqu'au {expiration.isoformat()}.",
            )
            futur = usagers.par_id(conn, res["usager_id"])
            issue = (
                f"à METTRE DE CÔTÉ pour {futur['prenom'] or ''} {futur['nom']} "
                f"(réservation, à récupérer avant le {expiration.strftime('%d/%m/%Y')})"
            ).replace("  ", " ")
        else:
            exemplaires.changer_statut(conn, exemplaire["id"], db.STATUT_DISPONIBLE)
            issue = "à remettre en rayon"

        db.journaliser(
            conn, "retour",
            f"Retour de {reference_exemplaire} « {oeuvre['titre']} » "
            f"(prêt n°{pret['id']}){details_retard}. Issue : {issue}.",
            acteur,
        )
        return {
            "titre": oeuvre["titre"],
            "retard_jours": jours_retard,
            "amende": montant_amende,
            "issue": issue,
        }


def prolonger(reference_exemplaire: str, acteur: str = "cli", usager_id: int | None = None) -> dict:
    """Prolongation : UNE seule fois, jamais en cas de retard ni de réservation
    en attente sur l'œuvre (règle n°5).

    `usager_id` : fourni par le compte lecteur en ligne, il garantit qu'un lecteur
    ne peut prolonger que SES propres prêts.
    """
    with db.transaction() as conn:
        exemplaire = exemplaires.par_reference(conn, normaliser_reference(reference_exemplaire))
        if exemplaire is None:
            raise ErreurMetier(f"Document {reference_exemplaire} inconnu.")
        pret = prets.pret_ouvert_dun_exemplaire(conn, exemplaire["id"])
        if pret is None or (usager_id is not None and pret["usager_id"] != usager_id):
            raise ErreurMetier("Aucun prêt en cours de votre part sur ce document.")
        oeuvre = oeuvres.par_id(conn, exemplaire["oeuvre_id"])
        usager = usagers.par_id(conn, pret["usager_id"])

        if pret["prolonge"]:
            raise ErreurMetier("Prolongation refusée : elle a déjà été utilisée pour ce prêt.")
        if date.fromisoformat(pret["date_retour_prevue"]) < db.aujourd_hui():
            raise ErreurMetier("Prolongation refusée : le prêt est déjà en retard.")
        if reservations.premiere_en_attente(conn, oeuvre["id"]) is not None:
            raise ErreurMetier(
                "Prolongation refusée : une réservation est en attente sur cette œuvre."
            )

        regle = _regle_ou_echec(conn, usager["categorie_usager"], oeuvre["type_document"])
        nouvelle_echeance = date.fromisoformat(pret["date_retour_prevue"]) + timedelta(
            days=regle["duree_jours"]
        )
        prets.marquer_prolonge(conn, pret["id"], nouvelle_echeance)
        db.journaliser(
            conn, "prolongation",
            f"Prolongation du prêt n°{pret['id']} ({reference_exemplaire}) : "
            f"nouvelle échéance {nouvelle_echeance.isoformat()}",
            acteur,
        )
        return {"nouvelle_echeance": nouvelle_echeance, "titre": oeuvre["titre"]}


def declarer_perte(reference_exemplaire: str, acteur: str = "cli") -> dict:
    """Perte déclarée : le prêt est clôturé, l'exemplaire passe « perdu »,
    une amende (motif « perte ») bloque la carte jusqu'au règlement."""
    return _perte_ou_degradation(reference_exemplaire, amendes.MOTIF_PERTE,
                                 db.STATUT_PERDU, regles.P_FRAIS_PERTE, acteur)


def declarer_degradation(reference_exemplaire: str, acteur: str = "cli") -> dict:
    return _perte_ou_degradation(reference_exemplaire, amendes.MOTIF_DEGRADATION,
                                 db.STATUT_EN_REPARATION, regles.P_FRAIS_DEGRADATION, acteur)


def _perte_ou_degradation(reference: str, motif: str, statut: str, cle_frais: str, acteur: str) -> dict:
    with db.transaction() as conn:
        reference = normaliser_reference(reference)
        exemplaire = exemplaires.par_reference(conn, reference)
        if exemplaire is None:
            raise ErreurMetier(f"Document {reference} inconnu.")
        pret = prets.pret_ouvert_dun_exemplaire(conn, exemplaire["id"])
        if pret is None:
            raise ErreurMetier("Cette opération ne s'applique qu'à un document actuellement emprunté.")
        oeuvre = oeuvres.par_id(conn, exemplaire["oeuvre_id"])
        frais = regles.parametre_float(conn, cle_frais, 15.0)
        prets.cloturer(conn, pret["id"], db.aujourd_hui())
        exemplaires.changer_statut(conn, exemplaire["id"], statut)
        amendes.creer(conn, pret["usager_id"], motif, frais, pret["id"])
        amendes.notifier(
            conn, pret["usager_id"], "amende",
            f"{motif.capitalize()} constatée sur « {oeuvre['titre']} » : "
            f"frais de {frais:.2f} €. La carte est bloquée jusqu'au règlement.",
        )
        db.journaliser(
            conn, "sanction",
            f"{motif.capitalize()} : exemplaire {reference} (« {oeuvre['titre']} ») passe "
            f"« {statut} », frais de {frais:.2f} € enregistrés (prêt n°{pret['id']})",
            acteur,
        )
        return {"titre": oeuvre["titre"], "frais": frais, "motif": motif}


def envoyer_relance(pret_id: int, acteur: str = "cli") -> str:
    """Relance manuelle (prévention) : notification au retardataire + journal."""
    with db.transaction() as conn:
        pret = prets.par_id(conn, pret_id)
        if pret is None or pret["date_retour_reelle"] is not None:
            raise ErreurMetier("Ce prêt n'est plus en cours : relance impossible.")
        oeuvre_row = conn.execute(
            "SELECT o.titre, e.reference FROM pret p "
            "JOIN exemplaire e ON e.id = p.exemplaire_id "
            "JOIN oeuvre o ON o.id = e.oeuvre_id WHERE p.id = ?",
            (pret_id,),
        ).fetchone()
        amendes.notifier(
            conn, pret["usager_id"], "retard",
            f"Relance : le document « {oeuvre_row['titre']} » "
            f"({oeuvre_row['reference']}) devait être rendu le {pret['date_retour_prevue']}. "
            "Merci de le rapporter rapidement : votre carte est bloquée tant que le retard dure.",
        )
        db.journaliser(
            conn, "relance",
            f"Relance envoyée pour le prêt n°{pret_id} "
            f"(échéance dépassée : {pret['date_retour_prevue']})",
            acteur,
        )
        return f"Relance enregistrée pour le prêt n°{pret_id} ({oeuvre_row['titre']})."


def operation_guichet(carte: str, reference: str, acteur: str = "cli") -> dict:
    """Le champ unique du guichet : l'agent scanne, le système décide.

    - document actuellement emprunté      -> RETOUR (la carte n'est pas nécessaire) ;
    - document disponible ou mis de côté  -> PRÊT (la carte est nécessaire).

    Chaque opération re-vérifie tout dans sa propre transaction : lire le statut
    ici ne crée donc aucun risque de course.
    """
    reference = normaliser_reference(reference)
    if not reference:
        raise ErreurMetier("Scannez ou saisissez la référence du document.")
    conn = db.get_conn()
    try:
        exemplaire = exemplaires.par_reference(conn, reference)
    finally:
        conn.close()
    if exemplaire is None:
        raise ErreurMetier(f"Document {reference} inconnu.")

    if exemplaire["statut"] == db.STATUT_EMPRUNTE:
        resultat = retourner(reference, acteur=acteur)
        resultat["operation"] = "retour"
        resultat["carte_inutile"] = bool((carte or "").strip())
        return resultat
    if not (carte or "").strip():
        raise ErreurMetier(
            "Ce document est disponible : indiquez la carte du lecteur pour enregistrer le prêt."
        )
    resultat = emprunter(carte, reference, acteur=acteur)
    resultat["operation"] = "pret"
    return resultat
