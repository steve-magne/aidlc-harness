from __future__ import annotations

import json
import re
import subprocess

from pathlib import Path
from .okf import okf_split_frontmatter
from .util import ensure_dir
from .util import read_text
"""Bundles OKF distants : sources declarees par le projet, cache local, sommaire,
recherche et lecture d'un concept.

Le but est l'economie de contexte : un agent lit un sommaire (une ligne par concept),
cherche des identifiants, puis n'ouvre que les un ou deux concepts utiles — au lieu de
parcourir un depot entier. C'est exactement la divulgation progressive de la spec OKF
v0.2 (index.md, frontmatter), appliquee a des depots distants.
"""

SOURCES_FILE = "knowledge-sources.json"
RESERVED = ("index.md", "log.md")  # fichiers reserves de la spec, jamais des concepts
_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")
_FLOW_LIST = re.compile(r"^\[(.*)\]$")


def sources_path(root: Path) -> Path:
    return root / SOURCES_FILE


def cache_root(root: Path) -> Path:
    # .aidlc/tmp/ est deja jetable et hors versionnement : un cache clone y est chez lui.
    return root / ".aidlc" / "tmp" / "knowledge"


def load_sources(root: Path) -> list:
    """Sources OKF declarees par le projet consommateur. Liste vide si non declarees.

    Le fichier est edite par un humain : une entree malformee leve, elle n'est pas
    ignoree en silence.
    """
    path = sources_path(root)
    if not path.exists():
        return []
    entries = json.loads(read_text(path)).get("sources", [])
    out = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        repo = str(entry.get("repo") or "").strip()
        sub = str(entry.get("path") or "").strip().strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or not repo or ".." in sub:
            raise ValueError(f"{SOURCES_FILE} : source invalide (name, repo, path) : {entry}")
        out.append({"name": name, "repo": repo, "path": sub,
                    "ref": str(entry.get("ref") or "").strip()})
    return out


def _git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=300)


def sync(root: Path, source: dict, refresh: bool = False) -> Path:
    """Chemin local du bundle d'une source, materialise si besoin.

    Un `repo` qui designe un dossier existant est utilise tel quel (bundle monte, depot
    voisin, ou test) ; sinon il est clone en profondeur 1 dans le cache.
    """
    local = Path(source["repo"]).expanduser()
    if not local.is_dir():
        local = cache_root(root) / source["name"]
        if not (local / ".git").is_dir():
            ensure_dir(local.parent)
            args = ["clone", "--depth", "1"]
            if source["ref"]:
                args += ["--branch", source["ref"]]
            res = _git([*args, source["repo"], str(local)])
            if res.returncode != 0:
                raise RuntimeError("{} : clone impossible - {}".format(
                    source["name"], res.stderr.strip()[:300]))
        elif refresh:
            res = _git(["pull", "--ff-only", "--depth", "1"], cwd=local)
            if res.returncode != 0:
                raise RuntimeError("{} : mise a jour impossible - {}".format(
                    source["name"], res.stderr.strip()[:300]))
    return (local / source["path"]).resolve() if source["path"] else local.resolve()


def front_values(text: str) -> dict:
    """Frontmatter d'un concept, reduit aux scalaires et aux listes en flux [a, b].

    # ponytail: meme sous-ensemble YAML que _aidlc.okf, pour la meme raison (pas de
    parseur YAML en stdlib). Les mappings en flux sont ignores : title, description,
    type et tags suffisent a router vers un concept.
    """
    front, _, state = okf_split_frontmatter(text)
    if state != "ferme":
        return {}
    values = {}
    for line in front.splitlines():
        match = _KEY.match(line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2).strip().strip("\"'")
        flow = _FLOW_LIST.match(raw)
        if flow:
            values[key] = [v.strip().strip("\"'") for v in flow.group(1).split(",") if v.strip()]
        elif raw and not raw.startswith("{"):
            values[key] = raw
    return values


def concepts(bundle: Path, source_name: str) -> list:
    """Concepts du bundle, un dict par fichier : reference, type, titre, description."""
    out = []
    for path in sorted(bundle.rglob("*.md")) if bundle.is_dir() else []:
        if path.name in RESERVED:
            continue
        values = front_values(read_text(path))
        rel = path.relative_to(bundle).as_posix()[:-3]
        tags = values.get("tags", [])
        out.append({"source": source_name, "ref": f"{source_name}/{rel}",
                    "type": values.get("type", ""),
                    "title": values.get("title", "") or Path(rel).name.replace("-", " "),
                    "description": values.get("description", ""),
                    "tags": tags if isinstance(tags, list) else [],
                    "path": str(path)})
    return out


def catalog(root: Path, refresh: bool = False, only: str = None) -> dict:
    """Catalogue agrege de toutes les sources declarees (une source en echec n'en bloque
    aucune autre : son erreur est reportee)."""
    sources, entries, errors = load_sources(root), [], []
    if only:
        sources = [s for s in sources if s["name"] == only]
        if not sources:
            errors.append(f"source inconnue : {only}")
    for source in sources:
        try:
            entries.extend(concepts(sync(root, source, refresh), source["name"]))
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            errors.append(str(exc))
    return {"sources": [s["name"] for s in sources], "concepts": entries, "errors": errors}


def search(entries: list, terms: list) -> list:
    """Concepts contenant tous les termes (frontmatter ou corps), les correspondances de
    frontmatter d'abord."""
    words = [t.lower() for t in terms if t.strip()]
    hits = []
    for entry in entries:
        head = " ".join([entry["ref"], entry["type"], entry["title"],
                         entry["description"], " ".join(entry["tags"])]).lower()
        body = read_text(Path(entry["path"])).lower()
        if not all(word in head or word in body for word in words):
            continue
        hits.append((-sum(word in head for word in words), entry["ref"], entry))
    return [entry for _, _, entry in sorted(hits, key=lambda hit: hit[:2])]


def render(entries: list) -> str:
    """Une ligne par concept : reference, type, titre, description. Le format compact
    est le produit du CLI — c'est ce qui tient dans le contexte d'un agent."""
    lines = []
    for entry in entries:
        line = entry["ref"]
        if entry["type"]:
            line += f" [{entry['type']}]"
        line += " - " + entry["title"]
        if entry["description"]:
            line += " : " + entry["description"]
        lines.append(line)
    return "\n".join(lines)


def resolve(entries: list, ref: str):
    """Concept designe par <source>/<concept-id>, ou None. La source est facultative
    quand l'identifiant est sans ambiguite."""
    exact = [e for e in entries if e["ref"] == ref]
    if exact:
        return exact[0]
    suffix = [e for e in entries if e["ref"].endswith("/" + ref.strip("/"))]
    return suffix[0] if len(suffix) == 1 else None
