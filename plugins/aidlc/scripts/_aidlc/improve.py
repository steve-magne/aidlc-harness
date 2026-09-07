from __future__ import annotations

import json
import re
import statistics

from pathlib import Path
from .okf import _okf_proposals
from .okf import _write_in_bundle
from .util import aidlc_dir
from .util import initiative
from .maturity import load_maturity
from .maturity import AXES
from .util import now_iso
from .util import read_text
from . import registry
from .checks import validate_stage
from .experiment import effects
"""Diagnostic d'amelioration : journaux de sessions, refus (humains + gate OKF), correlation et correctifs proposes."""

# ------------------------------------------------------------------------- improve

def iter_log_events(root: Path):
    log_dir = aidlc_dir(root) / "logs"
    if not log_dir.is_dir():
        return
    for path in sorted(log_dir.glob("*.jsonl")):
        for line in read_text(path).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def workflow_signals(root: Path, maturity: dict, events_per_stage: dict) -> dict:
    """Ce qui se juge au niveau de la chaine, pas au niveau d'un plugin.

    La boucle savait corriger un contrat, un gabarit ou une consigne — jamais dire
    « cette etape ne sert a rien » ou « il manque un maillon ». Ces quatre signaux sont
    les seuls que le depot peut etablir seul, sans avis : un trou producteur ->
    consommateur, un agent branche qui n'a jamais tourne, un agent publie que personne
    n'a branche, et le cout en tentatives de chaque etape. Le jugement reste humain.
    """
    catalog = registry.catalog()
    stages_entry = maturity.get("stages") or {}
    cost = {}
    for agent in registry.stages():
        runs = (stages_entry.get(agent["id"]) or {}).get("runs") or []
        accepted = next((r["run"] for r in runs if r.get("verdict") == "accepted"), None)
        cost[agent["id"]] = {
            "runs": len(runs),
            "runs_to_accept": accepted,
            "events": events_per_stage.get(agent["id"], 0),
            "team": agent.get("team"),
        }
    return {
        # Une entree que personne ne produit : la chaine a un maillon manquant, et
        # aucun correctif de plugin ne le comblera.
        "missing_producers": catalog.get("missing_producers") or [],
        # Branche, jamais joue : soit l'initiative n'y est pas encore, soit l'etape est
        # de trop dans ce workflow. Le diagnostic pose la question, il ne tranche pas.
        "never_ran": sorted(agent["id"] for agent in registry.stages()
                            if not (stages_entry.get(agent["id"]) or {}).get("runs")),
        # Publie par une equipe, absent de la liste blanche du projet.
        "undeclared": catalog.get("undeclared") or [],
        "cost_per_stage": cost,
    }


def feedback(root: Path, agent_filter=None) -> dict:
    """Ce que ce projet a mesure sur chaque agent, a rendre a l'equipe qui le maintient.

    Les scores, les refus et les reserves restent dans le projet consommateur : l'equipe
    qui publie l'agent `plan` ne saura jamais qu'il plafonne a 3,2 en tracabilite chez
    trois clients. `selfscore` note le depot du harnais sur ses axes internes (hygiene,
    tests, couverture) — utile, mais muet sur la maturite telle qu'elle est vecue.
    Cette vue est le rapport manquant : par agent, son equipe, son manifeste, sa serie
    de notes et les motifs ecrits par les humains.
    """
    maturity = load_maturity(root)
    stages_entry = maturity.get("stages") or {}
    queue = []
    queue_path = aidlc_dir(root) / "improvement-queue.jsonl"
    if queue_path.exists():
        for line in read_text(queue_path).splitlines():
            try:
                queue.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    reports = []
    for agent in registry.agents_list():
        if agent_filter and agent["id"] != agent_filter:
            continue
        runs = (stages_entry.get(agent["id"]) or {}).get("runs") or []
        axis_means = {}
        if runs:
            axis_means = {axis: round(statistics.fmean(
                [float(r["scores"].get(axis, 0)) for r in runs]), 2) for axis in AXES}
        voices = [item for item in queue
                  if item.get("stage") == agent["id"]
                  and item.get("source") == "human_review"]
        reports.append({
            "agent": agent["id"],
            "team": agent.get("team"),
            "version": agent.get("version"),
            "manifest": agent.get("manifest"),
            "kind": "stage" if agent.get("produces") else "capability",
            "runs": len(runs),
            "trend": [r.get("overall") for r in runs][-5:],
            "axis_means": axis_means,
            # Des axes tous a la meme note n'ont pas de « plus faible » : en nommer
            # deux quand meme envoie l'equipe corriger ce qui va bien.
            "weakest_axes": sorted(axis_means, key=lambda a: axis_means[a])[:2]
            if axis_means and len(set(axis_means.values())) > 1 else [],
            "rejected_runs": sum(1 for r in runs if r.get("verdict") != "accepted"),
            "human_rejections": [item for item in voices if item.get("kind") != "reserve"],
            "human_reserves": [item for item in voices if item.get("kind") == "reserve"],
        })
    return {"initiative": initiative(root) or None, "generated_at": now_iso(),
            "project": str(root), "agents": reports}


