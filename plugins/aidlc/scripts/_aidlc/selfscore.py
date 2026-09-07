from __future__ import annotations

import json

from pathlib import Path
from statistics import mean

from . import registry
from .checks import contract_problems
from .coverage import TOLERANCE
from .coverage import coverage_path
from .coverage import measure
from .okf import PROJECT_OKF_BUNDLES
from .okf import okf_report
from .syntax import json_report
from .syntax import python_report
from .util import read_text

"""Score de maturite du harnais : le depot lui-meme, note comme on note un livrable.

La grille de maturite de `maturity.py` juge un **livrable** produit par un agent ; celle-ci
juge le **harnais** qui les juge. Meme bareme (0 a 5), memes seuils (`maturity_threshold` et
`min_axis_score` de pipeline.json), meme code de sortie bloquant (2) — mais les axes sont
deterministes de bout en bout : aucun juge, aucun prompt, aucun reseau. Deux invocations sur
le meme arbre de fichiers rendent la meme note.

Cinq axes, cinq risques distincts :

  * `hygiene`   — le depot se charge (regle 6 : tout Python compile, tout JSON parse) ;
  * `contracts` — les manifestes et contrats d'agents de CE depot sont valides ;
  * `tests`     — la suite passe, et chaque module du moteur a son test en face (regle 8) ;
  * `coverage`  — la couverture mesuree ne descend pas sous le plancher fige ;
  * `knowledge` — les bundles OKF v0.2 du depot sont conformes.

La passe est en **lecture seule** : elle mesure, elle ne fige rien. Le plancher de couverture
n'est ecrit que par `aidlc.py coverage`, geste explicite et visible au diff — sans quoi un
`git commit` laisserait derriere lui un `.aidlc/coverage.json` modifie hors du commit.
"""

# ------------------------------------------------------------------------- bareme

#: Note maximale d'un axe. Meme echelle que la grille des livrables.
MAX = 5.0

#: Bandes du taux de couverture vers la note de l'axe. Table lue, jamais recalculee :
#: la note se verifie a l'oeil, et deplacer une exigence est un diff d'une ligne.
COVERAGE_BANDS = ((95.0, 5.0), (90.0, 4.0), (80.0, 3.0), (70.0, 2.0), (50.0, 1.0))

#: Plafond de constats rendus par axe. # ponytail: on ne recopie pas 300 erreurs de
#: compilation dans un JSON de CI ; les premieres suffisent a savoir quoi corriger.
FINDINGS = 20


def _axis(name: str, score, detail: str, findings=()) -> dict:
    """Un axe note. `score is None` = axe non applicable a ce projet : il est affiche,
    jamais moyenne — un consommateur n'a pas a etre note sur ce qu'il ne porte pas."""
    return {"axis": name, "score": None if score is None else round(float(score), 2),
            "detail": detail, "findings": list(findings)[:FINDINGS]}


# --------------------------------------------------------------------------- axes

def axis_hygiene(root: Path) -> dict:
    """Regle 6 : tout Python compile, tout JSON parse.

    Binaire, sans note intermediaire : un depot qui ne se charge pas n'a pas de qualite
    partielle. C'est la porte qui protege toutes les autres — un JSON casse rendrait les
    axes suivants incalculables.
    """
    py, js = python_report(root), json_report(root)
    findings = py["errors"] + js["errors"]
    return _axis("hygiene", 0.0 if findings else MAX,
                 "{} fichiers Python compilés, {} fichiers JSON parsés".format(
                     py["checked"], js["checked"]),
                 findings)


def axis_contracts(root: Path) -> dict:
    """Manifestes `agent.json` et contrats `checks.json` **de ce depot**.

    Meme severite asymetrique que `agents --strict` : le manifeste casse d'une equipe
    voisine, decouvert ailleurs, n'entre pas dans notre note — sinon la CI d'un
    consommateur rougirait pour du code qu'il ne maintient pas. Un cycle de dependances
    entre agents, lui, est toujours notre affaire : il rend l'ordre des etapes indefini.
    """
    view = registry.catalog()
    problems = view["problems"] + [problem for agent in view["agents"]
                                   for problem in contract_problems(agent)]
    here = str(root.resolve())
    findings = [message for message in problems if here in message]
    if view["cycle"]:
        findings.append("dépendances circulaires entre agents : "
                        + ", ".join(view["cycle"]))
    return _axis("contracts", 0.0 if findings else MAX,
                 "{} agents découverts, contrats contrôlés à vide".format(
                     len(view["agents"])),
                 findings)


def module_test_gaps() -> tuple:
    """(modules du moteur, modules sans `tests/test_<module>.py` en face).

    Regle 8 lue sur l'arborescence reelle du paquet qui s'execute — pas sur le projet
    courant : c'est bien le moteur installe que la note juge.
    """
    package = Path(__file__).resolve().parent
    modules = sorted(path.stem for path in package.glob("*.py")
                     if path.stem != "__init__")
    tested = {path.stem[len("test_"):] for path in (package / "tests").glob("test_*.py")}
    return modules, [name for name in modules if name not in tested]


