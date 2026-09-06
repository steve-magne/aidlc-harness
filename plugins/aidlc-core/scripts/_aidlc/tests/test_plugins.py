from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import shlex
import unittest

from pathlib import Path

from .harness import repo_root
from .. import checks
from .. import cli
from .. import registry

"""Coherence structurelle du depot reel, en lecture seule via `repo_root()`.

Ce module ne teste pas un module Python : il teste les ARTEFACTS du depot (manifestes,
hooks, skills, marketplace, checks.json, documentation) les uns contre les autres, pour
qu'un renommage ne casse jamais un hook, une skill ou une reference documentaire en
silence. Aucune ecriture : tout part de `repo_root()`, jamais de `self.root`."""


# --------------------------------------------------------------------- utilitaires


def _plugin_dirs() -> list:
    """Chaque sous-repertoire de plugins/ qui porte un plugin.json Claude Code."""
    root = repo_root()
    return sorted(
        p.parent.parent for p in (root / "plugins").glob("*/.claude-plugin/plugin.json")
    )


def _agent_manifest_paths() -> list:
    return sorted((repo_root() / "plugins").glob("*/agent.json"))


def _iter_hook_commands(hooks_data: dict):
    """Parcourt la structure hooks.json et rend chaque chaine `command` d'un hook de
    type `command`, sans presumer de la profondeur d'imbrication."""
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "command" and isinstance(node.get("command"), str):
                yield node["command"]
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)
    yield from walk(hooks_data)


def _subparser_choices() -> dict:
    """Sous-commandes reellement exposees par le parseur du moteur."""
    parser = cli.build_parser()
    action = next(a for a in parser._actions
                  if isinstance(a, argparse._SubParsersAction))
    return action.choices


# Motifs de chemins "racines" cites en prose : ${CLAUDE_PLUGIN_ROOT}/..., $CLAUDE_PROJECT_DIR/...
# et plugins/... nus. Les marqueurs de gabarit (`plugins/aidlc-<stage>/...`) sont exclus par le
# filtre "pas suivi de '<'" applique par l'appelant, puisque `<` n'appartient pas a la classe de
# caracteres et tronque le match juste avant.
_PLUGIN_ROOT_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}(?:/[A-Za-z0-9_.-]+)+")
_PROJECT_ROOT_RE = re.compile(r"\$CLAUDE_PROJECT_DIR(?:/[A-Za-z0-9_.-]+)+")
_BARE_PLUGINS_RE = re.compile(r"(?<![\w/])plugins(?:/[A-Za-z0-9_.-]+)+")


def _rooted_paths(text: str):
    """Rend une liste de (chemin_resolu_repo_relatif, racine) pour chaque reference de
    chemin explicitement rattachee a une racine connue dans `text`. Ignore les gabarits
    (chemin immediatement suivi de `<` dans le texte source, ex: `plugins/aidlc-<stage>/`)."""
    out = []
    for regex, root_kind in ((_PLUGIN_ROOT_RE, "plugin"),
                              (_PROJECT_ROOT_RE, "project"),
                              (_BARE_PLUGINS_RE, "repo")):
        for m in regex.finditer(text):
            end = m.end()
            if end < len(text) and text[end] == "<":
                continue
            out.append((m.group(0), root_kind))
    return out


class TestPluginManifests(unittest.TestCase):
    """Chaque plugins/*/.claude-plugin/plugin.json parse et porte ses champs attendus."""

    def test_chaque_plugin_json_parse_et_porte_les_champs_attendus(self):
        dirs = _plugin_dirs()
        self.assertTrue(dirs, "aucun plugin.json trouve sous plugins/")
        for plugin_dir in dirs:
            manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
            with self.subTest(plugin=plugin_dir.name):
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                for field in ("name", "description", "version", "author"):
                    self.assertIn(field, data,
                                  f"{manifest_path} : champ '{field}' manquant.")
                self.assertEqual(data["name"], plugin_dir.name,
                                 f"{manifest_path} : name != dossier du plugin.")
                self.assertIn("name", data["author"],
                             f"{manifest_path} : author.name manquant.")


