from __future__ import annotations

import json
import select
import sys

from .okf import PROJECT_OKF_BUNDLES
from pathlib import Path
from .util import emit
from .maturity import gate_stage
from .hookslog import guard_decision
from .hookslog import handle_log
from .hookslog import journal_bundle_write
from .improve import improve
from .util import load_pipeline
from .util import now_iso
from .okf import okf_report
from .maturity import enqueue_improvement
from .util import read_text
from .util import sanitize_session_id
from .maturity import record_score
from .maturity import render_status
from .maturity import review_request
from .checks import run_checks
from .scaffold import scaffold
from .checks import stage_for_file
from .maturity import status_data
from .checks import validate_stage
"""Gestionnaires de sous-commandes : mode ligne de commande et modes hooks (--touched, --stop, payloads stdin)."""

# ------------------------------------------------------------------- sous-commandes

def _read_hook_payload() -> dict:
    """JSON du hook sur stdin, sans jamais bloquer hors contexte de hook.

    # ponytail: select avec court delai pour ne pas figer le script quand stdin est un
    # pipe ouvert sans donnee (auto-test, ligne de commande). En vrai hook, les donnees
    # sont presentes et la lecture aboutit. Plafond : delai de 0.2s quand rien n'arrive.
    """
    if sys.stdin.isatty():
        return {}
    try:
        ready, _, _ = select.select([sys.stdin], [], [], 0.2)
        if not ready:
            return {}
    except Exception:
        pass  # select indisponible : on tente la lecture directe, qui aboutit en hook
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _hook_input(args) -> tuple:
    """(fichier touche, session_id, tool_name) des modes hook --touched et --stop.
    --file dispense du payload ; sinon le JSON stdin du hook est lu une seule fois et
    tool_input.file_path, session_id et tool_name en sont tires — les deux modes
    partagent ce contrat (validate --touched, check-okf --touched/--stop).
    """
    if getattr(args, "file", None):
        return args.file, None, None
    payload = _read_hook_payload()
    touched = (payload.get("tool_input") or {}).get("file_path")
    session_id = payload.get("session_id")
    return (touched or None), (sanitize_session_id(session_id) if session_id else None), \
        payload.get("tool_name")


def _hook_context(message: str) -> None:
    """Contexte additionnel d'un hook PostToolUse : retour informatif, jamais bloquant."""
    emit({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                 "additionalContext": message}})


def cmd_log(root: Path, raw: str) -> int:
    # Un hook qui casse la session est pire que pas de log. (# ponytail: silence total)
    try:
        handle_log(root, raw)
    except Exception:
        pass
    return 0


def cmd_guard(root: Path, raw: str) -> int:
    try:
        reason = guard_decision(root, raw)
        if reason:
            emit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }})
    except Exception:
        pass
    return 0


def cmd_validate(root: Path, args) -> int:
    try:
        pipe = load_pipeline()
    except Exception as exc:
        if args.touched:
            return 0
        sys.stderr.write(f"pipeline.json illisible : {exc}\n")
        return 1

    if args.touched:
        # Appele comme hook PostToolUse : sans --file, le chemin est lu dans le JSON du hook
        # sur stdin. Evite un pipe `jq | xargs` (dependance externe + casse sur les chemins
        # contenant un espace). (# ponytail: pas de parsing de hook plus riche tant qu'un
        # seul champ est utile)
        touched, _, _ = _hook_input(args)
        if not touched:
            return 0
        stage = stage_for_file(root, pipe, touched)
        if stage is None:
            return 0
        result = run_checks(root, stage, Path(touched).resolve())
        if result["ok"]:
            context = (f"Validation AI-DLC '{stage['id']}' : OK "
                       f"({result['checks_run']} regles).")
        else:
            context = ("Validation AI-DLC '{}' EN ECHEC ({} erreur(s)) :\n- {}\n"
                       "Corriger avant de rendre le livrable.").format(
                stage["id"], len(result["errors"]), "\n- ".join(result["errors"]))
        _hook_context(context)
        return 0

    if not args.stage:
        sys.stderr.write("usage : aidlc.py validate <stage> [--file PATH] [--json]\n")
        return 1
    result = validate_stage(root, pipe, args.stage, args.file)
    emit(result)
    if not args.json:
        for message in result["errors"]:
            sys.stderr.write(f"  [erreur] {message}\n")
        for message in result["warnings"]:
            sys.stderr.write(f"  [avertissement] {message}\n")
    return 0 if result["ok"] else 1


def cmd_score(root: Path, args) -> int:
    pipe = load_pipeline()
    review = json.loads(read_text(Path(args.file)))
    stage_id = args.stage
    if review.get("stage") and review["stage"] != stage_id:
        sys.stderr.write(
            f"Attention : la revue porte sur '{review['stage']}', argument '{stage_id}'.\n")
    try:
        record = record_score(root, pipe, stage_id, review)
    except ValueError as exc:
        sys.stderr.write(f"Revue invalide : {exc}\n")
        return 1
    emit(record)
    return 0


def cmd_gate(root: Path, args) -> int:
    decision = gate_stage(root, load_pipeline(), args.stage)
    emit(decision)
    if not decision["passed"]:
        for message in decision["blocking"]:
            sys.stderr.write(f"  [bloquant] {message}\n")
    return 0 if decision["passed"] else 2


