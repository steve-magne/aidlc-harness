from __future__ import annotations

import json
import os
import sys

from pathlib import Path
from .util import aidlc_dir
from .util import digest
from .util import harness_root
from .util import project_config_path
from .util import ensure_dir
from . import registry
from .util import now_iso
from .util import read_text
from .util import truncate
from .checks import contract_problems
from .checks import validate_stage
from .init import config_problems
from .util import write_json

AXES = ["completeness", "precision", "traceability", "autonomy"]

#: Les axes qui portent sur le **livrable**. Le plancher par axe ne s'applique qu'a
#: eux : ils decrivent une propriete du fichier note, donc reecrire le fichier est une
#: action de sortie. `autonomy` mesure le cout deja paye du procede — un run ne peut pas
#: le corriger, et le rejeter pour ce motif fermerait une porte sans issue tout en
#: punissant l'agent qui s'est corrige. Il pese toujours un quart de la moyenne.
DELIVERABLE_AXES = ["completeness", "precision", "traceability"]
"""Maturite des etapes : scores, autonomie, porte (gate), revue humaine et etat du pipeline (status)."""

# ------------------------------------------------------------------------ maturite

def maturity_path(root: Path) -> Path:
    return aidlc_dir(root) / "maturity.json"


def load_maturity(root: Path) -> dict:
    path = maturity_path(root)
    if not path.exists():
        return {"stages": {}}
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError:
        return {"stages": {}}
    data.setdefault("stages", {})
    return data


def stage_maturity(maturity: dict, stage_id: str) -> dict:
    return maturity["stages"].setdefault(stage_id, {"runs": [], "autonomous": False})


def human_review(root: Path, stage_id: str, run: int):
    path = aidlc_dir(root) / "reviews" / f"{stage_id}-{run}.json"
    if not path.exists():
        return None
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError:
        return None


def compute_autonomy(root: Path, pipe: dict, stage_id: str, maturity: dict) -> bool:
    """Autonomie = les N derniers runs sont au-dessus du seuil, et ceux qui ont ete
    produits **sous surveillance** portent une revue humaine approuvee.

    # ponytail: lecture stricte du contrat sur les runs supervises. Plafond : l'autonomie
    est plus longue a gagner. Upgrade : rendre la regle configurable dans pipeline.json.
    """
    threshold = float(pipe.get("maturity_threshold", 4.0))
    window = int(pipe.get("consecutive_runs_to_autonomy", 3))
    runs = stage_maturity(maturity, stage_id)["runs"]
    if len(runs) < window:
        return False
    for run in runs[-window:]:
        if run.get("verdict") != "accepted" or float(run.get("overall", 0)) < threshold:
            return False
        if not run.get("supervised", True):
            # Run produit alors que l'etape etait deja autonome : aucune revue humaine
            # n'a ete demandee, en exiger une ici retirerait l'autonomie des le premier
            # run qui en beneficie. Un run anterieur a ce champ est lu comme supervise.
            continue
        review = run.get("human_review") or human_review(root, stage_id, run.get("run", 0))
        if not review or not review.get("approved"):
            return False
    return True


def input_digests(root: Path, stage: dict) -> dict:
    """Empreintes courantes des entrees amont d'une etape."""
    return {path: digest(root / path) for path in (stage or {}).get("consumes") or []}


def stale_inputs(root: Path, stage: dict, run: dict) -> list:
    """Entrees amont modifiees depuis que ce run a ete note.

    C'est ce qui empeche un livrable aval de rester vert alors qu'il a ete bati sur une
    version disparue de son amont — le cas « le BA a revise apres que l'architecte a
    livre ». Un run enregistre avant l'existence des empreintes (cle 'inputs' absente) ne
    perime rien : on ne perime que ce dont on connait l'etat d'origine.
    """
    recorded = (run or {}).get("inputs")
    if not recorded:
        return []
    current = input_digests(root, stage)
    return sorted(path for path, value in recorded.items() if current.get(path) != value)