class TestAgentManifests(unittest.TestCase):
    """Chaque plugins/*/agent.json est accepte tel quel par registry.validate_manifest."""

    def test_chaque_agent_json_est_un_manifeste_valide(self):
        paths = _agent_manifest_paths()
        self.assertTrue(paths, "aucun agent.json trouve sous plugins/")
        for manifest_path in paths:
            with self.subTest(agent=manifest_path.parent.name):
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                problems = registry.validate_manifest(data, str(manifest_path))
                self.assertEqual(problems, [],
                                 f"{manifest_path} rejete : {problems}")

    def test_id_de_l_agent_correspond_au_nom_du_plugin(self):
        """`aidlc-plan` porte `id: plan`, `aidlc-security` porte `id: security-review` :
        convention de nommage, pas contrainte du registre, mais une divergence totale
        ici serait une source de confusion silencieuse (le mauvais plugin decouvert)."""
        for manifest_path in _agent_manifest_paths():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            plugin_name = manifest_path.parent.name
            stem = plugin_name[len("aidlc-"):] if plugin_name.startswith("aidlc-") \
                else plugin_name
            with self.subTest(agent=plugin_name):
                self.assertTrue(
                    stem == data["id"] or stem in data["id"] or data["id"] in stem,
                    f"{manifest_path} : id {data['id']!r} sans rapport avec le "
                    f"dossier {plugin_name!r}.")


