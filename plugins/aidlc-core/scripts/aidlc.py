#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aidlc.py — moteur deterministe du harness AI-DLC.

Un seul fichier, stdlib uniquement. Toute la logique non-agentique du harness vit ici :
journalisation des sessions, validation declarative des livrables, notation de maturite,
franchissement d'etape, demande de revue humaine, tableau de bord, scaffolding d'une
nouvelle etape et diagnostic d'auto-amelioration.

Sorties machine : JSON sur stdout. Messages humains : stderr.
Sous-commandes : log, guard, validate, score, gate, review-request, status, scaffold,
improve, plus --selftest.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

AXES = ["completeness", "precision", "traceability", "autonomy"]
MAX_FIELD = 2000
# ponytail: liste blanche des cles de payload journalisees. Plafond : un hook exotique
# perd ses champs specifiques. Upgrade : journaliser l'entree entiere tronquee.
PAYLOAD_KEYS = [
    "hook_event_name", "tool_name", "tool_input", "tool_response", "prompt",
    "source", "message", "reason", "trigger", "stop_hook_active", "permission_mode",
]
DENIED_WRITE = ["maturity.json", "reviews"]


# --------------------------------------------------------------------------- socle

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def workspace_root() -> Path:
    """Racine du projet consommateur : la ou habitent deliverables/ et .aidlc/.

    = CLAUDE_PROJECT_DIR quand le script est appele depuis une session Claude Code
    (hook ou skill), sinon le repertoire courant. Le depot du harnais n'est plus le
    lieu des livrables : ils sont produits dans le projet qui consomme les plugins aidlc.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    return Path.cwd().resolve()


def harness_root() -> Path:
    """Racine du harnais installe : la ou vivent pipeline.json et checks/<stage>.json.

    Resolution, dans l'ordre :
      1. AIDLC_HARNESS_ROOT (test, ou usage explicite) ;
      2. CLAUDE_PLUGIN_ROOT, si un pipeline.json s'y trouve (hooks et skills du plugin) ;
      3. auto-localisation du script : pipeline.json monte a cote de scripts/, meme forme
         dans le depot auteur (plugins/aidlc-core/) et dans la copie installee par
         Claude Code (CLAUDE_PLUGIN_ROOT pointe le plugin) ;
      4. repli : le repertoire du script.
    """
    env = os.environ.get("AIDLC_HARNESS_ROOT")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root and (Path(plugin_root) / "pipeline.json").exists():
        return Path(plugin_root).resolve()
    here = Path(__file__).resolve().parent  # .../aidlc-core/scripts
    for candidate in (here, here.parent, *here.parent.parents):
        if (candidate / "pipeline.json").exists():
            return candidate
    return here.parent


def load_pipeline() -> dict:
    return json.loads((harness_root() / "pipeline.json").read_text(encoding="utf-8"))


def find_stage(pipe: dict, stage_id: str):
    for stage in pipe.get("stages", []):
        if stage.get("id") == stage_id:
            return stage
    return None


def next_stage_id(pipe: dict, stage_id: str):
    ids = [s.get("id") for s in pipe.get("stages", [])]
    if stage_id in ids:
        pos = ids.index(stage_id) + 1
        if pos < len(ids):
            return ids[pos]
    return None


def aidlc_dir(root: Path) -> Path:
    return root / ".aidlc"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_json(path: Path, data) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def emit(data) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def truncate(value, limit: int = MAX_FIELD):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + " ...[tronque]"
    if isinstance(value, dict):
        return {k: truncate(v, limit) for k, v in list(value.items())[:50]}
    if isinstance(value, list):
        return [truncate(v, limit) for v in value[:50]]
    return value


# ------------------------------------------------------------------ frontmatter/md

def split_frontmatter(text: str):
    """Retourne (frontmatter, corps). Parseur de blocs `--- cle: valeur ---` ligne a ligne.

    # ponytail: on ne parse pas du vrai YAML (pas de dependance, stdlib only). Plafond :
    listes/imbrications ignorees, seules les cles de premier niveau sont vues.
    Upgrade : passer a un vrai parseur si les frontmatters se complexifient.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    front = {}
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            body = "\n".join(lines[index + 1:])
            return front, body
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", lines[index])
        if match:
            front[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return front, text


def heading_level(line: str) -> int:
    match = re.match(r"^(#{1,6})\s", line)
    return len(match.group(1)) if match else 0


def section_body(text: str, title: str) -> str:
    """Corps d'une section markdown : du titre exact jusqu'au prochain titre de niveau <=."""
    lines = text.splitlines()
    wanted = title.strip()
    level = heading_level(wanted) or 2
    collected, inside = [], False
    for line in lines:
        if inside:
            current = heading_level(line)
            if current and current <= level:
                break
            collected.append(line)
        elif line.strip() == wanted:
            inside = True
    return "\n".join(collected)


BULLET_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+\S")


def count_items(block: str) -> int:
    return sum(1 for line in block.splitlines() if BULLET_RE.match(line))


# --------------------------------------------------------------------- validation

KNOWN_RULES = {
    "required_frontmatter", "required_sections", "min_words", "max_words",
    "forbidden_patterns", "required_patterns", "must_reference_inputs",
    "min_items_per_section",
}


def run_checks(root: Path, stage: dict, file_path: Path) -> dict:
    """Applique le checks.json de l'etape au livrable. Ne leve pas : tout finit en erreur."""
    result = {
        "stage": stage.get("id"),
        "file": os.path.relpath(file_path, root),
        "ok": False,
        "errors": [],
        "warnings": [],
        "checks_run": 0,
    }
    if not file_path.exists():
        result["errors"].append(f"Livrable absent : {result['file']}")
        return result

    checks_rel = stage.get("checks")
    if not checks_rel:
        result["warnings"].append("Aucun fichier de checks declare pour cette etape.")
        result["ok"] = True
        return result
    # Le checks.json vit dans le harnais (a cote du pipeline.json), pas dans le projet.
    checks_path = harness_root() / checks_rel
    if not checks_path.exists():
        # ponytail: repli si le miroir checks/<stage>.json est absent (depot auteur sans
        # symlink) : chercher le checks.json dans le plugin de l'etape, voisin du noyau.
        plugin_name = stage.get("plugin")
        candidate = harness_root().parent / f"{plugin_name}/checks.json" if plugin_name else None
        if candidate and candidate.exists():
            checks_path = candidate
    if not checks_path.exists():
        result["errors"].append(f"Fichier de checks introuvable : {checks_rel}")
        return result
    try:
        checks = json.loads(read_text(checks_path))
    except json.JSONDecodeError as exc:
        result["errors"].append(f"checks.json illisible ({checks_rel}) : {exc}")
        return result

    text = read_text(file_path)
    front, body = split_frontmatter(text)
    errors, warnings = result["errors"], result["warnings"]
    ran = 0

    for key in checks:
        if key not in KNOWN_RULES and not key.startswith("_"):
            warnings.append(f"Regle inconnue ignoree : {key}")

    if "required_frontmatter" in checks:
        ran += 1
        for key in checks["required_frontmatter"]:
            if key not in front or not str(front.get(key, "")).strip():
                errors.append(f"Frontmatter : cle obligatoire manquante ou vide '{key}'.")

    if "required_sections" in checks:
        ran += 1
        present = {line.strip() for line in text.splitlines()}
        for section in checks["required_sections"]:
            if section.strip() not in present:
                errors.append(f"Section obligatoire absente : '{section}'.")

    words = len(body.split())
    if "min_words" in checks:
        ran += 1
        if words < int(checks["min_words"]):
            errors.append(f"Livrable trop court : {words} mots (minimum {checks['min_words']}).")
    if "max_words" in checks:
        ran += 1
        # ponytail: depasser max_words est un avertissement, pas un blocage — trop long
        # n'a jamais casse une etape aval. Upgrade : rendre la severite configurable.
        if words > int(checks["max_words"]):
            warnings.append(f"Livrable long : {words} mots (maximum conseille {checks['max_words']}).")

    for rule, is_forbidden in (("forbidden_patterns", True), ("required_patterns", False)):
        if rule in checks:
            ran += 1
            for pattern in checks[rule]:
                try:
                    found = re.search(pattern, text, re.IGNORECASE) is not None
                except re.error as exc:
                    warnings.append(f"Regex invalide dans {rule} : {pattern} ({exc}).")
                    continue
                if is_forbidden and found:
                    errors.append(f"Motif interdit present : '{pattern}'.")
                elif not is_forbidden and not found:
                    errors.append(f"Motif obligatoire absent : '{pattern}'.")

    if checks.get("must_reference_inputs"):
        ran += 1
        for input_path in stage.get("inputs", []):
            name = Path(input_path).name
            if input_path not in text and name not in text:
                errors.append(f"Input non reference dans le livrable : {input_path}.")

    if "min_items_per_section" in checks:
        ran += 1
        for section, minimum in checks["min_items_per_section"].items():
            count = count_items(section_body(text, section))
            if count < int(minimum):
                errors.append(
                    f"Section '{section}' : {count} element(s) liste, minimum {minimum}."
                )

    result["checks_run"] = ran
    result["ok"] = not errors
    return result


def validate_stage(root: Path, pipe: dict, stage_id: str, file_override=None) -> dict:
    stage = find_stage(pipe, stage_id)
    if stage is None:
        return {"stage": stage_id, "file": None, "ok": False,
                "errors": [f"Etape inconnue dans pipeline.json : {stage_id}"],
                "warnings": [], "checks_run": 0}
    path = Path(file_override).resolve() if file_override else (root / stage["deliverable"])
    return run_checks(root, stage, path)


def stage_for_file(root: Path, pipe: dict, file_path: str):
    try:
        target = Path(file_path).resolve()
    except OSError:
        return None
    for stage in pipe.get("stages", []):
        if (root / stage.get("deliverable", "")).resolve() == target:
            return stage
    return None


# ------------------------------------------------------------------------ maturite

def maturity_path(root: Path) -> Path:
    return aidlc_dir(root) / "maturity.json"


def load_maturity(root: Path) -> dict:
    path = maturity_path(root)
    if not path.exists():
        return {"stages": {}}
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError:
        return {"stages": {}}
    data.setdefault("stages", {})
    return data


def stage_maturity(maturity: dict, stage_id: str) -> dict:
    return maturity["stages"].setdefault(stage_id, {"runs": [], "autonomous": False})


def human_review(root: Path, stage_id: str, run: int):
    path = aidlc_dir(root) / "reviews" / f"{stage_id}-{run}.json"
    if not path.exists():
        return None
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError:
        return None


def compute_autonomy(root: Path, pipe: dict, stage_id: str, maturity: dict) -> bool:
    """Autonomie = les N derniers runs sont au-dessus du seuil ET humainement approuves.

    # ponytail: lecture stricte du contrat (chaque run de la fenetre doit porter une revue
    humaine approuvee). Plafond : l'autonomie est plus longue a gagner. Upgrade : rendre la
    regle configurable dans pipeline.json.
    """
    threshold = float(pipe.get("maturity_threshold", 4.0))
    window = int(pipe.get("consecutive_runs_to_autonomy", 3))
    runs = stage_maturity(maturity, stage_id)["runs"]
    if len(runs) < window:
        return False
    for run in runs[-window:]:
        if run.get("verdict") != "accepted" or float(run.get("overall", 0)) < threshold:
            return False
        review = run.get("human_review") or human_review(root, stage_id, run.get("run", 0))
        if not review or not review.get("approved"):
            return False
    return True


def record_score(root: Path, pipe: dict, stage_id: str, review: dict) -> dict:
    scores = review.get("scores") or {}
    missing = [axis for axis in AXES if axis not in scores]
    if missing:
        raise ValueError(f"Axes manquants dans la revue : {', '.join(missing)}")
    values = []
    for axis in AXES:
        value = float(scores[axis])
        if not 0 <= value <= 5:
            raise ValueError(f"Score hors bornes pour '{axis}' : {value} (attendu 0-5).")
        values.append(value)
    overall = round(sum(values) / len(values), 1)
    threshold = float(pipe.get("maturity_threshold", 4.0))
    verdict = review.get("verdict")
    if verdict not in ("accepted", "rejected"):
        verdict = "accepted" if overall >= threshold else "rejected"

    maturity = load_maturity(root)
    entry = stage_maturity(maturity, stage_id)
    run_number = len(entry["runs"]) + 1
    record = {
        "ts": now_iso(),
        "run": run_number,
        "scores": {axis: float(scores[axis]) for axis in AXES},
        "overall": overall,
        "verdict": verdict,
        "human_review": None,
        "findings": truncate(review.get("findings", [])),
        "recommendations": truncate(review.get("recommendations", [])),
    }
    entry["runs"].append(record)
    entry["autonomous"] = compute_autonomy(root, pipe, stage_id, maturity)
    write_json(maturity_path(root), maturity)
    return record


def queue_improvement(root: Path, item: dict) -> None:
    path = aidlc_dir(root) / "improvement-queue.jsonl"
    ensure_dir(path.parent)
    if path.exists():
        for line in read_text(path).splitlines():
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if existing.get("stage") == item.get("stage") and existing.get("run") == item.get("run"):
                return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------- gate

def gate_stage(root: Path, pipe: dict, stage_id: str) -> dict:
    stage = find_stage(pipe, stage_id)
    out = {"stage": stage_id, "passed": False, "blocking": [],
           "next_stage": next_stage_id(pipe, stage_id), "human_review_required": True}
    if stage is None:
        out["blocking"].append(f"Etape inconnue dans pipeline.json : {stage_id}")
        return out

    threshold = float(pipe.get("maturity_threshold", 4.0))
    validation = validate_stage(root, pipe, stage_id)
    out["validation_ok"] = validation["ok"]
    if not validation["ok"]:
        out["blocking"].append(
            "Validation deterministe en echec : " + " | ".join(validation["errors"][:5])
        )

    maturity = load_maturity(root)
    entry = stage_maturity(maturity, stage_id)
    runs = entry["runs"]
    autonomous = bool(entry.get("autonomous"))
    out["autonomous"] = autonomous
    out["human_review_required"] = not autonomous

    if not runs:
        out["blocking"].append("Aucun score de maturite enregistre : lancer le reviewer.")
        out["run"] = None
        return out

    last = runs[-1]
    out["run"] = last.get("run")
    out["overall"] = last.get("overall")
    out["verdict"] = last.get("verdict")
    if last.get("verdict") != "accepted":
        out["blocking"].append(f"Verdict du reviewer : {last.get('verdict')}.")
    if float(last.get("overall", 0)) < threshold:
        out["blocking"].append(
            f"Maturite {last.get('overall')} sous le seuil {threshold}."
        )

    review = human_review(root, stage_id, last.get("run", 0))
    if review:
        last["human_review"] = {
            "approved": bool(review.get("approved")),
            "reviewer": review.get("reviewer"),
            "ts": review.get("ts"),
        }
        if not review.get("approved"):
            out["blocking"].append(
                "Revue humaine refusee : " + str(review.get("justification", "sans justification"))
            )
            queue_improvement(root, {
                "ts": now_iso(), "stage": stage_id, "run": last.get("run"),
                "reviewer": review.get("reviewer"),
                "justification": review.get("justification", ""),
                "source": "human_review",
            })
    elif not autonomous:
        out["blocking"].append(
            f"Revue humaine requise : .aidlc/reviews/{stage_id}-{last.get('run')}.json absent."
        )

    entry["autonomous"] = compute_autonomy(root, pipe, stage_id, maturity)
    out["autonomous"] = entry["autonomous"]
    write_json(maturity_path(root), maturity)

    out["passed"] = not out["blocking"]
    return out


# ------------------------------------------------------------------ review-request

REVIEW_INSTRUCTIONS = """Revue humaine — etape '{stage}' (run {run})

Livrable a relire : {deliverable}
Role attendu      : {role}

A verifier :
  1. Le livrable repond au besoin reel, pas seulement au gabarit.
  2. Les criteres d'acceptation sont testables et chiffres.
  3. Les inputs amont sont cites et correctement interpretes.
  4. Aucun engagement implicite non assume (delai, cout, perimetre).

Ou signer : {target}
  - copier le fichier .template.json en {basename}
  - renseigner "approved" (true/false), "reviewer", "justification"

En cas de refus (approved=false) : la justification est obligatoire, elle est copiee
automatiquement dans .aidlc/improvement-queue.jsonl et alimente la skill improve.
"""


def review_request(root: Path, pipe: dict, stage_id: str) -> dict:
    stage = find_stage(pipe, stage_id)
    if stage is None:
        raise ValueError(f"Etape inconnue dans pipeline.json : {stage_id}")
    maturity = load_maturity(root)
    runs = stage_maturity(maturity, stage_id)["runs"]
    run = runs[-1]["run"] if runs else 1
    target = aidlc_dir(root) / "reviews" / f"{stage_id}-{run}.json"
    template_path = aidlc_dir(root) / "reviews" / f"{stage_id}-{run}.template.json"
    template = {
        "stage": stage_id,
        "run": run,
        "approved": False,
        "reviewer": "<nom du relecteur>",
        "justification": "<justification obligatoire, surtout en cas de refus>",
        "ts": now_iso(),
    }
    write_json(template_path, template)
    sys.stderr.write(REVIEW_INSTRUCTIONS.format(
        stage=stage_id, run=run, deliverable=stage.get("deliverable"),
        role=stage.get("human_role", "non precise"),
        target=os.path.relpath(target, root), basename=target.name,
    ))
    return {
        "stage": stage_id, "run": run,
        "template": os.path.relpath(template_path, root),
        "target": os.path.relpath(target, root),
        "deliverable": stage.get("deliverable"),
        "human_role": stage.get("human_role"),
    }


# -------------------------------------------------------------------------- status

def status_data(root: Path, pipe: dict) -> dict:
    threshold = float(pipe.get("maturity_threshold", 4.0))
    maturity = load_maturity(root)
    rows = []
    for stage in pipe.get("stages", []):
        stage_id = stage["id"]
        deliverable = root / stage.get("deliverable", "")
        entry = maturity["stages"].get(stage_id, {"runs": [], "autonomous": False})
        runs = entry.get("runs", [])
        last = runs[-1] if runs else None
        present = deliverable.exists()
        validation = validate_stage(root, pipe, stage_id) if present else None
        row = {
            "stage": stage_id,
            "name": stage.get("name", stage_id),
            "plugin": stage.get("plugin"),
            "plugin_status": stage.get("status", "planned"),
            "deliverable": stage.get("deliverable"),
            "deliverable_present": present,
            "validate_ok": bool(validation and validation["ok"]),
            "errors": (validation or {}).get("errors", []),
            "runs": len(runs),
            "last_overall": last.get("overall") if last else None,
            "last_verdict": last.get("verdict") if last else None,
            "autonomous": bool(entry.get("autonomous")),
            "human_role": stage.get("human_role"),
        }
        if row["plugin_status"] != "implemented":
            row["next_action"] = f"Scaffolder l'etape : aidlc.py scaffold {stage_id}"
        elif not present:
            row["next_action"] = f"Produire le livrable : skill {stage.get('skill')}"
        elif not row["validate_ok"]:
            row["next_action"] = f"Corriger {len(row['errors'])} erreur(s) de validation"
        elif last is None:
            row["next_action"] = "Lancer le reviewer (agent aidlc-core:reviewer)"
        elif last.get("verdict") != "accepted" or float(last.get("overall", 0)) < threshold:
            row["next_action"] = "Reprendre le livrable puis relancer le reviewer"
        elif not row["autonomous"] and not human_review(root, stage_id, last.get("run", 0)):
            row["next_action"] = f"Revue humaine : aidlc.py review-request {stage_id}"
        else:
            row["next_action"] = "Etape franchie"
        rows.append(row)
    current = next((r["stage"] for r in rows if r["next_action"] != "Etape franchie"), None)
    return {"root": str(root), "maturity_threshold": threshold,
            "current_stage": current, "stages": rows}


def render_status(data: dict) -> str:
    headers = ["ETAPE", "PLUGIN", "LIVRABLE", "VALIDE", "SCORE", "AUTO", "PROCHAINE ACTION"]
    rows = []
    for row in data["stages"]:
        rows.append([
            row["stage"],
            row["plugin_status"],
            "oui" if row["deliverable_present"] else "non",
            "oui" if row["validate_ok"] else ("non" if row["deliverable_present"] else "-"),
            str(row["last_overall"]) if row["last_overall"] is not None else "-",
            "oui" if row["autonomous"] else "non",
            row["next_action"],
        ])
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
              for i in range(len(headers))]
    lines = [
        f"AI-DLC — tableau de bord ({data['root']})",
        f"Seuil de maturite : {data['maturity_threshold']} | "
        f"Etape courante : {data['current_stage'] or 'pipeline complet'}",
        "",
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    lines.append("")
    lines.append("Roles humains : " + ", ".join(
        f"{r['stage']}={r['human_role']}" for r in data["stages"] if r.get("human_role")))
    return "\n".join(lines)


# ------------------------------------------------------------------------ scaffold

PLUGIN_JSON = """{{
  "name": "aidlc-{stage}",
  "description": "Etape {name} du pipeline AI-DLC : produit {deliverable}.",
  "version": "0.1.0",
  "author": {{ "name": "Steve" }}
}}
"""

AGENT_MD = """---
name: {stage}-analyst
description: Analyste de l'étape {name}. Dialogue avec le role {role} pour produire {deliverable}.
model: sonnet
tools: Read, Write, Edit, Glob, Grep, Bash
---

# Analyste {name}

Tu produis le livrable de l'étape **{name}** du pipeline AI-DLC : `{deliverable}` — chemin
relatif au projet qui consomme le harnais (`${{CLAUDE_PROJECT_DIR}}`).

## Regles
- Tu DIALOGUES avec le role metier ({role}). Tu poses des questions ciblees, tu ne devines pas.
- Tu lis d'abord les inputs de l'étape : {inputs}.
- Tu interroges l'agent `librarian` pour le contexte disponible dans `${{CLAUDE_PROJECT_DIR}}/knowledge/`.
- Tu pars du gabarit de ce plugin `${{CLAUDE_PLUGIN_ROOT}}/templates/{template}` et tu le
  remplis integralement.
- Aucun placeholder ne doit subsister dans le livrable rendu.
- Tu n'appelles pas le script du harnais toi-même : la validation déterministe est déclenchée
  par le hook du plugin aidlc-core à chaque écriture du livrable, puis rejouée par
  l'orchestrateur (`/aidlc-core:run {stage}`). Corrige ce que le hook signale jusqu'à ne
  plus avoir d'erreur.

## Sortie
Un unique fichier : `{deliverable}`. Rien d'autre.
"""

SKILL_MD = """---
name: {stage}
description: Produire le livrable de l'étape {name} du pipeline AI-DLC ({deliverable}).
argument-hint: "[contexte libre]"
---

# Étape {name}

## Objectif
Produire `{deliverable}` — chemin relatif au projet — conforme au contrat de l'étape porté
par ce plugin (`${{CLAUDE_PLUGIN_ROOT}}/checks.json`).

## Entrées
{inputs_list}

## Procédure
1. Lire chaque input ci-dessus. S'il en manque un, arrêter et le signaler : l'étape amont
   n'est pas franchie.
2. Demander au `librarian` le contexte pertinent (`${{CLAUDE_PROJECT_DIR}}/knowledge/index.json`).
3. Copier `${{CLAUDE_PLUGIN_ROOT}}/templates/{template}` vers `{deliverable}`.
4. Interroger le role **{role}** sur les points non tranchés. Une question à la fois,
   fermée quand c'est possible.
5. Remplir toutes les sections. Citer explicitement les inputs (la validation l'exige).
6. Ne pas appeler le script du harnais soi-même : la validation déterministe est déclenchée
   par le hook du plugin aidlc-core à chaque écriture et rejouée par l'orchestrateur
   (`/aidlc-core:run {stage}`). Corriger jusqu'à ne plus avoir d'erreur signalée.
7. Rendre la main a l'orchestrateur pour la validation, la revue de maturite et la porte.

## Interdits
- Rendre un livrable non valide.
- Écrire ailleurs que dans `{deliverable}`.
- Éditer `.aidlc/maturity.json` ou `.aidlc/reviews/`.
"""

TEMPLATE_MD = """---
stage: {stage}
version: 1
status: draft
author: <nom de l'auteur>
date: <AAAA-MM-JJ>
---

# {name}

## Contexte
<Situation actuelle, en citant les inputs : {inputs}>

## Objectif
<Ce que cette étape doit permettre, en une phrase vérifiable.>

## Contenu
<Le corps du livrable : décisions, éléments, structure.>

## Contraintes
- <Contrainte 1, chiffrée.>
- <Contrainte 2, chiffrée.>

## Critères d'acceptation
- <Critère 1, testable.>
- <Critère 2, testable.>
- <Critère 3, testable.>

## Hors périmètre
- <Ce que cette étape ne traite pas.>

## Sources et références
- <Input ou source de vérité citée.>
"""

SCAFFOLD_SECTIONS = [
    "## Contexte", "## Objectif", "## Contenu", "## Contraintes",
    "## Critères d'acceptation", "## Hors périmètre", "## Sources et références",
]


def authoring_root() -> Path:
    """Base du depot auteur du harnais : le repertoire qui contient plugins/ et le
    marketplace. Le scaffold est une operation d'auteur : il ne s'execute pas depuis la
    copie installee par Claude Code (ou il n'y a pas de marketplace.json a mettre a jour).
    """
    harness = harness_root()
    if harness.name == "aidlc-core" and harness.parent.name == "plugins":
        return harness.parent.parent
    return harness


def mirror_checks(source: Path, target: Path) -> None:
    """Met le checks.json du plugin d'etape a cote du pipeline (miroir checks/<stage>.json).

    # ponytail: symlink quand le systeme de fichiers le permet (depot auteur, macOS/Linux),
    # copie sinon (Windows). Le miroir garantit que le noyau lit TOUJOURS le contrat de
    # l'etape sans dependre de l'agencement des plugins dans le cache de Claude Code.
    """
    ensure_dir(target.parent)
    if target.exists() or target.is_symlink():
        target.unlink()
    try:
        target.symlink_to(os.path.relpath(source, target.parent))
    except OSError:
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def scaffold(pipe: dict, stage_id: str, force: bool = False) -> dict:
    """Genere le plugin d'une etape dans le depot auteur du harnais (jamais dans le projet
    consommateur). Bascule le statut dans le pipeline.json du noyau et inscrit le plugin
    au marketplace du depot.
    """
    stage = find_stage(pipe, stage_id)
    if stage is None:
        raise ValueError(
            f"Etape '{stage_id}' absente de pipeline.json : l'ajouter d'abord au pipeline."
        )
    base = authoring_root()
    plugin_dir = base / "plugins" / f"aidlc-{stage_id}"
    if plugin_dir.exists() and not force:
        raise ValueError(f"{os.path.relpath(plugin_dir, base)} existe deja (utiliser --force).")

    name = stage.get("name", stage_id.capitalize())
    deliverable = stage.get("deliverable", f"deliverables/{stage_id}/{stage_id}.md")
    template_name = Path(deliverable).name
    inputs = stage.get("inputs", [])
    inputs_txt = ", ".join(inputs) if inputs else "aucun"
    inputs_list = "\n".join(f"- `{i}`" for i in inputs) if inputs else "- Aucun input amont."
    role = stage.get("human_role", "role metier a preciser")
    fmt = dict(stage=stage_id, name=name, deliverable=deliverable, role=role,
               inputs=inputs_txt, inputs_list=inputs_list, template=template_name)

    created = []
    for rel, content in [
        (".claude-plugin/plugin.json", PLUGIN_JSON.format(**fmt)),
        (f"agents/{stage_id}-analyst.md", AGENT_MD.format(**fmt)),
        (f"skills/{stage_id}/SKILL.md", SKILL_MD.format(**fmt)),
        (f"templates/{template_name}", TEMPLATE_MD.format(**fmt)),
    ]:
        path = plugin_dir / rel
        ensure_dir(path.parent)
        path.write_text(content, encoding="utf-8")
        created.append(os.path.relpath(path, base))

    checks = {
        "required_frontmatter": ["stage", "version", "status", "author", "date"],
        "required_sections": SCAFFOLD_SECTIONS,
        "min_words": 250,
        "forbidden_patterns": [
            "(?i)\\bTODO\\b", "(?i)\\bTBD\\b", "\\bXXX\\b", "(?i)\\blorem\\b",
            "(?i)\\b[\u00e0a]\\s+compl[\u00e9e]ter\\b", "<[^>\\n]{3,}>",
        ],
        "must_reference_inputs": bool(inputs),
        "min_items_per_section": {"## Critères d'acceptation": 3, "## Contraintes": 2},
    }
    checks_path = plugin_dir / "checks.json"
    write_json(checks_path, checks)
    created.append(os.path.relpath(checks_path, base))

    stage["status"] = "implemented"
    stage["checks"] = f"checks/{stage_id}.json"
    write_json(harness_root() / "pipeline.json", pipe)
    mirror_checks(checks_path, harness_root() / "checks" / f"{stage_id}.json")
    created.append(os.path.relpath(harness_root() / "checks" / f"{stage_id}.json", base))

    market_path = base / ".claude-plugin" / "marketplace.json"
    if market_path.exists():
        market = json.loads(read_text(market_path))
    else:
        market = {"name": "aidlc", "owner": {"name": "Steve"}, "plugins": []}
    market.setdefault("plugins", [])
    if not any(p.get("name") == f"aidlc-{stage_id}" for p in market["plugins"]):
        market["plugins"].append({
            "name": f"aidlc-{stage_id}",
            "source": f"./plugins/aidlc-{stage_id}",
            "description": f"Etape {name} du pipeline AI-DLC : produit {deliverable}.",
        })
    write_json(market_path, market)
    created.append(os.path.relpath(market_path, base))

    return {"stage": stage_id, "plugin": f"aidlc-{stage_id}", "created": created,
            "template": template_name,
            "next": f"Éditer {os.path.relpath(checks_path, base)} et le SKILL.md "
                    f"pour coller au metier de l'étape."}


# ------------------------------------------------------------------------- improve

def iter_log_events(root: Path):
    log_dir = aidlc_dir(root) / "logs"
    if not log_dir.is_dir():
        return
    for path in sorted(log_dir.glob("*.jsonl")):
        for line in read_text(path).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def improve(root: Path, pipe: dict, stage_filter=None) -> dict:
    sessions, events, turns = set(), 0, 0
    tools, per_stage_events = {}, {}
    for event in iter_log_events(root):
        if stage_filter and event.get("stage") != stage_filter:
            continue
        events += 1
        sessions.add(event.get("session_id"))
        if event.get("event") == "UserPromptSubmit":
            turns += 1
        tool = (event.get("payload") or {}).get("tool_name")
        if tool:
            tools[tool] = tools.get(tool, 0) + 1
        stage_id = event.get("stage")
        if stage_id:
            per_stage_events[stage_id] = per_stage_events.get(stage_id, 0) + 1

    validation, error_counts = {}, {}
    for stage in pipe.get("stages", []):
        stage_id = stage["id"]
        if stage_filter and stage_id != stage_filter:
            continue
        if not (root / stage.get("deliverable", "")).exists():
            continue
        result = validate_stage(root, pipe, stage_id)
        validation[stage_id] = {"ok": result["ok"], "errors": result["errors"]}
        for message in result["errors"]:
            key = re.sub(r"\d+", "N", message)
            error_counts[key] = error_counts.get(key, 0) + 1

    maturity = load_maturity(root)
    maturity_out = {}
    for stage_id, entry in maturity.get("stages", {}).items():
        if stage_filter and stage_id != stage_filter:
            continue
        runs = entry.get("runs", [])
        if not runs:
            continue
        means = {axis: round(statistics.fmean(
            [float(r["scores"].get(axis, 0)) for r in runs]), 2) for axis in AXES}
        weakest = sorted(means, key=lambda axis: means[axis])[:2]
        maturity_out[stage_id] = {
            "runs": len(runs),
            "last_overall": runs[-1].get("overall"),
            "trend": [r.get("overall") for r in runs][-5:],
            "axis_means": means,
            "weakest_axes": weakest,
            "autonomous": bool(entry.get("autonomous")),
            "rejected_runs": sum(1 for r in runs if r.get("verdict") != "accepted"),
        }

    rejections = []
    queue_path = aidlc_dir(root) / "improvement-queue.jsonl"
    if queue_path.exists():
        for line in read_text(queue_path).splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if stage_filter and item.get("stage") != stage_filter:
                continue
            rejections.append(item)

    return {
        "scope": stage_filter or "all",
        "generated_at": now_iso(),
        "sessions": len([s for s in sessions if s]),
        "events": events,
        "turns": turns,
        "events_per_stage": per_stage_events,
        "top_tools": sorted(tools.items(), key=lambda kv: -kv[1])[:10],
        "validation": validation,
        "recurring_errors": sorted(error_counts.items(), key=lambda kv: -kv[1])[:10],
        "maturity": maturity_out,
        "human_rejections": rejections,
    }


# ----------------------------------------------------------------------- log/guard

def current_stage_id(root: Path, pipe: dict):
    try:
        for stage in pipe.get("stages", []):
            deliverable = root / stage.get("deliverable", "")
            if not deliverable.exists():
                return stage["id"]
            if not validate_stage(root, pipe, stage["id"])["ok"]:
                return stage["id"]
        stages = pipe.get("stages", [])
        return stages[-1]["id"] if stages else None
    except Exception:
        return None


def guess_stage(root: Path, pipe: dict, raw: str):
    """Devine l'etape courante depuis le texte du hook.

    # ponytail: heuristique par sous-chaine (chemin de livrable puis identifiant d'etape).
    Plafond : un texte francais contenant "plan" peut faussement matcher. Upgrade : faire
    porter l'etape par une variable d'environnement posee par l'orchestrateur.
    """
    try:
        for stage in pipe.get("stages", []):
            folder = os.path.dirname(stage.get("deliverable", ""))
            if folder and folder in raw:
                return stage["id"]
        for stage in pipe.get("stages", []):
            if re.search(r"\b" + re.escape(stage["id"]) + r"\b", raw, re.IGNORECASE):
                return stage["id"]
        return current_stage_id(root, pipe)
    except Exception:
        return None


def handle_log(root: Path, raw: str) -> dict:
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        data = {"raw": truncate(str(data))}
    session_id = str(data.get("session_id") or "unknown-" + uuid.uuid4().hex[:8])
    session_id = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:80]
    try:
        pipe = load_pipeline()
    except Exception:
        pipe = {"stages": []}
    payload = {k: truncate(data[k]) for k in PAYLOAD_KEYS if k in data}
    entry = {
        "ts": now_iso(),
        "event": data.get("hook_event_name", "unknown"),
        "session_id": session_id,
        "agent_id": data.get("agent_id"),
        "agent_type": data.get("agent_type"),
        "cwd": data.get("cwd"),
        "stage": guess_stage(root, pipe, raw[:8000]),
        "payload": payload,
    }
    log_path = ensure_dir(aidlc_dir(root) / "logs") / f"{session_id}.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def guard_decision(root: Path, raw: str):
    """Retourne un motif de refus si le hook veut ecrire dans les artefacts de score."""
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        return None
    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not target:
        return None
    try:
        resolved = Path(target).expanduser().resolve()
    except OSError:
        return None
    protected_root = aidlc_dir(root).resolve()
    try:
        relative = resolved.relative_to(protected_root)
    except ValueError:
        return None
    parts = relative.parts
    if parts and parts[0] == "maturity.json":
        return ("Ecriture refusee : .aidlc/maturity.json est l'integrite du score. "
                "Passer par `aidlc.py score <stage> --file <review.json>`.")
    if len(parts) >= 2 and parts[0] == "reviews" and parts[1].endswith(".json") \
            and not parts[1].endswith(".template.json"):
        return ("Ecriture refusee : les revues humaines .aidlc/reviews/*.json sont signees "
                "par un humain. Utiliser `aidlc.py review-request <stage>` et laisser "
                "l'humain remplir le fichier.")
    return None


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

    if saved_harness is None:
        os.environ.pop("AIDLC_HARNESS_ROOT", None)
    else:
        os.environ["AIDLC_HARNESS_ROOT"] = saved_harness
    sys.stderr.write(f"OK: {checked} assertions\n")
    return 0