def stale_deliverable(root: Path, stage: dict, run: dict) -> bool:
    """Le livrable a-t-il ete reecrit depuis qu'il a ete note ?

    Symetrique amont de `stale_inputs` : une note porte sur un contenu, pas sur un nom de
    fichier. Sans cette empreinte, un livrable pouvait etre reecrit apres sa revue et
    franchir la porte sur la note de la version disparue — `validate` ne voit que la
    forme, et la signature humaine est elle aussi attachee au run. Un run enregistre
    avant l'existence de l'empreinte ne perime rien.
    """
    recorded = (run or {}).get("deliverable")
    produces = (stage or {}).get("produces")
    if not recorded or not produces:
        return False
    return digest(root / produces) != recorded


def record_score(root: Path, pipe: dict, stage_id: str, review: dict) -> dict:
    scores = review.get("scores") or {}
    missing = [axis for axis in AXES if axis not in scores]
    if missing:
        raise ValueError(f"Axes manquants dans la revue : {', '.join(missing)}")
    values = []
    for axis in AXES:
        value = float(scores[axis])
        if not 0 <= value <= 5:
            raise ValueError(f"Score hors bornes pour '{axis}' : {value} (attendu 0-5).")
        # La grille n'a que six niveaux ancres (0 absent ... 5 exemplaire) : une demi-note
        # ne correspond a aucun. La regle etait ecrite dans la skill de revue, donc
        # dependante du modele qui la lit ; sans elle, un 2,9 juste sous le plancher ou un
        # 3,0 juste dessus se negocient, et l'echelle ordinale cesse d'etre comparable.
        if value != int(value):
            raise ValueError(f"Score non entier pour '{axis}' : {value} — la grille de "
                             "maturite n'a que six niveaux (0 a 5).")
        values.append(value)
    overall = round(sum(values) / len(values), 1)
    threshold = float(pipe.get("maturity_threshold", 4.0))
    verdict = review.get("verdict")
    if verdict not in ("accepted", "rejected"):
        verdict = "accepted" if overall >= threshold else "rejected"
    # Plancher par axe : une moyenne flatteuse ne rachete pas un axe effondre. Un
    # livrable complet, precis et rapide mais sans aucune tracabilite reste un livrable
    # qu'on ne peut pas auditer — et il servira d'entree a toute l'aval. La regle etait
    # ecrite dans le prompt du reviewer et nulle part dans le moteur : un reviewer
    # complaisant (ou un modele qui derive) la contournait sans que rien ne le voie.
    # C'est le moteur qui la tient, pas la consigne. Il ne porte que sur les axes du
    # livrable (voir DELIVERABLE_AXES).
    floor = float(pipe.get("min_axis_score", 3.0))
    weak = [axis for axis in DELIVERABLE_AXES if float(scores[axis]) < floor]
    if weak:
        verdict = "rejected"

    stage = registry.find_agent(stage_id) or {}
    maturity = load_maturity(root)
    entry = stage_maturity(maturity, stage_id)
    run_number = len(entry["runs"]) + 1
    record = {
        "ts": now_iso(),
        "run": run_number,
        "scores": {axis: float(scores[axis]) for axis in AXES},
        "overall": overall,
        "verdict": verdict,
        "human_review": None,
        "weak_axes": weak,
        "findings": truncate(review.get("findings", [])),
        "recommendations": truncate(review.get("recommendations", [])),
        "inputs": input_digests(root, stage),
        "deliverable": digest(root / stage["produces"]) if stage.get("produces") else "",
        # Etat de surveillance au moment de la note : c'est lui qui dit si l'absence de
        # signature humaine sur ce run est normale (voir compute_autonomy).
        "supervised": not bool(entry.get("autonomous")),
    }
    entry["runs"].append(record)
    entry["autonomous"] = compute_autonomy(root, pipe, stage_id, maturity)
    write_json(maturity_path(root), maturity)
    return record


