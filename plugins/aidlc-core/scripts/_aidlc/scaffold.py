from __future__ import annotations

import json
import os

from pathlib import Path
from .util import ensure_dir
from .util import find_stage
from .util import harness_root
from .util import read_text
from .util import write_json
"""Generation du plugin d'une etape declaree : squelettes, checks miroir, inscription au marketplace, pipeline."""

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
2. Demander au `librarian` le contexte pertinent (bundle OKF `${{CLAUDE_PROJECT_DIR}}/knowledge/`).
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
