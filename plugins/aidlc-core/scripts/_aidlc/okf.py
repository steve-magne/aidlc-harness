from __future__ import annotations

import os
import re

from pathlib import Path
from .util import read_text
"""Bundles de connaissance OKF v0.2 : conformance structurelle et correctifs proposes (frontmatter des concepts, sommaire index.md)."""

# ---------------------------------------------------------- okf (bundles de savoir)
# docs/ et knowledge/ sont des bundles Open Knowledge Format v0.2 : concepts Markdown a
# frontmatter YAML (cle `type` obligatoire) plus fichiers reserves index.md et log.md.
# La passe verifie la conformance structurelle de la spec (section 11) sur ce que la
# stdlib permet de verifier sans dependance.
# # ponytail: pas de parseur YAML en stdlib. On restreint le frontmatter des bundles du
# depot a un sous-ensemble ligne a ligne — scalaires, listes en flux [...] et mappings en
# flux {...} sur une seule ligne, items de liste indentless sous une cle — et on verifie
# la forme de ce sous-ensemble. Upgrade : sortir un vrai parseur si le frontmatter des
# bundles se complexifie (blocs multilignes, ancres, etc.).

OKF_RESERVED = ("index.md", "log.md")
OKF_INDEX_KEYS = {"okf_version"}
_KEY_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(\s+.*)?$")
_ITEM_LINE = re.compile(r"^-\s+\S.*$")
_EMPTY_LINE = re.compile(r"^\s*$")
_INDEX_LINK = re.compile(r"^\s*\*\s+\[[^\]\n]*\]\(([^)]+)\)")


def okf_split_frontmatter(text: str):
    """Decoupe (frontmatter, corps, etat) d'un fichier : 'absent' | 'ouvert' | 'ferme'."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text, "absent"
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:]), "ferme"
    return "", text, "ouvert"


def _flow_balanced(value: str) -> bool:
    """Equilibre de [], {} et des guillemets dans une valeur de flux sur une ligne."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    quote = None
    for ch in value:
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack[-1] != pairs[ch]:
                return False
            stack.pop()
    return not stack and quote is None


def _frontmatter_shape_problems(front: str) -> list:
    """Problemes de forme du sous-ensemble YAML autorise dans le frontmatter d'un bundle."""
    problems = []
    for lineno, line in enumerate(front.splitlines(), start=2):
        if _EMPTY_LINE.match(line):
            continue
        key_match = _KEY_LINE.match(line)
        if key_match:
            value = (key_match.group(2) or "").strip()
            if value.startswith(("{", "[")) and not _flow_balanced(value):
                problems.append(f"ligne {lineno} : valeur de flux desequilibree")
            continue
        if _ITEM_LINE.match(line):
            if not _flow_balanced(line):
                problems.append(f"ligne {lineno} : item de liste desequilibre")
            continue
        problems.append(f"ligne {lineno} : forme YAML hors sous-ensemble du depot")
    return problems


# Bundles OKF v0.2 gates par le hook PostToolUse a la racine du projet : knowledge/ est le
# bundle de tout projet consommateur ; docs/ n'existe que dans le depot du harnais lui-meme
# (le guide se gate comme la connaissance — meme passe, meme format).
PROJECT_OKF_BUNDLES = ("knowledge", "docs")


def okf_bundle_errors(bundle: Path) -> list:
    """Conformance OKF v0.2 structurelle d'un bundle. Retourne la liste des problemes."""
    errors = []
    for path in sorted(bundle.rglob("*.md")):
        rel = path.relative_to(bundle).as_posix()
        text = read_text(path)
        front, body, state = okf_split_frontmatter(text)
        if path.name == "index.md":
            if state == "ferme":
                keys = [m.group(1) for line in front.splitlines()
                        for m in [_KEY_LINE.match(line)] if m]
                if any(key not in OKF_INDEX_KEYS for key in keys):
                    errors.append(f"{rel} : index.md sans frontmatter, sauf okf_version en racine")
                if not re.search(r"^\s*\*\s+\[", body, re.MULTILINE):
                    errors.append(f"{rel} : le sommaire liste ses entrees en liens markdown")
            elif state == "ouvert":
                errors.append(f"{rel} : frontmatter non ferme")
            continue
        if path.name == "log.md":
            if state != "absent":
                errors.append(f"{rel} : log.md ne porte pas de frontmatter")
            for line in body.splitlines():
                if line.startswith("## ") and not re.fullmatch(
                        r"## \d{4}-\d{2}-\d{2}", line.strip()):
                    errors.append(f"{rel} : titre de date non ISO 8601 ({line.strip()})")
            continue
        if state != "ferme":
            errors.append(f"{rel} : un concept s'ouvre par un frontmatter YAML ferme (---)")
            continue
        if not re.search(r"(?m)^type\s*:\s*\S", front):
            errors.append(f"{rel} : frontmatter sans cle 'type' non vide")
        errors.extend(f"{rel} : {problem}"
                      for problem in _frontmatter_shape_problems(front))
    return errors