def enqueue_improvement(root: Path, item: dict, dedupe_keys: tuple) -> bool:
    """Seul ecrivain de .aidlc/improvement-queue.jsonl : ajoute item sauf si une entree
    existante du meme `kind` possede deja les memes valeurs sur `dedupe_keys`. Les refus
    humains (kind absent, dedupe stage/run), ceux du gate OKF (kind okf_stop, dedupe
    session/bundle/fichiers) et les haltes du watchdog (kind watchdog, dedupe
    detector/stage/file/session) partagent cette unique politique — le kind les distingue.
    Retourne True si une entree a ete ajoutee, False si elle etait un doublon."""
    kind = item.get("kind")
    path = aidlc_dir(root) / "improvement-queue.jsonl"
    ensure_dir(path.parent)
    if path.exists():
        for line in read_text(path).splitlines():
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if existing.get("kind") != kind:
                continue
            if all(existing.get(key) == item.get(key) for key in dedupe_keys):
                return False
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return True


# ---------------------------------------------------------------------------- gate

def upstream_blockers(root: Path, pipe: dict, stage: dict, seen: set) -> list:
    """Ce qui, en amont, interdit de franchir cette etape.

    Deux conditions, dans cet ordre : l'entree amont doit **exister** sur disque, et
    l'agent qui la produit doit avoir franchi **sa** porte. C'est ici que la chaine
    producteur -> consommateur devient une regle opposable, et non plus une consigne
    adressee a l'orchestrateur : sans ce controle, `gate` rendait `passed: true` sur une
    etape dont l'entree n'avait jamais ete ecrite, et le tableau de bord affichait une
    etape aval franchie au-dessus d'une etape amont vide.

    La remontee s'arrete au premier amont ferme et ne redescend que d'un cran a la fois :
    `seen` coupe une dependance circulaire, que le registre signale par ailleurs.
    """
    blockers = []
    for path in stage.get("consumes") or []:
        producer = registry.producer_of(path)
        if not (root / path).exists():
            blockers.append(
                "Entree amont absente : {} — {}.".format(
                    path,
                    f"produire d'abord le livrable de l'agent '{producer}'" if producer
                    else "aucun agent installe ne la produit, son plugin manque"))
        elif producer and producer not in seen:
            upstream = gate_stage(root, pipe, producer, _seen=seen)
            if not upstream["passed"]:
                blockers.append(
                    "Porte amont fermee : l'agent '{}' n'a pas franchi la sienne ({}).".format(
                        producer, upstream["blocking"][0] if upstream["blocking"]
                        else "motif indisponible"))
    return blockers


