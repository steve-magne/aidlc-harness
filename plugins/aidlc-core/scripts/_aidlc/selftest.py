from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tempfile

from .okf import OKF_RESERVED
from pathlib import Path
from .okf import _INDEX_LINK
from .okf import _frontmatter_shape_problems
from .syntax import json_report
from .syntax import python_report
from .util import aidlc_dir
from .commands import cmd_check_json
from .commands import cmd_check_okf
from .commands import cmd_check_python
from .commands import cmd_guard
from .commands import cmd_log
from .maturity import compute_autonomy
from .util import ensure_dir
from .maturity import gate_stage
from .hookslog import guard_decision
from .hookslog import handle_log
from .improve import improve
from .util import MAX_FIELD
from .maturity import load_maturity
from .util import load_pipeline
from .maturity import maturity_path
from .util import now_iso
from .okf import okf_bundle_errors
from .okf import okf_report
from .okf import okf_split_frontmatter
from .util import read_text
from .maturity import record_score
from .maturity import render_status
from .maturity import review_request
from .scaffold import scaffold
from .maturity import status_data
from .checks import validate_stage
from .util import write_json
"""Auto-test par assertions du moteur (--selftest) — le seul test du projet."""

# ------------------------------------------------------------------------ selftest

SELFTEST_PIPELINE = {
    "version": 1,
    "maturity_threshold": 4.0,
    "consecutive_runs_to_autonomy": 3,
    "stages": [
        {"id": "plan", "name": "Plan", "plugin": "aidlc-plan", "skill": "aidlc-plan:plan",
         "deliverable": "deliverables/plan/intent.md", "inputs": [],
         "checks": "checks/plan.json",
         "human_role": "Product Owner", "status": "implemented"},
        {"id": "design", "name": "Design", "plugin": "aidlc-design", "skill": "aidlc-design:design",
         "deliverable": "deliverables/design/spec.md",
         "inputs": ["deliverables/plan/intent.md"],
         "checks": "checks/design.json",
         "human_role": "Architecte", "status": "planned"},
    ],
}

SELFTEST_CHECKS = {
    "required_frontmatter": ["stage", "version", "status", "author", "date"],
    "required_sections": ["## Contexte", "## Probleme", "## Criteres d'acceptation"],
    "min_words": 60,
    "forbidden_patterns": ["TODO", "TBD"],
    "must_reference_inputs": True,
    "min_items_per_section": {"## Criteres d'acceptation": 3},
}

FILLER = ("Le harness orchestre les etapes du cycle de vie logiciel et journalise chaque "
          "session agentique afin de mesurer la maturite des livrables produits par les "
          "agents et par les humains qui les relisent avec attention et methode. ")


def _doc(sections: dict, front: dict = None, filler: int = 3) -> str:
    front = front or {"stage": "plan", "version": "1", "status": "draft",
                      "author": "Steve", "date": "2026-09-03"}
    out = ["---"] + [f"{k}: {v}" for k, v in front.items()] + ["---", ""]
    for title, body in sections.items():
        out += [title, body, ""]
    out.append(FILLER * filler)
    return "\n".join(out)


GOOD_SECTIONS = {
    "## Contexte": "Le contexte du besoin metier est decrit ici de facon detaillee.",
    "## Probleme": "Le probleme est la lenteur du cycle de livraison actuel.",
    "## Criteres d'acceptation": "- Critere un mesurable.\n- Critere deux mesurable.\n"
                                "- Critere trois mesurable.",
}


def _repo_root() -> Path:
    """Racine du depot qui porte les bundles dogfood (knowledge/, docs/) : montee depuis
    ce paquet (comme harness_root), jamais depuis le repertoire courant — le selftest
    doit rendre le meme nombre d'assertions d'ou qu'on le lance."""
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "knowledge" / "index.md").exists():
            return candidate
    return here.parent


