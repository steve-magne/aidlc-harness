from __future__ import annotations

import hashlib
import json
import os
import re
import sys

from pathlib import Path
from datetime import datetime
from datetime import timezone

MAX_FIELD = 2000
"""Socle du moteur : constantes, racines projet/harnais et IO (lecture, JSON, emission stdout, troncature)."""

# --------------------------------------------------------------------------- socle

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize_session_id(value) -> str:
    """Session assainie pour nommer un fichier .aidlc/logs/<id>.jsonl : alphanumerique,
    tiret, underscore, tronque a 80 caracteres (hooks log, --touched, --stop)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value))[:80]


def workspace_root() -> Path:
    """Racine du projet consommateur : la ou habitent deliverables/ et .aidlc/.

    = CLAUDE_PROJECT_DIR quand le script est appele depuis une session Claude Code
    (hook ou skill), sinon le repertoire courant. Le depot du harnais n'est plus le
    lieu des livrables : ils sont produits dans le projet qui consomme les plugins aidlc.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    return Path.cwd().resolve()


def harness_root() -> Path:
    """Racine du harnais installe : la ou vit pipeline.json (la gouvernance).

    Resolution, dans l'ordre :
      1. AIDLC_HARNESS_ROOT (test, ou usage explicite) ;
      2. CLAUDE_PLUGIN_ROOT, si un pipeline.json s'y trouve (hooks et skills du plugin) ;
      3. auto-localisation du script : pipeline.json monte a cote de scripts/, meme forme
         dans le depot auteur (plugins/aidlc-core/) et dans la copie installee par
         Claude Code (CLAUDE_PLUGIN_ROOT pointe le plugin) ;
      4. repli : le repertoire du script.
    """
    env = os.environ.get("AIDLC_HARNESS_ROOT")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root and (Path(plugin_root) / "pipeline.json").exists():
        return Path(plugin_root).resolve()
    here = Path(__file__).resolve().parent  # .../aidlc-core/scripts
    for candidate in (here, here.parent, *here.parent.parents):
        if (candidate / "pipeline.json").exists():
            return candidate
    return here.parent


#: Nom du fichier de gouvernance du **projet** consommateur, a sa racine. Le harnais
#: porte la gouvernance par defaut ; ce fichier-ci porte celle de l'initiative.
PROJECT_CONFIG = "aidlc.json"

#: Cles qu'un projet peut redefinir. Volontairement restreint : un projet regle son
#: exigence et declare son workflow, il ne redefinit pas le moteur.
PROJECT_KEYS = ("maturity_threshold", "min_axis_score", "consecutive_runs_to_autonomy",
                "watchdog", "planned_stages", "agents")


def project_config_path(root: Path = None) -> Path:
    return (root or workspace_root()) / PROJECT_CONFIG


def project_config(root: Path = None) -> dict:
    """Gouvernance declaree par le projet consommateur (aidlc.json a sa racine).

    Absent = dict vide : un projet qui n'en pose pas herite du harnais, ce qui est le
    cas courant. Illisible, en revanche, remonte : une config cassee silencieusement
    ignoree ferait tourner le pipeline sur des seuils que personne n'a choisis. Les
    appelants qui ne peuvent pas echouer (hooks) attrapent deja l'exception.
    """
    path = project_config_path(root)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("le fichier doit contenir un objet JSON", "{}", 0)
    return {key: value for key, value in data.items() if key in PROJECT_KEYS}


def load_pipeline() -> dict:
    """Gouvernance effective : celle du harnais, recouverte par celle du projet.

    Le harnais porte les defauts (seuils de maturite, autonomie, seuils du watchdog,
    feuille de route consultative `planned_stages`). Le projet consommateur les
    recouvre cle par cle dans son `aidlc.json` — c'est la seule facon pour une
    initiative de fixer SON exigence et SON workflow sans editer la copie installee du
    harnais, que le garde-fou protege. Ce fichier ne porte aucun registre d'etapes :
    « quels agents existent » se lit dans le registre ouvert (_aidlc.registry),
    alimente par les manifestes agent.json des plugins.
    """
    pipe = json.loads((harness_root() / "pipeline.json").read_text(encoding="utf-8"))
    pipe.update(project_config())
    return pipe


def aidlc_dir(root: Path) -> Path:
    return root / ".aidlc"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def digest(path: Path) -> str:
    """Empreinte courte d'un fichier ('' s'il est absent ou illisible). Sert a detecter
    qu'une entree amont a bouge depuis la revue de l'aval.

    # ponytail: on compare l'octet, pas le sens — une correction de typo dans l'amont
    perime l'aval. Plafond assume : une relance de reviewer de trop. Upgrade si ca gene :
    ne hasher que les sections citees par required_input_section.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def write_json(path: Path, data) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def emit(data) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def truncate(value, limit: int = MAX_FIELD):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + " ...[tronque]"
    if isinstance(value, dict):
        return {k: truncate(v, limit) for k, v in list(value.items())[:50]}
    if isinstance(value, list):
        return [truncate(v, limit) for v in value[:50]]
    return value
