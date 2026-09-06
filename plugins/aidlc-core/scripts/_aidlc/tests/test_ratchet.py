from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil

from .harness import AidlcTestCase
from .harness import manifest
from .. import registry
from ..commands import cmd_ratchet
from ..ratchet import freeze_current
from ..ratchet import ratchet_path
from ..ratchet import ratchet_reset
from ..ratchet import ratchet_run
from ..util import aidlc_dir
from ..util import read_text
from ..util import write_json

"""Suite du ratchet (plugins/aidlc-core/scripts/_aidlc/ratchet.py) : figeage des
planchers de severite (min_words, min_items_per_section, required_sections) au
premier passage, refus de toute regression, durcissement libre, reset explicite,
et registre ouvert (un agent qui disparait n'efface pas son plancher fige)."""


PROOF_CHECKS = {
    "required_frontmatter": ["stage", "version", "status", "author", "date"],
    "required_sections": ["## Contexte", "## Probleme", "## Criteres d'acceptation"],
    "min_words": 60,
    "forbidden_patterns": ["TODO", "TBD"],
    "must_reference_inputs": True,
    "min_items_per_section": {"## Criteres d'acceptation": 3},
}


def _run_ratchet(root, reset=None):
    """Invoque cmd_ratchet en process, stdout/stderr captures (comme l'ancien
    selftest.py) : renvoie (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cmd_ratchet(root, argparse.Namespace(reset=reset))
    return code, out.getvalue(), err.getvalue()


class RatchetFigeageEtRegressionTestCase(AidlcTestCase):
    """Migration du scenario 34 de l'ancien selftest.py : figeage au premier passage,
    regression refusee, durcissement accepte, reset explicite."""

    def setUp(self):
        super().setUp()
        self.design_checks_path = self.root / "plugins" / "aidlc-design" / "checks.json"
        write_json(self.design_checks_path, PROOF_CHECKS)

    def test_le_premier_passage_du_ratchet_doit_figer(self):
        code, _, _ = _run_ratchet(self.root)
        self.assertEqual(code, 0)

    def test_letat_du_ratchet_doit_etre_ecrit(self):
        _run_ratchet(self.root)
        self.assertTrue((aidlc_dir(self.root) / "ratchet.json").exists())

    def test_le_ratchet_doit_refuser_un_plancher_descendu(self):
        _run_ratchet(self.root)
        regressed = dict(PROOF_CHECKS)
        regressed["min_words"] = 10
        write_json(self.design_checks_path, regressed)
        code, _, _ = _run_ratchet(self.root)
        self.assertEqual(code, 2)

    def test_le_plancher_fige_ne_doit_pas_suivre_la_regression(self):
        _run_ratchet(self.root)
        regressed = dict(PROOF_CHECKS)
        regressed["min_words"] = 10
        write_json(self.design_checks_path, regressed)
        _run_ratchet(self.root)
        state = json.loads(read_text(aidlc_dir(self.root) / "ratchet.json"))
        self.assertEqual(state["stages"]["design"]["min_words"], 60)

    def test_durcir_un_plancher_doit_passer_sans_reset(self):
        _run_ratchet(self.root)
        hardened = dict(PROOF_CHECKS)
        hardened["min_words"] = 90
        write_json(self.design_checks_path, hardened)
        code, _, _ = _run_ratchet(self.root)
        self.assertEqual(code, 0)

    def test_le_figeage_doit_suivre_le_durcissement(self):
        _run_ratchet(self.root)
        hardened = dict(PROOF_CHECKS)
        hardened["min_words"] = 90
        write_json(self.design_checks_path, hardened)
        _run_ratchet(self.root)
        state = json.loads(read_text(aidlc_dir(self.root) / "ratchet.json"))
        self.assertEqual(state["stages"]["design"]["min_words"], 90)

    def test_le_reset_explicite_doit_repartir_du_checks_json_courant(self):
        _run_ratchet(self.root)
        regressed = dict(PROOF_CHECKS)
        regressed["min_words"] = 10
        write_json(self.design_checks_path, regressed)
        code, _, _ = _run_ratchet(self.root, reset="design")
        self.assertEqual(code, 0)

    def test_apres_reset_le_plancher_vaut_letat_courant_et_porte_reset_at(self):
        _run_ratchet(self.root)
        regressed = dict(PROOF_CHECKS)
        regressed["min_words"] = 10
        write_json(self.design_checks_path, regressed)
        _run_ratchet(self.root, reset="design")
        state = json.loads(read_text(aidlc_dir(self.root) / "ratchet.json"))
        self.assertEqual(state["stages"]["design"]["min_words"], 10)
        self.assertIn("reset_at", state["stages"]["design"])

    def test_retour_au_dessus_des_planchers_apres_reset(self):
        _run_ratchet(self.root)
        regressed = dict(PROOF_CHECKS)
        regressed["min_words"] = 10
        write_json(self.design_checks_path, regressed)
        _run_ratchet(self.root, reset="design")
        write_json(self.design_checks_path, PROOF_CHECKS)
        code, _, _ = _run_ratchet(self.root)
        self.assertEqual(code, 0)

    def test_ratchet_run_doit_rapporter_passed(self):
        _run_ratchet(self.root)
        result = ratchet_run(self.root, self.pipeline)
        self.assertTrue(result["passed"])

    def test_le_reset_dune_etape_inconnue_doit_echouer(self):
        _run_ratchet(self.root)
        with self.assertRaises(ValueError):
            ratchet_reset(self.root, self.pipeline, "inconnue")

    def test_le_reset_dune_etape_inconnue_leve_valueerror(self):
        # Doublon volontaire du libelle d'origine (deux check() distincts dans
        # selftest.py pour la meme assertion) : conserve pour ne perdre aucun libelle.
        _run_ratchet(self.root)
        try:
            ratchet_reset(self.root, self.pipeline, "inconnue")
        except ValueError:
            return
        self.fail("ratchet_reset aurait du lever ValueError pour une etape inconnue")


class FreezeCurrentTestCase(AidlcTestCase):
    """freeze_current lit le checks.json de chaque etape gouvernee du registre — un
    plugin sans fichier ou avec un fichier illisible est ignore silencieusement."""

    seed_agents = False

    def _seed_stage(self, checks=None, checks_content_raw=None):
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                  "deliverables/plan/intent.md"),
                          checks=None if (checks is None and checks_content_raw is None)
                          else None)
        target = self.root / "plugins" / "aidlc-plan"
        write_json(target / "agent.json",
                   manifest("plan", "Produit", "deliverables/plan/intent.md"))
        if checks is not None:
            write_json(target / "checks.json", checks)
        if checks_content_raw is not None:
            (target / "checks.json").write_text(checks_content_raw, encoding="utf-8")
        registry.reset_cache()

    def test_une_etape_sans_checks_json_est_ignoree(self):
        self._seed_stage(checks=None)
        self.assertEqual(freeze_current(self.pipeline), {})

    def test_une_etape_avec_un_checks_json_illisible_est_ignoree(self):
        self._seed_stage(checks_content_raw="{ ceci n'est pas du json")
        self.assertEqual(freeze_current(self.pipeline), {})

    def test_une_etape_sans_regle_figeable_est_absente_du_cliche(self):
        self._seed_stage(checks={"forbidden_patterns": ["TODO"]})
        self.assertEqual(freeze_current(self.pipeline), {})

    def test_les_planchers_min_words_et_sections_sont_captures(self):
        self._seed_stage(checks=PROOF_CHECKS)
        snapshot = freeze_current(self.pipeline)
        self.assertEqual(snapshot["plan"]["min_words"], 60)
        self.assertEqual(snapshot["plan"]["min_items_per_section"],
                         {"## Criteres d'acceptation": 3})
        self.assertEqual(snapshot["plan"]["required_sections"]["count"], 3)


class RatchetRunEtatDuFichierTestCase(AidlcTestCase):
    """Le fichier .aidlc/ratchet.json lui-meme : absent, cree, ou malforme."""

    def setUp(self):
        super().setUp()
        write_json(self.root / "plugins" / "aidlc-design" / "checks.json", PROOF_CHECKS)

    def test_ratchet_json_absent_donne_une_baseline_vraie(self):
        self.assertFalse(ratchet_path(self.root).exists())
        result = ratchet_run(self.root, self.pipeline)
        self.assertTrue(result["baseline"])
        self.assertTrue(ratchet_path(self.root).exists())

    def test_deuxieme_passage_sans_changement_nest_plus_une_baseline(self):
        ratchet_run(self.root, self.pipeline)
        result = ratchet_run(self.root, self.pipeline)
        self.assertFalse(result["baseline"])
        self.assertTrue(result["passed"])

    def test_un_ratchet_json_malforme_redemarre_a_zero(self):
        ratchet_run(self.root, self.pipeline)
        ratchet_path(self.root).write_text("{ pas du json valide", encoding="utf-8")
        result = ratchet_run(self.root, self.pipeline)
        self.assertTrue(result["passed"])
        self.assertIn("design", result["stages_frozen"])

    def test_design_est_bien_dans_les_etapes_figees(self):
        result = ratchet_run(self.root, self.pipeline)
        self.assertIn("design", result["stages_frozen"])


class RatchetRunViolationsTestCase(AidlcTestCase):
    """Chaque forme de regression detectee par _violations_for."""

    def setUp(self):
        super().setUp()
        self.design_checks_path = self.root / "plugins" / "aidlc-design" / "checks.json"
        write_json(self.design_checks_path, PROOF_CHECKS)
        ratchet_run(self.root, self.pipeline)

    def test_supprimer_min_words_est_une_regression(self):
        stripped = {k: v for k, v in PROOF_CHECKS.items() if k != "min_words"}
        write_json(self.design_checks_path, stripped)
        result = ratchet_run(self.root, self.pipeline)
        self.assertFalse(result["passed"])
        rules = {v["rule"] for v in result["violations"]}
        self.assertIn("min_words", rules)
        violation = next(v for v in result["violations"] if v["rule"] == "min_words")
        self.assertIsNone(violation["after"])

    def test_supprimer_une_section_de_min_items_per_section_est_une_regression(self):
        stripped = {k: v for k, v in PROOF_CHECKS.items() if k != "min_items_per_section"}
        write_json(self.design_checks_path, stripped)
        result = ratchet_run(self.root, self.pipeline)
        self.assertFalse(result["passed"])
        violation = next(v for v in result["violations"]
                         if v["rule"] == "min_items_per_section[## Criteres d'acceptation]")
        self.assertEqual(violation["before"], 3)
        self.assertIsNone(violation["after"])

    def test_baisser_min_items_per_section_est_une_regression(self):
        lowered = dict(PROOF_CHECKS)
        lowered["min_items_per_section"] = {"## Criteres d'acceptation": 1}
        write_json(self.design_checks_path, lowered)
        result = ratchet_run(self.root, self.pipeline)
        self.assertFalse(result["passed"])
        violation = next(v for v in result["violations"]
                         if v["rule"] == "min_items_per_section[## Criteres d'acceptation]")
        self.assertEqual(violation["before"], 3)
        self.assertEqual(violation["after"], 1)

    def test_supprimer_une_section_obligatoire_est_une_regression(self):
        reduced = dict(PROOF_CHECKS)
        reduced["required_sections"] = ["## Contexte", "## Probleme"]
        write_json(self.design_checks_path, reduced)
        result = ratchet_run(self.root, self.pipeline)
        self.assertFalse(result["passed"])
        rules = {v["rule"] for v in result["violations"]}
        self.assertIn("required_sections", rules)

    def test_ajouter_une_section_obligatoire_nest_pas_une_regression(self):
        extended = dict(PROOF_CHECKS)
        extended["required_sections"] = list(PROOF_CHECKS["required_sections"]) + ["## Risques"]
        write_json(self.design_checks_path, extended)
        result = ratchet_run(self.root, self.pipeline)
        self.assertTrue(result["passed"])
        state = json.loads(read_text(ratchet_path(self.root)))
        self.assertIn("## Risques", state["stages"]["design"]["required_sections"]["items"])

    def test_ajouter_une_nouvelle_section_a_min_items_per_section_est_figee(self):
        extended = dict(PROOF_CHECKS)
        extended["min_items_per_section"] = dict(PROOF_CHECKS["min_items_per_section"])
        extended["min_items_per_section"]["## Contexte"] = 2
        write_json(self.design_checks_path, extended)
        result = ratchet_run(self.root, self.pipeline)
        self.assertTrue(result["passed"])
        state = json.loads(read_text(ratchet_path(self.root)))
        self.assertEqual(state["stages"]["design"]["min_items_per_section"]["## Contexte"], 2)


class RatchetRunRegistreOuvertTestCase(AidlcTestCase):
    """Un agent qui disparait du registre, ou dont le contrat devient illisible ou
    absent apres figeage, ne fait pas taire le ratchet."""

    def setUp(self):
        super().setUp()
        self.design_checks_path = self.root / "plugins" / "aidlc-design" / "checks.json"
        write_json(self.design_checks_path, PROOF_CHECKS)
        ratchet_run(self.root, self.pipeline)

    def test_un_agent_absent_du_registre_est_une_violation(self):
        shutil.rmtree(self.root / "plugins" / "aidlc-design")
        registry.reset_cache()
        result = ratchet_run(self.root, self.pipeline)
        self.assertFalse(result["passed"])
        violation = next(v for v in result["violations"] if v["stage"] == "design")
        self.assertEqual(violation["rule"], "agent absent du registre")

    def test_un_checks_json_disparu_apres_figeage_est_ignore_sans_violation(self):
        self.design_checks_path.unlink()
        result = ratchet_run(self.root, self.pipeline)
        self.assertTrue(result["passed"])
        self.assertIn("design", result["stages_frozen"])

    def test_un_checks_json_illisible_apres_figeage_est_ignore_sans_violation(self):
        self.design_checks_path.write_text("{ toujours pas du json", encoding="utf-8")
        result = ratchet_run(self.root, self.pipeline)
        self.assertTrue(result["passed"])

    def test_une_etape_sans_plancher_figeable_nest_jamais_validee(self):
        self.write_agent("aidlc-build",
                         manifest("build", "Ingenierie", "deliverables/build/plan.md",
                                  ["deliverables/design/spec.md"]),
                         {"forbidden_patterns": ["TODO"]})
        result = ratchet_run(self.root, self.pipeline)
        self.assertTrue(result["passed"])
        self.assertNotIn("build", result["stages_frozen"])


class RatchetResetTestCase(AidlcTestCase):
    """ratchet_reset : ses trois facons d'echouer, et son succes."""

    def setUp(self):
        super().setUp()
        write_json(self.root / "plugins" / "aidlc-design" / "checks.json", PROOF_CHECKS)

    def test_reset_sans_ratchet_json_leve_valueerror(self):
        self.assertFalse(ratchet_path(self.root).exists())
        with self.assertRaises(ValueError):
            ratchet_reset(self.root, self.pipeline, "design")

    def test_reset_avec_un_ratchet_json_malforme_leve_valueerror(self):
        ratchet_run(self.root, self.pipeline)
        ratchet_path(self.root).write_text("{ pas du json", encoding="utf-8")
        with self.assertRaises(ValueError):
            ratchet_reset(self.root, self.pipeline, "design")

    def test_reset_dune_etape_sans_plancher_figeable_leve_valueerror(self):
        ratchet_run(self.root, self.pipeline)
        self.write_agent("aidlc-build",
                         manifest("build", "Ingenierie", "deliverables/build/plan.md",
                                  ["deliverables/design/spec.md"]),
                         {"forbidden_patterns": ["TODO"]})
        with self.assertRaises(ValueError):
            ratchet_reset(self.root, self.pipeline, "build")

    def test_reset_reussi_renvoie_les_planchers_et_la_date(self):
        ratchet_run(self.root, self.pipeline)
        result = ratchet_reset(self.root, self.pipeline, "design")
        self.assertEqual(result["stage"], "design")
        self.assertIn("reset_at", result)
        self.assertEqual(result["floors"]["min_words"], 60)


class RatchetNouvelleRegleTestCase(AidlcTestCase):
    """Une nouvelle etape gouvernee, apparue apres la premiere baseline, est figee au
    passage suivant sans jamais etre traitee comme une regression."""

    def setUp(self):
        super().setUp()
        write_json(self.root / "plugins" / "aidlc-design" / "checks.json", PROOF_CHECKS)
        ratchet_run(self.root, self.pipeline)

    def test_une_nouvelle_etape_gouvernee_est_figee_au_prochain_passage(self):
        self.write_agent("aidlc-build",
                         manifest("build", "Ingenierie", "deliverables/build/plan.md",
                                  ["deliverables/design/spec.md"]),
                         PROOF_CHECKS)
        result = ratchet_run(self.root, self.pipeline)
        self.assertTrue(result["passed"])
        self.assertIn("build", result["stages_frozen"])
        state = json.loads(read_text(ratchet_path(self.root)))
        self.assertEqual(state["stages"]["build"]["min_words"], 60)