def render_feedback(data: dict) -> str:
    if not data["agents"]:
        return "Aucun agent au registre : rien à remonter."
    lines = ["Retour d'usage — {}{}".format(
        data["project"],
        " (initiative « {} »)".format(data["initiative"]) if data["initiative"] else "")]
    lines.append("À transmettre à l'équipe qui maintient chaque agent.")
    lines.append("")
    for report in data["agents"]:
        head = "{} (équipe {}, v{})".format(
            report["agent"], report.get("team") or "?", report.get("version") or "?")
        if not report["runs"]:
            lines.append("{} — aucun run noté dans ce projet.".format(head))
            continue
        lines.append("{} — {} run(s), tendance {}{}".format(
            head, report["runs"],
            " ".join(str(value) for value in report["trend"]),
            ", {} refusé(s)".format(report["rejected_runs"])
            if report["rejected_runs"] else ""))
        if report["axis_means"]:
            lines.append("  moyennes : " + ", ".join(
                "{} {}".format(axis, value)
                for axis, value in report["axis_means"].items()))
        if report["weakest_axes"]:
            lines.append("  axes les plus faibles : "
                         + ", ".join(report["weakest_axes"]))
        for item in report["human_rejections"]:
            lines.append("  refus ({}) : {}".format(
                item.get("reviewer") or "?", item.get("justification") or ""))
        for item in report["human_reserves"]:
            lines.append("  réserve ({}) : {}".format(
                item.get("reviewer") or "?", item.get("justification") or ""))
    return "\n".join(lines)


