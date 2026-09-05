from __future__ import annotations

import json

from pathlib import Path
from .checks import resolve_checks_path
from .util import aidlc_dir
from .util import ensure_dir
from .util import harness_root
from .util import now_iso
from .util import read_text
from .util import write_json
"""Ratchet (inspire du dark factory) : les planchers de severite des checks.json ne
descendent jamais. Un plancher peut monter librement (durcir) ; le descendre exige
`aidlc.py ratchet --reset <stage>`, geste explicite de l'auteur du harnais."""


def ratchet_path(root: Path) -> Path:
    return aidlc_dir(root) / "ratchet.json"


def _floors_of(checks: dict) -> dict:
    """Planchers de severite extraits d'un checks.json : min_words, min_items_per_section,
    required_sections (le nombre ET l'ensemble des titres). # ponytail: seules ces trois
    regles sont figees — ce sont celles qu'on peut baisser « pour passer » ; les patterns
    interdits/obligatoires ne se demontent pas silencieusement (la CI check-json et le
    guard couvrent le reste)."""
    floors = {}
    if "min_words" in checks:
        floors["min_words"] = int(checks["min_words"])
    if checks.get("min_items_per_section"):
        floors["min_items_per_section"] = {
            section: int(value)
            for section, value in checks["min_items_per_section"].items()
        }
    if checks.get("required_sections"):
        floors["required_sections"] = {
            "count": len(checks["required_sections"]),
            "items": sorted(checks["required_sections"]),
        }
    return floors


def freeze_current(pipe: dict) -> dict:
    """Planchers courants de toutes les etapes implementees (source de verite : le harnais)."""
    harness = harness_root()
    snapshot = {}
    for stage in pipe.get("stages", []):
        if stage.get("status") != "implemented":
            continue
        checks_path = resolve_checks_path(harness, stage)
        if not checks_path or not checks_path.exists():
            continue
        try:
            checks = json.loads(read_text(checks_path))
        except (json.JSONDecodeError, OSError):
            continue
        floors = _floors_of(checks)
        if floors:
            snapshot[stage["id"]] = floors
    return snapshot


def _merge_lower(existing: dict, fresh: dict) -> dict:
    """Fusion conservatrice : garde le plancher le plus haut entre le figeage existant
    et l'etat courant — un figeage ne s'effrite jamais, meme apres un reset partiel."""
    merged = dict(existing)
    for stage_id, floors in fresh.items():
        kept = merged.get(stage_id)
        if kept is None:
            merged[stage_id] = floors
            continue
        kept = json.loads(json.dumps(kept))  # copie profonde legere (structures JSON)
        if "min_words" in floors:
            kept["min_words"] = max(int(kept.get("min_words", 0)), floors["min_words"])
        if "min_items_per_section" in floors:
            items = dict(kept.get("min_items_per_section", {}))
            for section, value in floors["min_items_per_section"].items():
                items[section] = max(int(items.get(section, 0)), value)
            kept["min_items_per_section"] = items
        if "required_sections" in floors:
            previous = set(kept.get("required_sections", {}).get("items", []))
            kept["required_sections"] = {
                "count": max(kept.get("required_sections", {}).get("count", 0),
                             floors["required_sections"]["count"]),
                "items": sorted(previous | set(floors["required_sections"]["items"])),
            }
        merged[stage_id] = kept
    return merged


def _violations_for(stage_id: str, frozen: dict, checks: dict) -> list:
    """Violations du ratchet pour une etape : un plancher descendu, une section
    obligatoire supprimee, une regle de severite enlevee."""
    violations = []
    if "min_words" in frozen:
        if "min_words" not in checks:
            violations.append({"stage": stage_id, "rule": "min_words",
                               "before": frozen["min_words"], "after": None})
        elif int(checks["min_words"]) < int(frozen["min_words"]):
            violations.append({"stage": stage_id, "rule": "min_words",
                               "before": frozen["min_words"], "after": int(checks["min_words"])})
    for section, floor in (frozen.get("min_items_per_section") or {}).items():
        current = (checks.get("min_items_per_section") or {}).get(section)
        if current is None:
            violations.append({"stage": stage_id, "rule": f"min_items_per_section[{section}]",
                               "before": floor, "after": None})
        elif int(current) < int(floor):
            violations.append({"stage": stage_id, "rule": f"min_items_per_section[{section}]",
                               "before": floor, "after": int(current)})
    frozen_sections = frozen.get("required_sections") or {}
    if frozen_sections:
        current = checks.get("required_sections") or []
        for item in frozen_sections.get("items", []):
            if item not in current:
                violations.append({"stage": stage_id, "rule": "required_sections",
                                   "before": item, "after": None})
    return violations


def ratchet_run(root: Path, pipe: dict) -> dict:
    """Passe du ratchet : fige au premier passage, revalide ensuite. Sortie JSON ;
    `passed` faux = au moins un plancher descendu (exit 2 pour la CI)."""
    path = ratchet_path(root)
    fresh = freeze_current(pipe)
    was_absent = not path.exists()
    state = {"ts": now_iso(), "baseline": was_absent, "stages": {}}
    if path.exists():
        try:
            state = json.loads(read_text(path))
        except json.JSONDecodeError:
            state = {"ts": now_iso(), "baseline": True, "stages": {}}
        state.setdefault("stages", {})
        state["baseline"] = was_absent
    state["stages"] = _merge_lower(state.get("stages", {}), fresh)

    violations = []
    for stage in pipe.get("stages", []):
        if stage.get("status") != "implemented":
            continue
        frozen = state["stages"].get(stage["id"])
        if not frozen:
            continue
        checks_path = resolve_checks_path(harness_root(), stage)
        if not checks_path or not checks_path.exists():
            continue
        try:
            checks = json.loads(read_text(checks_path))
        except (json.JSONDecodeError, OSError):
            continue
        violations.extend(_violations_for(stage["id"], frozen, checks))

    write_json(path, state)
    return {
        "ratchet": str(path),
        "baseline": was_absent,
        "stages_frozen": sorted(state["stages"]),
        "passed": not violations,
        "violations": violations,    "hint": ("Un plancher ne descend jamais. Pour l'assouplir legalement : faire "
             "evoluer le checks.json dans le depot auteur du harnais, puis "
             "`aidlc.py ratchet --reset <stage>` dans le projet."),
    } if violations else {
        "ratchet": str(path),
        "baseline": was_absent,
        "stages_frozen": sorted(state["stages"]),
        "passed": True,
        "violations": [],
    }


def ratchet_reset(root: Path, pipe: dict, stage_id: str) -> dict:
    """Reset explicite d'une etape : le plancher repart de l'etat courant du checks.json
    (auteur du harnais, geste humain). Trace dans l'entree elle-meme (champ reset_at)."""
    path = ratchet_path(root)
    if not path.exists():
        raise ValueError("Aucun ratchet fige : lancer `aidlc.py ratchet` d'abord.")
    try:
        state = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"ratchet.json illisible : {exc}")
    fresh = freeze_current(pipe).get(stage_id)
    if fresh is None:
        raise ValueError(f"Etape sans planchers figeables ou inconnue : {stage_id}")
    state["stages"][stage_id] = fresh
    state["stages"][stage_id]["reset_at"] = now_iso()
    write_json(path, state)
    return {"stage": stage_id, "floors": fresh, "reset_at": state["stages"][stage_id]["reset_at"]}
