from __future__ import annotations

import json

from pathlib import Path

from . import registry
from .util import PROJECT_CONFIG
from .util import PROJECT_KEYS
from .util import ensure_dir
from .util import now_iso
from .util import project_config_path
from .util import read_text
from .util import write_json

"""Amorcage d'un projet consommateur : sa gouvernance, ses dossiers, son bundle OKF.

Le harnais suppose un projet **existant** : une equipe installe les plugins dans un
depot qui a deja son code, son histoire et sa documentation. Rien n'amorcait ce
contexte — la premiere etape s'ouvrait sur un entretien a froid, et le `librarian`
n'avait aucun bundle a servir puisqu'il n'en existait pas encore. Le premier livrable
d'un projet mature etait donc redige sans que le harnais ait regarde le projet.

Cette passe est **deterministe et modeste** : elle ne resume rien, elle n'interprete
rien. Elle inventorie les sources de verite deja presentes (README, ADR, manifestes de
dependances, docs/) et les depose dans un concept OKF que le librarian saura servir.
Le sens reste a l'humain et aux agents ; ce module ne pose que la table.

Elle ne detruit jamais : un fichier qui existe est conserve tel quel et rapporte dans
`kept`. Relancer `init` est sans effet de bord.
"""

#: Fichiers de la racine qui font autorite sur « qu'est-ce que ce projet ».
#: # ponytail: liste fermee et profondeur 1, jamais de parcours recursif — un rglob
#: traverserait node_modules et vendor. Plafond : un README enfoui n'est pas vu.
#: Upgrade si ca gene : lire les chemins declares dans aidlc.json.
ROOT_SOURCES = (
    "README.md", "README.rst", "README.txt", "CONTRIBUTING.md", "CHANGELOG.md",
    "ARCHITECTURE.md", "CLAUDE.md", "AGENTS.md",
)

#: Manifestes de dependances : ils disent la pile technique sans qu'on ait a la deviner.
MANIFESTS = (
    "package.json", "pyproject.toml", "requirements.txt", "setup.py", "pom.xml",
    "build.gradle", "build.gradle.kts", "go.mod", "Cargo.toml", "Gemfile",
    "composer.json", "Dockerfile", "docker-compose.yml",
)

#: Dossiers de documentation explores a profondeur 1.
DOC_DIRS = ("docs", "doc", "adr", "decisions")

#: Lignes que tout projet consommateur a interet a ignorer : caches jetables.
GITIGNORE_LINES = (".aidlc/tmp/", ".aidlc/logs/")

INDEX_TEMPLATE = """---
okf_version: "0.2"
---
# Base de connaissance du projet

Memoire longue de ce projet : normes internes, decisions d'architecture, vocabulaire et
retours d'experience, au format Open Knowledge Format v0.2. Les agents du harnais AI-DLC
la lisent par le `librarian` ; chaque concept est un fichier Markdown a frontmatter, ce
sommaire en est la porte d'entree et `log.md` le journal des versements.

# Concepts
* [Sources du projet existant](sources/projet-existant.md) - Inventaire des sources de verite deja presentes dans le depot au moment de l'amorcage du harnais.
"""

LOG_TEMPLATE = """# Journal de la base de connaissance

## {date}
* **Amorcage du bundle** — `aidlc.py init` a cree ce bundle et inventorie les sources de
  verite deja presentes dans le depot. Cet inventaire est un point de depart, pas un
  etat des lieux : completez-le, et versez ici tout concept qu'un agent devra citer.
"""

