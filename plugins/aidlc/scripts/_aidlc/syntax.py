from __future__ import annotations

import json
import os
import py_compile
import tempfile

from pathlib import Path
from .util import read_text
"""Hygiene syntaxique du depot : tout Python compile, tout JSON parse (regle 6 non
negociable du depot), exposee en sous-commandes du moteur (check-python, check-json) —
la porte dure de la CI et du developpement local, et le controle au fil de l'eau des
fichiers .py/.json ecrits en session (--touched). Rien n'est ecrit dans le depot : les
.pyc jetables partent dans un dossier temporaire, les JSON sont lus sans transformation."""

# ----------------------------------------------------------------------- syntax

# On parcourt le depot en ignorant ce qui n'en fait pas partie (historique git) et les
# caches. # ponytail: pas de lecture de .gitignore — on saute .git et __pycache__ et
# rien d'autre ; l'etat local hors depot (ex. .freebuff/) ne porte aucun .py/.json.
SKIP_DIRS = {".git", "__pycache__"}


def _iter_sources(root: Path, suffix: str):
    """Chemins relatifs (posix) des fichiers de suffixe donne sous root, tries, hors
    repertoires ignores. Ordre stable : dirnames et filenames tries, sans symlink."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        base = Path(dirpath)
        for name in sorted(filenames):
            if name.endswith(suffix):
                yield (base / name).relative_to(root).as_posix()


def _python_problem(path: Path) -> str | None:
    """Description du probleme de compilation d'un fichier Python, None si conforme.
    # ponytail: py_compile exige un cfile regulier (refuse /dev/null) : chaque fichier
    compile vers un .pyc jetable d'un dossier temporaire — rien n'est ecrit cote depot.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            py_compile.compile(str(path), cfile=str(Path(tmp) / "sink.pyc"),
                               doraise=True)
    except py_compile.PyCompileError as exc:
        detail = getattr(exc, "exc_value", None)
        if isinstance(detail, SyntaxError) and detail.lineno:
            return f"erreur de syntaxe ligne {detail.lineno} : {detail.msg}"
        return str(exc)
    except OSError as exc:
        return f"illisible ({exc.strerror or exc})"
    return None


def _json_problem(path: Path) -> str | None:
    """Description du probleme de parsing d'un fichier JSON, None si conforme."""
    try:
        json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        return f"JSON invalide ligne {exc.lineno} colonne {exc.colno} : {exc.msg}"
    except OSError as exc:
        return f"illisible ({exc.strerror or exc})"
    return None


def python_report(root: Path) -> dict:
    """Rapport de compilation de tout Python sous root, sans aucune sortie (pur).
    Erreurs : chemin relatif + probleme. Les fichiers illisibles comptent aussi : un
    depot gate doit etre lisible.
    """
    errors = []
    checked = 0
    for rel in _iter_sources(root, ".py"):
        checked += 1
        problem = _python_problem(root / rel)
        if problem:
            errors.append(f"{rel} : {problem}")
    return {"dir": str(root), "ok": not errors, "checked": checked,
            "errors": errors}


def json_report(root: Path) -> dict:
    """Rapport de parsing de tout JSON sous root, sans aucune sortie (pur)."""
    errors = []
    checked = 0
    for rel in _iter_sources(root, ".json"):
        checked += 1
        problem = _json_problem(root / rel)
        if problem:
            errors.append(f"{rel} : {problem}")
    return {"dir": str(root), "ok": not errors, "checked": checked,
            "errors": errors}
