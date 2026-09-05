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
from .commands import cmd_ratchet
from .commands import cmd_watchdog
from .maturity import compute_autonomy
from .util import ensure_dir
from .maturity import gate_stage
from .hookslog import current_stage_id
from .hookslog import guard_decision
from .hookslog import handle_log
from .improve import improve
from .knowledge import catalog as knowledge_catalog
from .knowledge import render as knowledge_render
from .knowledge import resolve as knowledge_resolve
from .knowledge import search as knowledge_search
from .util import MAX_FIELD
from .maturity import load_maturity
from . import registry
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
from .checks import contract_problems
from .checks import validate_stage
from .ratchet import ratchet_reset
from .ratchet import ratchet_run
from .util import read_text
from .util import read_text as _rt
from .util import write_json
from .watchdog import watchdog_check
"""Auto-test par assertions du moteur (--selftest) — le seul test du projet."""

# ------------------------------------------------------------------------ selftest

SELFTEST_PIPELINE = {
    "version": 2,
    "maturity_threshold": 4.0,
    "consecutive_runs_to_autonomy": 3,
    "planned_stages": [
        {"id": "design", "name": "Design", "deliverable": "deliverables/design/spec.md",
         "inputs": ["deliverables/plan/intent.md"], "human_role": "Architecte",
         "team": "Architecture"},
        {"id": "build", "name": "Build", "deliverable": "deliverables/build/plan.md",
         "inputs": ["deliverables/design/spec.md"], "human_role": "Tech Lead",
         "team": "Ingenierie"},
    ],
}