CONCEPT_HEADER = """---
type: Reference
title: Sources du projet existant
description: Inventaire des sources de verite deja presentes dans le depot au moment de l'amorcage du harnais.
tags: [projet, sources, amorcage]
generated: {{ by: aidlc.py init, at: {ts} }}
---

# Sources du projet existant

Ce projet existait avant le harnais. Les fichiers ci-dessous ont ete trouves a la racine
et dans les dossiers de documentation au moment de l'amorcage : ce sont les sources que
les agents d'etape doivent citer plutot que de reinterroger l'humain sur ce qui est deja
ecrit. La liste est **brute** — aucun contenu n'a ete lu ni resume.

Tenez-la a jour : un agent qui cite une source disparue trace une reference morte.
"""


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def scan_sources(root: Path) -> dict:
    """Inventaire deterministe des sources de verite du depot d'accueil.

    Trois familles, parce qu'elles ne se citent pas de la meme facon : la documentation
    racine dit l'intention, les manifestes disent la pile, les dossiers de docs disent
    les decisions. Aucune n'est lue : on rend des chemins.
    """
    found = {"documentation": [], "manifests": [], "decisions": []}
    for name in ROOT_SOURCES:
        if (root / name).is_file():
            found["documentation"].append(name)
    for name in MANIFESTS:
        if (root / name).is_file():
            found["manifests"].append(name)
    for folder in DOC_DIRS:
        directory = root / folder
        if not directory.is_dir():
            continue
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_file() and entry.suffix.lower() in (".md", ".rst", ".adoc"):
                found["decisions"].append(_relative(root, entry))
    return found


def render_concept(sources: dict, ts: str) -> str:
    """Le concept OKF de l'inventaire. Un titre de section par famille, des liens
    relatifs — donc des aretes traversables par `knowledge links`."""
    out = [CONCEPT_HEADER.format(ts=ts)]
    titles = (("documentation", "## Documentation du depot"),
              ("manifests", "## Pile technique declaree"),
              ("decisions", "## Documentation et decisions"))
    for key, title in titles:
        out.append(title)
        if sources[key]:
            # Le concept vit dans knowledge/sources/ : deux crans pour rejoindre la
            # racine du depot, ou vivent les fichiers inventories.
            out.extend("* [{}](../../{})".format(path, path) for path in sources[key])
        else:
            out.append("* Aucun fichier de cette famille trouve a l'amorcage.")
        out.append("")
    return "\n".join(out)


def render_config(pipe: dict, agents: list) -> dict:
    """La gouvernance du projet, prete a etre editee.

    Les seuils sont recopies plutot que laisses implicites : une equipe qui ouvre ce
    fichier voit l'exigence a laquelle elle est tenue et peut la discuter, au lieu de la
    subir depuis une copie installee qu'elle n'a pas le droit d'ouvrir. `agents` fige le
    workflow de l'initiative : ce que la machine a installe ne decide plus de ce que le
    projet execute.
    """
    return {
        "_comment": "Gouvernance de CE projet. Recouvre le pipeline.json du harnais, "
                    "cle par cle. 'agents' declare le workflow de l'initiative : seuls "
                    "ces agents composent le pipeline, meme si d'autres plugins sont "
                    "installes sur la machine.",
        "maturity_threshold": pipe.get("maturity_threshold", 4.0),
        "min_axis_score": pipe.get("min_axis_score", 3.0),
        "consecutive_runs_to_autonomy": pipe.get("consecutive_runs_to_autonomy", 3),
        "agents": agents,
        # La feuille de route du projet, c'est ce qui lui **reste** a installer : une
        # etape deja portee par un plugin decouvert n'est plus « prevue », elle est la.
        "planned_stages": [stage for stage in pipe.get("planned_stages", [])
                           if stage.get("id") not in set(agents)],
    }


def _gitignore_additions(root: Path) -> list:
    """Les lignes de .gitignore qui manquent encore (comparaison ligne a ligne exacte)."""
    path = root / ".gitignore"
    present = set()
    if path.is_file():
        present = {line.strip() for line in read_text(path).splitlines()}
    return [line for line in GITIGNORE_LINES if line not in present]


