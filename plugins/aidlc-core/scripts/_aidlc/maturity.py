from __future__ import annotations

import json
import os
import sys

from pathlib import Path
from .util import aidlc_dir
from .util import digest
from .util import ensure_dir
from . import registry
from .util import now_iso
from .util import read_text
from .util import truncate
from .checks import contract_problems
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


def input_digests(root: Path, stage: dict) -> dict:
    """Empreintes courantes des entrees amont d'une etape."""
    return {path: digest(root / path) for path in (stage or {}).get("consumes") or []}


def stale_inputs(root: Path, stage: dict, run: dict) -> list:
    """Entrees amont modifiees depuis que ce run a ete note.

    C'est ce qui empeche un livrable aval de rester vert alors qu'il a ete bati sur une
    version disparue de son amont — le cas « le BA a revise apres que l'architecte a
    livre ». Un run enregistre avant l'existence des empreintes (cle 'inputs' absente) ne
    perime rien : on ne perime que ce dont on connait l'etat d'origine.
    """
    recorded = (run or {}).get("inputs")
    if not recorded:
        return []
    current = input_digests(root, stage)
    return sorted(path for path, value in recorded.items() if current.get(path) != value)


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
    # Plancher par axe : une moyenne flatteuse ne rachete pas un axe effondre. Un
    # livrable complet, precis et rapide mais sans aucune tracabilite reste un livrable
    # qu'on ne peut pas auditer — et il servira d'entree a toute l'aval. La regle etait
    # ecrite dans le prompt du reviewer et nulle part dans le moteur : un reviewer
    # complaisant (ou un modele qui derive) la contournait sans que rien ne le voie.
    # C'est le moteur qui la tient, pas la consigne.
    floor = float(pipe.get("min_axis_score", 3.0))
    weak = [axis for axis in AXES if float(scores[axis]) < floor]
    if weak:
        verdict = "rejected"

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
        "weak_axes": weak,
        "findings": truncate(review.get("findings", [])),
        "recommendations": truncate(review.get("recommendations", [])),
        "inputs": input_digests(root, registry.find_agent(stage_id)),
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
    stage = registry.find_agent(stage_id)
    out = {"stage": stage_id, "passed": False, "blocking": [],
           "next_stage": registry.next_agent_id(stage_id), "human_review_required": True}
    if stage is None:
        out["blocking"].append(f"Agent inconnu du registre : {stage_id}")
        return out
    if not stage.get("produces"):
        # Un agent consultatif n'a pas de livrable, donc pas de metre : il n'y a rien a
        # noter et rien a franchir. Ce n'est pas un echec, c'est une absence de porte.
        out["blocking"].append(
            f"L'agent '{stage_id}' est consultatif (pas de 'produces') : aucune porte "
            "de qualite ne s'y applique.")
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
    weak = last.get("weak_axes") or []
    if weak:
        floor = float(pipe.get("min_axis_score", 3.0))
        out["weak_axes"] = weak
        out["blocking"].append(
            "Axe sous le plancher {} : {} — une moyenne suffisante ne rachete pas un "
            "axe effondre.".format(floor, ", ".join(
                f"{axis}={last['scores'][axis]}" for axis in weak)))

    stale = stale_inputs(root, stage, last)
    if stale:
        out["stale_inputs"] = stale
        out["blocking"].append(
            "Entree amont modifiee depuis la revue : " + ", ".join(stale)
            + " — relancer le reviewer."
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
    stage = registry.find_agent(stage_id)
    if stage is None:
        raise ValueError(f"Agent inconnu du registre : {stage_id}")
    if not stage.get("produces"):
        raise ValueError(f"L'agent '{stage_id}' ne produit pas de livrable : "
                         "il n'y a rien a faire relire.")
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
        stage=stage_id, run=run, deliverable=stage.get("produces"),
        role=stage.get("human_role", "non precise"),
        target=os.path.relpath(target, root), basename=target.name,
    ))
    return {
        "stage": stage_id, "run": run,
        "template": os.path.relpath(template_path, root),
        "target": os.path.relpath(target, root),
        "deliverable": stage.get("produces"),
        "human_role": stage.get("human_role"),
    }


# -------------------------------------------------------------------------- status

