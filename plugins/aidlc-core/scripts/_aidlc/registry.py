from __future__ import annotations

import json
import os
import re

from pathlib import Path
from .util import harness_root
from .util import read_text
from .util import workspace_root
"""Registre ouvert des agents : decouverte des manifestes agent.json, validation de
forme, index des capacites et ordre d'invocation derive de la chaine producteur ->
consommateur. C'est la source de verite de « quels agents existent » — le noyau ne
tient plus de liste. Un agent qui declare `produces` est une etape gouvernee
(validate / score / gate / ratchet) ; sans `produces`, il est consultatif."""

MANIFEST_NAME = "agent.json"
MANIFEST_VERSION = 1
REQUIRED = ("manifest_version", "id", "team", "description", "capabilities", "invocation")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
CAPABILITY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")

# ponytail: cache memoire pour la duree du processus, jamais sur disque. Le guard
# PreToolUse tourne a chaque Write (timeout 5 s) et peut appeler la decouverte
# plusieurs fois ; un cache disque vivrait dans .aidlc/ (protege) et ajouterait une
# classe entiere de bugs de peremption. Plafond : un manifeste ajoute pendant qu'une
# commande tourne n'est pas vu. Upgrade : invalider sur mtime des racines.
_CACHE = {}


def reset_cache() -> None:
    """Oublie le catalogue memorise. A appeler apres avoir cree ou retire un manifeste
    dans le meme processus (scaffold, auto-test) : le registre a reellement change."""
    _CACHE.clear()


def default_platform() -> str:
    """Plateforme d'invocation courante. Le manifeste est neutre : seul le bloc
    `invocation` est indexe par plateforme, et c'est la toute la separation entre le
    contrat d'integration et l'implementation."""
    return (os.environ.get("AIDLC_PLATFORM") or "claude-code").strip()


# ------------------------------------------------------------------- decouverte

def _env_roots() -> list:
    """AIDLC_AGENT_PATH : racines explicites separees par os.pathsep. C'est le contrat
    documente — portable, utilisable en CI et sous Codex, testable."""
    raw = os.environ.get("AIDLC_AGENT_PATH") or ""
    return [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]


def _repo_roots() -> list:
    """plugins/ du depot auteur (voisin du noyau) et du projet consommateur."""
    roots = []
    harness = harness_root()
    if harness.parent.name == "plugins":
        roots.append(harness.parent)
    roots.append(workspace_root() / "plugins")
    return roots


def _installed_roots() -> list:
    """Plugins installes par Claude Code, au mieux.

    installed_plugins.json est un fichier interne non documente (son champ `version`
    prouve qu'il a deja change de forme) et il n'existe pas sous Codex : cette source
    n'est JAMAIS porteuse. Toute erreur est silencieuse, jamais une exception ni un
    code de sortie. Repli sur la disposition du cache, a profondeur fixe.
    """
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    try:
        data = json.loads(read_text(config / "plugins" / "installed_plugins.json"))
        roots = []
        for entries in (data.get("plugins") or {}).values():
            for entry in entries if isinstance(entries, list) else []:
                install = isinstance(entry, dict) and entry.get("installPath")
                if install:
                    roots.append(Path(install))
        if roots:
            return roots
    except Exception:
        pass
    try:
        # <config>/plugins/cache/<marketplace>/<plugin>/<version>/ — profondeur fixe.
        return sorted((config / "plugins" / "cache").glob("*/*/*"))
    except OSError:
        return []


def _scan(root: Path) -> list:
    """Manifestes sous une racine : <root>/agent.json puis <root>/*/agent.json.

    Profondeur 1 au maximum, jamais de parcours recursif : cette fonction est sur le
    chemin chaud du hook guard, et un glob recursif traverserait des node_modules.
    """
    found = []
    try:
        if not root.is_dir():
            return found
        if (root / MANIFEST_NAME).is_file():
            found.append(root / MANIFEST_NAME)
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and (entry / MANIFEST_NAME).is_file():
                found.append(entry / MANIFEST_NAME)
    except OSError:
        pass
    return found