def gate_stage(root: Path, pipe: dict, stage_id: str, _seen: set = None) -> dict:
    stage = registry.find_agent(stage_id)
    out = {"stage": stage_id, "passed": False, "blocking": [],
           "next_stage": registry.next_agent_id(stage_id), "human_review_required": True}
    if stage is None:
        out["blocking"].append(f"Agent inconnu du registre : {stage_id}")
        return out
    if not stage.get("produces"):
        # Un agent consultatif n'a pas de livrable, donc pas de metre : il n'y a rien a
        # noter et rien a franchir. Ce n'est pas un echec, c'est une absence de porte.
        out["blocking"].append(
            f"L'agent '{stage_id}' est consultatif (pas de 'produces') : aucune porte "
            "de qualite ne s'y applique.")
        return out

    # L'amont d'abord : une etape batie sur du vide n'a pas de qualite a mesurer, et le
    # dire avant la note evite d'envoyer l'utilisateur relancer un reviewer pour rien.
    seen = set(_seen or ())
    seen.add(stage_id)
    upstream = upstream_blockers(root, pipe, stage, seen)
    if upstream:
        out["upstream"] = upstream
        out["blocking"].extend(upstream)

    threshold = float(pipe.get("maturity_threshold", 4.0))
    validation = validate_stage(root, pipe, stage_id)
    out["validation_ok"] = validation["ok"]
    if not validation["ok"]:
        out["blocking"].append(
            "Validation deterministe en echec : " + " | ".join(validation["errors"][:5])
        )

    maturity = load_maturity(root)
    entry = stage_maturity(maturity, stage_id)
    runs = entry["runs"]
    autonomous = bool(entry.get("autonomous"))
    out["autonomous"] = autonomous
    out["human_review_required"] = not autonomous

    if not runs:
        out["blocking"].append("Aucun score de maturite enregistre : lancer le reviewer.")
        out["run"] = None
        return out

    last = runs[-1]
    out["run"] = last.get("run")
    out["overall"] = last.get("overall")
    out["verdict"] = last.get("verdict")
    if last.get("verdict") != "accepted":
        out["blocking"].append(f"Verdict du reviewer : {last.get('verdict')}.")
    if float(last.get("overall", 0)) < threshold:
        out["blocking"].append(
            f"Maturite {last.get('overall')} sous le seuil {threshold}."
        )
    weak = last.get("weak_axes") or []
    if weak:
        floor = float(pipe.get("min_axis_score", 3.0))
        out["weak_axes"] = weak
        out["blocking"].append(
            "Axe sous le plancher {} : {} — une moyenne suffisante ne rachete pas un "
            "axe effondre.".format(floor, ", ".join(
                f"{axis}={last['scores'][axis]}" for axis in weak)))

    stale = stale_inputs(root, stage, last)
    if stale:
        out["stale_inputs"] = stale
        out["blocking"].append(
            "Entree amont modifiee depuis la revue : " + ", ".join(stale)
            + " — relancer le reviewer."
        )

    if stale_deliverable(root, stage, last):
        out["stale_deliverable"] = True
        out["blocking"].append(
            "Livrable modifie depuis la revue : la note du run {} porte sur une version "
            "qui n'est plus sur disque — relancer le reviewer.".format(last.get("run")))

    review = human_review(root, stage_id, last.get("run", 0))
    if review:
        last["human_review"] = {
            "approved": bool(review.get("approved")),
            "reviewer": review.get("reviewer"),
            "ts": review.get("ts"),
        }
        if not review.get("approved"):
            out["blocking"].append(
                "Revue humaine refusee : " + str(review.get("justification", "sans justification"))
            )
            enqueue_improvement(root, {
                "ts": now_iso(), "stage": stage_id, "run": last.get("run"),
                "reviewer": review.get("reviewer"),
                "justification": review.get("justification", ""),
                "source": "human_review",
            }, ("stage", "run"))
    elif not autonomous:
        out["blocking"].append(
            f"Revue humaine requise : .aidlc/reviews/{stage_id}-{last.get('run')}.json absent."
        )

    entry["autonomous"] = compute_autonomy(root, pipe, stage_id, maturity)
    out["autonomous"] = entry["autonomous"]
    write_json(maturity_path(root), maturity)

    out["passed"] = not out["blocking"]
    return out


# ------------------------------------------------------------------------ recall

def recall(root: Path, stage_id: str, limit: int = 3) -> dict:
    """Ce qu'un agent doit savoir des tentatives precedentes avant de reprendre l'etape.

    Les findings du reviewer, les axes effondres et la justification d'un refus humain
    sont deja sur disque a la fin d'un run — mais rien ne les rendait, si bien qu'ils
    mouraient avec la session. Un agent qui reprenait une etape refusee refaisait
    l'erreur pour laquelle elle avait ete refusee.

    Ce n'est pas une entorse au principe « pas de memoire implicite » : rien ne circule
    tout seul entre deux etapes. C'est une lecture explicite, demandee, de ce que le
    projet a deja juge — le livrable reste le seul contrat entre agents.
    """
    stage = registry.find_agent(stage_id)
    if stage is None:
        raise ValueError(f"Agent inconnu du registre : {stage_id}")
    entry = stage_maturity(load_maturity(root), stage_id)
    runs = entry["runs"][-max(1, limit):] if entry["runs"] else []
    out = []
    for run in runs:
        # La signature humaine est relue sur disque plutot que prise dans le run : le
        # champ n'y est recopie que par `gate`, et un refus signe apres la derniere
        # porte serait invisible — or c'est exactement celui qui compte pour reprendre.
        review = human_review(root, stage_id, run.get("run", 0)) or {}
        out.append({
            "run": run.get("run"), "ts": run.get("ts"),
            "overall": run.get("overall"), "verdict": run.get("verdict"),
            "weak_axes": run.get("weak_axes") or [],
            "findings": run.get("findings") or [],
            "recommendations": run.get("recommendations") or [],
            "human_approved": review.get("approved") if review else None,
            "human_justification": review.get("justification", "") if review else "",
        })
    return {"stage": stage_id, "produces": stage.get("produces"),
            "autonomous": bool(entry.get("autonomous")),
            "total_runs": len(entry["runs"]), "runs": out}