def status_data(root: Path, pipe: dict) -> dict:
    """Tableau de bord derive du registre. Les etapes sont les agents qui produisent un
    livrable, dans l'ordre topologique ; les agents consultatifs sont listes a part.

    Un registre est ouvert : un plugin absent ferait retrecir le tableau en silence.
    Deux sections l'empechent — `missing_producers` (une entree attendue que personne
    ne produit) et `planned` (feuille de route declaree, plugin pas encore installe).
    """
    threshold = float(pipe.get("maturity_threshold", 4.0))
    maturity = load_maturity(root)
    view = registry.catalog()
    rows = []
    for stage in [agent for agent in view["agents"] if agent.get("produces")]:
        stage_id = stage["id"]
        deliverable = root / stage["produces"]
        entry = maturity["stages"].get(stage_id, {"runs": [], "autonomous": False})
        runs = entry.get("runs", [])
        last = runs[-1] if runs else None
        present = deliverable.exists()
        validation = validate_stage(root, pipe, stage_id) if present else None
        stale = stale_inputs(root, stage, last)
        row = {
            "stage": stage_id,
            "name": stage.get("description") or stage_id,
            "team": stage.get("team"),
            "version": stage.get("version"),
            "capabilities": stage.get("capabilities", []),
            "invoke": stage.get("invoke"),
            "invocable": stage.get("invocable"),
            "deliverable": stage["produces"],
            "deliverable_present": present,
            "validate_ok": bool(validation and validation["ok"]),
            "errors": (validation or {}).get("errors", []),
            "runs": len(runs),
            "last_overall": last.get("overall") if last else None,
            "last_verdict": last.get("verdict") if last else None,
            "autonomous": bool(entry.get("autonomous")),
            "human_role": stage.get("human_role"),
            "stale_inputs": stale,
        }
        if not row["invocable"]:
            row["next_action"] = (f"Agent non invocable sur {view['platform']} : "
                                  "completer 'invocation' dans son agent.json")
        elif not present:
            row["next_action"] = f"Produire le livrable : {stage.get('invoke')}"
        elif not row["validate_ok"]:
            row["next_action"] = f"Corriger {len(row['errors'])} erreur(s) de validation"
        elif stale:
            row["next_action"] = ("Entree amont modifiee ("
                                  + ", ".join(Path(p).name for p in stale)
                                  + ") : reprendre puis relancer le reviewer")
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
    known = {agent["id"] for agent in view["agents"]}
    planned = [stage for stage in pipe.get("planned_stages", [])
               if stage.get("id") not in known]
    return {
        "root": str(root),
        "platform": view["platform"],
        "maturity_threshold": threshold,
        "current_stage": current,
        "stages": rows,
        "advisors": [agent for agent in view["agents"] if not agent.get("produces")],
        "missing_producers": view["missing_producers"],
        "planned": planned,
        "cycle": view["cycle"],
        "problems": view["problems"],
        "contract_problems": [problem for agent in view["agents"]
                              for problem in contract_problems(agent)],
        "warnings": view["warnings"],
    }


def render_status(data: dict) -> str:
    headers = ["AGENT", "EQUIPE", "LIVRABLE", "VALIDE", "SCORE", "AUTO", "PROCHAINE ACTION"]
    rows = []
    for row in data["stages"]:
        rows.append([
            row["stage"],
            row.get("team") or "-",
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
        f"Plateforme : {data.get('platform')} | "
        f"Etape courante : {data['current_stage'] or 'chaine complete'}",
        "",
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    lines.append("")
    lines.append("Roles humains : " + (", ".join(
        f"{r['stage']}={r['human_role']}" for r in data["stages"] if r.get("human_role"))
        or "aucun declare"))
    for advisor in data.get("advisors", []):
        lines.append("Agent consultatif : {} (equipe {}) — {}".format(
            advisor["id"], advisor.get("team") or "?",
            ", ".join(advisor.get("capabilities", [])) or "aucune capacite declaree"))
    for hole in data.get("missing_producers", []):
        lines.append("Producteur absent : '{}' attend {} — aucun agent installe ne le "
                     "produit.".format(hole["agent"], hole["input"]))
    for stage in data.get("planned", []):
        lines.append("Prevu, plugin non installe : {} ({}) — aidlc.py scaffold {}".format(
            stage.get("id"), stage.get("name", ""), stage.get("id")))
    if data.get("cycle"):
        lines.append("Cycle de dependances entre agents : " + ", ".join(data["cycle"]))
    for message in data.get("warnings", []):
        lines.append("Avertissement : " + message)
    for message in data.get("problems", []):
        lines.append("Manifeste rejete : " + message)
    for message in data.get("contract_problems", []):
        lines.append("Contrat incoherent : " + message)
    return "\n".join(lines)