def validate_manifest(data, source: str) -> list:
    """Problemes de forme d'un manifeste. Liste vide = manifeste utilisable."""
    if not isinstance(data, dict):
        return [f"{source} : le manifeste doit etre un objet JSON."]
    if data.get("manifest_version") != MANIFEST_VERSION:
        return [f"{source} : manifest_version {data.get('manifest_version')!r} non "
                f"supporte (ce noyau lit la version {MANIFEST_VERSION})."]
    problems = []
    for key in REQUIRED:
        value = data.get(key)
        if value is None or (isinstance(value, (str, list, dict)) and not value):
            problems.append(f"{source} : champ obligatoire manquant ou vide '{key}'.")
    agent_id = data.get("id")
    if isinstance(agent_id, str) and not ID_RE.match(agent_id):
        problems.append(f"{source} : id '{agent_id}' invalide (minuscules, chiffres, "
                        "tiret et underscore).")
    capabilities = data.get("capabilities")
    if capabilities is not None and not isinstance(capabilities, list):
        problems.append(f"{source} : 'capabilities' doit etre une liste de chaines.")
    elif isinstance(capabilities, list):
        for capability in capabilities:
            if not isinstance(capability, str) or not CAPABILITY_RE.match(capability):
                problems.append(f"{source} : capacite invalide {capability!r} "
                                "(convention domaine:action).")
    invocation = data.get("invocation")
    if invocation is not None and not isinstance(invocation, dict):
        problems.append(f"{source} : 'invocation' doit etre un objet "
                        "{plateforme: invocation}.")
    elif isinstance(invocation, dict):
        for platform, value in invocation.items():
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{source} : invocation['{platform}'] doit etre une "
                                "chaine non vide.")
    for key in ("consumes", "requires"):
        if data.get(key) is not None and not isinstance(data[key], list):
            problems.append(f"{source} : '{key}' doit etre une liste.")
    if data.get("produces") is not None and not isinstance(data["produces"], str):
        problems.append(f"{source} : 'produces' doit etre le chemin d'un fichier unique.")
    if data.get("review") is not None and not isinstance(data["review"], str):
        problems.append(f"{source} : 'review' doit etre le chemin d'un fichier de "
                        "rubrique, relatif au plugin.")
    return problems


def _normalize(data: dict, manifest: Path, project: Path) -> dict:
    """Manifeste valide -> entree de catalogue. `root` sert a resoudre `checks`
    relativement au plugin de l'equipe ; `in_project` porte la severite (un manifeste
    du depot est de notre responsabilite, celui d'une autre equipe ne l'est pas)."""
    root = manifest.parent
    try:
        root.resolve().relative_to(project.resolve())
        in_project = True
    except (OSError, ValueError):
        in_project = False
    return {
        "id": data["id"],
        "team": data.get("team"),
        "version": data.get("version"),
        "description": data.get("description"),
        "capabilities": list(data.get("capabilities") or []),
        "invocation": dict(data.get("invocation") or {}),
        "produces": data.get("produces"),
        "consumes": list(data.get("consumes") or []),
        "requires": list(data.get("requires") or []),
        "checks": data.get("checks"),
        "review": data.get("review"),
        "human_role": data.get("human_role"),
        "manifest": str(manifest),
        "root": str(root),
        "in_project": in_project,
    }


def discover(refresh: bool = False) -> dict:
    """Catalogue brut : agents valides, problemes de forme, avertissements.

    Precedence : AIDLC_AGENT_PATH, puis les plugins du depot et du projet, puis les
    plugins installes par Claude Code. Dedoublonnage par id, premiere source gagnante,
    doublon signale avec les deux equipes proprietaires — deux directions qui publient
    le meme id est une panne d'entreprise reelle, pas un detail.
    """
    key = (os.environ.get("AIDLC_AGENT_PATH"), str(workspace_root()), str(harness_root()),
           os.environ.get("CLAUDE_CONFIG_DIR"))
    if not refresh and key in _CACHE:
        return _CACHE[key]

    project = workspace_root()
    agents, problems, warnings, seen = [], [], [], {}
    # Les racines se recouvrent legitimement — dans le depot auteur, le harnais et le
    # projet sont le meme dossier. Dedoublonner les chemins reels evite de signaler un
    # faux doublon d'identifiant sur un manifeste vu deux fois.
    roots, files = [], set()
    for root in _env_roots() + _repo_roots() + _installed_roots():
        try:
            real = root.resolve()
        except OSError:
            continue
        if real not in files:
            files.add(real)
            roots.append(root)
    files = set()
    for root in roots:
        for manifest in _scan(root):
            try:
                real = manifest.resolve()
            except OSError:
                continue
            if real in files:
                continue
            files.add(real)
            try:
                data = json.loads(read_text(manifest))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{manifest} : manifeste illisible ({exc}).")
                continue
            found = validate_manifest(data, str(manifest))
            if found:
                problems.extend(found)
                continue
            agent = _normalize(data, manifest, project)
            first = seen.get(agent["id"])
            if first:
                warnings.append(
                    "Identifiant en double '{}' : {} (equipe {}) ignore au profit de {} "
                    "(equipe {}).".format(agent["id"], agent["manifest"], agent["team"],
                                          first["manifest"], first["team"]))
                continue
            seen[agent["id"]] = agent
            agents.append(agent)

    result = {"agents": agents, "problems": problems, "warnings": warnings}
    _CACHE[key] = result
    return result