def render_recall(data: dict) -> str:
    """Rendu humain : le plus recent en premier, c'est celui qu'on doit corriger."""
    if not data["runs"]:
        return ("Etape '{}' : aucune tentative anterieure — rien a reprendre."
                .format(data["stage"]))
    lines = ["Etape '{}' — {} run(s), {} rappele(s){}".format(
        data["stage"], data["total_runs"], len(data["runs"]),
        ", autonome" if data["autonomous"] else "")]
    for run in reversed(data["runs"]):
        lines.append("")
        lines.append("run {} ({}) : {} — note {}{}".format(
            run["run"], run["ts"], run["verdict"], run["overall"],
            " | axes sous plancher : " + ", ".join(run["weak_axes"])
            if run["weak_axes"] else ""))
        if run["human_approved"] is False:
            lines.append("  refus humain : " + (run["human_justification"]
                                                or "sans justification"))
        for finding in run["findings"]:
            lines.append("  - reproche : " + str(finding))
        for reco in run["recommendations"]:
            lines.append("  - a faire  : " + str(reco))
    return "\n".join(lines)


# ------------------------------------------------------------------ review-request

REVIEW_INSTRUCTIONS = """Revue humaine — etape '{stage}' (run {run})

Livrable a relire : {deliverable}
Role attendu      : {role}

A verifier :
  1. Le livrable repond au besoin reel, pas seulement au gabarit.
  2. Les criteres d'acceptation sont testables et chiffres.
  3. Les inputs amont sont cites et correctement interpretes.
  4. Aucun engagement implicite non assume (delai, cout, perimetre).

Ou signer : {target}
  - copier le fichier .template.json en {basename}
  - renseigner "approved" (true/false), "reviewer", "justification"

En cas de refus (approved=false) : la justification est obligatoire, elle est copiee
automatiquement dans .aidlc/improvement-queue.jsonl et alimente la skill improve.
"""


def review_request(root: Path, pipe: dict, stage_id: str) -> dict:
    stage = registry.find_agent(stage_id)
    if stage is None:
        raise ValueError(f"Agent inconnu du registre : {stage_id}")
    if not stage.get("produces"):
        raise ValueError(f"L'agent '{stage_id}' ne produit pas de livrable : "
                         "il n'y a rien a faire relire.")
    maturity = load_maturity(root)
    runs = stage_maturity(maturity, stage_id)["runs"]
    run = runs[-1]["run"] if runs else 1
    target = aidlc_dir(root) / "reviews" / f"{stage_id}-{run}.json"
    template_path = aidlc_dir(root) / "reviews" / f"{stage_id}-{run}.template.json"
    template = {
        "stage": stage_id,
        "run": run,
        "approved": False,
        "reviewer": "<nom du relecteur>",
        "justification": "<justification obligatoire, surtout en cas de refus>",
        "ts": now_iso(),
    }
    write_json(template_path, template)
    sys.stderr.write(REVIEW_INSTRUCTIONS.format(
        stage=stage_id, run=run, deliverable=stage.get("produces"),
        role=stage.get("human_role", "non precise"),
        target=os.path.relpath(target, root), basename=target.name,
    ))
    return {
        "stage": stage_id, "run": run,
        "template": os.path.relpath(template_path, root),
        "target": os.path.relpath(target, root),
        "deliverable": stage.get("produces"),
        "human_role": stage.get("human_role"),
    }


# ---------------------------------------------------------------------- signature

