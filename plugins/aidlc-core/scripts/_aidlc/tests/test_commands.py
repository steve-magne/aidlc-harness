from __future__ import annotations

import io
import json
import sys

from contextlib import redirect_stderr
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from .harness import AidlcTestCase
from .harness import CHECKS
from .harness import document
from .harness import manifest
from .. import commands
from ..cli import build_parser
from ..maturity import record_score
from ..util import write_json

"""Couche commandes (_aidlc.commands) : les gestionnaires appeles par cli.main, en mode
ligne de commande et en mode hook (--touched, --stop, payload stdin). Chaque commande est
invoquee directement en Python, jamais en sous-processus (c'est le role de test_cli.py)."""


def parse(argv):
    """Args valides pour une commande, en passant par le vrai parseur : valide aussi la
    forme des arguments, pas seulement le comportement du gestionnaire."""
    return build_parser().parse_args(argv)


def run(func, *args):
    """Execute une commande en capturant stdout/stderr separement. Renvoie
    (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = func(*args)
    return code, out.getvalue(), err.getvalue()


class TestReadHookPayload(AidlcTestCase):
    """_read_hook_payload lit le JSON du hook sur stdin sans jamais bloquer hors
    contexte de hook — c'est la fonction la plus fragile de la couche commandes."""

    def test_stdin_tty_rend_un_dict_vide(self):
        with mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: True)):
            self.assertEqual(commands._read_hook_payload(), {})

    def test_rien_de_pret_sur_le_pipe_rend_un_dict_vide(self):
        fake_stdin = mock.Mock(isatty=lambda: False)
        with mock.patch.object(sys, "stdin", fake_stdin), \
             mock.patch.object(commands.select, "select", return_value=([], [], [])):
            self.assertEqual(commands._read_hook_payload(), {})

    def test_json_casse_sur_le_pipe_rend_un_dict_vide(self):
        fake_stdin = mock.Mock(isatty=lambda: False)
        fake_stdin.read = lambda: "pas du json"
        with mock.patch.object(sys, "stdin", fake_stdin), \
             mock.patch.object(commands.select, "select",
                               return_value=([fake_stdin], [], [])):
            self.assertEqual(commands._read_hook_payload(), {})

    def test_payload_json_valide_est_lu(self):
        fake_stdin = mock.Mock(isatty=lambda: False)
        fake_stdin.read = lambda: json.dumps({"session_id": "s1"})
        with mock.patch.object(sys, "stdin", fake_stdin), \
             mock.patch.object(commands.select, "select",
                               return_value=([fake_stdin], [], [])):
            self.assertEqual(commands._read_hook_payload(), {"session_id": "s1"})

    def test_une_liste_json_n_est_pas_un_payload(self):
        fake_stdin = mock.Mock(isatty=lambda: False)
        fake_stdin.read = lambda: "[1, 2]"
        with mock.patch.object(sys, "stdin", fake_stdin), \
             mock.patch.object(commands.select, "select",
                               return_value=([fake_stdin], [], [])):
            self.assertEqual(commands._read_hook_payload(), {})


class TestHookInput(AidlcTestCase):
    """_hook_input : --file dispense de lire stdin ; sinon le payload du hook fournit
    le fichier touche, la session assainie et le nom de l'outil."""

    def test_avec_file_le_payload_n_est_jamais_lu(self):
        with mock.patch.object(commands, "_read_hook_payload") as fake:
            touched, session_id, tool_name = commands._hook_input(
                parse(["validate", "--touched", "--file", "x.md"]))
        fake.assert_not_called()
        self.assertEqual((touched, session_id, tool_name), ("x.md", None, None))

    def test_sans_file_le_payload_stdin_est_source(self):
        payload = {"tool_input": {"file_path": "y.md"}, "session_id": "../s",
                  "tool_name": "Write"}
        with mock.patch.object(commands, "_read_hook_payload", return_value=payload):
            touched, session_id, tool_name = commands._hook_input(
                parse(["validate", "--touched"]))
        self.assertEqual(touched, "y.md")
        self.assertEqual(session_id, "___s")
        self.assertEqual(tool_name, "Write")

    def test_payload_vide_ne_fournit_rien(self):
        with mock.patch.object(commands, "_read_hook_payload", return_value={}):
            self.assertEqual(commands._hook_input(parse(["validate", "--touched"])),
                             (None, None, None))


class TestCmdLog(AidlcTestCase):
    """Un hook qui casse la session est pire que pas de log : silence total."""

    def test_journalise_un_evenement_valide(self):
        code = commands.cmd_log(self.root, json.dumps({"session_id": "s1",
                                                        "hook_event_name": "PreToolUse"}))
        self.assertEqual(code, 0)

    def test_entree_cassee_ne_leve_jamais(self):
        self.assertEqual(commands.cmd_log(self.root, "{ pas du json"), 0)

    def test_entree_vide_ne_leve_jamais(self):
        self.assertEqual(commands.cmd_log(self.root, ""), 0)


class TestCmdGuard(AidlcTestCase):
    """guard protege .aidlc/ : un refus se manifeste par une decision JSON deny sur
    stdout, jamais par un code de sortie non nul."""

    def test_entree_cassee_est_ignoree_silencieusement(self):
        code, out, err = run(commands.cmd_guard, self.root, "pas du json")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_ecriture_hors_dossier_protege_est_autorisee(self):
        raw = json.dumps({"tool_input": {"file_path": str(self.root / "notes.md")}})
        code, out, _ = run(commands.cmd_guard, self.root, raw)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_ecriture_de_maturity_json_est_refusee(self):
        target = self.root / ".aidlc" / "maturity.json"
        raw = json.dumps({"tool_input": {"file_path": str(target)}})
        code, out, _ = run(commands.cmd_guard, self.root, raw)
        self.assertEqual(code, 0)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("maturity.json", decision["permissionDecisionReason"])


