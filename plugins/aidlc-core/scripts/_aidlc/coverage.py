from __future__ import annotations

import json
import subprocess
import sys
import tempfile

from pathlib import Path

from .util import aidlc_dir
from .util import harness_root
from .util import now_iso
from .util import read_text
from .util import write_json

"""Ratchet de couverture : la couverture du moteur par sa suite ne descend jamais.

Meme geste que `ratchet.py` sur les planchers de severite, applique au taux de lignes
executees. Premier passage : on fige l'etat courant (`baseline`). Ensuite, toute
regression au-dela de la tolerance echoue avec exit 2 — la CI rougit. Monter est libre
et re-fige automatiquement ; descendre exige `aidlc.py coverage --reset`.

Mesure par `trace`, de la bibliotheque standard : aucune dependance ajoutee.
"""

#: Marge acceptee avant de crier a la regression, en points de pourcentage.
#: # ponytail: un refactor qui supprime des lignes deplace mecaniquement le taux de
#: quelques dixiemes sans rien tester de moins. Plafond assume : une regression reelle
#: inferieure a ce seuil passe. Upgrade si ca gene : figer le NOMBRE de lignes non
#: couvertes plutot que le taux.
TOLERANCE = 0.5

#: Prefixe des fichiers .cover a retenir : le moteur, rien d'autre.
_PREFIX = "_aidlc."

#: Modules exclus de la mesure : la suite ne se mesure pas elle-meme.
_EXCLUDED = {"tests", "selftest"}


def coverage_path(root: Path) -> Path:
    return aidlc_dir(root) / "coverage.json"


def entrypoint() -> Path:
    return harness_root() / "scripts" / "aidlc.py"


def _parse_cover(path: Path) -> tuple:
    """(lignes executees, lignes jamais executees) d'un fichier .cover produit par
    `trace --count --missing`. Les lignes mortes y sont prefixees par `>>>>>>`, les
    autres par leur compteur d'executions."""
    executed = missing = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(">>>>>>"):
            missing += 1
        elif line[:6].strip().rstrip(":").isdigit():
            executed += 1
    return executed, missing


def measure(select: str = None) -> dict:
    """Execute la suite sous `trace` et rend la couverture ligne par module.

    Le sous-processus isole la mesure de la session courante : la suite manipule des
    variables d'environnement et des repertoires temporaires, on ne veut rien de tout
    cela dans le processus qui mesure.

    # ponytail: `trace` ne suit pas les sous-processus, donc les tests de contrat CLI
    (qui relancent aidlc.py) ne comptent pas dans la mesure. Plafond assume : la
    couverture rendue est un plancher, jamais surestimee. Upgrade si ca gene :
    poser un sitecustomize.py qui arme trace dans les enfants.
    """
    script = entrypoint()
    if not script.exists():
        raise FileNotFoundError(f"Point d'entree introuvable : {script}")
    with tempfile.TemporaryDirectory() as tmp:
        command = [sys.executable, "-m", "trace", "--count", "--missing",
                   f"--coverdir={tmp}", str(script), "test"]
        if select:
            command += ["-k", select]
        run = subprocess.run(command, capture_output=True, text=True, check=False)
        modules, total_exec, total_miss = {}, 0, 0
        for cover in sorted(Path(tmp).glob(f"{_PREFIX}*.cover")):
            name = cover.name[len(_PREFIX):-len(".cover")]
            if name.split(".")[0] in _EXCLUDED or name == "__init__":
                continue
            executed, missing = _parse_cover(cover)
            if executed + missing == 0:
                continue
            modules[name] = {
                "executed": executed, "missing": missing,
                "pct": round(100 * executed / (executed + missing), 1),
            }
            total_exec += executed
            total_miss += missing
    if not modules:
        raise RuntimeError(
            "Aucune donnee de couverture produite. La suite a-t-elle echoue ?\n"
            + (run.stderr or "")[-2000:])
    return {
        "suite_passed": run.returncode == 0,
        "modules": modules,
        "total": round(100 * total_exec / (total_exec + total_miss), 1),
        "executed": total_exec,
        "missing": total_miss,
    }


def coverage_run(root: Path, select: str = None) -> dict:
    """Passe du ratchet de couverture : fige au premier passage, revalide ensuite.
    `passed` faux = au moins un module a perdu de la couverture (exit 2 pour la CI)."""
    path = coverage_path(root)
    fresh = measure(select)
    was_absent = not path.exists()
    floors = {}
    if not was_absent:
        try:
            floors = json.loads(read_text(path)).get("modules", {})
        except json.JSONDecodeError:
            was_absent, floors = True, {}

    regressions = []
    for name, floor in sorted(floors.items()):
        current = fresh["modules"].get(name)
        if current is None:
            regressions.append({"module": name, "before": floor, "after": None,
                                "reason": "module disparu de la mesure"})
        elif current["pct"] < floor - TOLERANCE:
            regressions.append({"module": name, "before": floor,
                                "after": current["pct"],
                                "reason": "couverture en baisse"})

    # Un plancher ne descend jamais : on garde le maximum entre le fige et le mesure.
    merged = dict(floors)
    for name, current in fresh["modules"].items():
        merged[name] = max(float(merged.get(name, 0.0)), current["pct"])

    if not regressions:
        write_json(path, {"ts": now_iso(), "baseline": was_absent,
                          "total": fresh["total"], "modules": merged})

    out = {
        "coverage": str(path),
        "baseline": was_absent,
        "suite_passed": fresh["suite_passed"],
        "total": fresh["total"],
        "executed": fresh["executed"],
        "missing": fresh["missing"],
        "modules": fresh["modules"],
        "passed": not regressions and fresh["suite_passed"],
        "regressions": regressions,
    }
    if regressions:
        out["hint"] = ("La couverture ne descend jamais. Ajoutez les tests manquants, "
                       "ou, si la baisse est voulue (code supprime), rebasez le "
                       "plancher avec `aidlc.py coverage --reset`.")
    elif not fresh["suite_passed"]:
        out["hint"] = ("La suite elle-meme est rouge : `aidlc.py test` pour le detail. "
                       "Le plancher n'est pas mis a jour tant qu'elle ne passe pas.")
    return out


def coverage_reset(root: Path, select: str = None) -> dict:
    """Rebase explicite : le plancher repart de l'etat courant. Geste humain, trace."""
    fresh = measure(select)
    if not fresh["suite_passed"]:
        raise ValueError("Suite rouge : on ne rebase pas un plancher sur un échec.")
    stamp = now_iso()
    write_json(coverage_path(root),
               {"ts": stamp, "baseline": True, "reset_at": stamp,
                "total": fresh["total"],
                "modules": {n: c["pct"] for n, c in fresh["modules"].items()}})
    return {"reset_at": stamp, "total": fresh["total"],
            "modules": {n: c["pct"] for n, c in fresh["modules"].items()}}