def sign_review(root: Path, pipe: dict, stage_id: str, approved: bool, reviewer: str,
                justification: str, force: bool = False) -> dict:
    """Ecrit la revue humaine d'une etape : `.aidlc/reviews/<stage>-<run>.json`.

    Jusqu'ici, signer voulait dire copier un gabarit, editer un JSON a la main — horodatage
    ISO compris — puis demander a l'agent de relancer la porte. Trois gestes manuels
    demandes a un Product Owner, et un format de date a respecter pour que la porte
    s'ouvre. Cette fonction fait le meme travail, en tenant les exigences que le fichier
    ne sait pas tenir : un relecteur nomme, une justification non vide (dans les deux
    sens : une approbation sans motif est un tampon, pas une revue), un run reellement
    note, et le refus d'ecraser une signature deja apposee.

    Elle n'affaiblit pas le garde-fou : c'est `cmd_sign` qui exige un terminal humain,
    la fonction reste pure et testable. La voie manuelle (editer le JSON) reste ouverte
    pour les contextes sans terminal.
    """
    stage = registry.find_agent(stage_id)
    if stage is None:
        raise ValueError(f"Agent inconnu du registre : {stage_id}")
    if not stage.get("produces"):
        raise ValueError(f"L'agent '{stage_id}' ne produit pas de livrable : "
                         "il n'y a rien a signer.")
    reviewer = (reviewer or "").strip()
    justification = (justification or "").strip()
    if not reviewer:
        raise ValueError("Le nom du relecteur est obligatoire : une revue anonyme "
                         "n'engage personne.")
    if not justification:
        raise ValueError("La justification est obligatoire, approbation comprise : "
                         "sans motif ecrit, la signature ne dit pas ce qui a ete verifie.")
    runs = stage_maturity(load_maturity(root), stage_id)["runs"]
    if not runs:
        raise ValueError(f"Aucun score enregistre pour '{stage_id}' : faites noter le "
                         "livrable par le reviewer avant de le signer.")
    run = runs[-1]["run"]
    path = aidlc_dir(root) / "reviews" / f"{stage_id}-{run}.json"
    if path.exists() and not force:
        existing = human_review(root, stage_id, run) or {}
        raise ValueError(
            "Le run {} de '{}' est deja signe par {} ({}) : une signature ne se reecrit "
            "pas. Faites renoter le livrable, ou supprimez {} pour revenir sur votre "
            "decision.".format(run, stage_id, existing.get("reviewer", "?"),
                               existing.get("ts", "?"), os.path.relpath(path, root)))
    review = {"stage": stage_id, "run": run, "approved": bool(approved),
              "reviewer": reviewer, "justification": justification, "ts": now_iso()}
    write_json(path, review)
    return {"stage": stage_id, "run": run, "approved": bool(approved),
            "reviewer": reviewer, "review": os.path.relpath(path, root),
            "deliverable": stage.get("produces")}


# -------------------------------------------------------------------------- status

