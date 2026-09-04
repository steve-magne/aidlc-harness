from __future__ import annotations

import json
import os
import re

from pathlib import Path
from .util import find_stage
from .util import harness_root
from .util import read_text
"""Validation deterministe des livrables d'etape : regles declarees (checks.json), sections, frontmatter, mot interdits."""

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
