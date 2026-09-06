from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from pathlib import Path

from .. import registry
from ..util import ensure_dir
from ..util import load_pipeline
from ..util import read_text
from ..util import write_json

"""Socle commun de la suite : projet neuf et environnement isole par test.

Toute classe de test herite de `AidlcTestCase`. Chaque methode `test_*` recoit un
repertoire temporaire tout neuf qui joue **les deux racines a la fois** (le harnais qui
porte pipeline.json et les plugins, le projet consommateur qui porte deliverables/ et
.aidlc/) — comme quand on ouvre une session dans ce depot. Les variables d'environnement
sont sauvees puis restaurees, et le cache du registre est vide avant et apres : la suite
rend le meme resultat d'ou qu'on la lance et quel que soit l'ordre des tests.
"""

#: Point d'entree public du moteur, pour les tests de contrat CLI en sous-processus.
ENTRYPOINT = Path(__file__).resolve().parents[2] / "aidlc.py"

#: Racine du depot qui porte les bundles dogfood (knowledge/, docs/) et les plugins
#: reels. Remontee depuis ce paquet, jamais depuis le repertoire courant.
def repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "knowledge" / "index.md").exists():
            return candidate
    return here.parents[3]


PIPELINE = {
    "version": 2,
    "maturity_threshold": 4.0,
    "consecutive_runs_to_autonomy": 3,
    "planned_stages": [
        {"id": "design", "name": "Design", "deliverable": "deliverables/design/spec.md",
         "inputs": ["deliverables/plan/intent.md"], "human_role": "Architecte",
         "team": "Architecture"},
        {"id": "build", "name": "Build", "deliverable": "deliverables/build/plan.md",
         "inputs": ["deliverables/design/spec.md"], "human_role": "Tech Lead",
         "team": "Ingenierie"},
    ],
}

CHECKS = {
    "required_frontmatter": ["stage", "version", "status", "author", "date"],
    "required_sections": ["## Contexte", "## Probleme", "## Criteres d'acceptation"],
    "min_words": 60,
    "forbidden_patterns": ["TODO", "TBD"],
    "must_reference_inputs": True,
    "min_items_per_section": {"## Criteres d'acceptation": 3},
}

FILLER = ("Le harness orchestre les etapes du cycle de vie logiciel et journalise chaque "
          "session agentique afin de mesurer la maturite des livrables produits par les "
          "agents et par les humains qui les relisent avec attention et methode. ")

GOOD_SECTIONS = {
    "## Contexte": "Le contexte du besoin metier est decrit ici de facon detaillee.",
    "## Probleme": "Le probleme est la lenteur du cycle de livraison actuel.",
    "## Criteres d'acceptation": "- Critere un mesurable.\n- Critere deux mesurable.\n"
                                "- Critere trois mesurable.",
}

DEFAULT_FRONTMATTER = {"stage": "plan", "version": "1", "status": "draft",
                       "author": "Steve", "date": "2026-09-03"}


def manifest(agent_id, team, produces=None, consumes=(), **extra) -> dict:
    """Manifeste de fixture. Tout est neutre sauf `invocation`, indexe par plateforme.
    Sans `produces` l'agent est consultatif : jamais note, jamais une etape."""
    out = {
        "manifest_version": 1, "id": agent_id, "team": team,
        "version": "0.1.0", "description": f"Agent de test {agent_id}.",
        "capabilities": [f"sdlc:{agent_id}"],
        "invocation": {"claude-code": f"aidlc-{agent_id}:{agent_id}"},
    }
    if produces:
        out.update({"produces": produces, "consumes": list(consumes),
                    "checks": "checks.json", "human_role": "Role de test"})
    out.update(extra)
    return out


def document(sections: dict = None, front: dict = None, filler: int = 3) -> str:
    """Livrable de fixture : frontmatter, sections, puis du remplissage pour passer
    `min_words`. `front={}` produit un document sans frontmatter du tout."""
    front = DEFAULT_FRONTMATTER if front is None else front
    sections = GOOD_SECTIONS if sections is None else sections
    out = ["---"] + [f"{k}: {v}" for k, v in front.items()] + ["---", ""]
    for title, body in sections.items():
        out += [title, body, ""]
    out.append(FILLER * filler)
    return "\n".join(out)


