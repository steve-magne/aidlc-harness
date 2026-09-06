from __future__ import annotations

import argparse
import json
import sys

from .commands import cmd_agents
from .commands import cmd_check_json
from .commands import cmd_coverage
from .commands import cmd_check_okf
from .commands import cmd_check_python
from .commands import cmd_experiment
from .commands import cmd_feedback
from .commands import cmd_gate
from .commands import cmd_guard
from .commands import cmd_improve
from .commands import cmd_init
from .commands import cmd_knowledge
from .commands import cmd_recall
from .commands import cmd_log
from .commands import cmd_review_request
from .commands import cmd_ratchet
from .commands import cmd_scaffold
from .commands import cmd_score
from .commands import cmd_sign
from .commands import cmd_selfscore
from .commands import cmd_status
from .commands import cmd_test
from .commands import cmd_validate
from .commands import cmd_watchdog
from .commands import cmd_workflow
from .commands import cmd_watchdog_touched
from .experiment import TARGETS
from .tests import run as tests_run
from .util import workspace_root
"""Parseur de commandes et bascule du moteur — appele par le point d'entree
scripts/aidlc.py (des sous-commandes exposees par commands)."""

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aidlc.py", description="Moteur déterministe du harnais AI-DLC.",
        epilog="Piloter un projet : init, workflow, status, validate, review-request, "
               "sign, gate, recall, knowledge, feedback.\n"
               "Maintenir le harnais : agents, scaffold, ratchet, improve, experiment, "
               "test, coverage, selfscore, check-*.\n"
               "Les modes appelés par les hooks (log, guard, watchdog-touched, --touched, "
               "--stop) ne s'invoquent pas à la main.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selftest", action="store_true",
                        help="Alias historique de `test` : lance la suite et sort.")
    # metavar : sans lui, argparse deroule les 24 choix dans la ligne d'usage, y
    # compris les modes de hook qu'on veut justement sortir de la vue.
    sub = parser.add_subparsers(dest="command", metavar="<commande>")

    # Modes de hook : fonctionnels, mais retires de l'aide. Ils sont declares dans
    # hooks.json et n'ont aucun usage a la main — les laisser en tete de la liste des
    # sous-commandes faisait ouvrir l'aide sur ce que personne ne tape.
    sub.add_parser("log")
    sub.add_parser("guard")

    init_cmd = sub.add_parser(
        "init", help="Amorce le projet consommateur : aidlc.json, deliverables/, "
                     "bundle knowledge/ et inventaire des sources existantes.")
    init_cmd.add_argument("--json", action="store_true",
                          help="Force le JSON machine, même dans un terminal.")

    workflow = sub.add_parser(
        "workflow",
        help="Compose le workflow de l'initiative : quels agents la composent. "
             "Sans option, montre ce qui est branché et ce qui ne l'est pas.")
    workflow.add_argument("--add", action="append", metavar="AGENT",
                          help="Ajoute un agent au workflow (repetable).")
    workflow.add_argument("--remove", action="append", metavar="AGENT",
                          help="Retire un agent du workflow (repetable).")
    workflow.add_argument("--initiative", metavar="NOM",
                          help="Nomme l'initiative : ses livrables et son état runtime "
                               "vivent alors sous ce nom. Chaîne vide = retour à plat.")
    workflow.add_argument("--json", action="store_true",
                          help="Force le JSON machine, même dans un terminal.")

    feedback_cmd = sub.add_parser(
        "feedback",
        help="Ce que ce projet a mesuré sur chaque agent : notes, axes faibles, refus "
             "et réserves — à rendre à l'équipe qui le maintient.")
    feedback_cmd.add_argument("--agent", help="Ne rendre que cet agent.")
    feedback_cmd.add_argument("--json", action="store_true", help="Forme machine.")

    validate = sub.add_parser("validate", help="Valide un livrable contre son checks.json.")
    validate.add_argument("stage", nargs="?")
    validate.add_argument("--file", help="Fichier à valider (défaut : livrable de l'étape).")
    validate.add_argument("--json", action="store_true", help="JSON seul, sans résumé humain.")
    validate.add_argument("--touched", action="store_true",
                          help="Mode hook PostToolUse : silencieux si le fichier n'est pas un livrable.")

    score = sub.add_parser("score", help="Enregistre une revue de maturité.")
    score.add_argument("stage")
    score.add_argument("--file", required=True, help="review.json produit par le reviewer.")
    score.add_argument("--json", action="store_true",
                       help="Force le JSON machine, même dans un terminal.")

    gate = sub.add_parser("gate", help="Décide si l'étape est franchie (exit 2 si bloquant).")
    gate.add_argument("stage")
    gate.add_argument("--json", action="store_true",
                      help="Force le JSON machine, même dans un terminal.")

    request = sub.add_parser("review-request", help="Prépare la revue humaine d'une étape.")
    request.add_argument("stage")

    sign = sub.add_parser(
        "sign", help="Signe la revue humaine d'une étape et rejoue la porte "
                     "(geste humain : exige un terminal).")
    sign.add_argument("stage")
    decision = sign.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", dest="approve", action="store_true",
                          help="Approuve le livrable en l'état.")
    decision.add_argument("--reject", dest="approve", action="store_false",
                          help="Refuse le livrable : la justification alimente improve.")
    sign.add_argument("--by", required=True, help="Nom du relecteur qui signe.")
    sign.add_argument("--why", required=True,
                      help="Justification, obligatoire dans les deux sens.")
    sign.add_argument("--force", action="store_true",
                      help="Remplace une signature déjà apposée sur ce run.")
    sign.add_argument("--json", action="store_true",
                      help="Force le JSON machine, même dans un terminal.")

    recall_cmd = sub.add_parser(
        "recall", help="Reproches des tentatives précédentes d'une étape (reprise).")
    recall_cmd.add_argument("stage")
    recall_cmd.add_argument("--limit", type=int, default=3,
                            help="Nombre de runs rappelés (défaut : 3).")
    recall_cmd.add_argument("--json", action="store_true", help="Forme machine.")

    agents_cmd = sub.add_parser(
        "agents", help="Catalogue du registre d'agents (manifestes agent.json).")
    agents_cmd.add_argument("--capability", help="Ne garder que les agents qui portent "
                                                 "cette capacité.")
    agents_cmd.add_argument("--platform", help="Plateforme d'invocation "
                                               "(défaut : AIDLC_PLATFORM ou claude-code).")
    agents_cmd.add_argument("--json", action="store_true", help="JSON seul, sans résumé humain.")
    agents_cmd.add_argument("--strict", action="store_true",
                            help="Exit 1 si un manifeste de ce dépôt est invalide (porte CI).")

    status = sub.add_parser("status", help="Tableau de bord du pipeline.")
    status.add_argument("--json", action="store_true")
    status.add_argument("--history", action="store_true",
                        help="Journal de passage : qui a produit, noté et signé quoi.")

    scaffold_cmd = sub.add_parser("scaffold", help="Génère le plugin d'une étape planifiée.")
    scaffold_cmd.add_argument("stage")
    scaffold_cmd.add_argument("--force", action="store_true",
                              help="Écrase un plugin existant.")

    knowledge = sub.add_parser(
        "knowledge",
        help="Savoir OKF des dépôts déclarés (knowledge-sources.json) : sommaire, "
             "recherche, lecture d'un concept, traversée des liens croisés.")
    knowledge.add_argument("action", choices=["index", "search", "get", "links"])
    knowledge.add_argument("terms", nargs="*",
                           help="search : mots-cles ; get et links : "
                                "<source>/<concept-id>.")
    knowledge.add_argument("--source", help="Restreindre à une source déclarée.")
    knowledge.add_argument("--refresh", action="store_true",
                           help="Met à jour le cache local (git pull) avant de répondre.")
    knowledge.add_argument("--limit", type=int, default=40,
                           help="Plafond de lignes affichées (défaut : 40).")
    knowledge.add_argument("--json", action="store_true", help="Forme machine.")

    improve_cmd = sub.add_parser("improve", help="Diagnostic d'auto-amélioration (JSON).")
    improve_cmd.add_argument("--stage", help="Restreindre à une étape.")

    experiment_cmd = sub.add_parser(
        "experiment",
        help="Mémoire de la boucle : correction appliquée au harnais, effet mesuré "
             "sur les runs suivants.")
    experiment_cmd.add_argument("action", choices=["record", "effect"])
    experiment_cmd.add_argument("--stage",
                                help="Étape concernée (requis pour record ; filtre "
                                     "optionnel pour effect).")
    experiment_cmd.add_argument("--target",
                                help="Ce que la correction vise : " + ", ".join(TARGETS) + ".")
    experiment_cmd.add_argument("--file", help="Fichier du harnais corrigé.")
    experiment_cmd.add_argument("--cause", help="Cause racine visée, en une phrase.")
    experiment_cmd.add_argument("--json", action="store_true",
                                help="JSON seul, sans résumé humain.")

    ratchet_cmd = sub.add_parser(
        "ratchet",
        help="Fige et fait respecter les planchers de sévérité des checks.json (exit 2 si régression).")
    ratchet_cmd.add_argument("--reset", metavar="STAGE",
                             help="Repart du checks.json courant pour une étape (geste auteur).")

    sub.add_parser("watchdog",
                   help="Détecteurs de stagnation sur les journaux (exit 2 si halte).")
    sub.add_parser("watchdog-touched")

    check_okf = sub.add_parser("check-okf",
                               help="Conformité OKF v0.2 d'un bundle (exit 1 si non conforme).")
    check_okf.add_argument("dir", nargs="?",
                           help="Dossier racine du bundle (ex: knowledge, docs).")
    check_okf.add_argument("--touched", action="store_true",
                           help="Mode hook PostToolUse : gate les bundles OKF du projet.")
    check_okf.add_argument("--stop", action="store_true",
                           help="Mode hook Stop : refuse la clôture de session si un bundle "
                                "du projet est non conforme.")
    check_okf.add_argument("--file",
                           help="Chemin du fichier touché (mode --touched ; défaut : stdin du hook).")

    check_python = sub.add_parser("check-python",
                                  help="Compile tout Python d'un dossier (exit 1 si erreur de syntaxe).")
    check_python.add_argument("dir", nargs="?",
                              help="Dossier racine à parcourir (défaut : racine du projet courant).")
    check_python.add_argument("--touched", action="store_true",
                              help="Mode hook PostToolUse : compile le fichier .py écrit, non bloquant.")
    check_python.add_argument("--file",
                              help="Chemin du fichier touché (mode --touched ; défaut : stdin du hook).")

    check_json = sub.add_parser("check-json",
                                help="Parse tout JSON d'un dossier (exit 1 si fichier invalide).")
    check_json.add_argument("dir", nargs="?",
                            help="Dossier racine à parcourir (défaut : racine du projet courant).")
    check_json.add_argument("--touched", action="store_true",
                            help="Mode hook PostToolUse : parse le fichier .json écrit, non bloquant.")
    check_json.add_argument("--file",
                            help="Chemin du fichier touché (mode --touched ; défaut : stdin du hook).")
    test = sub.add_parser("test",
                          help="Suite de tests du moteur (unittest, stdlib).")
    test.add_argument("-k", dest="select", metavar="MOTIF",
                      help="Ne garde que les tests dont l'identifiant contient MOTIF.")
    test.add_argument("-v", "--verbose", action="store_true",
                      help="Un nom de test par ligne.")
    test.add_argument("--failfast", action="store_true",
                      help="S'arrête au premier échec.")

    selfscore_cmd = sub.add_parser(
        "selfscore",
        help="Score de maturité du harnais : portes déterministes du dépôt, agrégées "
             "sur 5 (exit 2 sous le seuil).")
    selfscore_cmd.add_argument("--json", action="store_true",
                               help="JSON seul, sans résumé humain.")

    coverage_cmd = sub.add_parser(
        "coverage",
        help="Ratchet de couverture : la couverture ne descend jamais (exit 2).")
    coverage_cmd.add_argument("--reset", action="store_true",
                              help="Rebase le plancher sur l'état courant (geste humain).")
    coverage_cmd.add_argument("-k", dest="select", metavar="MOTIF",
                              help="Restreint la mesure aux tests correspondants.")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.selftest:
        return tests_run()
    if not args.command:
        parser.print_help(sys.stderr)
        return 1

    root = workspace_root()
    if args.command == "log":
        return cmd_log(root, sys.stdin.read())
    if args.command == "guard":
        return cmd_guard(root, sys.stdin.read())

    handlers = {
        "init": cmd_init, "workflow": cmd_workflow, "feedback": cmd_feedback,
        "validate": cmd_validate, "score": cmd_score, "gate": cmd_gate,
        "sign": cmd_sign, "agents": cmd_agents,
        "review-request": cmd_review_request, "recall": cmd_recall,
        "status": cmd_status,
        "scaffold": cmd_scaffold, "improve": cmd_improve,
        "experiment": cmd_experiment,
        "knowledge": cmd_knowledge,
        "check-okf": cmd_check_okf, "check-python": cmd_check_python,
        "check-json": cmd_check_json, "ratchet": cmd_ratchet,
        "watchdog": cmd_watchdog, "watchdog-touched": cmd_watchdog_touched,
        "test": cmd_test, "coverage": cmd_coverage,
        "selfscore": cmd_selfscore,
    }
    try:
        return handlers[args.command](root, args)
    except FileNotFoundError as exc:
        sys.stderr.write(f"Fichier introuvable : {exc}\n")
        return 1
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"JSON invalide : {exc}\n")
        return 1