class TestCmdValidate(AidlcTestCase):
    """validate : mode direct (CI, ligne de commande) et mode --touched (hook
    PostToolUse, silencieux hors livrable)."""

    def test_pipeline_illisible_en_mode_touche_rend_zero_silencieusement(self):
        self.write("pipeline.json", "{ pas du json")
        code = commands.cmd_validate(self.root, parse(
            ["validate", "--touched", "--file", "x.md"]))
        self.assertEqual(code, 0)

    def test_pipeline_illisible_hors_mode_touche_rend_un_et_ecrit_sur_stderr(self):
        self.write("pipeline.json", "{ pas du json")
        code, out, err = run(commands.cmd_validate, self.root, parse(["validate", "plan"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("pipeline.json illisible", err)

    def test_touche_sans_fichier_touche_rend_zero(self):
        code = commands.cmd_validate(self.root, parse(["validate", "--touched"]))
        self.assertEqual(code, 0)

    def test_touche_sur_un_fichier_qui_n_est_le_livrable_d_aucune_etape_rend_zero(self):
        path = self.write("ailleurs.md", "peu importe")
        code = commands.cmd_validate(self.root, parse(
            ["validate", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)

    def test_touche_sur_un_livrable_conforme_ajoute_un_contexte_ok(self):
        path = self.plan_intent()
        code, out, _ = run(commands.cmd_validate, self.root, parse(
            ["validate", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("OK", message)
        self.assertIn("plan", message)

    def test_touche_sur_un_livrable_non_conforme_ajoute_un_contexte_d_echec(self):
        path = self.plan_intent(sections={})
        code, out, _ = run(commands.cmd_validate, self.root, parse(
            ["validate", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("EN ECHEC", message)

    def test_sans_etape_ni_mode_touche_affiche_l_usage_et_rend_un(self):
        code, out, err = run(commands.cmd_validate, self.root, parse(["validate"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("usage", err)

    def test_etape_valide_rend_zero_sans_message_d_erreur(self):
        self.plan_intent()
        code, out, err = run(commands.cmd_validate, self.root, parse(["validate", "plan"]))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])
        self.assertEqual(err, "")

    def test_etape_avec_avertissement_l_affiche_sur_stderr(self):
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md"),
                         dict(CHECKS, regle_inconnue=True))
        self.plan_intent()
        code, out, err = run(commands.cmd_validate, self.root, parse(["validate", "plan"]))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])
        self.assertIn("[avertissement]", err)

    def test_etape_invalide_affiche_les_erreurs_sur_stderr(self):
        code, out, err = run(commands.cmd_validate, self.root, parse(["validate", "plan"]))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["ok"])
        self.assertIn("[erreur]", err)

    def test_json_supprime_le_resume_humain(self):
        code, out, err = run(commands.cmd_validate, self.root, parse(
            ["validate", "plan", "--json"]))
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        self.assertIn("errors", json.loads(out))


class TestCmdScore(AidlcTestCase):
    """score enregistre une revue de maturite ; une revue malformee est un echec
    propre (exit 1), jamais une exception qui remonte."""

    GOOD_REVIEW = {"scores": {"completeness": 4, "precision": 4,
                              "traceability": 4, "autonomy": 4},
                  "verdict": "accepted"}

    def test_revue_valide_est_enregistree(self):
        review_path = self.write_json("review.json", self.GOOD_REVIEW)
        code, out, _ = run(commands.cmd_score, self.root,
                           parse(["score", "plan", "--file", str(review_path)]))
        self.assertEqual(code, 0)
        record = json.loads(out)
        self.assertEqual(record["run"], 1)
        self.assertEqual(record["verdict"], "accepted")

    def test_etape_de_la_revue_differente_de_l_argument_avertit_sans_bloquer(self):
        review = dict(self.GOOD_REVIEW, stage="design")
        review_path = self.write_json("review.json", review)
        code, out, err = run(commands.cmd_score, self.root,
                             parse(["score", "plan", "--file", str(review_path)]))
        self.assertEqual(code, 0)
        self.assertIn("Attention", err)
        self.assertIn("design", err)

    def test_revue_avec_axe_manquant_rend_un(self):
        review_path = self.write_json("review.json", {"scores": {"completeness": 4}})
        code, out, err = run(commands.cmd_score, self.root,
                             parse(["score", "plan", "--file", str(review_path)]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("Revue invalide", err)

    def test_revue_avec_score_hors_bornes_rend_un(self):
        scores = dict(self.GOOD_REVIEW["scores"], completeness=9)
        review_path = self.write_json("review.json", {"scores": scores})
        code, out, err = run(commands.cmd_score, self.root,
                             parse(["score", "plan", "--file", str(review_path)]))
        self.assertEqual(code, 1)
        self.assertIn("Revue invalide", err)


class TestCmdGate(AidlcTestCase):
    """gate decide si l'etape est franchie : exit 2 (porte bloquante) si un motif de
    blocage subsiste, exit 0 sinon."""

    def test_etape_sans_score_est_bloquante(self):
        code, out, err = run(commands.cmd_gate, self.root, parse(["gate", "plan"]))
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["passed"])
        self.assertIn("[bloquant]", err)

    def test_agent_inconnu_est_bloquant(self):
        code, out, _ = run(commands.cmd_gate, self.root, parse(["gate", "fantome"]))
        self.assertEqual(code, 2)
        self.assertIn("Agent inconnu du registre", json.loads(out)["blocking"][0])


class TestCmdReviewRequest(AidlcTestCase):
    """review-request prepare le gabarit de revue humaine ; une etape sans livrable
    n'a rien a faire relire."""

    def test_prepare_le_gabarit_pour_une_etape_gouvernee(self):
        code, out, _ = run(commands.cmd_review_request, self.root,
                           parse(["review-request", "plan"]))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["stage"], "plan")
        self.assertTrue((self.root / data["template"]).exists())

    def test_agent_inconnu_rend_un(self):
        code, out, err = run(commands.cmd_review_request, self.root,
                             parse(["review-request", "fantome"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("Agent inconnu du registre", err)


class TestCmdRecall(AidlcTestCase):
    """recall : consigne de reprise humaine par defaut, JSON sur demande."""

    def _noter(self, **review):
        self.plan_intent()
        review.setdefault("scores", {"completeness": 2, "precision": 2,
                                     "traceability": 2, "autonomy": 2})
        record_score(self.root, self.pipeline, "plan", review)

    def test_etape_inconnue_rend_un_avec_le_motif_sur_stderr(self):
        code, out, err = run(commands.cmd_recall, self.root, parse(["recall", "fantome"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("Agent inconnu du registre", err)

    def test_mode_humain_affiche_le_reproche(self):
        self._noter(findings=["Criteres non chiffres."])
        code, out, _ = run(commands.cmd_recall, self.root, parse(["recall", "plan"]))
        self.assertEqual(code, 0)
        self.assertIn("Criteres non chiffres.", out)

    def test_mode_json_rend_la_structure_du_rappel(self):
        self._noter(findings=["Criteres non chiffres."])
        code, out, err = run(commands.cmd_recall, self.root,
                             parse(["recall", "plan", "--json"]))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out)["runs"][0]["findings"],
                         ["Criteres non chiffres."])

    def test_sans_run_le_mode_humain_le_dit_sans_echouer(self):
        code, out, _ = run(commands.cmd_recall, self.root, parse(["recall", "plan"]))
        self.assertEqual(code, 0)
        self.assertIn("rien a reprendre", out)


class TestCmdStatus(AidlcTestCase):
    """status : tableau de bord humain par defaut, JSON sur demande."""

    def test_mode_humain_affiche_le_tableau(self):
        code, out, _ = run(commands.cmd_status, self.root, parse(["status"]))
        self.assertEqual(code, 0)
        self.assertIn("tableau de bord", out)

    def test_mode_json_rend_la_structure_du_tableau(self):
        code, out, err = run(commands.cmd_status, self.root, parse(["status", "--json"]))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        data = json.loads(out)
        self.assertIn("stages", data)


class TestCmdScaffold(AidlcTestCase):
    """scaffold genere le plugin d'une etape planifiee ; un agent deja existant
    refuse sans --force."""

    seed_agents = False

    def test_genere_le_plugin_d_une_etape_planifiee(self):
        code, out, _ = run(commands.cmd_scaffold, self.root, parse(["scaffold", "build"]))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["plugin"], "aidlc-build")
        self.assertTrue((self.root / "plugins" / "aidlc-build" / "agent.json").exists())

    def test_agent_deja_existant_refuse_sans_force(self):
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md"), CHECKS)
        code, out, err = run(commands.cmd_scaffold, self.root, parse(["scaffold", "plan"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("existe deja", err)


class TestCmdAgents(AidlcTestCase):
    """agents : catalogue du registre. Severite asymetrique (un manifeste invalide du
    depot bloque --strict, celui d'une autre equipe non)."""

    seed_agents = False

    def test_registre_vide_signale_l_absence_d_agent(self):
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents"]))
        self.assertEqual(code, 0)
        self.assertIn("Aucun agent dans le registre", err)

    def test_affiche_chaque_agent_et_son_invocation(self):
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md"), CHECKS)
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents"]))
        self.assertEqual(code, 0)
        self.assertIn("plan", err)
        self.assertIn("Produit", err)
        self.assertIn("aidlc-plan:plan", err)

    def test_agent_non_invocable_sur_la_plateforme_est_signale(self):
        self.write_agent("aidlc-plan", manifest(
            "plan", "Produit", "deliverables/plan/intent.md",
            invocation={"une-autre-plateforme": "x"}), CHECKS)
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents"]))
        self.assertEqual(code, 0)
        self.assertIn("AUCUNE — agent non invocable ici", err)

    def test_producteur_manquant_est_signale_sans_bloquer(self):
        design_checks = dict(CHECKS)
        design_checks["required_sections"] = ["## Contexte"]
        self.write_agent("aidlc-design", manifest(
            "design", "Architecture", "deliverables/design/spec.md",
            ["deliverables/plan/intent.md"]), design_checks)
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents"]))
        self.assertEqual(code, 0)
        self.assertIn("[manque]", err)
        self.assertIn("deliverables/plan/intent.md", err)

    def test_cycle_de_dependances_bloque_meme_hors_strict(self):
        self.write_agent("aidlc-a", manifest(
            "stage-a", "Equipe A", "deliverables/a.md", ["deliverables/b.md"]),
            CHECKS)
        self.write_agent("aidlc-b", manifest(
            "stage-b", "Equipe B", "deliverables/b.md", ["deliverables/a.md"]),
            CHECKS)
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents"]))
        self.assertEqual(code, 1)
        self.assertIn("[cycle]", err)

    def test_identifiant_en_double_est_un_avertissement_pas_un_blocage(self):
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md"), CHECKS)
        outside = Path(__import__("tempfile").mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        self.write_agent("dup-plan", manifest("plan", "AutreEquipe",
                                              "deliverables/plan/intent.md"), CHECKS,
                         base=outside)
        self.agent_path(self.root / "plugins", outside)
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents"]))
        self.assertEqual(code, 0)
        self.assertIn("Identifiant en double", err)
        self.assertIn("[avertissement]", err)

    def test_mode_json_ne_produit_aucun_message_humain(self):
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md"), CHECKS)
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents", "--json"]))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        data = json.loads(out)
        self.assertEqual(len(data["agents"]), 1)

    def test_strict_bloque_un_manifeste_invalide_du_projet(self):
        write_json(self.root / "plugins" / "casse" / "agent.json", {"manifest_version": 1})
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents", "--strict"]))
        self.assertEqual(code, 1)
        self.assertIn("[manifeste]", err)

    def test_strict_ignore_un_manifeste_invalide_hors_projet(self):
        outside = Path(__import__("tempfile").mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside, ignore_errors=True))
        write_json(outside / "casse" / "agent.json", {"manifest_version": 1})
        self.agent_path(self.root / "plugins", outside)
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents", "--strict"]))
        self.assertEqual(code, 0)
        self.assertIn("[manifeste]", err)

    def test_sans_strict_un_manifeste_invalide_du_projet_ne_bloque_pas(self):
        write_json(self.root / "plugins" / "casse" / "agent.json", {"manifest_version": 1})
        code, out, err = run(commands.cmd_agents, self.root, parse(["agents"]))
        self.assertEqual(code, 0)


class TestCmdImprove(AidlcTestCase):
    """improve : diagnostic JSON, jamais un echec meme sur un projet vierge."""

    def test_rend_un_diagnostic_json_sur_un_projet_vierge(self):
        code, out, err = run(commands.cmd_improve, self.root, parse(["improve"]))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        json.loads(out)

    def test_filtre_par_etape(self):
        code, out, _ = run(commands.cmd_improve, self.root, parse(
            ["improve", "--stage", "plan"]))
        self.assertEqual(code, 0)
        json.loads(out)


class TestCmdExperiment(AidlcTestCase):
    """experiment : `record` exige de quoi mesurer, `effect` rend un verdict et ne
    bloque jamais — un correctif sans effet est une information, pas un defaut."""

    ARGS = ["experiment", "record", "--stage", "plan", "--target", "precision",
            "--file", "plugins/aidlc-plan/checks.json", "--cause", "SKILL trop vague"]

    def test_record_ecrit_le_registre_et_rend_l_entree_sur_stdout(self):
        code, out, err = run(commands.cmd_experiment, self.root, parse(self.ARGS))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["stage"], "plan")
        self.assertIn("plan / precision", err)

    def test_record_sans_les_options_requises_echoue_en_les_nommant(self):
        code, out, err = run(commands.cmd_experiment, self.root,
                             parse(["experiment", "record", "--stage", "plan"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        for option in ("--target", "--file", "--cause"):
            self.assertIn(option, err)

    def test_record_sur_une_etape_inconnue_echoue_proprement(self):
        argv = list(self.ARGS)
        argv[argv.index("plan")] = "fantome"
        code, out, err = run(commands.cmd_experiment, self.root, parse(argv))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("fantome", err)

    def test_effect_sur_un_registre_vide_rend_une_liste_et_le_geste_a_faire(self):
        code, out, err = run(commands.cmd_experiment, self.root,
                             parse(["experiment", "effect"]))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])
        self.assertIn("experiment record", err)

    def test_effect_resume_chaque_experience_sur_stderr(self):
        run(commands.cmd_experiment, self.root, parse(self.ARGS))
        code, out, err = run(commands.cmd_experiment, self.root,
                             parse(["experiment", "effect"]))
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)), 1)
        self.assertIn("pending", err)

    def test_effect_en_json_ne_dit_rien_a_l_humain(self):
        run(commands.cmd_experiment, self.root, parse(self.ARGS))
        code, out, err = run(commands.cmd_experiment, self.root,
                             parse(["experiment", "effect", "--json"]))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(len(json.loads(out)), 1)

    def test_effect_filtre_par_etape(self):
        run(commands.cmd_experiment, self.root, parse(self.ARGS))
        _, out, _ = run(commands.cmd_experiment, self.root,
                        parse(["experiment", "effect", "--stage", "design"]))
        self.assertEqual(json.loads(out), [])


class TestCmdRatchet(AidlcTestCase):
    """ratchet fige les planchers au premier passage, refuse toute regression, et
    --reset est le seul moyen legal de les assouplir."""

    def test_premier_passage_fige_la_base(self):
        code, out, err = run(commands.cmd_ratchet, self.root, parse(["ratchet"]))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["baseline"])
        self.assertIn("Ratchet fige pour la premiere fois", err)

    def test_regression_du_plancher_est_bloquante(self):
        run(commands.cmd_ratchet, self.root, parse(["ratchet"]))
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md"),
                         dict(CHECKS, min_words=1))
        code, out, err = run(commands.cmd_ratchet, self.root, parse(["ratchet"]))
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["passed"])
        self.assertIn("[ratchet]", err)

    def test_reset_sans_ratchet_fige_rend_un(self):
        code, out, err = run(commands.cmd_ratchet, self.root, parse(
            ["ratchet", "--reset", "plan"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("Aucun ratchet fige", err)

    def test_reset_apres_figeage_repart_de_l_etat_courant(self):
        run(commands.cmd_ratchet, self.root, parse(["ratchet"]))
        code, out, _ = run(commands.cmd_ratchet, self.root, parse(
            ["ratchet", "--reset", "plan"]))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["stage"], "plan")


class TestCmdWatchdog(AidlcTestCase):
    """watchdog : diagnostic de stagnation sur les journaux, exit 2 si halte."""

    def test_sans_journal_aucune_halte(self):
        with mock.patch.object(sys, "stdin", io.StringIO("")):
            code, out, err = run(commands.cmd_watchdog, self.root, parse(["watchdog"]))
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["halted"])

    def test_boucle_d_ecriture_declenche_une_halte(self):
        events = [{"ts": f"2026-01-01T00:00:0{i}+00:00", "session_id": "s1",
                  "payload": {"tool_name": "Write",
                             "tool_input": {"file_path": "x.md"}}}
                 for i in range(6)]
        lines = "\n".join(json.dumps(e) for e in events) + "\n"
        self.write(".aidlc/logs/s1.jsonl", lines)
        with mock.patch.object(sys, "stdin", io.StringIO("")):
            code, out, err = run(commands.cmd_watchdog, self.root, parse(["watchdog"]))
        self.assertEqual(code, 2)
        data = json.loads(out)
        self.assertTrue(data["halted"])
        self.assertIn("[watchdog]", err)
        self.assertIn("improvement-queue.jsonl", err)
        queue = self.read(".aidlc/improvement-queue.jsonl")
        self.assertIn("write_loop", queue)


class TestCmdWatchdogTouched(AidlcTestCase):
    """watchdog-touched : mode hook, jamais bloquant, silencieux sans detection."""

    def test_silence_total_sans_detection(self):
        with mock.patch.object(sys, "stdin", io.StringIO("")):
            code, out, err = run(commands.cmd_watchdog_touched, self.root,
                                 parse(["watchdog-touched"]))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_enregistre_une_halte_sans_jamais_bloquer(self):
        events = [{"ts": f"2026-01-01T00:00:0{i}+00:00", "session_id": "s1",
                  "payload": {"tool_name": "Write",
                             "tool_input": {"file_path": "x.md"}}}
                 for i in range(6)]
        lines = "\n".join(json.dumps(e) for e in events) + "\n"
        self.write(".aidlc/logs/s1.jsonl", lines)
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"session_id": "s1"}))):
            code, out, err = run(commands.cmd_watchdog_touched, self.root,
                                 parse(["watchdog-touched"]))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        queue = self.read(".aidlc/improvement-queue.jsonl")
        self.assertIn("write_loop", queue)


OKF_GOOD_CONCEPT = "---\ntype: Reference\ntitle: Concept Un\n---\n\nContenu du concept.\n"
OKF_BAD_CONCEPT = "Aucun frontmatter ici, juste du texte.\n"


class TestCmdCheckOkf(AidlcTestCase):
    """check-okf : conformance OKF v0.2 d'un bundle, en ligne de commande et en modes
    hook --touched (PostToolUse, non bloquant) et --stop (Stop, refus dur)."""

    def test_sans_argument_ni_mode_hook_affiche_l_usage(self):
        code, out, err = run(commands.cmd_check_okf, self.root, parse(["check-okf"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("usage", err)

    def test_bundle_introuvable_rend_un(self):
        code, out, err = run(commands.cmd_check_okf, self.root, parse(
            ["check-okf", str(self.root / "absent")]))
        self.assertEqual(code, 1)
        self.assertIn("Bundle introuvable", err)

    def test_bundle_conforme_rend_zero(self):
        self.write("knowledge/concept-un.md", OKF_GOOD_CONCEPT)
        code, out, err = run(commands.cmd_check_okf, self.root, parse(
            ["check-okf", str(self.root / "knowledge")]))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])
        self.assertIn("Conformite OKF v0.2", err)

    def test_bundle_non_conforme_liste_les_problemes(self):
        self.write("knowledge/concept-un.md", OKF_BAD_CONCEPT)
        code, out, err = run(commands.cmd_check_okf, self.root, parse(
            ["check-okf", str(self.root / "knowledge")]))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["ok"])
        self.assertIn("[okf]", err)

    def test_touche_sans_fichier_touche_rend_zero(self):
        code = commands.cmd_check_okf(self.root, parse(["check-okf", "--touched"]))
        self.assertEqual(code, 0)

    def test_touche_avec_un_chemin_qui_ne_resout_pas_rend_zero(self):
        with mock.patch("pathlib.Path.resolve", side_effect=OSError("boom")):
            code = commands.cmd_check_okf(self.root, parse(
                ["check-okf", "--touched", "--file", "x.md"]))
        self.assertEqual(code, 0)

    def test_touche_hors_de_tout_bundle_okf_rend_zero(self):
        path = self.write("ailleurs.md", "peu importe")
        code, out, _ = run(commands.cmd_check_okf, self.root, parse(
            ["check-okf", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_touche_sur_un_concept_conforme_ajoute_un_contexte_ok(self):
        # "OKF" contient deja la sous-chaine "OK" : assertIn("OK", message) seul ne
        # falsifie rien (il passerait meme sur la branche NON CONFORME). On verifie
        # la formule de succes exacte et l'absence du marqueur d'echec.
        path = self.write("knowledge/concept-un.md", OKF_GOOD_CONCEPT)
        code, out, _ = run(commands.cmd_check_okf, self.root, parse(
            ["check-okf", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("knowledge/ : OK (1 fichier(s))", message)
        self.assertNotIn("NON CONFORME", message)

    def test_touche_sur_un_concept_non_conforme_journalise_l_ecriture(self):
        path = self.write("knowledge/concept-un.md", OKF_BAD_CONCEPT)
        code, out, _ = run(commands.cmd_check_okf, self.root, parse(
            ["check-okf", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("NON CONFORME", message)

    def test_stop_sans_bundle_ne_bloque_pas_la_fermeture(self):
        with mock.patch.object(sys, "stdin", io.StringIO("{}")):
            code, out, err = run(commands.cmd_check_okf, self.root, parse(
                ["check-okf", "--stop"]))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_stop_avec_bundle_conforme_ne_bloque_pas(self):
        self.write("knowledge/concept-un.md", OKF_GOOD_CONCEPT)
        with mock.patch.object(sys, "stdin", io.StringIO("{}")):
            code, out, err = run(commands.cmd_check_okf, self.root, parse(
                ["check-okf", "--stop"]))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_touche_hors_du_bundle_alors_qu_un_bundle_voisin_existe_rend_zero(self):
        # Le bundle "knowledge" existe (relative_to echoue avec ValueError, boucle
        # continue) tandis que "docs" n'existe pas (continue via is_dir) : les deux
        # branches de continue de la boucle sont exercees, sans ajouter de contexte.
        self.write("knowledge/concept-un.md", OKF_GOOD_CONCEPT)
        path = self.write("ailleurs.md", "peu importe")
        code, out, _ = run(commands.cmd_check_okf, self.root, parse(
            ["check-okf", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_stop_avec_bundle_non_conforme_refuse_la_fermeture(self):
        self.write("knowledge/concept-un.md", OKF_BAD_CONCEPT)
        with mock.patch.object(sys, "stdin", io.StringIO("{}")):
            code, out, _ = run(commands.cmd_check_okf, self.root, parse(
                ["check-okf", "--stop"]))
        self.assertEqual(code, 0)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("knowledge/", decision["permissionDecisionReason"])
        queue = self.read(".aidlc/improvement-queue.jsonl")
        self.assertIn("okf_stop", queue)


class TestCmdCheckPython(AidlcTestCase):
    """check-python : compile tout le Python d'un dossier, ou (--touched) le seul
    fichier .py ecrit par le hook."""

    def test_dossier_sans_python_est_conforme(self):
        code, out, err = run(commands.cmd_check_python, self.root, parse(
            ["check-python", str(self.root)]))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    def test_dossier_introuvable_rend_un(self):
        code, out, err = run(commands.cmd_check_python, self.root, parse(
            ["check-python", str(self.root / "absent")]))
        self.assertEqual(code, 1)
        self.assertIn("Repertoire introuvable", err)

    def test_syntaxe_cassee_rend_un(self):
        self.write("script.py", "def f(:\n    pass\n")
        code, out, err = run(commands.cmd_check_python, self.root, parse(
            ["check-python", str(self.root)]))
        self.assertEqual(code, 1)
        self.assertIn("[syntax]", err)

    def test_touche_sans_fichier_touche_rend_zero(self):
        code = commands.cmd_check_python(self.root, parse(["check-python", "--touched"]))
        self.assertEqual(code, 0)

    def test_touche_sur_un_fichier_d_une_autre_extension_rend_zero(self):
        path = self.write("notes.txt", "peu importe")
        code, out, _ = run(commands.cmd_check_python, self.root, parse(
            ["check-python", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_touche_sur_un_python_valide_ajoute_un_contexte_de_compilation(self):
        path = self.write("script.py", "x = 1\n")
        code, out, _ = run(commands.cmd_check_python, self.root, parse(
            ["check-python", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("compile", message)

    def test_touche_sur_un_python_casse_ajoute_un_contexte_d_echec(self):
        path = self.write("script.py", "def f(:\n")
        code, out, _ = run(commands.cmd_check_python, self.root, parse(
            ["check-python", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("NON CONFORME", message)

    def test_touche_avec_un_chemin_qui_ne_resout_pas_rend_zero(self):
        with mock.patch("pathlib.Path.resolve", side_effect=OSError("boom")):
            code = commands.cmd_check_python(self.root, parse(
                ["check-python", "--touched", "--file", "script.py"]))
        self.assertEqual(code, 0)

    def test_relpath_impossible_replie_sur_le_chemin_absolu(self):
        path = self.write("script.py", "x = 1\n")
        with mock.patch("os.path.relpath", side_effect=ValueError("boom")):
            code, out, _ = run(commands.cmd_check_python, self.root, parse(
                ["check-python", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(str(path), message)

    def test_fichier_touche_hors_du_projet_garde_son_chemin_brut(self):
        # relpath reussit mais rend un chemin qui remonte hors du projet ("../..") :
        # on garde le chemin brut rapporte par le hook plutot que cette remontee.
        import shutil
        import tempfile
        outside_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside_dir, ignore_errors=True)
        path = outside_dir / "script.py"
        path.write_text("x = 1\n", encoding="utf-8")
        code, out, _ = run(commands.cmd_check_python, self.root, parse(
            ["check-python", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"Conformite syntaxique : {path} compile.", message)


class TestCmdCheckJson(AidlcTestCase):
    """check-json : symetrique de check-python pour les fichiers .json."""

    def test_dossier_avec_json_valide_est_conforme(self):
        code, out, err = run(commands.cmd_check_json, self.root, parse(
            ["check-json", str(self.root)]))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    def test_json_casse_rend_un(self):
        self.write("donnees.json", "{ pas fini")
        code, out, err = run(commands.cmd_check_json, self.root, parse(
            ["check-json", str(self.root)]))
        self.assertEqual(code, 1)
        self.assertIn("[syntax]", err)

    def test_touche_sur_un_json_valide_ajoute_un_contexte_de_parsing(self):
        path = self.write("donnees.json", "{}\n")
        code, out, _ = run(commands.cmd_check_json, self.root, parse(
            ["check-json", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("parse", message)

    def test_touche_sur_un_json_casse_ajoute_un_contexte_d_echec(self):
        path = self.write("donnees.json", "{ pas fini")
        code, out, _ = run(commands.cmd_check_json, self.root, parse(
            ["check-json", "--touched", "--file", str(path)]))
        self.assertEqual(code, 0)
        message = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("NON CONFORME", message)


CONCEPT_MARGE = ("---\ntype: Reference\ntitle: Marge brute\n"
                 "description: Calcul de la marge brute.\ntags: [finance, marge]\n---\n\n"
                 "La marge brute se calcule ainsi.\n")
CONCEPT_AUTRE = "---\ntype: Reference\ntitle: Autre concept\n---\n\nSans rapport.\n"
#: Cite CONCEPT_AUTRE : de quoi exercer les deux sens de la traversee.
CONCEPT_LIANT = ("---\ntype: Reference\ntitle: Marge brute\n"
                 "description: Calcul de la marge brute.\n---\n\n"
                 "Depend de [l'autre](concept-deux.md).\n")


class TestCmdKnowledge(AidlcTestCase):
    """knowledge sert le savoir OKF des sources declarees dans knowledge-sources.json.
    Un `repo` qui designe un dossier local existant est utilise tel quel (bundle de
    test) : aucun appel git n'est necessaire pour ces tests."""

    def _declare_source(self, name="acme", **files):
        bundle = self.root / "kb-repo"
        for rel, content in files.items():
            self.write(f"kb-repo/{rel}", content)
        self.write_json("knowledge-sources.json",
                        {"sources": [{"name": name, "repo": str(bundle), "path": ""}]})
        return bundle

    def test_aucune_source_declaree_rend_un_message_d_aide(self):
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "index"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("Aucune source de savoir declaree", err)

    def test_sources_json_illisible_rend_un(self):
        self.write("knowledge-sources.json", "{ pas du json")
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "index"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")

    def test_source_filtree_sans_correspondance_rend_un_sans_message_d_aide(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "index", "--source", "inconnue"]))
        self.assertEqual(code, 1)
        self.assertIn("[source]", err)
        self.assertNotIn("Aucune source de savoir declaree", err)

    def test_index_liste_les_concepts_de_toutes_les_sources(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE,
                                "concept-deux.md": CONCEPT_AUTRE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "index"]))
        self.assertEqual(code, 0)
        self.assertIn("Marge brute", out)
        self.assertIn("Autre concept", out)
        self.assertIn("2 concept(s)", err)

    def test_index_json_rend_la_forme_machine(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "index", "--json"]))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 1)
        self.assertNotIn("path", data["concepts"][0])

    def test_limit_tronque_et_le_signale(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE,
                                "concept-deux.md": CONCEPT_AUTRE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "index", "--limit", "1"]))
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIn("non affiche", err)

    def test_links_liste_le_lien_sortant(self):
        self._declare_source(**{"concept-un.md": CONCEPT_LIANT,
                                "concept-deux.md": CONCEPT_AUTRE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "links", "acme/concept-un"]))
        self.assertEqual(code, 0)
        self.assertIn("-> acme/concept-deux", out)

    def test_links_liste_le_retrolien(self):
        self._declare_source(**{"concept-un.md": CONCEPT_LIANT,
                                "concept-deux.md": CONCEPT_AUTRE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "links", "acme/concept-deux"]))
        self.assertEqual(code, 0)
        self.assertIn("<- acme/concept-un", out)

    def test_links_json_separe_les_deux_sens(self):
        self._declare_source(**{"concept-un.md": CONCEPT_LIANT,
                                "concept-deux.md": CONCEPT_AUTRE})
        code, out, _ = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "links", "acme/concept-un", "--json"]))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual([e["ref"] for e in data["out"]], ["acme/concept-deux"])
        self.assertEqual(data["in"], [])

    def test_links_annonce_le_compte_des_voisins_sur_stderr(self):
        self._declare_source(**{"concept-un.md": CONCEPT_LIANT,
                                "concept-deux.md": CONCEPT_AUTRE})
        _, _, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "links", "acme/concept-un"]))
        self.assertIn("1 lien(s) sortant(s), 0 retrolien(s)", err)

    def test_links_sans_terme_affiche_l_usage(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "links"]))
        self.assertEqual(code, 1)
        self.assertIn("Usage", err)

    def test_links_concept_introuvable_rend_un(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "links", "acme/absent"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("introuvable", err)

    def test_search_sans_terme_affiche_l_usage(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "search"]))
        self.assertEqual(code, 1)
        self.assertIn("Usage", err)

    def test_search_filtre_par_mot_cle(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE,
                                "concept-deux.md": CONCEPT_AUTRE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "search", "marge"]))
        self.assertEqual(code, 0)
        self.assertIn("Marge brute", out)
        self.assertNotIn("Autre concept", out)

    def test_get_sans_terme_affiche_l_usage(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "get"]))
        self.assertEqual(code, 1)
        self.assertIn("Usage", err)

    def test_get_un_concept_introuvable_rend_un(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "get", "ne-existe-pas"]))
        self.assertEqual(code, 1)
        self.assertIn("introuvable", err)

    def test_get_un_concept_rend_son_markdown_et_un_rappel_de_source(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE})
        code, out, err = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "get", "acme/concept-un"]))
        self.assertEqual(code, 0)
        self.assertEqual(out, CONCEPT_MARGE)
        self.assertIn("contenu externe", err)
        self.assertIn("acme", err)

    def test_get_json_ajoute_le_corps_au_concept(self):
        self._declare_source(**{"concept-un.md": CONCEPT_MARGE})
        code, out, _ = run(commands.cmd_knowledge, self.root, parse(
            ["knowledge", "get", "acme/concept-un", "--json"]))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["body"], CONCEPT_MARGE)
        self.assertEqual(data["ref"], "acme/concept-un")


class TestCmdTest(AidlcTestCase):
    """test route vers _aidlc.tests.run. Le routage est verifie par substitution :
    relancer la suite depuis un test recurserait a l'infini (voir _REENTRANCY)."""

    def test_delegue_a_tests_run_avec_les_bons_arguments(self):
        with mock.patch("_aidlc.tests.run", return_value=0) as fake_run:
            code, out, err = run(commands.cmd_test, self.root, parse(["test"]))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        fake_run.assert_called_once_with(select=None, verbosity=1, failfast=False)

    def test_verbose_et_failfast_et_select_sont_relayes(self):
        with mock.patch("_aidlc.tests.run", return_value=0) as fake_run:
            commands.cmd_test(self.root, parse(
                ["test", "-k", "motif", "--verbose", "--failfast"]))
        fake_run.assert_called_once_with(select="motif", verbosity=2, failfast=True)

    def test_relaie_le_code_de_sortie_de_la_suite(self):
        with mock.patch("_aidlc.tests.run", return_value=1):
            code = commands.cmd_test(self.root, parse(["test"]))
        self.assertEqual(code, 1)


class TestCmdCoverage(AidlcTestCase):
    """coverage : ratchet de couverture. --reset rebase la base ; sinon la mesure
    est comparee au plancher fige (baseline, regression, ou passage normal)."""

    def test_reset_emet_le_rapport_de_rebasage(self):
        with mock.patch.object(commands, "coverage_reset",
                              return_value={"reset_at": "2026-01-01", "total": 90}) as fake:
            code, out, err = run(commands.cmd_coverage, self.root, parse(
                ["coverage", "--reset"]))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 90)
        fake.assert_called_once_with(self.root, None)

    def test_premiere_mesure_fige_le_plancher(self):
        with mock.patch.object(commands, "coverage_run", return_value={
                "baseline": True, "passed": True, "total": 91, "modules": ["util"]}):
            code, out, err = run(commands.cmd_coverage, self.root, parse(["coverage"]))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["baseline"])
        self.assertIn("Plancher de couverture fige a 91%", err)

    def test_regression_est_bloquante_et_liste_les_modules(self):
        with mock.patch.object(commands, "coverage_run", return_value={
                "baseline": False, "passed": False,
                "regressions": [{"module": "commands", "before": 95, "after": 80,
                                 "reason": "lignes non couvertes ajoutees"}],
                "hint": "corriger ou --reset"}):
            code, out, err = run(commands.cmd_coverage, self.root, parse(["coverage"]))
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["passed"])
        self.assertIn("[couverture] commands : 95% -> 80%", err)
        self.assertIn("corriger ou --reset", err)

    def test_regression_avec_module_disparu_affiche_absent(self):
        with mock.patch.object(commands, "coverage_run", return_value={
                "baseline": False, "passed": False,
                "regressions": [{"module": "supprime", "before": 95, "after": None,
                                 "reason": "module supprime"}],
                "hint": ""}):
            code, out, err = run(commands.cmd_coverage, self.root, parse(["coverage"]))
        self.assertEqual(code, 2)
        self.assertIn("[couverture] supprime : 95% -> absent", err)

    def test_mesure_conforme_rend_zero_et_resume_la_couverture(self):
        with mock.patch.object(commands, "coverage_run", return_value={
                "baseline": False, "passed": True, "total": 98, "missing": 12}):
            code, out, err = run(commands.cmd_coverage, self.root, parse(["coverage"]))
        self.assertEqual(code, 0)
        self.assertIn("Couverture : 98% (12 lignes non couvertes).", err)

    def test_select_est_relaye_a_coverage_run(self):
        with mock.patch.object(commands, "coverage_run", return_value={
                "baseline": False, "passed": True, "total": 98, "missing": 0}) as fake:
            run(commands.cmd_coverage, self.root, parse(["coverage", "-k", "commands"]))
        fake.assert_called_once_with(self.root, "commands")

    def test_erreur_du_moteur_est_un_echec_propre(self):
        with mock.patch.object(commands, "coverage_run",
                              side_effect=RuntimeError("suite indisponible")):
            code, out, err = run(commands.cmd_coverage, self.root, parse(["coverage"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("suite indisponible", err)


def rapport(overall=4.8, passed=True, weak=(), axes=None):
    """Rapport de selfscore_run pret a etre injecte : le contrat que rend la commande."""
    if axes is None:
        axes = [{"axis": "hygiene", "score": 5.0, "detail": "38 fichiers", "findings": []},
                {"axis": "knowledge", "score": None, "detail": "aucun bundle",
                 "findings": []}]
    return {"overall": overall, "threshold": 4.0, "min_axis_score": 3.0,
            "axes": axes, "weak_axes": list(weak), "passed": passed}


class TestCmdSelfscore(AidlcTestCase):
    """selfscore : score de maturite du harnais. Le contrat que consomment le hook
    pre-commit et la CI est un code de sortie (0 conforme, 2 bloquant, 1 en panne) ;
    le JSON de stdout et le resume de stderr ne se melangent jamais."""

    def test_un_depot_conforme_rend_zero(self):
        with mock.patch.object(commands, "selfscore_run", return_value=rapport()):
            code, out, err = run(commands.cmd_selfscore, self.root, parse(["selfscore"]))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["passed"])

    def test_le_resume_donne_une_ligne_par_axe(self):
        with mock.patch.object(commands, "selfscore_run", return_value=rapport()):
            code, out, err = run(commands.cmd_selfscore, self.root, parse(["selfscore"]))
        self.assertIn("hygiene", err)
        self.assertIn("38 fichiers", err)

    def test_un_axe_non_applicable_s_affiche_sans_note(self):
        with mock.patch.object(commands, "selfscore_run", return_value=rapport()):
            code, out, err = run(commands.cmd_selfscore, self.root, parse(["selfscore"]))
        self.assertIn("knowledge    n/a/5", err)

    def test_les_constats_d_un_axe_sont_listes_sous_lui(self):
        axes = [{"axis": "tests", "score": 4.0, "detail": "16/17 modules",
                 "findings": ["selfscore : aucun tests/test_selfscore.py en face"]}]
        with mock.patch.object(commands, "selfscore_run",
                              return_value=rapport(axes=axes)):
            code, out, err = run(commands.cmd_selfscore, self.root, parse(["selfscore"]))
        self.assertIn("- selfscore : aucun tests/test_selfscore.py en face", err)

    def test_le_score_et_les_seuils_sont_rappeles(self):
        with mock.patch.object(commands, "selfscore_run", return_value=rapport()):
            code, out, err = run(commands.cmd_selfscore, self.root, parse(["selfscore"]))
        self.assertIn("Score de maturite du harnais : 4.80/5", err)
        self.assertIn("seuil 4.0", err)

    def test_un_axe_effondre_bloque_avec_le_code_deux(self):
        with mock.patch.object(commands, "selfscore_run",
                              return_value=rapport(overall=3.8, passed=False,
                                                   weak=["coverage"])):
            code, out, err = run(commands.cmd_selfscore, self.root, parse(["selfscore"]))
        self.assertEqual(code, 2)
        self.assertIn("Bloquant : coverage", err)

    def test_une_moyenne_insuffisante_bloque_sans_nommer_d_axe(self):
        with mock.patch.object(commands, "selfscore_run",
                              return_value=rapport(overall=3.9, passed=False)):
            code, out, err = run(commands.cmd_selfscore, self.root, parse(["selfscore"]))
        self.assertEqual(code, 2)
        self.assertIn("moyenne sous le seuil", err)

    def test_json_seul_tait_le_resume_mais_pas_le_verdict(self):
        """--json est pour une machine : le detail humain disparait, le motif de blocage
        reste sur stderr — un runner de CI doit pouvoir dire pourquoi il rougit."""
        with mock.patch.object(commands, "selfscore_run",
                              return_value=rapport(overall=3.8, passed=False,
                                                   weak=["hygiene"])):
            code, out, err = run(commands.cmd_selfscore, self.root,
                                parse(["selfscore", "--json"]))
        self.assertNotIn("Score de maturite", err)
        self.assertIn("Bloquant : hygiene", err)
        self.assertEqual(json.loads(out)["overall"], 3.8)

    def test_une_mesure_impossible_est_un_echec_propre(self):
        with mock.patch.object(commands, "selfscore_run",
                              side_effect=RuntimeError("suite indisponible")):
            code, out, err = run(commands.cmd_selfscore, self.root, parse(["selfscore"]))
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("suite indisponible", err)

    def test_un_point_d_entree_absent_est_un_echec_propre(self):
        with mock.patch.object(commands, "selfscore_run",
                              side_effect=FileNotFoundError("aidlc.py introuvable")):
            code, out, err = run(commands.cmd_selfscore, self.root, parse(["selfscore"]))
        self.assertEqual(code, 1)
        self.assertIn("introuvable", err)