class AidlcTestCase(unittest.TestCase):
    """Base de tous les tests du moteur.

    Attributs prets a l'emploi apres `setUp` :
      * `self.root`     — Path du projet/harnais temporaire (les deux racines) ;
      * `self.pipeline` — la gouvernance chargee depuis `self.root/pipeline.json`.

    Points d'extension (attributs de classe) :
      * `seed_agents = False` — projet nu : aucun agent, aucun contrat, aucune etape.
    """

    ENV = ("AIDLC_HARNESS_ROOT", "AIDLC_AGENT_PATH", "CLAUDE_PROJECT_DIR",
           "CLAUDE_CONFIG_DIR", "CLAUDE_PLUGIN_ROOT", "AIDLC_PLATFORM")

    seed_agents = True

    maxDiff = None

    def setUp(self):
        saved = {name: os.environ.get(name) for name in self.ENV}
        self.addCleanup(self._restore_env, saved)
        self.addCleanup(registry.reset_cache)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

        os.environ["AIDLC_HARNESS_ROOT"] = str(self.root)
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.root)
        # Isole la decouverte des plugins reellement installes sur la machine.
        os.environ["CLAUDE_CONFIG_DIR"] = str(ensure_dir(self.root / "fake-config"))
        os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        os.environ.pop("AIDLC_PLATFORM", None)
        os.environ["AIDLC_AGENT_PATH"] = str(self.root / "plugins")

        write_json(self.root / "pipeline.json", PIPELINE)
        if self.seed_agents:
            self.seed_default_agents()
        registry.reset_cache()
        self.pipeline = load_pipeline()

    @staticmethod
    def _restore_env(saved):
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # ------------------------------------------------------------------ fixtures

    def seed_default_agents(self):
        """Les deux etapes gouvernees de reference : plan produit intent.md, design le
        consomme et produit spec.md. Chaque contrat vit dans le plugin de son agent."""
        self.write_agent("aidlc-plan",
                         manifest("plan", "Produit", "deliverables/plan/intent.md"),
                         CHECKS)
        design_checks = dict(CHECKS)
        design_checks["required_sections"] = ["## Contexte"]
        design_checks["min_items_per_section"] = {}
        self.write_agent("aidlc-design",
                         manifest("design", "Architecture", "deliverables/design/spec.md",
                                  ["deliverables/plan/intent.md"]),
                         design_checks)

    def write_agent(self, plugin_dir: str, agent: dict, checks: dict = None,
                    base: Path = None) -> Path:
        """Publie un agent : son manifeste, et son contrat s'il produit un livrable.
        `base` permet de le poser hors du projet (autre depot d'equipe)."""
        target = (base or self.root / "plugins") / plugin_dir
        write_json(target / "agent.json", agent)
        if checks is not None:
            write_json(target / "checks.json", checks)
        registry.reset_cache()
        return target

    def agent_path(self, *dirs: Path):
        """Redefinit AIDLC_AGENT_PATH (precedence maximale de decouverte)."""
        os.environ["AIDLC_AGENT_PATH"] = os.pathsep.join(str(d) for d in dirs)
        registry.reset_cache()

    def write(self, relpath: str, text: str) -> Path:
        """Ecrit un fichier texte relatif a la racine temporaire."""
        path = self.root / relpath
        ensure_dir(path.parent)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, relpath: str, data) -> Path:
        path = self.root / relpath
        write_json(path, data)
        return path

    def read(self, relpath: str) -> str:
        return read_text(self.root / relpath)

    def read_json(self, relpath: str):
        return json.loads(self.read(relpath))

    def plan_intent(self, sections: dict = None, front: dict = None,
                    filler: int = 3) -> Path:
        """Ecrit le livrable de l'etape plan et renvoie son chemin."""
        return self.write("deliverables/plan/intent.md",
                          document(sections, front, filler))

    # ------------------------------------------------------------------- contrat

    def run_cli(self, *args, stdin: str = "", cwd: Path = None):
        """Invoque `aidlc.py` en sous-processus : le contrat public que consomment les
        hooks et les skills. Renvoie un CompletedProcess (returncode, stdout, stderr).
        L'environnement isole du test est herite tel quel."""
        return subprocess.run(
            [sys.executable, str(ENTRYPOINT), *[str(a) for a in args]],
            input=stdin, capture_output=True, text=True,
            cwd=str(cwd or self.root), env=dict(os.environ), check=False)

    @contextlib.contextmanager
    def muted(self):
        """Avale les messages humains qu'une fonction du moteur ecrit sur stderr
        (review_request, les portes, les hints). Ils polluent la sortie du runner sans
        rien prouver. Le tampon est rendu : on peut y assertionner si besoin."""
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            yield buffer

    def assertJson(self, completed, msg: str = None):
        """La sortie machine est du JSON sur stdout — jamais melangee a stderr."""
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - message de diagnostic
            self.fail(msg or f"stdout n'est pas du JSON ({exc}) : {completed.stdout!r}")
