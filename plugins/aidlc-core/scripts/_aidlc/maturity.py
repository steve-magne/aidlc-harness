from __future__ import annotations

import json
import os
import sys

from pathlib import Path
from .util import aidlc_dir
from .util import ensure_dir
from .util import find_stage
from .util import next_stage_id
from .util import now_iso
from .util import read_text
from .util import truncate
from .checks import validate_stage
from .util import write_json

AXES = ["completeness", "precision", "traceability", "autonomy"]
"""Maturite des etapes : scores, autonomie, porte (gate), revue humaine et etat du pipeline (status)."""

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


def enqueue_improvement(root: Path, item: dict, dedupe_keys: tuple) -> bool:
    """Seul ecrivain de .aidlc/improvement-queue.jsonl : ajoute item sauf si une entree
    existante du meme `kind` possede deja les memes valeurs sur `dedupe_keys`. Les refus
    humains (kind absent, dedupe stage/run), ceux du gate OKF (kind okf_stop, dedupe
    session/bundle/fichiers) et les haltes du watchdog (kind watchdog, dedupe
    detector/stage/file/session) partagent cette unique politique — le kind les distingue.
    Retourne True si une entree a ete ajoutee, False si elle etait un doublon."""
    kind = item.get("kind")
    path = aidlc_dir(root) / "improvement-queue.jsonl"
    ensure_dir(path.parent)
    if path.exists():
        for line in read_text(path).splitlines():
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if existing.get("kind") != kind:
                continue
            if all(existing.get(key) == item.get(key) for key in dedupe_keys):
                return False
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return True


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
            enqueue_improvement(root, {
                "ts": now_iso(), "stage": stage_id, "run": last.get("run"),
                "reviewer": review.get("reviewer"),
                "justification": review.get("justification", ""),
                "source": "human_review",
            }, ("stage", "run"))
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