# ------------------------------------------------------------------------- ordre

def order(agents: list) -> tuple:
    """(agents ordonnes, cycle). L'ordre n'est plus positionnel : il se derive de la
    chaine producteur -> consommateur (produces / consumes) et de `requires`. Tri
    stable par id pour departager les agents independants. Une dependance vers un
    agent absent du catalogue n'immobilise rien : elle ressort dans missing_producers.
    """
    by_product = {}
    for agent in agents:
        if agent.get("produces"):
            by_product.setdefault(agent["produces"], agent["id"])
    known = {agent["id"] for agent in agents}
    deps = {}
    for agent in agents:
        needed = set(agent.get("requires") or [])
        for path in agent.get("consumes") or []:
            producer = by_product.get(path)
            if producer:
                needed.add(producer)
        needed.discard(agent["id"])
        deps[agent["id"]] = needed & known

    ordered, placed = [], set()
    remaining = sorted(agents, key=lambda agent: agent["id"])
    while remaining:
        ready = [agent for agent in remaining if deps[agent["id"]] <= placed]
        if not ready:
            return ordered, sorted(agent["id"] for agent in remaining)
        for agent in ready:
            ordered.append(agent)
            placed.add(agent["id"])
        remaining = [agent for agent in remaining if agent["id"] not in placed]
    return ordered, []


def missing_producers(agents: list) -> list:
    """Entrees attendues que personne ne produit : le plugin producteur n'est pas
    installe. C'est ce qui empeche le tableau de bord de retrecir en silence quand un
    plugin manque sur une machine."""
    produced = {agent["produces"] for agent in agents if agent.get("produces")}
    holes = []
    for agent in agents:
        for path in agent.get("consumes") or []:
            if path not in produced:
                holes.append({"agent": agent["id"], "input": path})
    return holes


# ---------------------------------------------------------------------- catalogue

def catalog(capability: str = None, platform: str = None, refresh: bool = False) -> dict:
    """Vue ordonnee du registre, filtree par capacite si demande. C'est l'entree de
    l'orchestrateur : le script sait qui existe, l'agent sait qui appeler."""
    found = discover(refresh)
    platform = platform or default_platform()
    agents, cycle = order(found["agents"])
    if capability:
        agents = [agent for agent in agents if capability in agent["capabilities"]]
    rows = []
    for agent in agents:
        row = dict(agent)
        row["invocable"] = platform in agent["invocation"]
        row["invoke"] = agent["invocation"].get(platform)
        row["kind"] = "stage" if agent.get("produces") else "capability"
        rows.append(row)
    capabilities = {}
    for agent in found["agents"]:
        for name in agent["capabilities"]:
            capabilities.setdefault(name, []).append(agent["id"])
    return {
        "platform": platform,
        "agents": rows,
        "capabilities": {name: sorted(ids) for name, ids in sorted(capabilities.items())},
        "missing_producers": missing_producers(found["agents"]),
        "cycle": cycle,
        "problems": found["problems"],
        "warnings": found["warnings"],
    }


def agents_list(refresh: bool = False) -> list:
    """Tous les agents du registre, dans l'ordre d'invocation."""
    return order(discover(refresh)["agents"])[0]


def stages(refresh: bool = False) -> list:
    """Les agents gouvernes (ceux qui produisent un livrable), dans l'ordre. Successeur
    de l'ancien tableau pipeline.json.stages[]."""
    return [agent for agent in agents_list(refresh) if agent.get("produces")]


def find_agent(agent_id: str, refresh: bool = False):
    for agent in agents_list(refresh):
        if agent["id"] == agent_id:
            return agent
    return None


def next_agent_id(agent_id: str):
    """Etape suivante dans l'ordre derive — successeur de util.next_stage_id."""
    ids = [agent["id"] for agent in stages()]
    if agent_id in ids:
        position = ids.index(agent_id) + 1
        if position < len(ids):
            return ids[position]
    return None


def agent_for_file(root: Path, file_path: str):
    """L'agent dont le livrable est exactement ce fichier (comparaison de chemin
    exacte, comme l'ancien checks.stage_for_file)."""
    try:
        target = Path(file_path).resolve()
    except OSError:
        return None
    for agent in stages():
        try:
            if (root / agent["produces"]).resolve() == target:
                return agent
        except OSError:
            continue
    return None