def okf_report(bundle: Path) -> dict:
    """Rapport de conformance OKF v0.2 d'un bundle, sans aucune sortie (pur)."""
    errors = okf_bundle_errors(bundle)
    checked = len(list(bundle.rglob("*.md")))
    return {"bundle": str(bundle), "ok": not errors, "checked": checked,
            "errors": errors}


def _fallback_title(rel: str) -> str:
    stem = Path(rel).stem.replace("-", " ").replace("_", " ").strip()
    return stem[:1].upper() + stem[1:] if stem else Path(rel).name


def _concept_front_values(bundle: Path, rel: str) -> tuple:
    """(titre, description) declares dans le frontmatter d'un concept (vides sinon)."""
    front, _, state = okf_split_frontmatter(read_text(bundle / rel))
    values = {}
    if state == "ferme":
        for key in ("title", "description"):
            match = re.search(r"(?m)^" + key + r"\s*:\s*(\S.*)$", front)
            if match:
                value = match.group(1).strip().strip("\"'")
                if value and not value.startswith(("{", "[")):
                    values[key] = value
    return values.get("title", ""), values.get("description", "")


def _concept_title(bundle: Path, rel: str) -> str:
    """Titre lisible d'un concept : cle 'title' du frontmatter, sinon premier titre H1,
    sinon nom de fichier humanise."""
    title, _ = _concept_front_values(bundle, rel)
    if title:
        return title
    heading = next((ln.strip() for ln in read_text(bundle / rel).splitlines()
                    if re.match(r"^#\s+\S", ln)), "")
    if heading:
        return re.sub(r"^#+\s*", "", heading).strip()
    return _fallback_title(rel)


def _write_in_bundle(target: str, root: Path, bundle_name: str, rel: str) -> bool:
    """Un Write/Edit journalise touche-t-il le fichier rel du bundle bundle_name ?
    # ponytail: les journaux gardent le file_path tel que Claude Code l'a passe (souvent
    absolu). On compare les chemins resolvables, sinon une correspondance de suffixe du
    chemin normalise — approximation suffisante pour la correlation, pas pour un constat.
    """
    if not target:
        return False
    try:
        if Path(target).expanduser().resolve() == (root / bundle_name / rel).resolve():
            return True
    except OSError:
        pass
    norm = os.path.normpath(target).replace(os.sep, "/")
    return (norm == rel or norm == f"{bundle_name}/{rel}"
            or norm.endswith(f"/{bundle_name}/{rel}"))


def okf_frontmatter_fix(bundle: Path, rel: str, errors: list) -> dict | None:
    """Correctif deterministe du frontmatter d'un concept non conforme.

    Couvre ce que la passe sait verifier : frontmatter absent, ouvert (jamais ferme), ou
    cle 'type' absente/vide. Le type par defaut (Reference) et le titre (derive du premier
    titre H1, sinon du nom de fichier) sont des valeurs semantiques : la proposition les
    affiche pour confirmation humaine, elle ne decide pas. Les erreurs de forme (lignes
    hors sous-ensemble, flux desequilibres) restent manuelles.
    # ponytail: reparation en memoire sur le sous-ensemble YAML ligne a ligne du depot,
    # verifiee avec les memes regles que la passe. Le sommaire index.md a sa propre
    # proposition (okf_index_proposal) ; log.md (dates du journal) reste manuel.
    """
    if not errors:
        return None
    lines = read_text(bundle / rel).splitlines()
    _, _, state = okf_split_frontmatter("\n".join(lines))
    edits = []
    if state == "absent":
        title = _concept_title(bundle, rel)
        edits = [{"at": 0,
                  "insert": "---\ntype: Reference\ntitle: {}\n---\n".format(title)}]
    elif state == "ouvert":
        close_at = len(lines)
        for index in range(1, len(lines)):
            if not (_KEY_LINE.match(lines[index]) or _ITEM_LINE.match(lines[index])
                    or _EMPTY_LINE.match(lines[index])):
                close_at = index
                break
        edits = [{"at": close_at, "insert": "---\n"}]
    # etat ferme sans cle 'type' non vide : aucun edit pour l'instant, on ajoute la cle
    # seulement si la verification en memoire confirme qu'elle manque.
    repaired = list(lines)
    for edit in sorted(edits, key=lambda e: -e["at"]):
        repaired[edit["at"]:edit["at"]] = edit["insert"].rstrip("\n").split("\n")
    front, _, state2 = okf_split_frontmatter("\n".join(repaired))
    if state2 == "ferme" and not re.search(r"(?m)^type\s*:\s*\S", front):
        edit = {"at": 1, "insert": "type: Reference\n"}
        edits.append(edit)
        repaired[1:1] = edit["insert"].rstrip("\n").split("\n")
    front, _, state2 = okf_split_frontmatter("\n".join(repaired))
    if (state2 != "ferme" or not re.search(r"(?m)^type\s*:\s*\S", front)
            or _frontmatter_shape_problems(front)):
        return None
    return {"file": rel, "kind": "frontmatter", "problem": errors[0],
            "edits": edits,
            "note": "type par défaut Reference et titre dérivé du premier titre H1 "
                     "(sinon du nom de fichier) : a confirmer avant application.",
            "preview": "\n".join(repaired).splitlines()[:6]}


