from __future__ import annotations

import json
import os
import re

from pathlib import Path
from . import registry
from .util import harness_root
from .util import read_text
"""Validation deterministe des livrables d'etape : regles declarees (checks.json), sections, frontmatter, mots interdits, preuve d'execution, holdout (le livrable ne cite pas ses propres regles)."""

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
    "min_items_per_section", "proof_of_run", "required_input_section",
    "must_not_violate_scope", "checks_do_not_self_reference",
}


def resolve_checks_path(pipe_root: Path, stage: dict) -> Path:
    """Chemin du checks.json d'un agent : relatif a son manifeste, donc lu dans le
    plugin de l'equipe qui le maintient. Le noyau ne garde plus de miroir — c'etait la
    centralisation qui obligeait a toucher le harnais pour publier un agent.

    # ponytail: repli conserve sur l'ancien miroir checks/<id>.json du noyau, pour une
    # installation heritee ou l'agent n'a pas encore de manifeste. Plafond : le repli
    # disparaitra quand plus aucun consommateur ne portera de miroir.
    """
    checks_rel = stage.get("checks")
    if not checks_rel:
        return None
    root = stage.get("root")
    if root:
        candidate = Path(root) / checks_rel
        if candidate.exists():
            return candidate
    checks_path = pipe_root / checks_rel
    if checks_path.exists():
        return checks_path
    plugin_name = stage.get("plugin")
    fallback = pipe_root.parent / f"{plugin_name}/checks.json" if plugin_name else None
    if fallback and fallback.exists():
        return fallback
    return checks_path


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

    if not stage.get("checks"):
        result["warnings"].append("Aucun fichier de checks declare pour cette etape.")
        result["ok"] = True
        return result
    # Le checks.json vit dans le harnais (a cote du pipeline.json), pas dans le projet.
    checks_path = resolve_checks_path(harness_root(), stage)
    if not checks_path.exists():
        result["errors"].append(f"Fichier de checks introuvable : {stage.get('checks')}")
        return result
    try:
        checks = json.loads(read_text(checks_path))
    except json.JSONDecodeError as exc:
        result["errors"].append(f"checks.json illisible ({checks_path}) : {exc}")
        return result

    text = read_text(file_path)
    front, body = split_frontmatter(text)
    errors, warnings = result["errors"], result["warnings"]
    ran = 0
    present = {line.strip() for line in text.splitlines()}

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
        for input_path in stage.get("consumes", []):
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

    # Preuve d'execution (inspire du dark factory : evidence, not claims) — une section
    # declaree "preuve" doit citer une valeur observee concrete, pas reformuler l'attendu.
    if "proof_of_run" in checks:
        ran += 1
        for section in checks["proof_of_run"]:
            if section.strip() not in present:
                errors.append(f"Section obligatoire absente : '{section}'.")
                continue
            evidence = find_evidence(section_body(text, section))
            if not evidence:
                errors.append(
                    f"Preuve d'execution absente dans '{section}' : aucune valeur observee "
                    "concrete (chiffre, unite, chemin, id, date). Un rapport qui reformule "
                    "l'attendu sans la valeur constatee n'est pas une preuve."
                )

    # Citation d'entree dans une section precise : plus fort que must_reference_inputs,
    # qui cherche le chemin partout dans le texte.
    if "required_input_section" in checks:
        ran += 1
        for input_path, section in checks["required_input_section"].items():
            if section.strip() not in present:
                errors.append(f"Section obligatoire absente : '{section}'.")
                continue
            name = Path(input_path).name
            body = section_body(text, section)
            if input_path not in body and name not in body:
                errors.append(
                    f"Input non reference dans '{section}' : {input_path} doit etre cite "
                    "dans cette section, pas seulement ailleurs dans le livrable."
                )

    # Perimetre : le livrable doit citer la section 'Hors perimetre' du plan amont et ne
    # pas la contredire (les items de plan restent hors perimetre dans le livrable).
    if checks.get("must_not_violate_scope"):
        ran += 1
        scope_section = checks["must_not_violate_scope"].get("section", "## Hors périmètre")
        for input_path in stage.get("consumes", []):
            source = root / input_path
            if not source.exists():
                continue
            scope_items = scope_items_of(read_text(source), scope_section)
            if not scope_items:
                continue
            if scope_section.strip() not in present:
                errors.append(
                    f"Perimetre : la section '{scope_section}' est obligatoire quand "
                    f"l'entree {input_path} en declare une."
                )
                continue
            for item in scope_items:
                if not scope_respected(body, item):
                    errors.append(
                        f"Perimetre : l'item hors perimetre du plan, '{item}', n'est pas "
                        "declare hors perimetre — le marquer exclu dans "
                        f"'{scope_section}', ou ne pas y toucher."
                    )

    # Holdout (essence stdlib du dark factory) : le livrable ne doit pas citer ses
    # propres regles de validation — optimiser contre le metre au lieu de l'ouvrage.
    if checks.get("checks_do_not_self_reference"):
        ran += 1
        try:
            rules_text = read_text(checks_path)
        except OSError:
            rules_text = ""
        for line in rules_text.splitlines():
            line = line.strip()
            if len(line) >= 12 and line in text:
                errors.append(
                    "Holdout : le livrable cite une ligne de son propre checks.json "
                    f"({line[:60]}...) — travailler sur le livrable, pas sur le metre."
                )
                break

    result["checks_run"] = ran
    result["ok"] = not errors
    return result


