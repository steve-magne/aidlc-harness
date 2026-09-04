from __future__ import annotations

import json
import os
import re
import uuid

from pathlib import Path
from .util import aidlc_dir
from .util import ensure_dir
from .util import load_pipeline
from .util import now_iso
from .util import read_text
from .util import sanitize_session_id
from .util import truncate
from .checks import validate_stage

# ponytail: liste blanche des cles de payload journalisees. Plafond : un hook exotique
# perd ses champs specifiques. Upgrade : journaliser l'entree entiere tronquee.
PAYLOAD_KEYS = [
    "hook_event_name", "tool_name", "tool_input", "tool_response", "prompt",
    "source", "message", "reason", "trigger", "stop_hook_active", "permission_mode",
]
"""Journalisation JSONL des sessions et garde-fou d'ecriture sur les artefacts de score (.aidlc/)."""

# ----------------------------------------------------------------------- log/guard

def current_stage_id(root: Path, pipe: dict):
    try:
        for stage in pipe.get("stages", []):
            deliverable = root / stage.get("deliverable", "")
            if not deliverable.exists():
                return stage["id"]
            if not validate_stage(root, pipe, stage["id"])["ok"]:
                return stage["id"]
        stages = pipe.get("stages", [])
        return stages[-1]["id"] if stages else None
    except Exception:
        return None


def guess_stage(root: Path, pipe: dict, raw: str):
    """Devine l'etape courante depuis le texte du hook.

    # ponytail: heuristique par sous-chaine (chemin de livrable puis identifiant d'etape).
    Plafond : un texte francais contenant "plan" peut faussement matcher. Upgrade : faire
    porter l'etape par une variable d'environnement posee par l'orchestrateur.
    """
    try:
        for stage in pipe.get("stages", []):
            folder = os.path.dirname(stage.get("deliverable", ""))
            if folder and folder in raw:
                return stage["id"]
        for stage in pipe.get("stages", []):
            if re.search(r"\b" + re.escape(stage["id"]) + r"\b", raw, re.IGNORECASE):
                return stage["id"]
        return current_stage_id(root, pipe)
    except Exception:
        return None


def handle_log(root: Path, raw: str) -> dict:
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        data = {"raw": truncate(str(data))}
    session_id = sanitize_session_id(
        data.get("session_id") or "unknown-" + uuid.uuid4().hex[:8])
    try:
        pipe = load_pipeline()
    except Exception:
        pipe = {"stages": []}
    payload = {k: truncate(data[k]) for k in PAYLOAD_KEYS if k in data}
    entry = {
        "ts": now_iso(),
        "event": data.get("hook_event_name", "unknown"),
        "session_id": session_id,
        "agent_id": data.get("agent_id"),
        "agent_type": data.get("agent_type"),
        "cwd": data.get("cwd"),
        "stage": guess_stage(root, pipe, raw[:8000]),
        "payload": payload,
    }
    log_path = ensure_dir(aidlc_dir(root) / "logs") / f"{session_id}.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def journal_bundle_write(root: Path, session_id: str | None, file_path: Path,
                         tool_name: str | None) -> None:
    """Journalise dans .aidlc/logs/<session>.jsonl une ecriture dans un bundle OKF
    (contexte du hook PostToolUse check-okf --touched), au format lu par la correlation
    d'improve : event=PostToolUse, payload.tool_name et tool_input.file_path. Dedupe :
    une meme session n'enregistre qu'une fois un meme fichier — la correlation cherche
    qui a ecrit le fichier fautif, pas combien de fois il a ete retouche.
    """
    if not session_id:
        return
    try:
        target = file_path.resolve()
    except OSError:
        return
    log_path = ensure_dir(aidlc_dir(root) / "logs") / f"{session_id}.jsonl"
    if log_path.exists():
        for line in read_text(log_path).splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = entry.get("payload") or {}
            prev = (payload.get("tool_input") or {}).get("file_path")
            if not prev or payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
                continue
            try:
                if Path(prev).resolve() == target:
                    return
            except OSError:
                if os.path.normpath(prev) == os.path.normpath(str(target)):
                    return
    entry = {"ts": now_iso(), "event": "PostToolUse", "session_id": session_id,
             "payload": {"tool_name": tool_name or "Write",
                         "tool_input": {"file_path": str(target)}}}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def guard_decision(root: Path, raw: str):
    """Retourne un motif de refus si le hook veut ecrire dans les artefacts de score."""
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        return None
    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not target:
        return None
    try:
        resolved = Path(target).expanduser().resolve()
    except OSError:
        return None
    protected_root = aidlc_dir(root).resolve()
    try:
        relative = resolved.relative_to(protected_root)
    except ValueError:
        return None
    parts = relative.parts
    if parts and parts[0] == "maturity.json":
        return ("Ecriture refusee : .aidlc/maturity.json est l'integrite du score. "
                "Passer par `aidlc.py score <stage> --file <review.json>`.")
    if len(parts) >= 2 and parts[0] == "reviews" and parts[1].endswith(".json") \
            and not parts[1].endswith(".template.json"):
        return ("Ecriture refusee : les revues humaines .aidlc/reviews/*.json sont signees "
                "par un humain. Utiliser `aidlc.py review-request <stage>` et laisser "
                "l'humain remplir le fichier.")
    return None