def init_project(root: Path, pipe: dict) -> dict:
    """Amorce le projet consommateur. Ne remplace jamais un fichier existant.

    Rend `created` (ce qui a ete pose), `kept` (ce qui existait deja, laisse tel quel)
    et `sources` (l'inventaire du depot d'accueil) — de quoi dire a l'humain ce qui
    vient de changer chez lui, ce que ni un message generique ni un exit code ne font.
    """
    created, kept = [], []

    def place(rel: str, write) -> None:
        target = root / rel
        if target.exists():
            kept.append(rel)
            return
        ensure_dir(target.parent)
        write(target)
        created.append(rel)

    ts = now_iso()
    sources = scan_sources(root)
    catalog = registry.catalog()
    declared = [agent["id"] for agent in catalog["agents"]]

    place(PROJECT_CONFIG,
          lambda target: write_json(target, render_config(pipe, declared)))
    place("deliverables/.gitkeep", lambda target: target.write_text("", encoding="utf-8"))
    place("knowledge-sources.json", lambda target: write_json(target, {"sources": []}))
    place("knowledge/index.md",
          lambda target: target.write_text(INDEX_TEMPLATE, encoding="utf-8"))
    place("knowledge/log.md",
          lambda target: target.write_text(LOG_TEMPLATE.format(date=ts[:10]),
                                           encoding="utf-8"))
    place("knowledge/sources/projet-existant.md",
          lambda target: target.write_text(render_concept(sources, ts), encoding="utf-8"))

    additions = _gitignore_additions(root)
    if additions:
        path = root / ".gitignore"
        existing = read_text(path).rstrip("\n") + "\n" if path.is_file() else ""
        path.write_text(existing + "\n".join(additions) + "\n", encoding="utf-8")
        created.append(".gitignore ({})".format(", ".join(additions)))

    return {
        "root": str(root),
        "created": created,
        "kept": kept,
        "agents": declared,
        "sources": sources,
        "config": PROJECT_CONFIG if project_config_path(root).is_file() else None,
    }


def render_init(result: dict) -> str:
    """Compte rendu humain : ce qui a ete pose, ce qui existait, et la suite."""
    lines = ["Projet amorce : {}".format(result["root"]), ""]
    for rel in result["created"]:
        lines.append("  cree   {}".format(rel))
    for rel in result["kept"]:
        lines.append("  garde  {} (existait deja, non modifie)".format(rel))
    total = sum(len(paths) for paths in result["sources"].values())
    lines.append("")
    lines.append("{} source(s) du projet existant inventoriee(s) dans "
                 "knowledge/sources/projet-existant.md.".format(total))
    if result["agents"]:
        lines.append("Workflow declare dans {} : {}".format(
            PROJECT_CONFIG, ", ".join(result["agents"])))
    else:
        lines.append("Aucun agent decouvert : installez les plugins de vos equipes, puis "
                     "completez la cle 'agents' de {}.".format(PROJECT_CONFIG))
    lines.append("Relisez {} — c'est votre exigence et votre workflow, pas ceux du "
                 "harnais.".format(PROJECT_CONFIG))
    lines.append("Ensuite : aidlc.py status, puis la skill /aidlc-core:run.")
    return "\n".join(lines)


def config_problems(root: Path) -> list:
    """Ce qui, dans l'aidlc.json du projet, ne veut rien dire.

    Un fichier de gouvernance ne se relit qu'une fois par trimestre : une cle mal
    orthographiee y survivrait longtemps, et le projet tournerait sur les seuils du
    harnais en croyant tenir les siens. On lit le fichier brut, pas la vue filtree par
    `project_config`, qui a justement deja jete l'inconnu.
    """
    path = project_config_path(root)
    if not path.is_file():
        return []
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        return [f"{path.name} : JSON invalide ({exc})."]
    if not isinstance(data, dict):
        return [f"{path.name} : le fichier doit contenir un objet JSON."]
    problems = []
    for key in data:
        if key not in PROJECT_KEYS and not key.startswith("_"):
            problems.append(f"{path.name} : cle inconnue '{key}' — elle est ignoree.")
    agents = data.get("agents")
    if agents is not None and not isinstance(agents, list):
        problems.append(f"{path.name} : 'agents' doit etre une liste d'identifiants.")
    for key in ("maturity_threshold", "min_axis_score"):
        if key in data and not isinstance(data[key], (int, float)):
            problems.append(f"{path.name} : '{key}' doit etre un nombre.")
    return problems