def improve(root: Path, pipe: dict, stage_filter=None) -> dict:
    sessions, events, turns = set(), 0, 0
    tools, per_stage_events = {}, {}
    for event in iter_log_events(root):
        if stage_filter and event.get("stage") != stage_filter:
            continue
        events += 1
        sessions.add(event.get("session_id"))
        if event.get("event") == "UserPromptSubmit":
            turns += 1
        tool = (event.get("payload") or {}).get("tool_name")
        if tool:
            tools[tool] = tools.get(tool, 0) + 1
        stage_id = event.get("stage")
        if stage_id:
            per_stage_events[stage_id] = per_stage_events.get(stage_id, 0) + 1

    validation, error_counts = {}, {}
    for stage in registry.stages():
        stage_id = stage["id"]
        if stage_filter and stage_id != stage_filter:
            continue
        if not (root / stage["produces"]).exists():
            continue
        result = validate_stage(root, pipe, stage_id)
        validation[stage_id] = {"ok": result["ok"], "errors": result["errors"]}
        for message in result["errors"]:
            key = re.sub(r"\d+", "N", message)
            error_counts[key] = error_counts.get(key, 0) + 1

    maturity = load_maturity(root)
    maturity_out = {}
    for stage_id, entry in maturity.get("stages", {}).items():
        if stage_filter and stage_id != stage_filter:
            continue
        runs = entry.get("runs", [])
        if not runs:
            continue
        means = {axis: round(statistics.fmean(
            [float(r["scores"].get(axis, 0)) for r in runs]), 2) for axis in AXES}
        weakest = sorted(means, key=lambda axis: means[axis])[:2]
        maturity_out[stage_id] = {
            "runs": len(runs),
            "last_overall": runs[-1].get("overall"),
            "trend": [r.get("overall") for r in runs][-5:],
            "axis_means": means,
            "weakest_axes": weakest,
            "autonomous": bool(entry.get("autonomous")),
            "rejected_runs": sum(1 for r in runs if r.get("verdict") != "accepted"),
        }

    rejections = []
    reserves = []
    okf_refusals = []
    watchdog_halts = []
    queue_path = aidlc_dir(root) / "improvement-queue.jsonl"
    if queue_path.exists():
        for line in read_text(queue_path).splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("kind") == "okf_stop":
                # Refus du gate OKF de sortie : il alimente la section "okf" du
                # diagnostic, pas les refus humains d'etape.
                okf_refusals.append(item)
                continue
            if item.get("kind") == "watchdog":
                # Haltes du watchdog : elles forment leur propre section du diagnostic —
                # la forme du blocage y est decrite, la reprise humaine est le remede.
                watchdog_halts.append(item)
                continue
            if stage_filter and item.get("stage") != stage_filter:
                continue
            if item.get("kind") == "reserve":
                # Approbations motivees : l'humain a laisse passer *et* dit ce qui
                # clochait. Elles ne prouvent pas un echec, donc elles ne se lisent pas
                # comme un refus — mais c'est le gisement le plus regulier de la boucle.
                reserves.append(item)
                continue
            rejections.append(item)

    # Correlation des refus OKF avec les sessions : qui a ecrit dans le bundle, sur
    # quels fichiers, autour du refus (journaux .aidlc/logs). Approximation honnete :
    # si aucune session ne correspond, implicated reste vide.
    writes = []
    for event in iter_log_events(root):
        payload = event.get("payload") or {}
        if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
            continue
        target = (payload.get("tool_input") or {}).get("file_path")
        if not target:
            continue
        writes.append({"ts": event.get("ts") or "",
                       "session_id": event.get("session_id"),
                       "target": target})
    for refusal in okf_refusals:
        bundle_name = refusal.get("bundle", "knowledge")
        implicated = []
        for rel in refusal.get("files") or []:
            hits = [w for w in writes
                    if _write_in_bundle(w["target"], root, bundle_name, rel)]
            same = ([w for w in hits if w["session_id"] == refusal["session_id"]]
                    if refusal.get("session_id") else [])
            candidates = same or hits
            if not candidates:
                continue
            best = max(candidates, key=lambda w: w["ts"])
            implicated.append({"file": rel,
                               "session_id": best["session_id"],
                               "ts": best["ts"]})
        refusal["implicated"] = implicated

    return {
        "scope": stage_filter or "all",
        "generated_at": now_iso(),
        "sessions": len([s for s in sessions if s]),
        "events": events,
        "turns": turns,
        "events_per_stage": per_stage_events,
        "top_tools": sorted(tools.items(), key=lambda kv: -kv[1])[:10],
        "validation": validation,
        "recurring_errors": sorted(error_counts.items(), key=lambda kv: -kv[1])[:10],
        "maturity": maturity_out,
        # Ce qui a deja ete tente, et l'effet mesure : c'est ce qui empeche de
        # reproposer un correctif que les runs ont deja juge sans effet.
        "experiments": effects(root, stage_filter),
        "human_rejections": rejections,
        "human_reserves": reserves,
        # Ce que le diagnostic dit du **workflow** et non des plugins : les trous de la
        # chaine, les agents branches qui ne servent jamais, ceux qui sont publies mais
        # pas branches, et ce que chaque etape coute en allers-retours.
        "workflow": workflow_signals(root, maturity, per_stage_events),
        "watchdog": {
            # haltes enregistrees par le watchdog (kind: watchdog) : la forme du blocage,
            # la session et l'etape concernees — la reprise humaine est le remede.
            "halts": watchdog_halts,
        },
        "okf": {
            # refus enregistres par le hook Stop (check-okf --stop), enrichis de la
            # session fautive quand les journaux la montrent ;
            "refusals": okf_refusals,
            # correctifs de frontmatter proposes sur l'etat courant des bundles, chacun
            # verifie en memoire avant d'etre propose ;
            "proposals": _okf_proposals(root),
        },
    }