class TestHooksJson(unittest.TestCase):
    """hooks.json ne doit jamais pointer un script absent ni une sous-commande fantome :
    c'est la porte qui empeche un renommage de casser les hooks en silence."""

    @classmethod
    def setUpClass(cls):
        cls.hooks_path = repo_root() / "plugins" / "aidlc-core" / "hooks" / "hooks.json"
        cls.plugin_root = cls.hooks_path.parent.parent
        cls.hooks_data = json.loads(cls.hooks_path.read_text(encoding="utf-8"))
        cls.commands = list(_iter_hook_commands(cls.hooks_data))
        cls.choices = _subparser_choices()

    def test_hooks_json_parse_et_contient_des_commandes(self):
        self.assertTrue(self.commands, "hooks.json ne cite aucune commande de type command.")

    def test_chaque_commande_resout_aidlc_py_vers_un_fichier_present(self):
        for command in self.commands:
            tokens = shlex.split(command)
            script_token = next((t for t in tokens if t.endswith("aidlc.py")), None)
            with self.subTest(command=command):
                self.assertIsNotNone(script_token, "aucun aidlc.py cite dans la commande.")
                resolved = script_token.replace(
                    "${CLAUDE_PLUGIN_ROOT}", str(self.plugin_root))
                script_path = Path(resolved)
                self.assertTrue(script_path.is_file(),
                                f"{script_path} (depuis {command!r}) n'existe pas.")
                # Toutes les commandes visent le meme point d'entree stable.
                self.assertEqual(script_path.resolve(),
                                 (self.plugin_root / "scripts" / "aidlc.py").resolve())

    def _events_appelant(self, subcommand):
        """Evenements de hooks.json dont un bloc appelle cette sous-commande."""
        out = set()
        for event, blocks in self.hooks_data["hooks"].items():
            for block in blocks:
                for hook in block.get("hooks", []):
                    tail = hook.get("command", "").split('aidlc.py" ')[-1]
                    if tail.split()[:1] == [subcommand]:
                        out.add(event)
        return out

    def test_le_journal_couvre_les_evenements_lus_par_les_diagnostics(self):
        """Le watchdog compte les ecritures (`payload.tool_name`, `tool_input.file_path`)
        et `improve` compte les outils : cette matiere n'existe que si `log` est branche
        sur un evenement d'outil. Elle a manque, et deux des trois detecteurs du watchdog
        etaient inatteignables sans qu'aucun test ne le voie — chacun fabriquait son
        journal a la main. C'est le cablage que ce test tient, pas la detection."""
        evenements = self._events_appelant("log")
        self.assertIn("PostToolUse", evenements,
                      "aucun evenement d'outil n'alimente .aidlc/logs/ : le detecteur "
                      "d'ecritures du watchdog ne peut jamais se declencher.")
        self.assertIn("UserPromptSubmit", evenements,
                      "sans UserPromptSubmit journalise, le detecteur de relances "
                      "(rerun_storm) ne compte rien.")

    def test_le_journal_couvre_les_evenements_qui_disent_le_cout_du_procede(self):
        """L'axe *autonomy* mesure ce que le procédé a coûté : un outil qui échoue, une
        permission demandée, un refus humain, un contexte qui déborde. Ces événements
        n'existent pour le diagnostic que s'ils sont journalisés — non branchés, ils ne
        laissent aucune trace et l'axe se note à l'impression."""
        attendus = {"PostToolUseFailure", "Notification", "PermissionDenied",
                    "PreCompact", "SessionEnd"}
        manquants = attendus - self._events_appelant("log")
        self.assertFalse(manquants, f"evenements non journalises : {sorted(manquants)}")

    def test_le_journal_precede_les_verifications_du_meme_evenement(self):
        """Dans PostToolUse, `log` passe en premier : le journal doit exister meme quand
        une validation echoue ensuite, et la dedup de journal_bundle_write s'appuie sur
        cette entree deja ecrite pour ne pas compter l'ecriture deux fois."""
        blocks = self.hooks_data["hooks"]["PostToolUse"]
        tails = [b["hooks"][0]["command"].split('aidlc.py" ')[-1] for b in blocks]
        self.assertEqual(tails[0], "log", f"ordre des hooks PostToolUse : {tails}")

    def test_chaque_sous_commande_existe_dans_le_parseur(self):
        for command in self.commands:
            tokens = shlex.split(command)
            script_index = next(
                i for i, t in enumerate(tokens) if t.endswith("aidlc.py"))
            remainder = tokens[script_index + 1:]
            if not remainder:
                continue
            subcommand = remainder[0]
            with self.subTest(command=command):
                self.assertIn(subcommand, self.choices,
                             f"sous-commande {subcommand!r} absente de "
                             "_aidlc.cli.build_parser().")
                # Les options citees (--touched, --stop, ...) doivent aussi etre
                # acceptees par ce sous-parseur, sinon le hook echouerait a l'usage.
                buffer = io.StringIO()
                try:
                    with contextlib.redirect_stderr(buffer):
                        cli.build_parser().parse_args(remainder)
                except SystemExit as exc:
                    self.fail(f"{command!r} rejete par argparse : {buffer.getvalue()}")


class TestSkillMdPaths(unittest.TestCase):
    """Chaque chemin de fichier explicitement rattache a une racine connue
    (${CLAUDE_PLUGIN_ROOT}/..., $CLAUDE_PROJECT_DIR/..., plugins/...) dans un SKILL.md
    existe reellement."""

    def test_chemins_rattaches_existent(self):
        root = repo_root()
        skill_files = sorted(root.glob("plugins/*/skills/*/SKILL.md"))
        self.assertTrue(skill_files, "aucun SKILL.md trouve sous plugins/*/skills/*/")
        checked_at_least_one = False
        for skill_path in skill_files:
            text = skill_path.read_text(encoding="utf-8")
            plugin_root = skill_path.parents[2]
            for raw, kind in _rooted_paths(text):
                checked_at_least_one = True
                if kind == "plugin":
                    suffix = raw[len("${CLAUDE_PLUGIN_ROOT}"):]
                    target = plugin_root / suffix.lstrip("/")
                elif kind == "project":
                    suffix = raw[len("$CLAUDE_PROJECT_DIR"):]
                    target = root / suffix.lstrip("/")
                else:
                    target = root / raw
                with self.subTest(skill=str(skill_path.relative_to(root)), path=raw):
                    self.assertTrue(target.exists(),
                                    f"{skill_path} cite {raw!r} -> {target} absent.")
        self.assertTrue(checked_at_least_one,
                        "aucun chemin rattache a une racine n'a ete trouve dans les "
                        "SKILL.md : le motif de detection a peut-etre divergé du contenu.")