def authoring(root: Path) -> bool:
    """Sommes-nous dans le depot qui **ecrit** le harnais, ou dans un projet qui le
    consomme ? Le harnais installe vit alors sous la racine du projet (session ouverte
    dans le depot auteur) ; sinon il est dans le cache de plugins de Claude Code.

    Ce n'est pas un detail d'affichage : une etape prevue mais non installee se
    scaffolde chez l'auteur et s'attend chez le consommateur. Proposer `scaffold` a une
    equipe projet, c'est lui proposer d'ecrire dans une copie que le garde-fou protege.
    """
    try:
        harness_root().resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def status_data(root: Path, pipe: dict) -> dict:
    """Tableau de bord derive du registre. Les etapes sont les agents qui produisent un
    livrable, dans l'ordre topologique ; les agents consultatifs sont listes a part.

    Un registre est ouvert : un plugin absent ferait retrecir le tableau en silence.
    Deux sections l'empechent — `missing_producers` (une entree attendue que personne
    ne produit) et `planned` (feuille de route declaree, plugin pas encore installe).
    """
    threshold = float(pipe.get("maturity_threshold", 4.0))
    maturity = load_maturity(root)
    view = registry.catalog()
    rows = []
    # Qui produit quoi, et qui a deja franchi. `view["agents"]` est trie par la chaine
    # producteur -> consommateur : un amont est donc toujours evalue avant son aval, et
    # `cleared` se remplit au fil de l'eau — le tableau de bord chaine sans jamais
    # rappeler `gate`, qui revaliderait chaque livrable a chaque ligne.
    producers = {agent["produces"]: agent["id"]
                 for agent in view["agents"] if agent.get("produces")}
    cleared = {}
    for stage in [agent for agent in view["agents"] if agent.get("produces")]:
        stage_id = stage["id"]
        deliverable = root / stage["produces"]
        entry = maturity["stages"].get(stage_id, {"runs": [], "autonomous": False})
        runs = entry.get("runs", [])
        last = runs[-1] if runs else None
        present = deliverable.exists()
        validation = validate_stage(root, pipe, stage_id) if present else None
        stale = stale_inputs(root, stage, last)
        row = {
            "stage": stage_id,
            "name": stage.get("description") or stage_id,
            "team": stage.get("team"),
            "version": stage.get("version"),
            "capabilities": stage.get("capabilities", []),
            "invoke": stage.get("invoke"),
            "invocable": stage.get("invocable"),
            "deliverable": stage["produces"],
            "deliverable_present": present,
            "validate_ok": bool(validation and validation["ok"]),
            "errors": (validation or {}).get("errors", []),
            "runs": len(runs),
            "last_overall": last.get("overall") if last else None,
            "last_verdict": last.get("verdict") if last else None,
            "autonomous": bool(entry.get("autonomous")),
            "human_role": stage.get("human_role"),
            "stale_inputs": stale,
            "stale_deliverable": stale_deliverable(root, stage, last),
        }
        blocked_by = []
        for path in stage.get("consumes") or []:
            producer = producers.get(path)
            if not (root / path).exists():
                blocked_by.append({
                    "input": path, "producer": producer,
                    "reason": "livrable pas encore produit" if producer
                    else "aucun agent installe ne le produit"})
            elif producer and not cleared.get(producer, False):
                blocked_by.append({"input": path, "producer": producer,
                                   "reason": "porte amont non franchie"})
        row["blocked_by"] = blocked_by
        if not row["invocable"]:
            row["next_action"] = (f"Agent non invocable sur {view['platform']} : "
                                  "completer 'invocation' dans son agent.json")
        elif blocked_by:
            row["next_action"] = "En attente de l'amont : " + ", ".join(
                item["producer"] or Path(item["input"]).name for item in blocked_by)
        elif not present:
            row["next_action"] = f"Produire le livrable : {stage.get('invoke')}"
        elif not row["validate_ok"]:
            row["next_action"] = f"Corriger {len(row['errors'])} erreur(s) de validation"
        elif stale:
            row["next_action"] = ("Entree amont modifiee ("
                                  + ", ".join(Path(p).name for p in stale)
                                  + ") : reprendre puis relancer le reviewer")
        elif last is None:
            row["next_action"] = "Lancer le reviewer (agent aidlc-core:reviewer)"
        elif row["stale_deliverable"]:
            row["next_action"] = ("Livrable modifie depuis la revue : relancer le "
                                  "reviewer")
        elif last.get("verdict") != "accepted" or float(last.get("overall", 0)) < threshold:
            row["next_action"] = "Reprendre le livrable puis relancer le reviewer"
        elif not row["autonomous"] and not human_review(root, stage_id, last.get("run", 0)):
            row["next_action"] = f"Revue humaine : aidlc.py review-request {stage_id}"
        else:
            row["next_action"] = "Etape franchie"
        cleared[stage_id] = row["next_action"] == "Etape franchie"
        # Qui doit agir maintenant. Une etape franchie n'attend personne ; une etape
        # bloquee par son amont non plus — l'action est sur la ligne du dessus, et
        # afficher deux noms a la fois est la meilleure facon que personne ne bouge.
        row["waiting_for"] = (None if cleared[stage_id] or blocked_by
                              else stage.get("human_role"))
        rows.append(row)
    current = next((r["stage"] for r in rows if r["next_action"] != "Etape franchie"), None)
    known = {agent["id"] for agent in view["agents"]}
    planned = [stage for stage in pipe.get("planned_stages", [])
               if stage.get("id") not in known]
    return {
        "root": str(root),
        "platform": view["platform"],
        "maturity_threshold": threshold,
        "project_config": project_config_path(root).name
        if project_config_path(root).is_file() else None,
        "authoring": authoring(root),
        "current_stage": current,
        "stages": rows,
        "advisors": [agent for agent in view["agents"] if not agent.get("produces")],
        "missing_producers": view["missing_producers"],
        "planned": planned,
        "cycle": view["cycle"],
        "problems": view["problems"],
        "contract_problems": [problem for agent in view["agents"]
                              for problem in contract_problems(agent)],
        "config_problems": config_problems(root),
        "warnings": view["warnings"],
    }