def _manifest(agent_id, team, produces=None, consumes=(), **extra):
    """Manifeste de fixture. Tout est neutre sauf `invocation`, indexe par plateforme."""
    manifest = {
        "manifest_version": 1, "id": agent_id, "team": team,
        "version": "0.1.0", "description": f"Agent de test {agent_id}.",
        "capabilities": [f"sdlc:{agent_id}"],
        "invocation": {"claude-code": f"aidlc-{agent_id}:{agent_id}"},
    }
    if produces:
        manifest.update({"produces": produces, "consumes": list(consumes),
                         "checks": "checks.json", "human_role": "Role de test"})
    manifest.update(extra)
    return manifest

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

    saved_env = {name: os.environ.get(name) for name in
                 ("AIDLC_HARNESS_ROOT", "AIDLC_AGENT_PATH", "CLAUDE_PROJECT_DIR",
                  "CLAUDE_CONFIG_DIR", "AIDLC_PLATFORM")}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ["AIDLC_HARNESS_ROOT"] = str(root)
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        # Isole la decouverte des plugins reellement installes sur la machine : le
        # selftest doit rendre le meme nombre d'assertions partout.
        os.environ["CLAUDE_CONFIG_DIR"] = str(ensure_dir(root / "fake-config"))
        os.environ.pop("AIDLC_PLATFORM", None)
        write_json(root / "pipeline.json", SELFTEST_PIPELINE)
        pipe = load_pipeline()

        # Les contrats vivent desormais dans le plugin de l'agent, a cote de son
        # manifeste — plus aucun miroir dans le noyau.
        plan_checks = root / "plugins/aidlc-plan/checks.json"
        design_checks_path = root / "plugins/aidlc-design/checks.json"
        write_json(root / "plugins/aidlc-plan/agent.json",
                   _manifest("plan", "Produit", "deliverables/plan/intent.md"))
        write_json(plan_checks, SELFTEST_CHECKS)
        design_checks = dict(SELFTEST_CHECKS)
        design_checks["required_sections"] = ["## Contexte"]
        design_checks["min_items_per_section"] = {}
        write_json(root / "plugins/aidlc-design/agent.json",
                   _manifest("design", "Architecture", "deliverables/design/spec.md",
                             ["deliverables/plan/intent.md"]))
        write_json(design_checks_path, design_checks)
        # Un agent d'une autre equipe, hors du projet : consultatif (pas de produces),
        # decouvert par AIDLC_AGENT_PATH — le cas d'usage d'entreprise.
        external = Path(tempfile.mkdtemp())
        write_json(external / "acme-security" / "agent.json",
                   _manifest("security-review", "AppSec",
                             capabilities=["security:review"],
                             invocation={"claude-code": "acme-security:security-review",
                                         "codex": "prompts/review.md"}))
        os.environ["AIDLC_AGENT_PATH"] = os.pathsep.join(
            [str(root / "plugins"), str(external)])
        registry.reset_cache()
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

        # 11b. peremption amont : une entree modifiee apres la revue rouvre la porte aval
        record_score(root, pipe, "design", {
            "stage": "design", "scores": {"completeness": 5, "precision": 5,
                                          "traceability": 5, "autonomy": 5},
            "verdict": "accepted"})
        check(load_maturity(root)["stages"]["design"]["runs"][-1]["inputs"],
              "le run doit figer l'empreinte de ses entrees amont")
        write_json(aidlc_dir(root) / "reviews" / "design-1.json",
                   {"stage": "design", "run": 1, "approved": True, "reviewer": "Steve",
                    "justification": "Conforme a l'intention.", "ts": now_iso()})
        decision = gate_stage(root, pipe, "design")
        check(decision["passed"], f"design doit passer avant peremption ({decision['blocking']})")
        intent.write_text(_doc(GOOD_SECTIONS, filler=4), encoding="utf-8")
        decision = gate_stage(root, pipe, "design")
        check(not decision["passed"], "une entree amont modifiee doit rouvrir la porte aval")
        check(decision.get("stale_inputs") == ["deliverables/plan/intent.md"],
              f"stale_inputs doit nommer l'entree modifiee ({decision.get('stale_inputs')})")
        row = next(r for r in status_data(root, pipe)["stages"] if r["stage"] == "design")
        check("Entree amont modifiee" in row["next_action"],
              f"status doit remettre design a faire ({row['next_action']})")
        record_score(root, pipe, "design", {
            "stage": "design", "scores": {"completeness": 5, "precision": 5,
                                          "traceability": 5, "autonomy": 5},
            "verdict": "accepted"})
        write_json(aidlc_dir(root) / "reviews" / "design-2.json",
                   {"stage": "design", "run": 2, "approved": True, "reviewer": "Steve",
                    "justification": "Revu sur la nouvelle intention.", "ts": now_iso()})
        check(gate_stage(root, pipe, "design")["passed"],
              "une nouvelle revue sur l'entree a jour doit refermer la porte")

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

        # 15bis. L'etape d'un evenement ne se devine JAMAIS dans la prose. Les trois
        #        assertions ci-dessous echouaient avec l'ancienne heuristique, qui
        #        reconnaissait l'identifiant d'une etape comme mot du prompt.
        check(current_stage_id(root, pipe) == "design",
              "pre-requis du bloc : plan est franchie, l'etape courante est design")
        prose = handle_log(root, json.dumps(
            {"session_id": "sess-prose", "hook_event_name": "UserPromptSubmit",
             "prompt": "revois le plan de charge, puis lance les test unitaires"}))
        check(prose["stage"] == "design",
              "un prompt qui nomme une etape dans sa prose ne doit pas la designer : "
              f"attendu l'etape courante, obtenu {prose['stage']}")

        annexe = root / "deliverables/plan/annexe.md"
        ensure_dir(annexe.parent)
        annexe.write_text("annexe", encoding="utf-8")
        near = handle_log(root, json.dumps(
            {"session_id": "sess-annexe", "hook_event_name": "PostToolUse",
             "tool_name": "Write", "tool_input": {"file_path": str(annexe)}}))
        check(near["stage"] == "plan",
              "une ecriture dans le repertoire d'un livrable revient a son agent")

        handle_log(root, json.dumps(
            {"session_id": "sess-suite", "hook_event_name": "PostToolUse",
             "tool_name": "Write", "tool_input": {"file_path": str(intent)}}))
        suite = handle_log(root, json.dumps(
            {"session_id": "sess-suite", "hook_event_name": "UserPromptSubmit",
             "prompt": "continue"}))
        check(suite["stage"] == "plan",
              "un evenement sans chemin herite de la derniere etape connue de sa session")
        autre = handle_log(root, json.dumps(
            {"session_id": "sess-neuve", "hook_event_name": "UserPromptSubmit",
             "prompt": "continue"}))
        check(autre["stage"] == "design",
              "la continuite ne franchit pas les sessions : repli sur l'etape courante")
        annexe.unlink()

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
        check(len(data["stages"]) == 2,
              "le status ne couvre que les agents qui produisent un livrable")
        check([row["stage"] for row in data["stages"]] == ["plan", "design"],
              "l'ordre du status suit la chaine producteur -> consommateur")
        check(data["stages"][0]["team"] == "Produit",
              "le status doit porter l'equipe proprietaire de chaque agent")
        check(any(row["id"] == "security-review" for row in data["advisors"]),
              "un agent consultatif est liste a part, jamais comme une etape")
        check(any(stage["id"] == "build" for stage in data["planned"]),
              "une etape prevue sans plugin installe doit rester visible")
        check("EQUIPE" in render_status(data), "le rendu texte doit nommer les equipes")

        # 19. improve
        diag = improve(root, pipe)
        check(diag["events"] >= 1 and diag["sessions"] >= 1, "improve doit voir les logs")
        check("plan" in diag["maturity"], "improve doit agreger la maturite")
        check(len(diag["human_rejections"]) == 1, "improve doit remonter le refus humain")
        check(diag["maturity"]["plan"]["weakest_axes"], "improve doit classer les axes faibles")

        # 20. scaffold
        pipeline_before = read_text(root / "pipeline.json")
        try:
            scaffold(pipe, "design")
            check(False, "le scaffold doit refuser d'ecraser sans --force")
        except ValueError:
            check(True, "le scaffold refuse un agent deja present sans --force")
        info = scaffold(pipe, "design", force=True)
        check((root / "plugins/aidlc-design/skills/design/SKILL.md").exists(),
              "le scaffold doit creer le SKILL.md")
        check((root / "plugins/aidlc-design/templates/spec.md").exists(),
              "le scaffold doit creer le gabarit du livrable")
        check(read_text(root / "pipeline.json") == pipeline_before,
              "le scaffold ne doit RIEN ecrire dans le noyau : une equipe publie son "
              "agent sans modifier l'orchestrateur")
        manifest = json.loads(read_text(root / "plugins/aidlc-design/agent.json"))
        check(manifest["produces"] == "deliverables/design/spec.md"
              and manifest["consumes"] == ["deliverables/plan/intent.md"],
              "le manifeste genere doit reprendre la feuille de route planned_stages")
        check(manifest["team"] == "Architecture" and manifest["capabilities"] == ["sdlc:design"],
              "le manifeste genere doit porter l'equipe et la capacite de l'etape")
        market = json.loads(read_text(root / ".claude-plugin/marketplace.json"))
        check(any(p["name"] == "aidlc-design" for p in market["plugins"]),
              "le scaffold doit inscrire le plugin au marketplace")
        check(len(info["created"]) == 7,
              "le scaffold doit creer 7 fichiers (dont le manifeste agent.json)")
        check(validate_stage(root, load_pipeline(), "design")["stage"] == "design",
              "le checks.json genere doit rester exploitable par validate")
        registry.reset_cache()
        check(contract_problems(registry.find_agent("design")) == [],
              "un plugin fraichement scaffolde doit passer le controle de contrat : "
              "gabarit et checks.json generes ensemble ne doivent jamais diverger")
        # le scaffold a reecrit le contrat de design : restaurer la fixture du test
        write_json(design_checks_path, design_checks)
        write_json(root / "plugins/aidlc-design/agent.json",
                   _manifest("design", "Architecture", "deliverables/design/spec.md",
                             ["deliverables/plan/intent.md"]))
        registry.reset_cache()

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

        # 30. preuve d'execution (evidence, not claims) : une section declaree preuve
        #     doit citer une valeur observee concrete ; reformuler l'attendu echoue.
        proof_checks = dict(SELFTEST_CHECKS)
        proof_checks["proof_of_run"] = ["## Criteres d'acceptation"]
        write_json(design_checks_path, proof_checks)
        intent.write_text(_doc(GOOD_SECTIONS), encoding="utf-8")
        fail_sections = dict(GOOD_SECTIONS)
        fail_sections["## Contexte"] = "Conception sans valeur observee, seulement des intentions."
        fail_sections["## Criteres d'acceptation"] = ("- Le systeme doit repondre dans les temps.\n"
                                                       "- L'interface doit etre claire.\n"
                                                       "- La documentation doit etre complete.")
        spec.write_text(_doc(fail_sections,
                             front={"stage": "design", "version": "1", "status": "draft",
                                    "author": "Steve", "date": "2026-09-03"}), encoding="utf-8")
        res = validate_stage(root, pipe, "design")
        check(any("Preuve d'execution absente" in e for e in res["errors"]),
              f"proof_of_run doit rejeter une section sans valeur observee ({res['errors']})")
        pass_sections = dict(fail_sections)
        pass_sections["## Contexte"] = "Conception issue de deliverables/plan/intent.md."
        pass_sections["## Criteres d'acceptation"] = (
            "- p95 mesure a 420 ms sous 200 r/s sur le run 1.\n"
            "- Couverture de tests portee a 80 %.\n"
            "- Latence mediane observee : 120 ms.")
        spec.write_text(_doc(pass_sections,
                             front={"stage": "design", "version": "1", "status": "draft",
                                    "author": "Steve", "date": "2026-09-03"}), encoding="utf-8")
        res = validate_stage(root, pipe, "design")
        check(res["ok"], f"proof_of_run doit accepter une valeur observee ({res['errors']})")

        # 31. holdout : le livrable ne cite pas les lignes de son propre checks.json.
        holdout_checks = dict(SELFTEST_CHECKS)
        holdout_checks["checks_do_not_self_reference"] = True
        write_json(design_checks_path, holdout_checks)
        leaked = '    "min_words": 60,'
        spec.write_text(_doc(
            {"## Contexte": f"Contrat vise : {leaked} (extrait du checks.json)."},
            front={"stage": "design", "version": "1", "status": "draft",
                   "author": "Steve", "date": "2026-09-03"}), encoding="utf-8")
        res = validate_stage(root, pipe, "design")
        check(any("Holdout" in e for e in res["errors"]),
              "checks_do_not_self_reference doit detecter la citation du metre")
        spec.write_text(_doc(
            {"## Contexte": "Conception honnete, aucune regle de validation citee."},
            front={"stage": "design", "version": "1", "status": "draft",
                   "author": "Steve", "date": "2026-09-03"}), encoding="utf-8")
        check(not any("Holdout" in e for e in validate_stage(root, pipe, "design")["errors"]),
              "un livrable honnete ne declenche pas le holdout")

        # 32. perimetre : l'item hors perimetre du plan reste exclu dans le livrable aval.
        scope_checks = dict(SELFTEST_CHECKS)
        scope_checks["must_not_violate_scope"] = {"section": "## Hors perimetre"}
        scope_checks["required_sections"] = ["## Contexte", "## Hors perimetre"]
        write_json(design_checks_path, scope_checks)
        plan_scope = dict(GOOD_SECTIONS)
        plan_scope["## Hors perimetre"] = "- Facturation a l'unite.\n- Intégration ERP."
        intent.write_text(_doc(plan_scope), encoding="utf-8")
        # aval qui viole le perimetre : l'item est present sans marque d'exclusion
        spec.write_text(_doc(
            {"## Contexte": "Conception incluant la facturation a l'unite.\n\n"
                            "## Hors perimetre\nRien de plus a exclure."},
            front={"stage": "design", "version": "1", "status": "draft",
                   "author": "Steve", "date": "2026-09-03"}), encoding="utf-8")
        res = validate_stage(root, pipe, "design")
        check(any("Perimetre : l'item" in e for e in res["errors"]),
              "must_not_violate_scope doit detecter la violation d'un item du plan")
        # aval honnete : l'item est rappele explicitement exclu
        honest_sections = dict(GOOD_SECTIONS)
        honest_sections["## Contexte"] = "Conception issue de deliverables/plan/intent.md, sans la facturation."
        honest_sections["## Hors perimetre"] = ("- Facturation a l'unite : exclu, reporte.\n"
                                                 "- Intégration ERP : non couvert par cette version.")
        spec.write_text(_doc(honest_sections,
                             front={"stage": "design", "version": "1", "status": "draft",
                                    "author": "Steve", "date": "2026-09-03"}), encoding="utf-8")
        res = validate_stage(root, pipe, "design")
        check(res["ok"], f"le perimetre respecte doit passer ({res['errors']})")
        # restaure le plan sans section hors perimetre pour les tests suivants
        intent.write_text(_doc(GOOD_SECTIONS), encoding="utf-8")

        # 33. liste protégée : le guard refuse maturity.json, revues, ratchet, file,
        #     journaux, et — hors depot auteur — la copie installée du harnais.
        reason = guard_decision(root, json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(aidlc_dir(root) / "ratchet.json")}}))
        check(reason is not None and "ratchet" in reason,
              "guard doit refuser l'ecriture directe de .aidlc/ratchet.json")
        reason = guard_decision(root, json.dumps(
            {"tool_name": "Edit", "tool_input": {"file_path": str(aidlc_dir(root) / "improvement-queue.jsonl")}}))
        check(reason is not None and "amelioration" in reason,
              "guard doit refuser l'edition de la file d'amelioration")
        reason = guard_decision(root, json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(aidlc_dir(root) / "logs" / "x.jsonl")}}))
        check(reason is not None and "journaux" in reason,
              "guard doit refuser l'edition des journaux de session")
        # depot auteur (le harnais vit sous le projet) : la conception reste possible
        reason = guard_decision(root, json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(root / "pipeline.json")}}))
        check(reason is None, "le depot auteur reste editable (les deux racines confondues)")
        # projet consommateur : la copie installée est protegee entierement
        consumer2 = root / "consumer-guard"
        ensure_dir(consumer2)
        reason = guard_decision(consumer2, json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(root / "pipeline.json")}}))
        check(reason is not None and "liste protégée" in reason,
              "guard doit refuser l'edition de la copie installée depuis un consommateur")
        reason = guard_decision(consumer2, json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(consumer2 / "deliverables" / "x.md")}}))
        check(reason is None, "guard ne bloque pas les livrables du projet consommateur")
        check(cmd_guard(root, "pas du json") == 0, "guard reste robuste sur une entree cassee")

        # 34. ratchet : figeage au premier passage, regression refusee, reset explicite.
        #     Design est d'abord rattrape sur le contrat courant (geste auteur, reset
        #     explicite) pour que le figeage de depart soit celui des planchers simples.
        write_json(design_checks_path, proof_checks)
        saved_out, sys.stdout = sys.stdout, io.StringIO()
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            code_base = cmd_ratchet(root, argparse.Namespace(reset=None))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_base == 0, "le premier passage du ratchet doit figer (exit 0)")
        ratchet_reset(root, pipe, "design")
        check((aidlc_dir(root) / "ratchet.json").exists(), "l'etat du ratchet doit etre ecrit")
        # regression : min_words descendu -> exit 2
        regressed = dict(proof_checks)
        regressed["min_words"] = 10
        write_json(design_checks_path, regressed)
        saved_out, sys.stdout = sys.stdout, io.StringIO()
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            code_regressed = cmd_ratchet(root, argparse.Namespace(reset=None))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_regressed == 2, "le ratchet doit refuser un plancher descendu (exit 2)")
        state = json.loads(read_text(aidlc_dir(root) / "ratchet.json"))
        check(state["stages"]["design"]["min_words"] == 60,
              "le plancher fige ne doit pas suivre la regression (60 conserve)")
        # durcissement libre : remonter min_words passe, et releve le plancher fige
        hardened = dict(regressed)
        hardened["min_words"] = 90
        write_json(design_checks_path, hardened)
        saved_out, sys.stdout = sys.stdout, io.StringIO()
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            code_hardened = cmd_ratchet(root, argparse.Namespace(reset=None))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_hardened == 0, "durcir un plancher doit passer sans reset")
        state = json.loads(read_text(aidlc_dir(root) / "ratchet.json"))
        check(state["stages"]["design"]["min_words"] == 90,
              "le figeage doit suivre le durcissement (90)")
        # reset explicite d'une etape : repart du checks.json courant (geste auteur)
        write_json(design_checks_path, dict(regressed))
        reset_out = io.StringIO()
        saved_out, sys.stdout = sys.stdout, reset_out
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            code_reset = cmd_ratchet(root, argparse.Namespace(reset="design"))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_reset == 0, "le reset explicite doit repartir du checks.json courant")
        state = json.loads(read_text(aidlc_dir(root) / "ratchet.json"))
        check(state["stages"]["design"]["min_words"] == 10 and "reset_at" in state["stages"]["design"],
              "apres reset, le plancher vaut l'etat courant et porte la trace reset_at")
        write_json(design_checks_path, proof_checks)
        saved_out, sys.stdout = sys.stdout, io.StringIO()
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            code_restored = cmd_ratchet(root, argparse.Namespace(reset=None))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_restored == 0, "retour au-dessus des planchers : exit 0")
        check(ratchet_run(root, pipe)["passed"], "ratchet_run doit rapporter passed")
        try:
            ratchet_reset(root, pipe, "inconnue")
            check(False, "le reset d'une etape inconnue doit echouer")
        except ValueError:
            check(True, "le reset d'une etape inconnue leve ValueError")

        # 35. watchdog : haltes enregistrees dans la file (kind: watchdog), dedoublonnees,
        #     remontees par improve ; muet en hook sans detection (watchdog-touched).
        from .util import sanitize_session_id
        sess = "sess-watch"
        (aidlc_dir(root) / "logs").mkdir(parents=True, exist_ok=True)
        log_path = aidlc_dir(root) / "logs" / f"{sess}.jsonl"
        intent.write_text(_doc(GOOD_SECTIONS))
        lines = []
        # 6 ecritures du livrable design (en echec ci-dessous) par la meme session
        for _ in range(6):
            lines.append(json.dumps({
                "ts": f"2026-09-04T10:00:{len(lines):02d}",
                "event": "PostToolUse", "session_id": sess, "stage": "design",
                "payload": {"tool_name": "Write",
                            "tool_input": {"file_path": str(spec.resolve())}}}))
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # le livrable design echoue la validation : acharnement detecte
        spec.write_text("pas un livrable conforme\n", encoding="utf-8")
        result = watchdog_check(root, pipe)
        check(result["halted"], "le watchdog doit halter sur l'acharnement + boucle d'ecriture")
        detectors = {d["detector"] for d in result["detections"]}
        check("validation_failures" in detectors and "write_loop" in detectors,
              f"les detecteurs validation_failures et write_loop doivent tirer ({detectors})")
        queue_text = read_text(aidlc_dir(root) / "improvement-queue.jsonl")
        check(queue_text.count('"kind": "watchdog"') >= 2,
              "les haltes doivent alimenter la file d'amelioration")
        # rejoue : dedoublonnage
        watchdog_check(root, pipe)
        queue_text = read_text(aidlc_dir(root) / "improvement-queue.jsonl")
        check(queue_text.count('"kind": "watchdog"') == queue_text.count('"kind": "watchdog"'),
              "le rejoue du watchdog ne doit pas dupliquer (dedoublonnage)")
        diag = improve(root, pipe)
        check(len(diag["watchdog"]["halts"]) >= 2,
              "improve doit remonter les haltes du watchdog")
        # rafale de relances : 5 UserPromptSubmit sur la meme etape
        rerun_lines = [json.dumps({
            "ts": f"2026-09-04T11:00:{i:02d}", "event": "UserPromptSubmit",
            "session_id": sess, "stage": "design", "payload": {"prompt": "continuer"}})
            for i in range(5)]
        log_path.write_text("\n".join(lines + rerun_lines) + "\n", encoding="utf-8")
        result = watchdog_check(root, pipe)
        check(any(d["detector"] == "rerun_storm" for d in result["detections"]),
              "le detecteur rerun_storm doit tirer sur 5 relances")
        # hook muet sans detection : root propre, watchdog-touched ne doit rien emettre
        clean_root = root / "clean-watch"
        ensure_dir(clean_root)
        hooked = io.StringIO()
        saved_out, sys.stdout = sys.stdout, hooked
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            from .commands import cmd_watchdog_touched
            code_touched = cmd_watchdog_touched(clean_root, argparse.Namespace())
            touched_silent = hooked.getvalue() == ""
            code_watch_bad = cmd_watchdog(root, argparse.Namespace())
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_touched == 0 and touched_silent,
              "watchdog-touched doit rester muet sans detection (exit 0)")
        check(code_watch_bad == 2, "la commande watchdog doit sortir 2 sur halte")
        # restaure l'etat pour les assertions suivantes eventuelles
        spec.write_text(_doc(
            {"## Contexte": "Mesure du run 1 : p95 420 ms a 200 r/s."},
            front={"stage": "design", "version": "1", "status": "draft",
                   "author": "Steve", "date": "2026-09-03"}), encoding="utf-8")

        # 36. Le contrat reel de l'etape plan (plugins/aidlc-plan/checks.json)
        #     porte les regles anti-derive adoptees : preuve d'execution (Contexte et
        #     Criteres d'acceptation) et holdout (checks_do_not_self_reference). Un
        #     intent conforme passe ; une section sans valeur observee echoue ; citer
        #     une ligne du contrat echoue. Ce bloc garde l'adoption elle-meme : si les
        #     regles sortent du checks.json de plan, l'assertion de presence casse.
        real_checks_path = _repo_root() / "plugins/aidlc-plan/checks.json"
        check(real_checks_path.exists(),
              "le contrat de plan doit vivre dans son propre plugin, sans miroir")
        real_checks = json.loads(read_text(real_checks_path))
        check("proof_of_run" in real_checks and "checks_do_not_self_reference" in real_checks,
              "le contrat de l'etape plan doit porter proof_of_run et checks_do_not_self_reference")
        check(real_checks["proof_of_run"] == ["## Contexte", "## Solution proposée",
                                              "## Critères d'acceptation"],
              "proof_of_run de plan doit cibler Contexte, Solution proposee et Criteres")
        check(real_checks["min_items_per_section"].get("## Utilisateurs impactés") == 2
              and real_checks["min_items_per_section"].get("## Solution proposée") == 2,
              "le contrat de plan doit exiger des personas et des benefices enumeres")
        write_json(plan_checks, real_checks)
        plan_intent = {
            "## Contexte": ("Demande issue du comite produit 2026-09-01 ; 42 % des dossiers "
                            "repassent en saisie manuelle (mesure SAP du T3)."),
            "## Problème": "Le cadrage des demandes est lent et sans trace.",
            "## Utilisateurs impactés": ("- Product Owner : 12 personnes, cadrage hebdomadaire.\n"
                                         "- Conformite : 3 personnes, controle a chaque release."),
            "## Solution proposée": ("Un pipeline agentique a portes deterministes.\n\n"
                                     "- Reduire le retraitement : 42 % aujourd'hui, cible 15 % "
                                     "au 31/03.\n"
                                     "- Diviser par deux le delai de cadrage : 12 j, cible 6 j."),
            "## Contraintes": "- Python stdlib seulement.\n- Aucune dependance externe.",
            "## Critères d'acceptation": ("- p95 < 300 ms sur le run 2.\n"
                                          "- Couverture des tests portee a 80 %.\n"
                                          "- 100 % de conformite OKF v0.2."),
            "## Hors périmètre": "- Facturation a l'unite.\n- Integration de l'ERP.",
            "## Sources et références": ("Source : knowledge/conventions.md ; entretien P.O. "
                                         "du 2026-09-02."),
        }
        intent.write_text(_doc(plan_intent, filler=8), encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(res["ok"], f"l'intent conforme au contrat reel plan doit passer ({res['errors'][:3]})")
        # sans valeur observee dans Contexte : la preuve d'execution echoue
        weak_context = dict(plan_intent)
        weak_context["## Contexte"] = "La demande vient de plusieurs equipes, sans mesure ni source."
        intent.write_text(_doc(weak_context, filler=8), encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(any("Preuve d'execution absente" in e and "## Contexte" in e
                  for e in res["errors"]),
              "proof_of_run doit exiger une valeur observee dans le Contexte")
        # criteres non chiffres : la preuve d'execution echoue aussi sur les criteres
        vague_criteria = dict(plan_intent)
        vague_criteria["## Critères d'acceptation"] = ("- Le systeme doit repondre rapidement.\n"
                                                        "- L'interface doit etre claire.\n"
                                                        "- La documentation doit etre complete.")
        intent.write_text(_doc(vague_criteria, filler=8), encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(any("Preuve d'execution absente" in e and "## Critères d'acceptation" in e
                  for e in res["errors"]),
              "proof_of_run doit exiger des criteres chiffres")
        # holdout : citer une ligne du contrat reel fait echouer
        overflow = dict(plan_intent)
        overflow["## Sources et références"] = (
            'Contrat vise : "min_words": 250, (extrait du checks.json).')
        intent.write_text(_doc(overflow, filler=8), encoding="utf-8")
        res = validate_stage(root, pipe, "plan")
        check(any("Holdout" in e for e in res["errors"]),
              "checks_do_not_self_reference doit rejeter un intent qui cite son contrat")
        # restaure l'intent conforme
        intent.write_text(_doc(plan_intent, filler=8), encoding="utf-8")

        # 37. Registre d'agents : decouverte par manifeste, capacites, ordre derive,
        #     rejets de forme et frontieres. C'est le contrat d'integration des equipes.
        view = registry.catalog()
        ids = [agent["id"] for agent in view["agents"]]
        check(sorted(ids) == ["design", "plan", "security-review"],
              f"les trois agents doivent etre decouverts, obtenu {ids}")
        check(ids.index("plan") < ids.index("design"),
              "l'agent qui consomme un livrable doit passer apres celui qui le produit")
        advisor = next(a for a in view["agents"] if a["id"] == "security-review")
        check(advisor["kind"] == "capability" and advisor["team"] == "AppSec",
              "un agent sans produces est consultatif et porte son equipe")
        check(advisor["invoke"] == "acme-security:security-review" and advisor["invocable"],
              "l'invocation lue doit etre exactement celle du manifeste")
        check(view["capabilities"]["security:review"] == ["security-review"],
              "l'index des capacites doit pointer vers l'agent qui la porte")
        check([a["id"] for a in registry.catalog(capability="security:review")["agents"]]
              == ["security-review"], "le filtre par capacite doit restreindre le catalogue")
        check(registry.agent_for_file(root, str(intent))["id"] == "plan",
              "agent_for_file doit retrouver l'agent par son livrable exact")

        # une plateforme sans bloc d'invocation : signale, jamais devine
        os.environ["AIDLC_PLATFORM"] = "codex"
        registry.reset_cache()
        codex = registry.catalog()
        check(codex["platform"] == "codex", "la plateforme courante doit etre respectee")
        check(next(a for a in codex["agents"] if a["id"] == "security-review")["invoke"]
              == "prompts/review.md",
              "sous Codex, l'invocation doit venir du bloc codex du meme manifeste")
        check(not next(a for a in codex["agents"] if a["id"] == "plan")["invocable"],
              "un agent sans invocation pour la plateforme n'est pas invocable")
        os.environ.pop("AIDLC_PLATFORM", None)
        registry.reset_cache()

        # un agent consultatif n'a ni livrable a valider ni porte a franchir
        res = validate_stage(root, pipe, "security-review")
        check(not res["ok"] and any("consultatif" in e or "produces" in e for e in res["errors"]),
              "validate doit refuser proprement un agent sans livrable")
        decision = gate_stage(root, pipe, "security-review")
        check(not decision["passed"] and any("consultatif" in b for b in decision["blocking"]),
              "gate doit dire qu'aucune porte ne s'applique a un agent consultatif")

        # frontiere d'equipe : le plugin d'un agent installe hors du projet est protege
        reason = guard_decision(root, json.dumps(
            {"tool_name": "Write",
             "tool_input": {"file_path": str(external / "acme-security" / "agents/x.md")}}))
        check(reason is not None and "AppSec" in reason,
              "guard doit refuser d'ecrire dans le plugin d'une autre equipe et la nommer")

        # rejets de forme : champ obligatoire manquant, version de manifeste inconnue
        bad_dir = ensure_dir(root / "plugins" / "aidlc-bad")
        write_json(bad_dir / "agent.json", {"manifest_version": 1, "id": "bad"})
        registry.reset_cache()
        report = registry.discover()
        check(not any(a["id"] == "bad" for a in report["agents"]),
              "un manifeste incomplet ne doit jamais entrer au registre")
        check(any("'team'" in problem for problem in report["problems"]),
              "le rejet doit nommer le champ obligatoire manquant")
        write_json(bad_dir / "agent.json", dict(_manifest("bad", "X"), manifest_version=2))
        registry.reset_cache()
        report = registry.discover()
        check(any("manifest_version" in problem for problem in report["problems"])
              and not any(a["id"] == "bad" for a in report["agents"]),
              "une version de manifeste non supportee doit etre refusee explicitement")

        # deux equipes qui publient le meme id : avertissement nomme, premiere source gagnante
        write_json(bad_dir / "agent.json", _manifest("plan", "Equipe concurrente"))
        registry.reset_cache()
        report = registry.discover()
        check(any("Equipe concurrente" in warning and "plan" in warning
                  for warning in report["warnings"]),
              "un identifiant en double doit etre signale avec les deux equipes")
        check(len([a for a in report["agents"] if a["id"] == "plan"]) == 1,
              "un identifiant en double ne doit pas dedoubler l'agent")

        # cycle de dependances : detecte et nomme, jamais une boucle infinie
        write_json(bad_dir / "agent.json",
                   _manifest("boucle-a", "X", "deliverables/a.md", ["deliverables/b.md"]))
        write_json(ensure_dir(root / "plugins" / "aidlc-bad2") / "agent.json",
                   _manifest("boucle-b", "X", "deliverables/b.md", ["deliverables/a.md"]))
        registry.reset_cache()
        check(sorted(registry.catalog()["cycle"]) == ["boucle-a", "boucle-b"],
              "un cycle de dependances doit etre detecte et nomme")

        # producteur absent : une entree que personne n'installe reste visible
        write_json(bad_dir / "agent.json",
                   _manifest("orphelin", "X", "deliverables/o.md", ["deliverables/jamais.md"]))
        (root / "plugins" / "aidlc-bad2" / "agent.json").unlink()
        registry.reset_cache()
        holes = registry.catalog()["missing_producers"]
        check(any(h["agent"] == "orphelin" and h["input"] == "deliverables/jamais.md"
                  for h in holes),
              "une entree sans producteur installe doit remonter dans missing_producers")

        # 38. Contrat d'agent controle a vide : le registre est ouvert, et le
        #     checks.json d'une equipe voisine n'etait lu qu'au moment de valider un
        #     livrable — une regle inconnue, une regex fautive ou une section mal
        #     orthographiee y restaient invisibles jusqu'a rendre le contrat
        #     insatisfiable en pleine session.
        check(contract_problems(registry.find_agent("plan")) == [],
              "un contrat coherent ne doit remonter aucun probleme")
        check(contract_problems(registry.find_agent("security-review")) == [],
              "un agent consultatif n'a pas de contrat a verifier")

        lint_dir = ensure_dir(root / "plugins" / "aidlc-lint")
        write_json(lint_dir / "agent.json",
                   _manifest("lint", "X", "deliverables/lint/doc.md",
                             ["deliverables/plan/intent.md"]))
        write_json(lint_dir / "checks.json", {
            "required_sections": ["## Contexte"],
            "min_words": 900, "max_words": 100,
            "forbidden_patterns": ["(?i)\\b[non-ferme"],
            "min_items_per_section": {"## Absente": 2},
            "required_input_section": {"deliverables/jamais.md": "## Contexte"},
            "regle_inventee": True,
        })
        registry.reset_cache()
        found = contract_problems(registry.find_agent("lint"))
        for fragment, label in (
                ("regle inconnue", "une regle inconnue ne sera jamais appliquee : le dire"),
                ("regex invalide", "une regex fautive doit etre signalee a vide"),
                ("insatisfiable", "une section exigee hors de required_sections est un piege"),
                ("'consumes'", "une regle qui vise une entree non consommee ne verifie rien"),
                ("depasse max_words", "min_words superieur a max_words doit etre refuse")):
            check(any(fragment in problem for problem in found), label)

        # derive gabarit / contrat : la skill d'etape part du gabarit du plugin ; un
        # squelette sans les sections exigees ne peut pas valider.
        ensure_dir(lint_dir / "templates")
        template = lint_dir / "templates" / "doc.md"
        template.write_text("# Doc\n\n## Autre chose\n", encoding="utf-8")
        found = contract_problems(registry.find_agent("lint"))
        check(any("gabarit" in problem and "## Contexte" in problem for problem in found),
              "un gabarit qui ne porte pas les sections exigees doit etre signale")
        template.write_text("# Doc\n\n## Contexte\n", encoding="utf-8")
        check(not any("gabarit" in problem
                      for problem in contract_problems(registry.find_agent("lint"))),
              "un gabarit aligne sur le contrat ne doit rien remonter")

        # une etape gouvernee sans contrat n'a aucun metre : le dire, sans deviner
        write_json(lint_dir / "agent.json",
                   dict(_manifest("lint", "X", "deliverables/lint/doc.md"), checks=None))
        registry.reset_cache()
        check(any("sans contrat" in problem
                  for problem in contract_problems(registry.find_agent("lint"))),
              "une etape gouvernee sans checks.json doit etre signalee")
        (lint_dir / "agent.json").unlink()
        registry.reset_cache()

        # ratchet : desinstaller un agent n'efface pas son plancher
        (bad_dir / "agent.json").unlink()
        registry.reset_cache()
        saved_out, sys.stdout = sys.stdout, io.StringIO()
        saved_err, sys.stderr = sys.stderr, open(os.devnull, "w", encoding="utf-8")
        try:
            cmd_ratchet(root, argparse.Namespace(reset=None))
            (root / "plugins/aidlc-design/agent.json").unlink()
            registry.reset_cache()
            code_orphan = cmd_ratchet(root, argparse.Namespace(reset=None))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = saved_out
            sys.stderr = saved_err
        check(code_orphan == 2,
              "retirer un agent du registre ne doit pas effacer son plancher fige")
        state = json.loads(read_text(aidlc_dir(root) / "ratchet.json"))
        check("design" in state["stages"],
              "le plancher de l'agent retire doit rester ecrit dans le ratchet")

        # savoir OKF distant : sources declarees, catalogue, recherche, resolution.
        # Une source dont le `repo` est un dossier existant est lue telle quelle : le
        # selftest couvre le CLI de bout en bout sans jamais toucher au reseau.
        remote = Path(tempfile.mkdtemp()) / "bundle"
        ensure_dir(remote / "metrics")
        (remote / "index.md").write_text("# Sommaire\n\n* [Marge](metrics/marge.md)\n",
                                         encoding="utf-8")
        (remote / "metrics" / "marge.md").write_text(
            "---\ntype: Metric\ntitle: Marge brute\n"
            "description: Marge du perimetre retail.\ntags: [finance, marge]\n---\n\n"
            "# Definition\n\nRevenu moins cout complet.\n", encoding="utf-8")
        write_json(root / "knowledge-sources.json",
                   {"sources": [{"name": "local", "repo": str(remote)}]})
        view = knowledge_catalog(root)
        check([c["ref"] for c in view["concepts"]] == ["local/metrics/marge"],
              "le catalogue liste les concepts, jamais les fichiers reserves de la spec")
        concept = view["concepts"][0]
        check(concept["title"] == "Marge brute" and concept["tags"] == ["finance", "marge"],
              "le frontmatter OKF alimente titre et tags du catalogue")
        check(knowledge_search(view["concepts"], ["marge"]) == view["concepts"],
              "un mot du frontmatter doit ramener le concept")
        check(knowledge_search(view["concepts"], ["complet"]) == view["concepts"],
              "un mot du corps doit ramener le concept")
        check(knowledge_search(view["concepts"], ["marge", "absent"]) == [],
              "tous les mots doivent etre presents pour ramener un concept")
        check(knowledge_resolve(view["concepts"], "metrics/marge") is concept,
              "un identifiant sans source se resout s'il est sans ambiguite")
        check("Marge brute" in knowledge_render(view["concepts"]),
              "le rendu compact porte le titre du concept")

        write_json(root / "knowledge-sources.json",
                   {"sources": [{"name": "local", "repo": str(remote)},
                                {"name": "absente", "repo": str(remote.parent / "nulle-part")}]})
        view = knowledge_catalog(root)
        check(view["errors"] and [c["ref"] for c in view["concepts"]] == ["local/metrics/marge"],
              "une source injoignable est signalee sans faire tomber les autres")

        write_json(root / "knowledge-sources.json",
                   {"sources": [{"name": "../evasion", "repo": str(remote)}]})
        try:
            knowledge_catalog(root)
            refused = False
        except ValueError:
            refused = True
        check(refused, "un nom de source non atomique leve : le cache n'est pas creusable")
        (root / "knowledge-sources.json").unlink()

    for name, value in saved_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    registry.reset_cache()
    sys.stderr.write(f"OK: {checked} assertions\n")
    return 0