def axis_tests(fresh: dict) -> dict:
    """Regle 8 : la suite passe, et chaque module du moteur a son test en face.

    Suite rouge = 0, sans appel : une note calculee sur un moteur casse ne veut rien
    dire. Sinon un point de moins par module orphelin — un module neuf sans test est
    visible des le premier, bloquant au troisieme (plancher `min_axis_score`).
    """
    if not fresh.get("suite_passed"):
        return _axis("tests", 0.0, "la suite du moteur est rouge",
                     ["`aidlc.py test` echoue : aucune note tant que la suite est rouge"])
    modules, gaps = module_test_gaps()
    return _axis("tests", max(0.0, MAX - len(gaps)),
                 "{}/{} modules du moteur ont leur test en face".format(
                     len(modules) - len(gaps), len(modules)),
                 ["{} : aucun tests/test_{}.py en face".format(name, name)
                  for name in gaps])


def coverage_floors(root: Path) -> dict:
    """Planchers de couverture figes (.aidlc/coverage.json), {} si absent ou illisible.
    Un plancher illisible ne bloque pas : il n'est simplement pas oppose a la mesure."""
    path = coverage_path(root)
    if not path.exists():
        return {}
    try:
        return json.loads(read_text(path)).get("modules") or {}
    except json.JSONDecodeError:
        return {}


def band(total: float) -> float:
    """Note de l'axe couverture pour un taux donne, selon COVERAGE_BANDS."""
    for floor, score in COVERAGE_BANDS:
        if total >= floor:
            return score
    return 0.0


def axis_coverage(root: Path, fresh: dict) -> dict:
    """Couverture mesuree du moteur, confrontee au plancher fige.

    Une regression sous le plancher vaut 0 quel que soit le taux absolu : c'est le meme
    contrat que `aidlc.py coverage`, la couverture ne descend jamais. Sans plancher
    (premier passage, ou projet consommateur), seule la bande compte.
    """
    floors = coverage_floors(root)
    regressions = []
    for name, floor in sorted(floors.items()):
        current = fresh["modules"].get(name)
        if current is None:
            regressions.append(
                "{} : module disparu de la mesure (plancher {} %)".format(name, floor))
        elif current["pct"] < float(floor) - TOLERANCE:
            regressions.append("{} : {} % sous le plancher de {} %".format(
                name, current["pct"], floor))
    total = float(fresh["total"])
    return _axis("coverage", 0.0 if regressions else band(total),
                 "{} % de lignes couvertes".format(total), regressions)


def axis_knowledge(root: Path) -> dict:
    """Conformance OKF v0.2 des bundles du projet (knowledge/, docs/).

    Note proportionnelle : le savoir se degrade bundle par bundle, pas d'un coup. Aucun
    bundle = axe non applicable, pas axe a zero — un projet consommateur qui n'en porte
    aucun ne merite pas d'etre puni pour ca.
    """
    bundles = [(name, root / name) for name in PROJECT_OKF_BUNDLES
               if (root / name).is_dir()]
    if not bundles:
        return _axis("knowledge", None, "aucun bundle OKF dans ce projet")
    reports = [(name, okf_report(path)) for name, path in bundles]
    conform = [name for name, report in reports if report["ok"]]
    findings = ["{}/{}".format(name, error)
                for name, report in reports for error in report["errors"]]
    return _axis("knowledge", MAX * len(conform) / len(reports),
                 "{}/{} bundles conformes OKF v0.2".format(len(conform), len(reports)),
                 findings)


# --------------------------------------------------------------------------- passe

def selfscore_run(root: Path, pipe: dict) -> dict:
    """Une passe complete du score de maturite du harnais.

    La suite ne tourne **qu'une fois** (sous `trace`, via `coverage.measure`) : les axes
    `tests` et `coverage` sont deux lectures de la meme mesure. `passed` est faux des
    qu'un axe applicable passe sous `min_axis_score`, meme si la moyenne suffit — un
    axe effondre ne se compense pas, comme pour la note d'un livrable.
    """
    fresh = measure()
    axes = [axis_hygiene(root), axis_contracts(root), axis_tests(fresh),
            axis_coverage(root, fresh), axis_knowledge(root)]
    scored = [axis for axis in axes if axis["score"] is not None]
    threshold = float(pipe.get("maturity_threshold", 4.0))
    floor = float(pipe.get("min_axis_score", 3.0))
    weak = [axis["axis"] for axis in scored if axis["score"] < floor]
    overall = round(mean(axis["score"] for axis in scored), 2) if scored else 0.0
    return {
        "overall": overall,
        "threshold": threshold,
        "min_axis_score": floor,
        "axes": axes,
        "weak_axes": weak,
        "passed": overall >= threshold and not weak,
    }
