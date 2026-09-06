from __future__ import annotations

import json
import os

from pathlib import Path
from . import registry
from .util import ensure_dir
from .util import harness_root
from .util import read_text
from .util import write_json
"""Generation du plugin d'un agent : squelettes, manifeste agent.json, contrat checks.json
et inscription au marketplace du depot. Le noyau n'est jamais modifie — c'est la condition
pour qu'une equipe publie son agent sans toucher a l'orchestrateur."""

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

REVIEW_MD = """# Rubrique de revue — étape {name}

Ce fichier appartient à l'équipe **{team}**. Il ne remplace pas la grille universelle du reviewer
(`aidlc-core`) : il dit ce que chaque axe veut dire **pour ce livrable**, et quelles fautes de ce
métier sont rédhibitoires. Le barème (0-5), le calcul de la note globale, le plancher par axe et
l'enregistrement du score restent au noyau — une équipe ne note pas sa propre copie.

## `completeness` — ce que « complet » veut dire ici
- <Section de ce livrable qui doit porter de la substance, et ce qui compte comme creux.>

## `precision` — ce que « testable » veut dire ici
- <Ce qui doit être chiffré dans ce métier, avec son unité et sa référence.>

## `traceability` — ce que « tracé » veut dire ici
- <Ce que ce livrable doit citer : {inputs}, et les sources de vérité du métier.>

## `autonomy`
Grille universelle. <Nuance propre à l'étape, s'il y en a une.>

## Fautes rédhibitoires (verdict `rejected`, quelle que soit la moyenne)
- <Faute de ce métier qu'aucune moyenne ne rachète.>
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


def planned_stage(pipe: dict, stage_id: str) -> dict:
    """Entree de la feuille de route consultative (pipeline.json > planned_stages), si
    l'etape y figure. C'est un pre-remplissage, jamais une condition : un agent peut
    naitre sans avoir ete prevu."""
    for stage in pipe.get("planned_stages", []):
        if stage.get("id") == stage_id:
            return dict(stage)
    return {}


def _load_marketplace(market_path: Path, base: Path) -> dict:
    """Marketplace du depot, ou un squelette neuf s'il n'existe pas encore.

    Un fichier present mais illisible leve un ValueError explicite, comme les deux
    autres gardes de `scaffold` — et non la JSONDecodeError brute qui remontait
    jusqu'a l'appelant sans nommer le fichier ni le geste correctif.
    """
    if not market_path.exists():
        return {"name": "aidlc", "owner": {"name": "Steve"}, "plugins": []}
    try:
        return json.loads(read_text(market_path))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{os.path.relpath(market_path, base)} est illisible ({exc}) : "
            "reparer le JSON du marketplace avant de generer un agent.") from exc


def scaffold(pipe: dict, stage_id: str, force: bool = False) -> dict:
    """Genere le plugin d'un agent dans le depot auteur (jamais dans le projet
    consommateur), avec son manifeste agent.json et son contrat checks.json, et
    l'inscrit au marketplace du depot.

    Le noyau n'est pas touche : ni pipeline.json, ni miroir de contrat. C'est ce qui
    permet a chaque equipe de publier son agent de facon autonome — l'orchestrateur le
    decouvre par son manifeste.
    """
    if registry.find_agent(stage_id) and not force:
        raise ValueError(f"L'agent '{stage_id}' existe deja dans le registre "
                         "(utiliser --force).")
    stage = planned_stage(pipe, stage_id)
    base = authoring_root()
    plugin_dir = base / "plugins" / f"aidlc-{stage_id}"
    if plugin_dir.exists() and not force:
        raise ValueError(f"{os.path.relpath(plugin_dir, base)} existe deja (utiliser --force).")
    # Le marketplace est lu ICI, avant la moindre ecriture : un fichier illisible doit
    # arreter le scaffold avant qu'il ne laisse un plugin a moitie genere derriere lui.
    market_path = base / ".claude-plugin" / "marketplace.json"
    market = _load_marketplace(market_path, base)

    name = stage.get("name", stage_id.capitalize())
    deliverable = stage.get("deliverable", f"deliverables/{stage_id}/{stage_id}.md")
    template_name = Path(deliverable).name
    inputs = stage.get("inputs", [])
    team = stage.get("team", "<equipe proprietaire de cet agent>")
    inputs_txt = ", ".join(inputs) if inputs else "aucun"
    inputs_list = "\n".join(f"- `{i}`" for i in inputs) if inputs else "- Aucun input amont."
    role = stage.get("human_role", "role metier a preciser")
    fmt = dict(stage=stage_id, name=name, deliverable=deliverable, role=role,
               inputs=inputs_txt, inputs_list=inputs_list, template=template_name,
               team=team)

    created = []
    for rel, content in [
        (".claude-plugin/plugin.json", PLUGIN_JSON.format(**fmt)),
        (f"agents/{stage_id}-analyst.md", AGENT_MD.format(**fmt)),
        (f"skills/{stage_id}/SKILL.md", SKILL_MD.format(**fmt)),
        (f"templates/{template_name}", TEMPLATE_MD.format(**fmt)),
        # La rubrique de revue nait avec l'agent : sans elle, le reviewer noterait
        # l'etape a la grille universelle sans que personne ait dit ce que « precis »
        # veut dire pour ce metier.
        ("review.md", REVIEW_MD.format(**fmt)),
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

    # Le manifeste : le seul contrat que l'orchestrateur lit. Tout y est neutre sauf
    # `invocation`, indexe par plateforme — c'est la, et seulement la, que vit
    # l'implementation propre a Claude Code ou a Codex.
    manifest = {
        "manifest_version": 1,
        "id": stage_id,
        "team": team,
        "version": "0.1.0",
        "description": f"Etape {name} du cycle de vie : produit {deliverable}.",
        "capabilities": [f"sdlc:{stage_id}"],
        "invocation": {"claude-code": f"aidlc-{stage_id}:{stage_id}"},
        "produces": deliverable,
        "consumes": inputs,
        "checks": "checks.json",
        "review": "review.md",
        "human_role": role,
    }
    manifest_path = plugin_dir / "agent.json"
    write_json(manifest_path, manifest)
    created.append(os.path.relpath(manifest_path, base))
    registry.reset_cache()  # le registre vient de changer dans ce processus

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
            "manifest": os.path.relpath(manifest_path, base),
            "next": f"Éditer {os.path.relpath(manifest_path, base)} (équipe "
                    f"propriétaire, capacités) et {os.path.relpath(checks_path, base)} "
                    f"et {os.path.relpath(plugin_dir / 'review.md', base)} "
                    f"pour coller au métier de l'étape."}