# ------------------------------------------------- preuve d'execution / perimetre

EVIDENCE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:ms|s|min|h|j|%|r/s|req/s|Mo|ko|Go|Mio|kio|octets?|bytes?|€|\$|USD|EUR)"
    r"|\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2})?\b"
    r"|(?:^|\s)[a-zA-Z0-9_./-]+/(?:[a-zA-Z0-9_./-]+)"
    r"|\b(?:p9[05]|p99[0-9]?|id\s*[:=]|uid\s*[:=]|run\s*#?\d+)\b",
    re.IGNORECASE)
"""Valeur observee concrete : chiffre+unite, date, chemin, p95/p99, id explicite."""


def find_evidence(block: str) -> bool:
    """Vrai si le bloc contient au moins une valeur observee concrete."""
    return any(EVIDENCE_RE.search(line) for line in block.splitlines())


def scope_items_of(plan_text: str, section: str = "## Hors périmètre") -> list:
    """Items de la section hors perimetre du livrable amont, nettoyees des puces."""
    body = section_body(plan_text, section)
    items = []
    for line in body.splitlines():
        match = re.match(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+(.+)$", line)
        if match:
            item = match.group(1).strip()
            if len(item) >= 3:
                items.append(item)
    return items


def scope_respected(downstream_text: str, item: str) -> bool:
    """Vrai si l'item hors perimetre du plan reste hors perimetre dans le livrable aval :
    soit il n'y est jamais mentionne, soit il est rappele dans une ligne qui le marque
    explicitement hors perimetre / exclus. Comparaison insensible a la casse : la prose
    francaise ne conserve pas la casse de l'item du plan."""
    wanted = item.casefold()
    for line in downstream_text.splitlines():
        if wanted not in line.casefold():
            continue
        if re.search(r"(?i)hors\s+p[eéè]rim[eè]tre|exclu|non\s+couver|defer|report[eé]",
                     line):
            continue
        return False
    return True


def validate_stage(root: Path, pipe: dict, stage_id: str, file_override=None) -> dict:
    stage = registry.find_agent(stage_id)
    if stage is None:
        return {"stage": stage_id, "file": None, "ok": False,
                "errors": [f"Agent inconnu du registre : {stage_id}. "
                           "Lister les agents disponibles : aidlc.py agents"],
                "warnings": [], "checks_run": 0}
    if not stage.get("produces"):
        return {"stage": stage_id, "file": None, "ok": False,
                "errors": [f"L'agent '{stage_id}' ne produit pas de livrable "
                           "(pas de champ 'produces') : rien a valider."],
                "warnings": [], "checks_run": 0}
    path = Path(file_override).resolve() if file_override else (root / stage["produces"])
    return run_checks(root, stage, path)


def stage_for_file(root: Path, pipe: dict, file_path: str):
    """L'agent dont le livrable est exactement ce fichier. Delegue au registre : le
    noyau ne tient plus de liste d'etapes."""
    return registry.agent_for_file(root, file_path)
