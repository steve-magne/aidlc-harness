from __future__ import annotations

import json
import os
import uuid

from pathlib import Path
from . import registry
from .util import PROJECT_CONFIG
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
    "hook_event_name", "tool_name", "tool_input", "tool_error", "prompt",
    "notification_type", "source", "message", "reason", "trigger", "stop_hook_active",
    "permission_mode",
]
# `tool_output` est volontairement absent : la sortie d'un outil (un Read entier) est le
# plus gros champ du payload et aucun diagnostic ne la relit. `tool_error`, lui, dit
# pourquoi un outil a echoue — c'est la matiere de PostToolUseFailure.

# ponytail: du `tool_input` d'une ecriture, seuls les chemins sont relus dans le journal
# (attribution d'etape, comptage du watchdog). Journaliser le reste ferait entrer le
# contenu des fichiers ecrits dans .aidlc/logs/ — deux kilo-octets par ecriture, qui
# consommeraient la fenetre de LOG_TAIL_BYTES en une trentaine d'evenements et y
# recopieraient le travail en clair. Plafond : un consommateur futur qui aurait besoin
# d'un autre champ d'entree l'ajoute ici.
TOOL_INPUT_KEYS = ("file_path", "notebook_path")
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
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        payload["tool_input"] = {k: v for k, v in tool_input.items()
                                 if k in TOOL_INPUT_KEYS}
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

    Depuis que le hook `log` est branche sur PostToolUse, il ecrit cette entree en
    premier et la dedup la trouve : cette fonction ne fait alors rien. Elle reste le
    filet du cas ou la journalisation generale n'a pas eu lieu (hook en timeout,
    plateforme qui ne cable que check-okf), et c'est cette dedup qui empeche l'ecriture
    d'etre comptee deux fois par le watchdog.
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
    reason = _config_protection_reason(root, resolved)
    if reason:
        return reason
    reason = _deliverable_protection_reason(root, resolved, data)
    if reason:
        return reason
    # Ordre impératif : test de chemin pur d'abord. Ce hook tourne à chaque Write avec
    # un timeout de 5 s ; la découverte des manifestes (I/O) n'a lieu que pour une cible
    # déjà connue comme extérieure au projet — ou, juste au-dessus, pour une écriture que
    # le payload attribue à un sous-agent nommé. Le Write courant d'une session, lui, ne
    # la déclenche jamais.
    try:
        resolved.relative_to(root.resolve())
        return None
    except (OSError, ValueError):
        pass
    reason = _harness_protection_reason(root, resolved)
    if reason:
        return reason
    return _agent_protection_reason(resolved)


def _actor_agent_id(data: dict):
    """Id de registre du sous-agent qui declenche le hook, ou None s'il n'est pas nomme.

    Claude Code designe un sous-agent par son invocation (`aidlc-plan:plan`) ; c'est
    exactement ce que porte le bloc `invocation` du manifeste. L'id nu est accepte aussi,
    pour une plateforme qui nommerait autrement.
    """
    name = str(data.get("agent_type") or data.get("agent_id") or "").strip()
    if not name:
        return None
    try:
        for agent in registry.agents_list():
            if name == agent["id"] or name in (agent.get("invocation") or {}).values():
                return agent["id"]
    except Exception:
        return None
    return None


def _deliverable_protection_reason(root: Path, resolved: Path, data: dict):
    """Le livrable d'un agent appartient a cet agent : personne d'autre ne l'ecrit.

    La chaine producteur -> consommateur n'ordonne plus rien si n'importe quel agent peut
    ecrire n'importe quel maillon : l'agent aval qui « corrige » son entree amont se
    fabrique le contrat sur lequel il sera juge, et la porte de l'etape amont note un
    texte que son propre agent n'a pas ecrit. Le refus est nominatif — il ne mord que sur
    le `produces` exact d'un autre agent, jamais sur une annexe ou une note de travail.

    # ponytail: ne mord que si le payload nomme l'agent courant. Sans identite (session
    # principale, plateforme qui ne transmet rien), aucun refus : un garde-fou qui devine
    # bloquerait du travail legitime, et la porte dure reste `validate` + le reviewer.
    # Le test d'identite est un pur test de dict, donc le chemin chaud (Write ordinaire)
    # ne declenche aucune I/O de decouverte.
    """
    actor = _actor_agent_id(data)
    if actor is None:
        return None
    for agent in registry.agents_list():
        produces = agent.get("produces")
        if not produces or agent["id"] == actor:
            continue
        try:
            if resolved != (root / produces).resolve():
                continue
        except (OSError, ValueError):
            continue  # `produces` illegal dans un manifeste : il ne protege rien
        return ("Écriture refusée : {} est le livrable de l'agent « {} » (équipe {}), pas "
                "celui de « {} ». Un agent n'écrit que son propre `produces` ; une entrée "
                "amont qui ne convient pas se corrige en relançant l'agent qui la "
                "produit.".format(produces, agent["id"], agent.get("team") or "inconnue",
                                  actor))
    return None


