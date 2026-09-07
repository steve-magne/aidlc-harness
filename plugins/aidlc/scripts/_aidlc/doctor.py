from __future__ import annotations

import json

from pathlib import Path

from . import registry
from .checks import contract_problems
from .init import config_problems
from .okf import PROJECT_OKF_BUNDLES
from .okf import okf_report
from .util import DELIVERABLES
from .util import PROJECT_CONFIG
from .util import aidlc_dir
from .util import harness_root
from .util import initiative
from .util import project_config
from .util import project_config_path
from .util import read_text
from .util import scoped
from .util import write_json

"""Diagnostic d'installation : ce qui, dans ce projet, ne repond plus a ce que la
version installee du harnais attend.

Le harnais est un plugin : il se met a jour sous les pieds du projet, sans que rien
dans le projet ne bouge. Un agent branche dont l'equipe a retire le plugin, un contrat
qui a change de forme, un livrable reste au chemin qu'un manifeste ne declare plus —
aucun de ces ecarts ne casse quoi que ce soit sur le coup. Ils se voient trois semaines
plus tard, sur une porte qui refuse sans raison lisible.

Cette passe les nomme en une commande, et ne repare rien : chaque constat porte le
geste qui le corrige, et ce geste appartient a l'humain ou a l'equipe proprietaire.
"""

#: Ce que la passe sait rendre, du plus grave au plus anodin. `blocking` = le harnais
#: ne peut pas fonctionner en l'etat ; `warning` = il fonctionne mais ment quelque part ;
#: `info` = a savoir, sans action requise.
SEVERITIES = ("blocking", "warning", "info")


def harness_version() -> str:
    """Version du plugin installe, '' si le manifeste est absent ou illisible."""
    manifest = harness_root() / ".claude-plugin" / "plugin.json"
    try:
        return str(json.loads(read_text(manifest)).get("version") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def stamp_path(root: Path) -> Path:
    """Empreinte de la version vue au dernier diagnostic. Sous `.aidlc/` a plat, jamais
    sous l'initiative : c'est le harnais qu'elle date, pas une idee du projet."""
    return root / ".aidlc" / "harness.json"


def _finding(severity: str, message: str, fix: str = "") -> dict:
    return {"severity": severity, "message": message, "fix": fix}


def _deliverable_findings(root: Path) -> list:
    """Livrables presents sur disque qu'aucun manifeste ne reclame plus.

    C'est la derive la plus silencieuse : une equipe change le `produces` de son agent,
    l'ancien fichier reste, et personne ne sait plus lequel des deux fait foi.
    """
    base = root / scoped(DELIVERABLES, root)
    if not base.is_dir():
        return []
    claimed = {(root / scoped(agent["produces"], root)).resolve()
               for agent in registry.stages() if agent.get("produces")}
    out = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.resolve() in claimed:
            continue
        out.append(_finding(
            "warning",
            f"{path.relative_to(root)} : aucun agent installe ne declare ce livrable.",
            "Verifiez le `produces` du manifeste, ou archivez le fichier."))
    return out


def diagnose(root: Path, stamp: bool = True) -> dict:
    """Etat de sante du projet face a la version installee du harnais.

    `stamp` date le passage dans `.aidlc/harness.json` : c'est ce qui permet au
    diagnostic suivant de dire « le harnais a change depuis ». Le mettre a faux rend la
    passe purement lecture seule (tests, inspection).
    """
    version = harness_version()
    findings = []

    config = project_config_path(root)
    if not config.is_file():
        findings.append(_finding(
            "blocking", f"{PROJECT_CONFIG} absent : ce projet n'est pas amorce.",
            "Lancez `/aidlc init`."))
    findings += [_finding("warning", problem, "Corrigez le fichier a la main.")
                 for problem in config_problems(root)]

    seen = ""
    try:
        seen = str(json.loads(read_text(stamp_path(root))).get("version") or "")
    except (OSError, json.JSONDecodeError):
        pass
    if seen and version and seen != version:
        findings.append(_finding(
            "info", f"Le harnais est passe de la version {seen} a la version {version}.",
            "Relisez les notes de version si une porte se comporte autrement."))

    catalog = registry.catalog()
    known = {agent["id"] for agent in catalog["agents"]}
    for agent_id in (project_config(root).get("agents") or []):
        if agent_id not in known:
            findings.append(_finding(
                "blocking",
                f"L'agent '{agent_id}' est branche sur ce workflow mais aucun plugin "
                "installe ne le porte.",
                f"Installez son plugin, ou retirez-le : "
                f"`aidlc workflow --remove {agent_id}`."))

    for agent in catalog["agents"]:
        for problem in contract_problems(agent):
            findings.append(_finding(
                "blocking", problem,
                f"Ce contrat se corrige dans le depot de l'equipe "
                f"« {agent.get('team') or '?'} », pas ici."))

    findings += _deliverable_findings(root)

    for name in PROJECT_OKF_BUNDLES:
        bundle = root / name
        if not bundle.is_dir():
            continue
        report = okf_report(bundle)
        if not report["ok"]:
            findings.append(_finding(
                "warning",
                f"{name}/ : {len(report['errors'])} ecart(s) a OKF v0.2.",
                f"Detail : `aidlc check-okf {name}`."))

    if stamp and version:
        write_json(stamp_path(root), {"version": version})

    findings.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    return {
        "harness_version": version,
        "harness_root": str(harness_root()),
        "project_root": str(root),
        "initiative": initiative(root),
        "state_dir": str(aidlc_dir(root)),
        "findings": findings,
        "ok": not any(f["severity"] == "blocking" for f in findings),
    }


def render(report: dict) -> str:
    """Le diagnostic en clair. Les gestes de reparation sont montres, jamais joues."""
    lines = [f"Harnais {report['harness_version'] or '?'} · projet "
             f"{report['project_root']}"]
    if report["initiative"]:
        lines.append(f"Initiative « {report['initiative']} » · etat dans "
                     f"{report['state_dir']}")
    if not report["findings"]:
        lines.append("Rien a signaler : le projet et le harnais sont d'accord.")
        return "\n".join(lines) + "\n"
    labels = {"blocking": "BLOQUANT", "warning": "ecart", "info": "info"}
    for finding in report["findings"]:
        lines.append(f"  [{labels[finding['severity']]}] {finding['message']}")
        if finding["fix"]:
            lines.append(f"      -> {finding['fix']}")
    if not report["ok"]:
        lines.append("Au moins un bloquant : le harnais ne peut pas fonctionner en l'etat.")
    return "\n".join(lines) + "\n"
