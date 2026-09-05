from __future__ import annotations

import json

from pathlib import Path
from . import registry
from .checks import validate_stage
from .maturity import enqueue_improvement
from .util import aidlc_dir
from .util import now_iso
from .util import read_text
from .util import sanitize_session_id
from .util import truncate
"""Watchdog (inspire du dark factory) : un tick n'a pas de memoire. Les journaux JSONL
des sessions sont la matiere premiere de trois detecteurs de stagnation — ecritures
repetees contre un contrat de validation qui echoue encore, boucle d'ecriture sur un
meme fichier par une meme session, relances humaines en rafale sur une meme etape.
Le watchdog arrete sur « la forme du blocage » : ses haltes alimentent la file
d'amelioration (kind: watchdog) et le diagnostic improve."""

# ---------------------------------------------------------------------- configuration

WATCHDOG_DEFAULTS = {
    "validation_failures_threshold": 5,   # ecritures contre un livrable encore en echec
    "write_loop_threshold": 6,            # ecritures d'une meme session sur un meme fichier
    "rerun_threshold": 5,                 # relances (UserPromptSubmit) sur une meme etape
    "window": 60,                         # fenetre glissante : derniers evenements par journal
}


def _watchdog_config(pipe: dict) -> dict:
    """Seuils du watchdog : defauts du moteur, surchargeables par un bloc `watchdog`
    de pipeline.json (c'est la seule configuration du watchdog)."""
    configured = dict(WATCHDOG_DEFAULTS)
    for key in WATCHDOG_DEFAULTS:
        value = (pipe.get("watchdog") or {}).get(key)
        if isinstance(value, (int, float)) and value > 0:
            configured[key] = int(value)
    return configured


# ------------------------------------------------------------------------ detection

def _events(root: Path, window: int) -> list:
    """Les `window` derniers evenements de chaque journal, tous journaux confondus,
    ordre chronologique (ts puis ordre fichier)."""
    log_dir = aidlc_dir(root) / "logs"
    if not log_dir.is_dir():
        return []
    events = []
    for path in sorted(log_dir.glob("*.jsonl")):
        lines = [line for line in read_text(path).splitlines() if line.strip()]
        for line in lines[-window:]:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    events.sort(key=lambda event: event.get("ts") or "")
    return events


def _write_counts(events: list) -> dict:
    """Ecritures par (session, fichier) et par fichier, d'apres les evenements
    PostToolUse journalises."""
    per_pair, per_file = {}, {}
    for event in events:
        payload = event.get("payload") or {}
        if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
            continue
        target = (payload.get("tool_input") or {}).get("file_path")
        if not target:
            continue
        pair = (event.get("session_id") or "?", target)
        per_pair[pair] = per_pair.get(pair, 0) + 1
        per_file[target] = per_file.get(target, 0) + 1
    return per_pair, per_file


def _detections(root: Path, pipe: dict) -> list:
    """Toutes les haltes detectees sur l'etat courant des journaux. Le detecteur
    validation_failures ne devine pas : il demande au moteur si le livrable echoue
    encore, et compte les ecritures qui s'acharnent dessus."""
    config = _watchdog_config(pipe)
    events = _events(root, config["window"])
    if not events:
        return []
    per_pair, per_file = _write_counts(events)
    detections = []

    # 1. Acharnement sur un contrat qui echoue : livrable present + validate en echec
    #    + assez d'ecritures dans la fenetre = l'agent iteration sans progresser, soit
    #    le livrable resiste, soit le checks.json est inadapte. Halte.
    for stage in registry.stages():
        stage_id = stage["id"]
        deliverable = root / stage["produces"]
        if not deliverable.exists():
            continue
        if validate_stage(root, pipe, stage_id)["ok"]:
            continue
        writes = per_file.get(str(deliverable.resolve()), 0)
        if writes >= config["validation_failures_threshold"]:
            detections.append({
                "detector": "validation_failures", "stage": stage_id,
                "count": writes, "threshold": config["validation_failures_threshold"],
                "detail": (f"{writes} ecritures contre le livrable de '{stage_id}' qui "
                           f"echoue encore a la validation (seuil "
                           f"{config['validation_failures_threshold']}) : le livrable "
                           "resiste ou le contrat est inadapte — halte, reprise humaine."),
            })

    # 2. Boucle d'ecriture : meme session, meme fichier, au-dela du seuil, independamment
    #    de l'etat de validation (un fichier non livre peut aussi tourner en boucle).
    for (session_id, target), count in sorted(per_pair.items(), key=lambda kv: -kv[1]):
        if count >= config["write_loop_threshold"]:
            detections.append({
                "detector": "write_loop", "stage": None, "session_id": session_id,
                "file": target, "count": count,
                "threshold": config["write_loop_threshold"],
                "detail": (f"la session {session_id} a ecrit {count} fois le meme fichier "
                           f"(seuil {config['write_loop_threshold']}) : boucle d'iteration "
                           "sans progression — halte, reprise humaine."),
            })

    # 3. Rafale de relances : beaucoup de tours (UserPromptSubmit) sur la meme etape =
    #    la session patine.
    reruns = {}
    for event in events:
        if event.get("event") != "UserPromptSubmit":
            continue
        stage_id = event.get("stage")
        if stage_id:
            reruns[stage_id] = reruns.get(stage_id, 0) + 1
    for stage_id, count in sorted(reruns.items()):
        if count >= config["rerun_threshold"]:
            detections.append({
                "detector": "rerun_storm", "stage": stage_id,
                "count": count, "threshold": config["rerun_threshold"],
                "detail": (f"{count} relances humaines sur l'etape '{stage_id}' "
                           f"(seuil {config['rerun_threshold']}) : la session patine sur "
                           "la meme etape — halte, reprise humaine."),
            })
    return detections


def _enqueue_halts(root: Path, detections: list, session_id) -> None:
    """Chaque halte devient une entree de .aidlc/improvement-queue.jsonl (kind: watchdog),
    dedoublonnee par la politique commune (detector + stage/file + session)."""
    for detection in detections:
        item = {"kind": "watchdog", "ts": now_iso(),
                "session_id": session_id, "halted": True}
        item.update(truncate(detection))
        enqueue_improvement(root, item,
                            ("detector", "stage", "file", "session_id"))


# ------------------------------------------------------------------- points d'entree

def watchdog_check(root: Path, pipe: dict, session_id=None) -> dict:
    """Passe de diagnostic (commande `aidlc.py watchdog`, CI) : detecte, enregistre,
    rapporte. `halted` vrai = au moins une halte (exit 2 pour la CI)."""
    detections = _detections(root, pipe)
    _enqueue_halts(root, detections, session_id)
    return {
        "watchdog": True,
        "halted": bool(detections),
        "detections": detections,
        "generated_at": now_iso(),
    }


def watchdog_touched(root: Path, pipe: dict, payload: dict) -> None:
    """Mode hook PostToolUse : diagnostic apres chaque ecriture, non bloquant — le
    watchdog n'interrompt jamais une session qui travaille ; il enregistre la halte
    dans la file d'amelioration, et le diagnostic `aidlc.py watchdog` (ou la CI) la
    rend visible. Sans detection : silence total."""
    try:
        detections = _detections(root, pipe)
        if not detections:
            return
        session_id = sanitize_session_id(payload.get("session_id") or "") or None
        _enqueue_halts(root, detections, session_id)
    except Exception:
        pass  # un watchdog qui casse une session vaut moins que pas de watchdog