def selftest() -> int:
    checked = 0

    def check(condition, label):
        nonlocal checked
        assert condition, f"ECHEC : {label}"
        checked += 1

    saved_harness = os.environ.get("AIDLC_HARNESS_ROOT")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ["AIDLC_HARNESS_ROOT"] = str(root)
        write_json(root / "pipeline.json", SELFTEST_PIPELINE)
        pipe = load_pipeline()
        write_json(root / "checks/plan.json", SELFTEST_CHECKS)
        design_checks = dict(SELFTEST_CHECKS)
        design_checks["required_sections"] = ["## Contexte"]
        design_checks["min_items_per_section"] = {}
        write_json(root / "checks/design.json", design_checks)
        # un dossier plugins/aidlc-design existant simule une etape deja ebauchee :
        # le scaffold doit refuser de l'ecraser sans --force.
        ensure_dir(root / "plugins" / "aidlc-design")
        intent = root / "deliverables/plan/intent.md"
        ensure_dir(intent.parent)

        # 1. section manquante
        sections = dict(GOOD_SECTIONS)
        sections.pop("## Probleme")
        intent.write_text(_doc(sections), encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(not res["ok"], "une section manquante doit invalider")
        check(any("## Probleme" in e for e in res["errors"]), "l'erreur doit nommer la section")

        # 2. mot interdit
        bad = dict(GOOD_SECTIONS)
        bad["## Probleme"] = "Probleme a preciser, TODO plus tard."
        intent.write_text(_doc(bad), encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(not res["ok"] and any("interdit" in e for e in res["errors"]),
              "un motif interdit doit invalider")

        # 3. frontmatter incomplet
        intent.write_text(_doc(GOOD_SECTIONS, front={"stage": "plan", "version": "1"}),
                          encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(any("Frontmatter" in e for e in res["errors"]),
              "un frontmatter incomplet doit invalider")

        # 4. items insuffisants
        few = dict(GOOD_SECTIONS)
        few["## Criteres d'acceptation"] = "- Un seul critere."
        intent.write_text(_doc(few), encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(any("minimum 3" in e for e in res["errors"]),
              "min_items_per_section doit compter les puces")

        # 5. trop court
        intent.write_text(_doc(GOOD_SECTIONS, filler=0), encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(any("trop court" in e for e in res["errors"]), "min_words doit invalider")

        # 6. livrable conforme
        intent.write_text(_doc(GOOD_SECTIONS), encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(res["ok"], f"le livrable conforme doit passer ({res['errors']})")
        check(res["checks_run"] >= 5, "toutes les regles declarees doivent etre comptees")

        # 7. input non reference
        spec = root / "deliverables/design/spec.md"
        ensure_dir(spec.parent)
        spec.write_text(_doc({"## Contexte": "Un contexte sans citation d'amont."},
                             front={"stage": "design", "version": "1", "status": "draft",
                                    "author": "Steve", "date": "2026-09-03"}), encoding="utf-8")
        res = validate_stage(root, pipe, "design")
        check(any("Input non reference" in e for e in res["errors"]),
              "must_reference_inputs doit detecter l'absence de citation")
        spec.write_text(_doc({"## Contexte": "Contexte issu de deliverables/plan/intent.md."},
                             front={"stage": "design", "version": "1", "status": "draft",
                                    "author": "Steve", "date": "2026-09-03"}), encoding="utf-8")
        check(validate_stage(root, pipe, "design")["ok"],
              "citer l'input doit lever l'erreur de tracabilite")

        # 8. fichier absent / etape inconnue
        check(not validate_stage(root, pipe, "inconnue")["ok"], "une etape inconnue est invalide")

        # 9. score : moyenne recalculee, valeur fournie ignoree
        record = record_score(root, pipe, "plan", {
            "stage": "plan", "scores": {"completeness": 4, "precision": 4,
                                        "traceability": 5, "autonomy": 3},
            "overall": 1.0, "verdict": "accepted"})
        check(record["overall"] == 4.0, f"overall doit valoir 4.0, obtenu {record['overall']}")
        check(record["run"] == 1, "le premier run doit etre numerote 1")
        check(maturity_path(root).exists(), "maturity.json doit etre ecrit")

        # 10. gate bloque sans revue humaine
        decision = gate_stage(root, pipe, "plan")
        check(not decision["passed"], "gate doit bloquer sans revue humaine")
        check(decision["human_review_required"], "la revue humaine doit etre requise")
        check(any("Revue humaine requise" in b for b in decision["blocking"]),
              "le blocage doit nommer la revue humaine manquante")
        check(decision["next_stage"] == "design", "next_stage doit suivre l'ordre du pipeline")

        # 11. gate passe avec revue approuvee
        write_json(aidlc_dir(root) / "reviews" / "plan-1.json",
                   {"stage": "plan", "run": 1, "approved": True, "reviewer": "Steve",
                    "justification": "Conforme au besoin.", "ts": now_iso()})
        decision = gate_stage(root, pipe, "plan")
        check(decision["passed"], f"gate doit passer ({decision['blocking']})")

        # 12. refus humain -> file d'amelioration
        record_score(root, pipe, "plan", {
            "stage": "plan", "scores": {"completeness": 5, "precision": 5,
                                        "traceability": 5, "autonomy": 5},
            "verdict": "accepted"})
        write_json(aidlc_dir(root) / "reviews" / "plan-2.json",
                   {"stage": "plan", "run": 2, "approved": False, "reviewer": "Steve",
                    "justification": "Criteres non chiffres.", "ts": now_iso()})
        decision = gate_stage(root, pipe, "plan")
        check(not decision["passed"], "un refus humain doit bloquer")
        queue = read_text(aidlc_dir(root) / "improvement-queue.jsonl")
        check("Criteres non chiffres." in queue, "la justification doit alimenter la file")
        gate_stage(root, pipe, "plan")
        queue = read_text(aidlc_dir(root) / "improvement-queue.jsonl")
        check(len(queue.strip().splitlines()) == 1, "pas de doublon dans la file")

        # 13. score sous le seuil
        record_score(root, pipe, "plan", {
            "stage": "plan", "scores": {"completeness": 2, "precision": 2,
                                        "traceability": 2, "autonomy": 2}})
        maturity = load_maturity(root)
        last = maturity["stages"]["plan"]["runs"][-1]
        check(last["overall"] == 2.0 and last["verdict"] == "rejected",
              "un score sous le seuil doit produire un verdict rejected")

        # 14. autonomie
        check(not compute_autonomy(root, pipe, "plan", load_maturity(root)),
              "l'autonomie ne doit pas etre acquise avec un run refuse")

        # 15. log ne casse jamais
        entry = handle_log(root, json.dumps(
            {"session_id": "abc/../123", "hook_event_name": "PostToolUse",
             "tool_name": "Write", "tool_input": {"file_path": str(intent), "content": "x" * 5000},
             "cwd": str(root)}))
        check(entry["session_id"] == "abc____123", "le session_id doit etre assaini")
        check(entry["stage"] == "plan", "le stage doit etre devine depuis le chemin")
        check(len(entry["payload"]["tool_input"]["content"]) <= MAX_FIELD + 20,
              "les gros champs doivent etre tronques")
        for payload in ["", "pas du json {{{", json.dumps([1, 2, 3]), json.dumps({"a": 1})]:
            check(cmd_log(root, payload) == 0, f"log doit sortir 0 sur : {payload[:20]!r}")

        # 16. guard
        reason = guard_decision(root, json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(maturity_path(root))}}))
        check(reason is not None, "guard doit refuser l'ecriture de maturity.json")
        reason = guard_decision(root, json.dumps(
            {"tool_name": "Edit",
             "tool_input": {"file_path": str(aidlc_dir(root) / "reviews" / "plan-1.json")}}))
        check(reason is not None, "guard doit refuser l'edition d'une revue humaine")
        reason = guard_decision(root, json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(intent)}}))
        check(reason is None, "guard doit laisser passer un livrable normal")
        check(cmd_guard(root, "pas du json") == 0, "guard doit sortir 0 sur une entree cassee")

        # 17. review-request (instructions humaines mises de cote pendant le test)
        saved_stderr, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            request = review_request(root, pipe, "plan")
        finally:
            sys.stderr.close()
            sys.stderr = saved_stderr
        check((root / request["template"]).exists(), "le gabarit de revue doit etre ecrit")

        # 18. status
        data = status_data(root, pipe)
        check(len(data["stages"]) == 2, "le status doit couvrir les 2 etapes")
        check(data["stages"][1]["next_action"].startswith("Scaffolder"),
              "une etape non implementee doit proposer le scaffold")
        check("ETAPE" in render_status(data), "le rendu texte doit contenir l'en-tete")

        # 19. improve
        diag = improve(root, pipe)
        check(diag["events"] >= 1 and diag["sessions"] >= 1, "improve doit voir les logs")
        check("plan" in diag["maturity"], "improve doit agreger la maturite")
        check(len(diag["human_rejections"]) == 1, "improve doit remonter le refus humain")
        check(diag["maturity"]["plan"]["weakest_axes"], "improve doit classer les axes faibles")

        # 20. scaffold
        try:
            scaffold(pipe, "design")
            check(False, "le scaffold doit refuser d'ecraser sans --force")
        except ValueError:
            check(True, "le scaffold refuse d'ecraser un dossier existant sans --force")
        info = scaffold(pipe, "design", force=True)
        check((root / "plugins/aidlc-design/skills/design/SKILL.md").exists(),
              "le scaffold doit creer le SKILL.md")
        check((root / "plugins/aidlc-design/templates/spec.md").exists(),
              "le scaffold doit creer le gabarit du livrable")
        check(load_pipeline()["stages"][1]["status"] == "implemented",
              "le scaffold doit passer l'etape en implemented")
        market = json.loads(read_text(root / ".claude-plugin/marketplace.json"))
        check(any(p["name"] == "aidlc-design" for p in market["plugins"]),
              "le scaffold doit inscrire le plugin au marketplace")
        check(len(info["created"]) == 7, "le scaffold doit creer 7 fichiers (dont le miroir checks/)")
        check(validate_stage(root, load_pipeline(), "design")["stage"] == "design",
              "le checks.json genere doit rester exploitable par validate")
        mirror = root / "checks/design.json"
        check(mirror.exists() and read_text(mirror) == read_text(root / "plugins/aidlc-design/checks.json"),
              "le miroir checks/design.json doit refleter le checks.json genere")

        # 21. conformance OKF v0.2 des bundles de connaissance du depot (docs/, knowledge/),
        #     ancres sur la racine du depot (au-dessus du paquet). Quand le paquet est
        #     installe sans bundle a cote (consommateur), le test reste muet.
        for bundle_name in ("knowledge", "docs"):
            bundle = _repo_root() / bundle_name
            if not (bundle / "index.md").exists():
                continue
            errors = okf_bundle_errors(bundle)
            check(not errors, f"conformance OKF v0.2 de {bundle_name}/ : {errors[:3]}")

        # 22. sous-commande check-okf : gate un bundle arbitraire (ex. le knowledge/ d'un
        #     projet consommateur), JSON sur stdout, exit 1 si non conforme
        kb = root / "kb"
        ensure_dir(kb)
        (kb / "index.md").write_text(
            "---\nokf_version: \"0.2\"\n---\n# KB\n* [Concept](concept.md) - conforme.\n",
            encoding="utf-8")
        (kb / "concept.md").write_text(
            "---\ntype: Reference\ntitle: Concept\ngenerated: { by: process:selftest, at: 2026-09-04T00:00:00Z }\n"
            "---\n# Concept\nCorps du concept.\n", encoding="utf-8")
        saved_out, sys.stdout = sys.stdout, open(os.devnull, "w", encoding="utf-8")
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            code_ok = cmd_check_okf(root, argparse.Namespace(dir=str(kb), touched=False))
            (kb / "orphelin.md").write_text("# Sans frontmatter\n", encoding="utf-8")
            code_bad = cmd_check_okf(root, argparse.Namespace(dir=str(kb), touched=False))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_ok == 0, "check-okf doit accepter un bundle conforme")
        check(code_bad == 1, "check-okf doit refuser un concept sans frontmatter")
        report = okf_report(kb)
        check(report["ok"] is False and any("orphelin.md" in e for e in report["errors"]),
              "le rapport check-okf doit nommer le fichier fautif")

        # 23. check-okf --touched : mode hook PostToolUse. Une ecriture hors bundle est
        #     muette ; une ecriture dans knowledge/ conforme renvoie un contexte OK ; un
        #     concept non conforme est signale en contexte, sans casser la session (exit 0).
        know = root / "knowledge"
        ensure_dir(know)
        (know / "index.md").write_text(
            "---\nokf_version: \"0.2\"\n---\n# KB\n* [Concept](concept.md) - conforme.\n",
            encoding="utf-8")
        (know / "concept.md").write_text(
            "---\ntype: Reference\ntitle: Concept\n---\n# Concept\nCorps du concept.\n",
            encoding="utf-8")
        hook_out = io.StringIO()
        saved_out, sys.stdout = sys.stdout, hook_out
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            code_hook = cmd_check_okf(root, argparse.Namespace(
                touched=True, file=str(root / "README.md"), dir=None))
            silent = hook_out.getvalue() == ""
            (know / "sans-frontmatter.md").write_text("# Orphelin\n", encoding="utf-8")
            code_bad_hook = cmd_check_okf(root, argparse.Namespace(
                touched=True, file=str(know / "sans-frontmatter.md"), dir=None))
            feedback = hook_out.getvalue()
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_hook == 0 and silent,
              "check-okf --touched doit rester muet hors d'un bundle du projet")
        check(code_bad_hook == 0 and "sans-frontmatter.md" in feedback,
              "check-okf --touched doit signaler le fichier fautif en contexte, sans casser "
              "la session (exit 0)")

        # 24. check-okf --stop : hook Stop — la cloture de session est la porte dure du
        #     bundle. Conforme ou absent : silence (arret autorise). Non conforme : refus
        #     d'arret (deny) nommant le fichier fautif, sans casser le hook (exit 0).
        consumer = root / "consumer"
        ensure_dir(consumer / "knowledge")
        (consumer / "knowledge/index.md").write_text(
            "---\nokf_version: \"0.2\"\n---\n# KB\n* [Concept](concept.md) - conforme.\n",
            encoding="utf-8")
        (consumer / "knowledge/concept.md").write_text(
            "---\ntype: Reference\ntitle: Concept\n---\n# Concept\nCorps du concept.\n",
            encoding="utf-8")
        bare = root / "bare"  # projet sans bundle : l'arret n'est jamais bloque
        ensure_dir(bare)
        stop_out = io.StringIO()
        saved_out, sys.stdout = sys.stdout, stop_out
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            code_stop_ok = cmd_check_okf(consumer, argparse.Namespace(
                stop=True, touched=False, file=None, dir=None))
            ok_silent = stop_out.getvalue() == ""
            code_stop_bare = cmd_check_okf(bare, argparse.Namespace(
                stop=True, touched=False, file=None, dir=None))
            bare_silent = stop_out.getvalue() == ""
            (consumer / "knowledge/sans-frontmatter.md").write_text(
                "# Orphelin\n", encoding="utf-8")
            code_stop_bad = cmd_check_okf(consumer, argparse.Namespace(
                stop=True, touched=False, file=None, dir=None))
            decision = json.loads(stop_out.getvalue())
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_stop_ok == 0 and ok_silent,
              "check-okf --stop doit laisser fermer une session au bundle conforme")
        check(code_stop_bare == 0 and bare_silent,
              "check-okf --stop doit rester muet sans bundle dans le projet")
        check(code_stop_bad == 0
              and decision["hookSpecificOutput"]["hookEventName"] == "Stop"
              and decision["hookSpecificOutput"]["permissionDecision"] == "deny"
              and "sans-frontmatter.md" in decision["hookSpecificOutput"]
              ["permissionDecisionReason"],
              "check-okf --stop doit refuser l'arret d'une session au bundle non conforme "
              "(deny nommant le fichier fautif), sans casser le hook (exit 0)")

        # 25. le refus du gate Stop alimente la file d'amelioration ; improve le correle
        #     aux sessions et propose un correctif de frontmatter deterministe.
        queue_path = aidlc_dir(consumer) / "improvement-queue.jsonl"
        queue_text = read_text(queue_path)
        check(queue_text.count("okf_stop") == 1,
              "un refus Stop doit alimenter la file d'amelioration une fois")
        # la session redemande l'arret (elle est bloquee) : pas de doublon dans la file
        saved_out, sys.stdout = sys.stdout, io.StringIO()
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            cmd_check_okf(consumer, argparse.Namespace(
                stop=True, touched=False, file=None, dir=None))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        queue_text = read_text(queue_path)
        check(queue_text.count("okf_stop") == 1,
              "un --stop rejoue ne doit pas doublonner dans la file")
        diag = improve(consumer, load_pipeline())
        check(len(diag["okf"]["refusals"]) == 1,
              "improve doit remonter le refus du gate OKF")
        check(diag["human_rejections"] == [],
              "le refus OKF ne doit pas etre compte comme refus humain")
        fixes = [p for p in diag["okf"]["proposals"]
                 if p["file"] == "sans-frontmatter.md"]
        check(fixes and fixes[0]["edits"] and fixes[0]["preview"][0] == "---",
              "improve doit proposer un correctif de frontmatter (add), avec apercu")
        # appliquee telle quelle, la proposition rend le concept conforme
        target = consumer / "knowledge" / "sans-frontmatter.md"
        repaired = read_text(target).splitlines()
        for edit in sorted(fixes[0]["edits"], key=lambda e: -e["at"]):
            repaired[edit["at"]:edit["at"]] = edit["insert"].rstrip("\n").split("\n")
        front, _, state3 = okf_split_frontmatter("\n".join(repaired))
        check(state3 == "ferme" and re.search(r"(?m)^type\s*:\s*\S", front)
              and not _frontmatter_shape_problems(front),
              "le correctif propose doit rendre le concept conforme")

        # 26. le sommaire index.md (fichier reserve) recoit les concepts orphelins
        idx = [p for p in diag["okf"]["proposals"] if p["kind"] == "index_entries"]
        check(idx and "sans-frontmatter.md" in idx[0]["problem"],
              "improve doit proposer les concepts orphelins au sommaire index.md")
        idx_lines = read_text(consumer / "knowledge/index.md").splitlines()
        for edit in sorted(idx[0]["edits"], key=lambda e: -e["at"]):
            idx_lines[edit["at"]:edit["at"]] = edit["insert"].rstrip("\n").split("\n")
        concepts = sorted(str(p.relative_to(consumer / "knowledge"))
                          for p in (consumer / "knowledge").rglob("*.md")
                          if p.name not in OKF_RESERVED)
        listed = set()
        for line in idx_lines:
            m = _INDEX_LINK.match(line)
            if m:
                listed.add(m.group(1).split("#", 1)[0])
        check(all(rel in listed for rel in concepts),
              "appliquee, la proposition index.md ne laisse aucun orphelin")

        # 27. le hook --touched journalise l'ecriture fautive (PostToolUse + session) :
        #     la correlation d'improve retrouve la session reelle, pas seulement les
        #     evenements de cycle de vie. Dedupe : une meme session et un meme fichier
        #     ne produisent qu'une seule entree.
        payload = json.dumps({"session_id": "sess-ecrivain",
                              "hook_event_name": "PostToolUse", "tool_name": "Write",
                              "tool_input": {"file_path": str(
                                  consumer / "knowledge/sans-frontmatter.md")}})
        saved_stdin = sys.stdin
        hook_out2 = io.StringIO()
        saved_out, sys.stdout = sys.stdout, hook_out2
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            # la session re-ecrit le meme fichier deux fois : une seule entree attendue
            for _ in range(2):
                sys.stdin = io.StringIO(payload)
                code_journal = cmd_check_okf(consumer, argparse.Namespace(
                    stop=False, touched=True, file=None, dir=None))
        finally:
            sys.stdin = saved_stdin
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        writer_log = read_text(aidlc_dir(consumer) / "logs" / "sess-ecrivain.jsonl")
        check(code_journal == 0 and writer_log.count("PostToolUse") == 1
              and "sans-frontmatter.md" in writer_log,
              "le hook --touched doit journaliser une fois l'ecriture fautive")
        diag_j = improve(consumer, load_pipeline())
        implicated = diag_j["okf"]["refusals"][0]["implicated"]
        check(any(i["session_id"] == "sess-ecrivain"
                  and i["file"] == "sans-frontmatter.md" for i in implicated),
              "improve doit relier le refus du gate a la session journalisee par --touched")

        # 28. check-python / check-json : portes d'hygiene syntaxique du depot (regle 6 :
        #     tout Python compile, tout JSON parse). Le bac a sable contient deja des
        #     .py/.json conformes (pipeline, checks, marketplace, revues) : la passe
        #     accepte l'etat courant, refuse un fichier casse en le nommant, et un dossier
        #     propre passe meme quand le depot voisin est casse (portee restreinte).
        (root / "good.py").write_text("x = 1\n", encoding="utf-8")
        (root / "good.json").write_text('{"a": 1}\n', encoding="utf-8")
        clean = root / "clean"
        ensure_dir(clean)
        (clean / "ok.py").write_text("y = 2\n", encoding="utf-8")
        (clean / "ok.json").write_text('{"b": 2}\n', encoding="utf-8")
        saved_out, sys.stdout = sys.stdout, open(os.devnull, "w", encoding="utf-8")
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            py_ok = cmd_check_python(root, argparse.Namespace(dir=None))
            json_ok = cmd_check_json(root, argparse.Namespace(dir=None))
            scoped_ok = cmd_check_python(root, argparse.Namespace(dir=str(clean)))
            scoped_json = cmd_check_json(root, argparse.Namespace(dir=str(clean)))
            (root / "broken.py").write_text("def casse(:\n", encoding="utf-8")
            (root / "broken.json").write_text('{"a": }\n', encoding="utf-8")
            py_bad = cmd_check_python(root, argparse.Namespace(dir=None))
            json_bad = cmd_check_json(root, argparse.Namespace(dir=None))
            missing = cmd_check_python(root, argparse.Namespace(dir="absent"))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(py_ok == 0, "check-python doit accepter un dossier dont tout Python compile")
        check(json_ok == 0, "check-json doit accepter un dossier dont tout JSON parse")
        check(scoped_ok == 0 and scoped_json == 0,
              "check-python/check-json doivent ignorer le reste du depot hors du dossier donne")
        check(py_bad == 1, "check-python doit sortir en 1 sur une erreur de syntaxe")
        check(json_bad == 1, "check-json doit sortir en 1 sur un JSON invalide")
        check(missing == 1, "check-python doit sortir en 1 sur un dossier introuvable")
        py_report = python_report(root)
        check(not py_report["ok"]
              and any("broken.py" in e for e in py_report["errors"]),
              "le rapport check-python doit nommer le fichier fautif")
        syntax_json = json_report(root)
        check(not syntax_json["ok"]
              and any("broken.json" in e for e in syntax_json["errors"]),
              "le rapport check-json doit nommer le fichier fautif")
        check(python_report(clean)["ok"] and json_report(clean)["ok"],
              "un dossier propre doit rester conforme, meme dans un depot casse")

        # 29. check-python/check-json --touched : mode hook PostToolUse — la passe
        #     controle le fichier ecrit et lui seul (la syntaxe est sans etat
        #     cross-fichier). Hors de l'extension concernee : muette. .py/.json
        #     conformes : retour OK en contexte. Fautifs : retour NON CONFORME nommant
        #     le probleme, sans casser la session (exit 0) et sans scanner le depot.
        touched = root / "touched"
        ensure_dir(touched)
        (touched / "ok.py").write_text("z = 3\n", encoding="utf-8")
        (touched / "ok.json").write_text('{"c": 3}\n', encoding="utf-8")
        hook_out3 = io.StringIO()
        saved_out, sys.stdout = sys.stdout, hook_out3
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            silent_md = cmd_check_python(root, argparse.Namespace(
                touched=True, file=str(root / "note.md"), dir=None))
            md_silent = hook_out3.getvalue() == ""
            silent_wrong = cmd_check_json(root, argparse.Namespace(
                touched=True, file=str(touched / "ok.py"), dir=None))
            wrong_silent = hook_out3.getvalue() == ""
            good_py = cmd_check_python(root, argparse.Namespace(
                touched=True, file=str(touched / "ok.py"), dir=None))
            good_py_ctx = hook_out3.getvalue()
            good_json = cmd_check_json(root, argparse.Namespace(
                touched=True, file=str(touched / "ok.json"), dir=None))
            good_json_ctx = hook_out3.getvalue()
            bad_py = cmd_check_python(root, argparse.Namespace(
                touched=True, file=str(root / "broken.py"), dir=None))
            bad_py_ctx = hook_out3.getvalue()
            bad_json = cmd_check_json(root, argparse.Namespace(
                touched=True, file=str(root / "broken.json"), dir=None))
            bad_json_ctx = hook_out3.getvalue()
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(silent_md == 0 and md_silent,
              "check-python --touched doit rester muet hors d'une ecriture .py")
        check(silent_wrong == 0 and wrong_silent,
              "check-json --touched doit rester muet sur une ecriture .py")
        check(good_py == 0 and "ok.py" in good_py_ctx and "compile" in good_py_ctx,
              "check-python --touched doit confirmer un .py conforme en contexte")
        check(good_json == 0 and "ok.json" in good_json_ctx and "parse" in good_json_ctx,
              "check-json --touched doit confirmer un .json conforme en contexte")
        check(bad_py == 0 and "NON CONFORME" in bad_py_ctx
              and "broken.py" in bad_py_ctx and "erreur de syntaxe" in bad_py_ctx,
              "check-python --touched doit signaler le .py fautif sans casser la session")
        check(bad_json == 0 and "NON CONFORME" in bad_json_ctx
              and "broken.json" in bad_json_ctx and "JSON invalide" in bad_json_ctx,
              "check-json --touched doit signaler le .json fautif sans casser la session")
        check("broken.py" not in good_py_ctx and "clean/ok.py" not in good_py_ctx,
              "le controle --touched doit etre limite au fichier ecrit, sans scan du depot")

    if saved_harness is None:
        os.environ.pop("AIDLC_HARNESS_ROOT", None)
    else:
        os.environ["AIDLC_HARNESS_ROOT"] = saved_harness
    sys.stderr.write(f"OK: {checked} assertions\n")
    return 0