#: Largeur maximale de la colonne des roles humains. Un role d'entreprise est long
#: (« Product Owner / Business Analyst ») et il ne doit pas pousser la prochaine action
#: hors de l'ecran : c'est elle qu'on vient lire.
ROLE_WIDTH = 26


def _short(value: str, width: int = ROLE_WIDTH) -> str:
    value = value or "-"
    return value if len(value) <= width else value[:width - 3] + "..."


def render_status(data: dict) -> str:
    headers = ["AGENT", "EQUIPE", "LIVRABLE", "VALIDE", "SCORE", "AUTO",
               "EN ATTENTE DE", "PROCHAINE ACTION"]
    rows = []
    for row in data["stages"]:
        rows.append([
            row["stage"],
            row.get("team") or "-",
            "oui" if row["deliverable_present"] else "non",
            "oui" if row["validate_ok"] else ("non" if row["deliverable_present"] else "-"),
            str(row["last_overall"]) if row["last_overall"] is not None else "-",
            "oui" if row["autonomous"] else "non",
            _short(row.get("waiting_for")),
            row["next_action"],
        ])
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
              for i in range(len(headers))]
    lines = [
        f"AI-DLC — tableau de bord ({data['root']})",
        f"Seuil de maturite : {data['maturity_threshold']} | "
        f"Plateforme : {data.get('platform')} | "
        f"Gouvernance : {data.get('project_config') or 'harnais (pipeline.json)'} | "
        f"Etape courante : {data['current_stage'] or 'chaine complete'}",
        "",
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    lines.append("")
    for row in data["stages"]:
        for item in row.get("blocked_by") or []:
            lines.append("Bloque : {} attend {} — {}.".format(
                row["stage"], item["input"], item["reason"]))
    for advisor in data.get("advisors", []):
        lines.append("Agent consultatif : {} (equipe {}) — {}".format(
            advisor["id"], advisor.get("team") or "?",
            ", ".join(advisor.get("capabilities", [])) or "aucune capacite declaree"))
    for hole in data.get("missing_producers", []):
        lines.append("Producteur absent : '{}' attend {} — aucun agent installe ne le "
                     "produit.".format(hole["agent"], hole["input"]))
    for stage in data.get("planned", []):
        lines.append("Prevu, plugin non installe : {} ({}) — {}".format(
            stage.get("id"), stage.get("name", ""),
            "aidlc.py scaffold {}".format(stage.get("id")) if data.get("authoring")
            else "a publier par l'equipe {}".format(stage.get("team") or "proprietaire")))
    if data.get("cycle"):
        lines.append("Cycle de dependances entre agents : " + ", ".join(data["cycle"]))
    for message in data.get("warnings", []):
        lines.append("Avertissement : " + message)
    for message in data.get("problems", []):
        lines.append("Manifeste rejete : " + message)
    for message in data.get("contract_problems", []):
        lines.append("Contrat incoherent : " + message)
    for message in data.get("config_problems", []):
        lines.append("Gouvernance du projet : " + message)
    return "\n".join(lines)