class TestMarketplace(unittest.TestCase):
    """.claude-plugin/marketplace.json liste exactement les plugins presents sous
    plugins/ - ni de plus (plugin fantome), ni de moins (plugin oublie)."""

    def test_marketplace_liste_exactement_les_plugins_du_depot(self):
        root = repo_root()
        marketplace = json.loads(
            (root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        declared = {entry["name"] for entry in marketplace["plugins"]}
        present = {p.name for p in _plugin_dirs()}
        self.assertEqual(declared, present)

    def test_chaque_source_declaree_pointe_un_dossier_reel(self):
        root = repo_root()
        marketplace = json.loads(
            (root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        for entry in marketplace["plugins"]:
            source = entry["source"]
            with self.subTest(plugin=entry["name"]):
                self.assertTrue(source.startswith("./"),
                                f"{entry['name']} : source {source!r} pas relative au depot.")
                target = root / source[2:]
                self.assertTrue(target.is_dir(),
                                f"{entry['name']} : source {source!r} -> {target} absent.")
                self.assertTrue((target / ".claude-plugin" / "plugin.json").exists())


class TestChecksJson(unittest.TestCase):
    """Chaque checks.json du depot parse et n'utilise que des regles connues de
    _aidlc.checks - une regle inconnue serait silencieusement ignoree par run_checks."""

    def test_chaque_checks_json_du_depot_n_utilise_que_des_regles_connues(self):
        root = repo_root()
        checks_files = sorted(root.glob("plugins/*/checks.json"))
        self.assertTrue(checks_files, "aucun checks.json trouve sous plugins/")
        for checks_path in checks_files:
            with self.subTest(checks=str(checks_path.relative_to(root))):
                data = json.loads(checks_path.read_text(encoding="utf-8"))
                self.assertIsInstance(data, dict)
                inconnues = [k for k in data if k not in checks.KNOWN_RULES
                            and not k.startswith("_")]
                self.assertEqual(inconnues, [],
                                 f"{checks_path} : regles inconnues {inconnues}.")

    def test_chaque_agent_gouverne_a_un_checks_json_qui_parse(self):
        """Un agent.json qui declare `produces` doit pointer un checks.json qui existe
        et parse, sinon aucun livrable de cette etape ne pourra jamais etre valide."""
        for manifest_path in _agent_manifest_paths():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not data.get("produces"):
                continue
            checks_rel = data.get("checks")
            with self.subTest(agent=data["id"]):
                self.assertTrue(checks_rel, f"{manifest_path} : produces sans checks.")
                checks_path = manifest_path.parent / checks_rel
                self.assertTrue(checks_path.exists(),
                                f"{manifest_path} : checks {checks_rel!r} absent.")
                json.loads(checks_path.read_text(encoding="utf-8"))


class TestDocPaths(unittest.TestCase):
    """Tout chemin plugins/... cite dans CLAUDE.md et dans les README des plugins existe
    reellement dans le depot."""

    def test_chemins_plugins_de_claude_md_existent(self):
        root = repo_root()
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        found = False
        for raw, _kind in _rooted_paths(text):
            if not raw.startswith("plugins/"):
                continue
            found = True
            with self.subTest(path=raw):
                self.assertTrue((root / raw).exists(),
                                f"CLAUDE.md cite {raw!r} -> {root / raw} absent.")
        self.assertTrue(found, "aucun chemin plugins/... trouve dans CLAUDE.md.")

    def test_chemins_plugins_des_readme_existent(self):
        root = repo_root()
        readmes = sorted(root.glob("plugins/*/README.md"))
        self.assertTrue(readmes, "aucun README.md trouve sous plugins/")
        found_any = False
        for readme_path in readmes:
            text = readme_path.read_text(encoding="utf-8")
            for raw, _kind in _rooted_paths(text):
                if not raw.startswith("plugins/"):
                    continue
                found_any = True
                with self.subTest(readme=str(readme_path.relative_to(root)), path=raw):
                    self.assertTrue((root / raw).exists(),
                                    f"{readme_path} cite {raw!r} -> {root / raw} absent.")
        self.assertTrue(found_any,
                        "aucun chemin plugins/... trouve dans les README de plugins.")


if __name__ == "__main__":
    unittest.main()


#: Appels au moteur cites dans un fichier de porte (hook shell, workflow CI).
_AIDLC_CALL_RE = re.compile(r"aidlc\.py\s+([a-z][a-z-]*)")


class TestPortesLocalesEtCI(unittest.TestCase):
    """Le hook pre-commit et le workflow CI sont deux fichiers hors du moteur qui
    invoquent le moteur : un renommage de sous-commande ou du point d'entree les casse
    en silence. Meme porte que `TestHooksJson`, appliquee aux portes de qualite."""

    ENTRYPOINT = "plugins/aidlc-core/scripts/aidlc.py"

    @classmethod
    def setUpClass(cls):
        cls.hook = repo_root() / ".githooks" / "pre-commit"
        cls.workflow = repo_root() / ".github" / "workflows" / "ci.yml"
        cls.choices = _subparser_choices()

    def test_le_hook_pre_commit_existe(self):
        self.assertTrue(self.hook.is_file(), f"{self.hook} absent.")

    def test_le_hook_pre_commit_est_executable(self):
        """Git n'execute qu'un hook dont le bit d'execution est pose ; sans lui, la porte
        locale est silencieusement inerte — le pire mode de panne pour un garde-fou."""
        self.assertTrue(self.hook.stat().st_mode & 0o111,
                        "Le bit d'execution du hook n'est pas pose (chmod +x).")

    def test_le_hook_vise_le_point_d_entree_reel(self):
        self.assertIn(self.ENTRYPOINT, self.hook.read_text(encoding="utf-8"))
        self.assertTrue((repo_root() / self.ENTRYPOINT).is_file())

    def test_le_hook_n_invoque_que_des_sous_commandes_exposees(self):
        called = _AIDLC_CALL_RE.findall(self.hook.read_text(encoding="utf-8"))
        self.assertTrue(called, "Le hook pre-commit n'invoque aucune sous-commande.")
        for name in called:
            with self.subTest(sous_commande=name):
                self.assertIn(name, self.choices)

    def test_le_workflow_ci_n_invoque_que_des_sous_commandes_exposees(self):
        called = _AIDLC_CALL_RE.findall(self.workflow.read_text(encoding="utf-8"))
        self.assertTrue(called, "Le workflow CI n'invoque aucune sous-commande.")
        for name in called:
            with self.subTest(sous_commande=name):
                self.assertIn(name, self.choices)

    def test_le_workflow_ci_vise_le_point_d_entree_reel(self):
        self.assertIn(self.ENTRYPOINT, self.workflow.read_text(encoding="utf-8"))

    def test_la_porte_du_score_est_tenue_des_deux_cotes(self):
        """Le local et le distant rendent le meme verdict : `selfscore` est la porte
        agregee, elle ne doit pas exister d'un seul cote."""
        for path in (self.hook, self.workflow):
            with self.subTest(fichier=path.name):
                self.assertIn("selfscore",
                              _AIDLC_CALL_RE.findall(path.read_text(encoding="utf-8")))
