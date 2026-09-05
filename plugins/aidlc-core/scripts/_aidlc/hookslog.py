from __future__ import annotations

import json
import os
import uuid

from pathlib import Path
from . import registry
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
LOG_TAIL_BYTES = 64 * 1024
"""Queue de journal relue pour retrouver la derniere etape d'une session."""

PAYLOAD_KEYS = [
    "hook_event_name", "tool_name", "tool_input", "tool_response", "prompt",
    "source", "message", "reason", "trigger", "stop_hook_active", "permission_mode",
]
"""Journalisation JSONL des sessions et garde-fou d'ecriture sur les artefacts de score (.aidlc/)."""

# ----------------------------------------------------------------------- log/guard

def current_stage_id(root: Path, pipe: dict):
    try:
        stages = registry.stages()
        for stage in stages:
            if not (root / stage["produces"]).exists():
                return stage["id"]
            if not validate_stage(root, pipe, stage["id"])["ok"]:
                return stage["id"]
        return stages[-1]["id"] if stages else None
    except Exception:
        return None


def stage_from_payload(root: Path, data: dict):
    """Etape portee par l'evenement lui-meme : le chemin de fichier qu'il touche.

    Chemin exact du livrable d'un agent d'abord (certitude), sinon le repertoire de ce
    livrable — l'ecriture porte alors sur une annexe, ou sur le livrable avant sa
    creation. Deux agents qui partagent un repertoire : le premier de l'ordre gagne,
    ce qui est deja un defaut de conception a corriger cote manifestes.
    """
    tool_input = data.get("tool_input") or {}
    target = (tool_input.get("file_path") or tool_input.get("notebook_path")
              or data.get("file_path"))
    if not target:
        return None
    agent = registry.agent_for_file(root, target)
    if agent:
        return agent["id"]
    try:
        resolved = Path(target).resolve()
    except OSError:
        return None
    for stage in registry.stages():
        try:
            resolved.relative_to((root / stage["produces"]).parent.resolve())
        except (OSError, ValueError):
            continue
        return stage["id"]
    return None


def last_known_stage(root: Path, session_id: str):
    """Derniere etape attribuee dans cette session. Une session qui vient d'ecrire un
    livrable garde son etape pour les evenements qui ne portent aucun chemin (prompt,
    demarrage, arret) : c'est de la continuite constatee, pas une devinette.

    # ponytail: on ne relit que la queue du journal. Plafond : une etape attribuee il y
    # a plus de LOG_TAIL_BYTES est oubliee, l'evenement retombe alors sur l'etape
    # courante du pipeline. Upgrade : indexer la derniere etape par session si les
    # journaux deviennent enormes.
    """
    log_path = aidlc_dir(root) / "logs" / f"{session_id}.jsonl"
    try:
        with log_path.open("rb") as handle:
            handle.seek(max(0, log_path.stat().st_size - LOG_TAIL_BYTES))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("stage"):
            return entry["stage"]
    return None


def guess_stage(root: Path, pipe: dict, data: dict, session_id: str):
    """Etape d'un evenement de hook, par fiabilite decroissante : le chemin de fichier
    qu'il porte, puis la derniere etape attribuee dans la meme session, puis l'etape
    courante du pipeline.

    Aucune correspondance n'est cherchee dans le texte libre. L'ancienne heuristique
    reconnaissait l'identifiant d'une etape comme mot du prompt : « le plan de charge »
    etait attribue a `plan`, « lance les test » a `test`, ce qui faussait
    `improve --stage` et le detecteur de relances du watchdog. Un registre ouvert
    aggrave le probleme, les identifiants d'agents etant des mots courants choisis par
    chaque equipe.
    """
    try:
        return (stage_from_payload(root, data)
                or last_known_stage(root, session_id)
                or current_stage_id(root, pipe))
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
        "stage": guess_stage(root, pipe, data, session_id),
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
    # Ordre impératif : test de chemin pur d'abord. Ce hook tourne à chaque Write avec
    # un timeout de 5 s ; la découverte des manifestes (I/O) n'a lieu que pour une cible
    # déjà connue comme extérieure au projet, donc jamais sur le chemin chaud courant.
    try:
        resolved.relative_to(root.resolve())
        return None
    except (OSError, ValueError):
        pass
    reason = _harness_protection_reason(root, resolved)
    if reason:
        return reason
    return _agent_protection_reason(resolved)


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
    return ("Ecriture refusee : la copie installée du harnais (hors du projet) est sa "
            "liste protégée (pipeline.json, checks/, hooks/, script, agents, skills, "
            "templates). Un agent n'édite pas les règles qui le jugent ; faire évoluer "
            "le harnais dans son dépôt auteur, via /aidlc-core:improve ou "
            "/aidlc-core:new-stage.")


def _agent_protection_reason(resolved: Path):
    """Le plugin d'un agent d'une autre équipe, installé hors du projet, est protégé au
    même titre que le noyau : chaque équipe reste maîtresse de son agent, et une session
    ne réécrit pas l'implémentation d'une direction voisine depuis le cache de plugins.
    N'est appelée qu'après le test de chemin pur (cible hors du projet)."""
    try:
        for agent in registry.agents_list():
            if agent.get("in_project"):
                continue
            try:
                resolved.relative_to(Path(agent["root"]).resolve())
            except (OSError, ValueError):
                continue
            return ("Ecriture refusée : {} appartient au plugin de l'agent '{}' (équipe "
                    "{}), installé hors de ce projet. Chaque équipe maintient son agent "
                    "dans son propre dépôt ; ici, seul son manifeste est lu."
                    .format(resolved.name, agent["id"], agent.get("team") or "inconnue"))
    except Exception:
        return None
    return None
