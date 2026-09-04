from __future__ import annotations

import json
import re
import statistics

from pathlib import Path
from .okf import _okf_proposals
from .okf import _write_in_bundle
from .util import aidlc_dir
from .maturity import load_maturity
from .maturity import AXES
from .util import now_iso
from .util import read_text
from .checks import validate_stage
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
    for stage in pipe.get("stages", []):
        stage_id = stage["id"]
        if stage_filter and stage_id != stage_filter:
            continue
        if not (root / stage.get("deliverable", "")).exists():
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
    okf_refusals = []
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
            if stage_filter and item.get("stage") != stage_filter:
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
        "human_rejections": rejections,
        "okf": {
            # refus enregistres par le hook Stop (check-okf --stop), enrichis de la
            # session fautive quand les journaux la montrent ;
            "refusals": okf_refusals,
            # correctifs de frontmatter proposes sur l'etat courant des bundles, chacun
            # verifie en memoire avant d'etre propose ;
            "proposals": _okf_proposals(root),
        },
    }
