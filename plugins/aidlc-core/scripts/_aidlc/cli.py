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
from .commands import cmd_gate
from .commands import cmd_guard
from .commands import cmd_improve
from .commands import cmd_knowledge
from .commands import cmd_log
from .commands import cmd_review_request
from .commands import cmd_ratchet
from .commands import cmd_scaffold
from .commands import cmd_score
from .commands import cmd_status
from .commands import cmd_test
from .commands import cmd_validate
from .commands import cmd_watchdog
from .commands import cmd_watchdog_touched
from .experiment import TARGETS
from .tests import run as tests_run
from .util import workspace_root
"""Parseur de commandes et bascule du moteur — appele par le point d'entree
scripts/aidlc.py (des sous-commandes exposees par commands)."""

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aidlc.py", description="Moteur deterministe du harness AI-DLC.")
    parser.add_argument("--selftest", action="store_true",
                        help="Alias historique de `test` : lance la suite et sort.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("log", help="Journalise un evenement de hook lu sur stdin.")
    sub.add_parser("guard", help="Protege .aidlc/ des ecritures d'agents (hook PreToolUse).")

    validate = sub.add_parser("validate", help="Valide un livrable contre son checks.json.")
    validate.add_argument("stage", nargs="?")
    validate.add_argument("--file", help="Fichier a valider (defaut : livrable de l'etape).")
    validate.add_argument("--json", action="store_true", help="JSON seul, sans resume humain.")
    validate.add_argument("--touched", action="store_true",
                          help="Mode hook PostToolUse : silencieux si le fichier n'est pas un livrable.")

    score = sub.add_parser("score", help="Enregistre une revue de maturite.")
    score.add_argument("stage")
    score.add_argument("--file", required=True, help="review.json produit par le reviewer.")

    gate = sub.add_parser("gate", help="Decide si l'etape est franchie (exit 2 si bloquant).")
    gate.add_argument("stage")

    request = sub.add_parser("review-request", help="Prepare la revue humaine d'une etape.")
    request.add_argument("stage")

    agents_cmd = sub.add_parser(
        "agents", help="Catalogue du registre d'agents (manifestes agent.json).")
    agents_cmd.add_argument("--capability", help="Ne garder que les agents qui portent "
                                                 "cette capacite.")
    agents_cmd.add_argument("--platform", help="Plateforme d'invocation "
                                               "(defaut : AIDLC_PLATFORM ou claude-code).")
    agents_cmd.add_argument("--json", action="store_true", help="JSON seul, sans resume humain.")
    agents_cmd.add_argument("--strict", action="store_true",
                            help="Exit 1 si un manifeste de ce depot est invalide (porte CI).")

    status = sub.add_parser("status", help="Tableau de bord du pipeline.")
    status.add_argument("--json", action="store_true")

    scaffold_cmd = sub.add_parser("scaffold", help="Genere le plugin d'une etape planifiee.")
    scaffold_cmd.add_argument("stage")
    scaffold_cmd.add_argument("--force", action="store_true",
                              help="Ecrase un plugin existant.")

    knowledge = sub.add_parser(
        "knowledge",
        help="Savoir OKF des depots declares (knowledge-sources.json) : sommaire, "
             "recherche, lecture d'un concept.")
    knowledge.add_argument("action", choices=["index", "search", "get"])
    knowledge.add_argument("terms", nargs="*",
                           help="search : mots-cles ; get : <source>/<concept-id>.")
    knowledge.add_argument("--source", help="Restreindre a une source declaree.")
    knowledge.add_argument("--refresh", action="store_true",
                           help="Met a jour le cache local (git pull) avant de repondre.")
    knowledge.add_argument("--limit", type=int, default=40,
                           help="Plafond de lignes affichees (defaut : 40).")
    knowledge.add_argument("--json", action="store_true", help="Forme machine.")

    improve_cmd = sub.add_parser("improve", help="Diagnostic d'auto-amelioration (JSON).")
    improve_cmd.add_argument("--stage", help="Restreindre a une etape.")

    experiment_cmd = sub.add_parser(
        "experiment",
        help="Memoire de la boucle : correction appliquee au harnais, effet mesure "
             "sur les runs suivants.")
    experiment_cmd.add_argument("action", choices=["record", "effect"])
    experiment_cmd.add_argument("--stage",
                                help="Etape concernee (requis pour record ; filtre "
                                     "optionnel pour effect).")
    experiment_cmd.add_argument("--target",
                                help="Ce que la correction vise : " + ", ".join(TARGETS) + ".")
    experiment_cmd.add_argument("--file", help="Fichier du harnais corrige.")
    experiment_cmd.add_argument("--cause", help="Cause racine visee, en une phrase.")
    experiment_cmd.add_argument("--json", action="store_true",
                                help="JSON seul, sans resume humain.")

    ratchet_cmd = sub.add_parser(
        "ratchet",
        help="Fige et fait respecter les planchers de severite des checks.json (exit 2 si regression).")
    ratchet_cmd.add_argument("--reset", metavar="STAGE",
                             help="Repart du checks.json courant pour une etape (geste auteur).")

    sub.add_parser("watchdog",
                   help="Detecteurs de stagnation sur les journaux (exit 2 si halte).")
    sub.add_parser("watchdog-touched",
                   help="Mode hook PostToolUse du watchdog : diagnostic non bloquant.")

    check_okf = sub.add_parser("check-okf",
                               help="Conformance OKF v0.2 d'un bundle (exit 1 si non conforme).")
    check_okf.add_argument("dir", nargs="?",
                           help="Dossier racine du bundle (ex: knowledge, docs).")
    check_okf.add_argument("--touched", action="store_true",
                           help="Mode hook PostToolUse : gate les bundles OKF du projet.")
    check_okf.add_argument("--stop", action="store_true",
                           help="Mode hook Stop : refuse la cloture de session si un bundle "
                                "du projet est non conforme.")
    check_okf.add_argument("--file",
                           help="Chemin du fichier touche (mode --touched ; defaut : stdin du hook).")

    check_python = sub.add_parser("check-python",
                                  help="Compile tout Python d'un dossier (exit 1 si erreur de syntaxe).")
    check_python.add_argument("dir", nargs="?",
                              help="Dossier racine a parcourir (defaut : racine du projet courant).")
    check_python.add_argument("--touched", action="store_true",
                              help="Mode hook PostToolUse : compile le fichier .py ecrit, non bloquant.")
    check_python.add_argument("--file",
                              help="Chemin du fichier touche (mode --touched ; defaut : stdin du hook).")

    check_json = sub.add_parser("check-json",
                                help="Parse tout JSON d'un dossier (exit 1 si fichier invalide).")
    check_json.add_argument("dir", nargs="?",
                            help="Dossier racine a parcourir (defaut : racine du projet courant).")
    check_json.add_argument("--touched", action="store_true",
                            help="Mode hook PostToolUse : parse le fichier .json ecrit, non bloquant.")
    check_json.add_argument("--file",
                            help="Chemin du fichier touche (mode --touched ; defaut : stdin du hook).")
    test = sub.add_parser("test",
                          help="Suite de tests du moteur (unittest, stdlib).")
    test.add_argument("-k", dest="select", metavar="MOTIF",
                      help="Ne garde que les tests dont l'identifiant contient MOTIF.")
    test.add_argument("-v", "--verbose", action="store_true",
                      help="Un nom de test par ligne.")
    test.add_argument("--failfast", action="store_true",
                      help="S'arrete au premier echec.")

    coverage_cmd = sub.add_parser(
        "coverage",
        help="Ratchet de couverture : la couverture ne descend jamais (exit 2).")
    coverage_cmd.add_argument("--reset", action="store_true",
                              help="Rebase le plancher sur l'etat courant (geste humain).")
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
        "validate": cmd_validate, "score": cmd_score, "gate": cmd_gate,
        "agents": cmd_agents,
        "review-request": cmd_review_request, "status": cmd_status,
        "scaffold": cmd_scaffold, "improve": cmd_improve,
        "experiment": cmd_experiment,
        "knowledge": cmd_knowledge,
        "check-okf": cmd_check_okf, "check-python": cmd_check_python,
        "check-json": cmd_check_json, "ratchet": cmd_ratchet,
        "watchdog": cmd_watchdog, "watchdog-touched": cmd_watchdog_touched,
        "test": cmd_test, "coverage": cmd_coverage,
    }
    try:
        return handlers[args.command](root, args)
    except FileNotFoundError as exc:
        sys.stderr.write(f"Fichier introuvable : {exc}\n")
        return 1
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"JSON invalide : {exc}\n")
        return 1
