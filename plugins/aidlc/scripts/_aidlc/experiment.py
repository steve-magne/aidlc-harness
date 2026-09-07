from __future__ import annotations

import json
import statistics

from pathlib import Path

from . import registry
from .maturity import AXES
from .maturity import load_maturity
from .maturity import stage_maturity
from .util import aidlc_dir
from .util import ensure_dir
from .util import now_iso
from .util import read_text
from .util import truncate

"""Registre des experiences d'amelioration : ce qui a ete corrige dans le harnais, et
l'effet mesure sur les runs qui ont suivi.

La boucle collecte des signaux (refus humains, haltes du watchdog, gate OKF) et propose
des correctifs — mais rien ne gardait trace de ce qui avait ete applique. Sans cette
memoire, la boucle repropose indefiniment ce qui n'a pas marche et ne sait jamais ce qui
a marche : c'est un diagnostic, pas une boucle. Une correction est une **hypothese** : on
la date, on fige la moyenne de l'axe vise a cet instant, puis on la confronte aux runs
suivants. Le verdict est mesure, pas raconte.
"""

#: Cibles mesurables : les quatre axes de la rubrique, plus la note globale.
TARGETS = AXES + ["overall"]

#: Runs necessaires apres une correction avant de conclure quoi que ce soit.
#: # ponytail: deux runs, comme l'exige deja la skill improve. Plafond assume : deux
#: runs restent un echantillon minuscule. Upgrade si ca gene : exiger la fenetre
#: consecutive_runs_to_autonomy du pipeline.
MIN_RUNS_AFTER = 2

#: Amplitude en deca de laquelle on ne conclut rien (scores sur 0-5).
#: # ponytail: un demi-point, soit un run qui gagne un point entier sur deux runs.
#: Plafond assume : un effet reel plus fin est lu comme du bruit.
EFFECT_MARGIN = 0.5


def experiments_path(root: Path) -> Path:
    return aidlc_dir(root) / "experiments.jsonl"


def load_experiments(root: Path, stage_filter: str = None) -> list:
    """Le registre, ligne a ligne. Une ligne illisible est ignoree, jamais fatale : le
    diagnostic doit survivre a un fichier tronque."""
    path = experiments_path(root)
    if not path.exists():
        return []
    out = []
    for line in read_text(path).splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if stage_filter and item.get("stage") != stage_filter:
            continue
        out.append(item)
    return out


def _mean(runs: list, target: str):
    """Moyenne de l'axe (ou de la note globale) sur ces runs, None si aucune valeur."""
    values = []
    for run in runs:
        value = run.get("overall") if target == "overall" \
            else (run.get("scores") or {}).get(target)
        if value is not None:
            values.append(float(value))
    return round(statistics.fmean(values), 2) if values else None


def record(root: Path, stage_id: str, target: str, path: str, cause: str) -> dict:
    """Date une correction appliquee au harnais et fige la mesure d'avant.

    `baseline_runs` est le nombre de runs deja notes : c'est lui qui separe l'avant de
    l'apres. Seul ce module ecrit .aidlc/experiments.jsonl (un hook PreToolUse refuse
    l'edition a la main) — sinon l'apres pourrait etre antidate.
    """
    if target not in TARGETS:
        raise ValueError(
            "Cible inconnue : {} (attendu : {}).".format(target, ", ".join(TARGETS)))
    if registry.find_agent(stage_id) is None:
        raise ValueError(f"Agent inconnu du registre : {stage_id}")
    if not (cause or "").strip():
        raise ValueError(
            "Une experience sans cause enoncee n'est pas mesurable : --cause est requis.")
    runs = stage_maturity(load_maturity(root), stage_id)["runs"]
    entry = {
        "ts": now_iso(),
        "stage": stage_id,
        "target": target,
        "file": path,
        "cause": truncate(cause),
        "baseline": _mean(runs, target),
        "baseline_runs": len(runs),
    }
    destination = experiments_path(root)
    ensure_dir(destination.parent)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def effects(root: Path, stage_filter: str = None) -> list:
    """Chaque experience confrontee aux runs qui l'ont suivie.

    Verdicts : `pending` (pas encore assez de runs pour conclure), `improved`,
    `regressed`, `no_effect`, et `no_baseline` quand l'etape n'avait aucun run avant la
    correction — il y a alors une mesure, mais rien a quoi la comparer.
    """
    maturity = load_maturity(root)
    out = []
    for entry in load_experiments(root, stage_filter):
        runs = (maturity.get("stages", {}).get(entry.get("stage")) or {}).get("runs") or []
        floor = int(entry.get("baseline_runs") or 0)
        after = [run for run in runs if int(run.get("run") or 0) > floor]
        measured = _mean(after, entry.get("target"))
        baseline = entry.get("baseline")
        delta = (round(measured - float(baseline), 2)
                 if measured is not None and baseline is not None else None)
        if len(after) < MIN_RUNS_AFTER:
            verdict = "pending"
        elif delta is None:
            verdict = "no_baseline"
        elif delta >= EFFECT_MARGIN:
            verdict = "improved"
        elif delta <= -EFFECT_MARGIN:
            verdict = "regressed"
        else:
            verdict = "no_effect"
        out.append({**entry, "runs_after": len(after), "measured": measured,
                    "delta": delta, "verdict": verdict})
    return out