# ------------------------------------------------------------------- sous-commandes

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
        touched = args.file
        if not touched and not sys.stdin.isatty():
            try:
                payload = json.loads(sys.stdin.read() or "{}")
                touched = (payload.get("tool_input") or {}).get("file_path")
            except Exception:
                touched = None
        if not touched:
            return 0
        args.file = touched
        stage = stage_for_file(root, pipe, args.file)
        if stage is None:
            return 0
        result = run_checks(root, stage, Path(args.file).resolve())
        if result["ok"]:
            context = (f"Validation AI-DLC '{stage['id']}' : OK "
                       f"({result['checks_run']} regles).")
        else:
            context = ("Validation AI-DLC '{}' EN ECHEC ({} erreur(s)) :\n- {}\n"
                       "Corriger avant de rendre le livrable.").format(
                stage["id"], len(result["errors"]), "\n- ".join(result["errors"]))
        emit({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                     "additionalContext": context}})
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aidlc.py", description="Moteur deterministe du harness AI-DLC.")
    parser.add_argument("--selftest", action="store_true",
                        help="Lance l'auto-test integre et sort.")
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

    status = sub.add_parser("status", help="Tableau de bord du pipeline.")
    status.add_argument("--json", action="store_true")

    scaffold_cmd = sub.add_parser("scaffold", help="Genere le plugin d'une etape planifiee.")
    scaffold_cmd.add_argument("stage")
    scaffold_cmd.add_argument("--force", action="store_true",
                              help="Ecrase un plugin existant.")

    improve_cmd = sub.add_parser("improve", help="Diagnostic d'auto-amelioration (JSON).")
    improve_cmd.add_argument("--stage", help="Restreindre a une etape.")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
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
        "review-request": cmd_review_request, "status": cmd_status,
        "scaffold": cmd_scaffold, "improve": cmd_improve,
    }
    try:
        return handlers[args.command](root, args)
    except FileNotFoundError as exc:
        sys.stderr.write(f"Fichier introuvable : {exc}\n")
        return 1
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"JSON invalide : {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
