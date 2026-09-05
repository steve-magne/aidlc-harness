from __future__ import annotations

import json
import os
import re
import uuid

from pathlib import Path
from .util import aidlc_dir
from .util import ensure_dir
from .util import harness_root
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
    """Retourne un motif de refus si le hook veut ecrire dans les artefacts de score
    (.aidlc/) ou dans le referentiel de regles du harnais (liste protégée)."""
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
    reason = _aidlc_protection_reason(root, resolved)
    if reason:
        return reason
    return _harness_protection_reason(root, resolved)


def _aidlc_protection_reason(root: Path, resolved: Path):
    """Protege l'etat runtime (.aidlc/) : integrite du score, revues signees, ratchet,
    file d'amelioration, journaux — seuls les scripts ecrivent, jamais un agent."""
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
    if parts and parts[0] == "ratchet.json":
        return ("Ecriture refusee : .aidlc/ratchet.json fige les planchers de validation. "
                "Seul `aidlc.py ratchet` ecrit ce fichier ; toute modification hors de "
                "cette sous-commande est une fraude au metre.")
    if parts and parts[0] == "improvement-queue.jsonl":
        return ("Ecriture refusee : la file d'amelioration est alimentee par les refus "
                "(humains, gate OKF, watchdog), jamais editee a la main.")
    if parts and parts[0] == "logs":
        return ("Ecriture refusee : les journaux .aidlc/logs/*.jsonl sont la matiere "
                "premiere du diagnostic (autonomie, watchdog). Ils ne sont editables "
                "que par le hook de journalisation.")
    return None


def _harness_protection_reason(root: Path, resolved: Path):
    """Liste protégée (inspirée du dark factory) : la copie du harnais située HORS du
    projet consommateur est protégée en entier — pipeline.json, contrats checks/,
    hooks.json, script, agents, skills, templates. Un agent n'édite pas les règles qui
    le jugent : le harnais évolue dans son dépôt auteur, via /aidlc-core:new-stage et
    /aidlc-core:improve. Invariant géométrique : tout ce qui est sous la racine du
    projet reste éditable (dépôt auteur, où les deux racines se confondent, livrables
    et knowledge du projet) ; seule la copie extérieure au projet est verrouillée.
    # ponytail: seuls les chemins attribués à Write ou Edit sont vus ici ; un
    contournement via Bash n'est pas intercepté — la CI (check-json, selftest) reste la
    porte dure."""
    try:
        harness = harness_root().resolve()
        resolved.relative_to(harness)
    except (OSError, ValueError):
        return None  # hors harnais : jamais concerne
    try:
        resolved.relative_to(root.resolve())
        return None  # sous le projet : livrables, knowledge, depot auteur — editable
    except (OSError, ValueError):
        pass
    return ("Ecriture refusee : la copie installée du harnais (hors du projet) est sa "
            "liste protégée (pipeline.json, checks/, hooks/, script, agents, skills, "
            "templates). Un agent n'édite pas les règles qui le jugent ; faire évoluer "
            "le harnais dans son dépôt auteur, via /aidlc-core:improve ou "
            "/aidlc-core:new-stage.")