def cmd_review_request(root: Path, args) -> int:
    try:
        emit(review_request(root, load_pipeline(), args.stage))
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


def cmd_status(root: Path, args) -> int:
    data = status_data(root, load_pipeline())
    if args.json:
        emit(data)
    else:
        sys.stdout.write(render_status(data) + "\n")
    return 0


def cmd_scaffold(root: Path, args) -> int:
    try:
        emit(scaffold(load_pipeline(), args.stage, args.force))
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


def cmd_improve(root: Path, args) -> int:
    emit(improve(root, load_pipeline(), args.stage))
    return 0


def cmd_check_okf(root: Path, args) -> int:
    """Verifie la conformance OKF v0.2 d'un bundle (docs/, knowledge/, ou un dossier
    consommateur). JSON sur stdout ; messages humains sur stderr ; exit 1 si non conforme.

    --touched = mode hook PostToolUse : gate les bundles OKF du projet (knowledge/, et
    docs/ quand il existe) touches par l'ecriture. Non bloquant, retour 0 dans tous les
    cas : le resultat remonte en contexte additionnel, comme validate --touched.

    --stop = mode hook Stop : la cloture de session est la porte dure du bundle. Bundle
    conforme (ou absent) : silence, la session se ferme. Bundle non conforme : refus
    d'arret (permissionDecision deny) avec la liste des problemes, retour 0 — la decision
    passe par le JSON du hook, jamais par un code de sortie.
    """
    if getattr(args, "stop", False):
        bad_bundles = []
        for name in PROJECT_OKF_BUNDLES:
            bundle = (root / name).resolve()
            if not bundle.is_dir():
                continue
            report = okf_report(bundle)
            if not report["ok"]:
                bad_bundles.append((name, report))
        if not bad_bundles:
            return 0
        # Chaque refus est enregistre dans .aidlc/improvement-queue.jsonl (kind
        # okf_stop) avec la session concernee : c'est la matiere premiere du diagnostic
        # improve, qui correle et propose le correctif de frontmatter.
        session_id = _hook_input(args)[1]
        for name, report in bad_bundles:
            files = sorted({message.split(" : ", 1)[0] for message in report["errors"]})
            enqueue_improvement(root, {"kind": "okf_stop", "ts": now_iso(),
                                       "session_id": session_id, "bundle": name,
                                       "files": files, "errors": report["errors"]},
                                ("session_id", "bundle", "files"))
        problems = []
        for name, report in bad_bundles:
            problems.append("{}/ ({} probleme(s)) :\n- {}".format(
                name, len(report["errors"]), "\n- ".join(report["errors"])))
        reason = ("Arret refuse : la base de connaissance n'est pas conforme OKF v0.2.\n"
                  + "\n".join(problems)
                  + "\nCorriger puis redemander l'arret de la session.")
        emit({"hookSpecificOutput": {"hookEventName": "Stop",
                                     "permissionDecision": "deny",
                                     "permissionDecisionReason": reason}})
        return 0
    if args.touched:
        # Le payload stdin n'est lu qu'une fois : le chemin touche sert au controle, la
        # session sert a journaliser l'ecriture fautive pour la correlation d'improve.
        touched, session_id, tool_name = _hook_input(args)
        if not touched:
            return 0
        try:
            target = Path(touched).resolve()
        except OSError:
            return 0
        for name in PROJECT_OKF_BUNDLES:
            bundle = (root / name).resolve()
            if not bundle.is_dir():
                continue
            try:
                target.relative_to(bundle)
            except ValueError:
                continue
            report = okf_report(bundle)
            if report["ok"]:
                context = (f"Conformite OKF v0.2 de {name}/ : OK "
                           f"({report['checked']} fichier(s)).")
            else:
                # Le bundle est non conforme : l'ecriture a laisse un fichier fautif — on
                # journalise la session qui l'a ecrite (une fois par session et fichier).
                context = ("Conformite OKF v0.2 de {}/ NON CONFORME ({} probleme(s)) :\n"
                           "- {}\nCorriger (frontmatter, sommaire, journal) avant de "
                           "rendre.").format(name, len(report["errors"]),
                                            "\n- ".join(report["errors"]))
                journal_bundle_write(root, session_id, target, tool_name)
            _hook_context(context)
        return 0

    if not args.dir:
        sys.stderr.write("usage : aidlc.py check-okf <dir> | --touched | --stop\n")
        return 1
    bundle = Path(args.dir).expanduser().resolve()
    if not bundle.is_dir():
        sys.stderr.write(f"Bundle introuvable : {args.dir}\n")
        return 1
    report = okf_report(bundle)
    emit(report)
    if report["ok"]:
        sys.stderr.write(f"Conformite OKF v0.2 : {bundle} ({report['checked']} fichier(s)).\n")
    else:
        sys.stderr.write(f"Bundle non conforme ({len(report['errors'])} probleme(s)) :\n")
        for message in report["errors"]:
            sys.stderr.write(f"  [okf] {message}\n")
    return 0 if report["ok"] else 1