def _index_entry_line(bundle: Path, rel: str) -> str:
    """Ligne de sommaire `* [Titre](rel) - description` au format des bundles du depot.
    Titre et description repris du frontmatter du concept (sinon derives du fichier) ;
    crochets retires pour ne pas casser le lien markdown."""
    title, description = _concept_front_values(bundle, rel)
    title = (title or _concept_title(bundle, rel)).replace("[", "").replace("]", "")
    if description:
        description = description.replace("[", "").replace("]", "")
        return f"* [{title}]({rel}) - {description}"
    return f"* [{title}]({rel})"


def okf_index_proposal(bundle: Path) -> dict | None:
    """Propose au sommaire index.md les concepts orphelins : presents dans le bundle,
    absents de la liste. Etat courant, sans historique. L'ajout n'effleure ni le
    frontmatter du sommaire (absent, ou limite a okf_version) ni son corps : il vient en
    queue de la liste existante, et la proposition est verifiee en memoire (plus aucun
    orphelin apres application).
    # ponytail: detection par liens markdown `* [..](rel)` ligne a ligne. Plafond : pas
    de regroupement par sections — l'ordonnancement et le libelle restent humains, la
    proposition n'est qu'un point de depart verifie.
    """
    index = bundle / "index.md"
    if not index.exists():
        return None
    lines = read_text(index).splitlines()
    front, _, state = okf_split_frontmatter("\n".join(lines))
    if state == "ouvert":
        return None
    if state == "ferme":
        keys = [m.group(1) for line in front.splitlines()
                for m in [_KEY_LINE.match(line)] if m]
        if any(key not in OKF_INDEX_KEYS for key in keys):
            return None
    listed = []
    for line in lines:
        m = _INDEX_LINK.match(line)
        if m:
            listed.append(m.group(1).split("#", 1)[0])
    concepts = sorted(p.relative_to(bundle).as_posix()
                      for p in bundle.rglob("*.md")
                      if p.name not in OKF_RESERVED)
    orphans = [rel for rel in concepts if rel not in listed]
    if not orphans:
        return None
    entries = [_index_entry_line(bundle, rel) for rel in orphans]
    insert_at = len(lines)
    for index in range(len(lines) - 1, -1, -1):
        if _INDEX_LINK.match(lines[index]):
            insert_at = index + 1
            break
    edit = {"at": insert_at, "insert": "\n".join(entries) + "\n"}
    repaired = list(lines)
    repaired[edit["at"]:edit["at"]] = edit["insert"].rstrip("\n").split("\n")
    check_listed = set()
    for line in repaired:
        m = _INDEX_LINK.match(line)
        if m:
            check_listed.add(m.group(1).split("#", 1)[0])
    if any(rel not in check_listed for rel in concepts):
        return None
    return {"file": "index.md", "kind": "index_entries",
            "problem": f"{len(orphans)} concept(s) absent(s) du sommaire : "
                       f"{', '.join(orphans)}",
            "edits": [edit],
            "note": "entrees ajoutees en queue de la liste existante, titre et "
                    "description repris du frontmatter de chaque concept (sinon derives "
                    "du fichier) : l'ordonnancement par sections reste manuel.",
            "preview": entries[:6]}


def _okf_proposals(root: Path) -> list:
    """Correctifs proposes sur l'etat courant des bundles du projet : frontmatter des
    concepts non conformes, et entrees manquantes du sommaire index.md (orphelins).
    Etat courant, pas historique : on ne propose que du reparage qui vaut encore
    aujourd'hui."""
    proposals = []
    for name in PROJECT_OKF_BUNDLES:
        bundle = (root / name).resolve()
        if not bundle.is_dir():
            continue
        errors_by_file = {}
        for message in okf_bundle_errors(bundle):
            rel = message.split(" : ", 1)[0]
            errors_by_file.setdefault(rel, []).append(message)
        for rel in sorted(errors_by_file):
            if Path(bundle / rel).name in OKF_RESERVED:
                continue
            fix = okf_frontmatter_fix(bundle, rel, errors_by_file[rel])
            if fix:
                fix = dict(fix)
                fix["bundle"] = name
                proposals.append(fix)
        index_fix = okf_index_proposal(bundle)
        if index_fix:
            index_fix = dict(index_fix)
            index_fix["bundle"] = name
            proposals.append(index_fix)
    return proposals