def _config_protection_reason(root: Path, resolved: Path):
    """Protege la gouvernance du projet (aidlc.json) : c'est le metre, pas un livrable.

    Ce fichier porte le seuil de maturite, le plancher par axe et la liste des agents qui
    composent le pipeline. Un agent qui pourrait l'ecrire abaisserait le seuil qui le juge,
    ou se retirerait de la liste pour echapper a sa porte — exactement ce que la liste
    protegee interdit deja pour `.aidlc/` et pour la copie installee du harnais. Il est
    hors de `.aidlc/` (il se versionne avec le projet), donc il lui faut sa propre garde.

    `aidlc.py init` l'ecrit en Python, pas par un outil d'edition : ce refus ne le gene pas.
    """
    if resolved != (root / PROJECT_CONFIG).resolve():
        return None
    return ("Écriture refusée : {} porte la gouvernance du projet — seuil de maturité, "
            "plancher par axe, et la liste des agents qui composent le pipeline. Un agent "
            "n'édite pas les règles qui le jugent. C'est une décision d'équipe : elle se "
            "prend à la main, dans un terminal.".format(PROJECT_CONFIG))


#: Noms de premier niveau sous .aidlc/ que la garde connait. Tout autre premier
#: segment est un nom d'initiative : la protection le traverse pour retrouver le
#: fichier qu'elle protege.
AIDLC_ENTRIES = ("maturity.json", "reviews", "ratchet.json", "improvement-queue.jsonl",
                 "experiments.jsonl", "logs")


def _aidlc_protection_reason(root: Path, resolved: Path):
    """Protege l'etat runtime (.aidlc/) : integrite du score, revues signees, ratchet,
    file d'amelioration, journaux — seuls les scripts ecrivent, jamais un agent.

    La garde porte sur **tout** `.aidlc/`, pas sur le seul sous-dossier de l'initiative
    courante : sinon, declarer une nouvelle initiative deverrouillerait les scores et les
    signatures de la precedente — soit exactement la fraude que cette fonction existe
    pour empecher.
    """
    protected_root = (root / ".aidlc").resolve()
    try:
        relative = resolved.relative_to(protected_root)
    except ValueError:
        return None
    parts = relative.parts
    if parts and parts[0] not in AIDLC_ENTRIES and len(parts) > 1:
        parts = parts[1:]
    if parts and parts[0] == "maturity.json":
        return ("Écriture refusée : .aidlc/maturity.json est l'intégrité du score. "
                "Passer par `aidlc.py score <stage> --file <review.json>`.")
    if len(parts) >= 2 and parts[0] == "reviews" and parts[1].endswith(".json") \
            and not parts[1].endswith(".template.json"):
        return ("Écriture refusée : les revues humaines .aidlc/reviews/*.json sont signées "
                "par un humain. Utiliser `aidlc.py review-request <stage>` et laisser "
                "l'humain remplir le fichier.")
    if parts and parts[0] == "ratchet.json":
        return ("Écriture refusée : .aidlc/ratchet.json fige les planchers de validation. "
                "Seul `aidlc.py ratchet` écrit ce fichier ; toute modification hors de "
                "cette sous-commande est une fraude au mètre.")
    if parts and parts[0] == "improvement-queue.jsonl":
        return ("Écriture refusée : la file d'amélioration est alimentée par les refus "
                "(humains, gate OKF, watchdog), jamais éditée à la main.")
    if parts and parts[0] == "experiments.jsonl":
        return ("Écriture refusée : .aidlc/experiments.jsonl est la mémoire de la "
                "boucle d'amélioration — ce qui a été corrigé, et l'effet mesuré. "
                "Passer par `aidlc.py experiment record` ; antidater une expérience "
                "reviendrait à se noter soi-même.")
    if parts and parts[0] == "logs":
        return ("Écriture refusée : les journaux .aidlc/logs/*.jsonl sont la matière "
                "première du diagnostic (autonomie, watchdog). Ils ne sont éditables "
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
    return ("Écriture refusée : la copie installée du harnais (hors du projet) est sa "
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
            return ("Écriture refusée : {} appartient au plugin de l'agent « {} » (équipe "
                    "{}), installé hors de ce projet. Chaque équipe maintient son agent "
                    "dans son propre dépôt ; ici, seul son manifeste est lu."
                    .format(resolved.name, agent["id"], agent.get("team") or "inconnue"))
    except Exception:
        return None
    return None
