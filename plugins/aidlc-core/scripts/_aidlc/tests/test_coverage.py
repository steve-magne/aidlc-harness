from __future__ import annotations

import json
import subprocess

from pathlib import Path
from unittest.mock import patch

from .harness import AidlcTestCase
from ..coverage import TOLERANCE
from ..coverage import _parse_cover
from ..coverage import coverage_path
from ..coverage import coverage_reset
from ..coverage import coverage_run
from ..coverage import entrypoint
from ..coverage import measure
from ..util import aidlc_dir
from ..util import ensure_dir
from ..util import read_text

"""Suite du ratchet de couverture (plugins/aidlc-core/scripts/_aidlc/coverage.py) :
lecture des fichiers .cover produits par `trace`, chemins, et le meme geste que
ratchet.py (figeage au premier passage, refus de regression au-dela de TOLERANCE,
durcissement libre, reset explicite) applique au taux de couverture.

`measure()` relance la suite entiere en sous-processus : jamais appelee pour de vrai
ici. `coverage_run`/`coverage_reset` sont testes en substituant `measure` ; `measure`
lui-meme est teste en substituant `subprocess.run` et en fabriquant de faux .cover.
"""


def _fresh(total, modules, suite_passed=True, executed=None, missing=None):
    """Fabrique un retour de measure() pret a etre injecte via patch."""
    if executed is None:
        executed = sum(m["executed"] for m in modules.values())
    if missing is None:
        missing = sum(m["missing"] for m in modules.values())
    return {"suite_passed": suite_passed, "modules": modules, "total": total,
            "executed": executed, "missing": missing}


def _module(pct, executed=90, missing=10):
    return {"executed": executed, "missing": missing, "pct": pct}


class ParseCoverTestCase(AidlcTestCase):
    """_parse_cover sur un vrai contenu .cover fabrique a la main : compte les lignes
    executees (prefixees d'un compteur), les lignes mortes (prefixees de >>>>>>), et
    ignore le reste (lignes vides, lignes sans marque de couverture)."""

    def _write_cover(self, content: str) -> Path:
        return self.write("scratch/fake.cover", content)

    def test_une_ligne_avec_compteur_est_executee(self):
        path = self._write_cover("    3: import os\n")
        executed, missing = _parse_cover(path)
        self.assertEqual((executed, missing), (1, 0))

    def test_une_ligne_prefixee_de_chevrons_est_morte(self):
        path = self._write_cover(">>>>>>     def jamais_appelee():\n")
        executed, missing = _parse_cover(path)
        self.assertEqual((executed, missing), (0, 1))

    def test_une_ligne_sans_marque_de_couverture_nest_ni_lune_ni_lautre(self):
        # Ligne de continuation du format trace : six espaces, pas de compteur.
        path = self._write_cover("       def foo():\n")
        executed, missing = _parse_cover(path)
        self.assertEqual((executed, missing), (0, 0))

    def test_une_ligne_vide_nest_ni_lune_ni_lautre(self):
        path = self._write_cover("\n")
        executed, missing = _parse_cover(path)
        self.assertEqual((executed, missing), (0, 0))

    def test_un_fichier_mixte_cumule_correctement(self):
        content = ("    3: import os\n"
                   "       \n"
                   ">>>>>>     def dead():\n"
                   "    1:     return 1\n"
                   "\n")
        path = self._write_cover(content)
        executed, missing = _parse_cover(path)
        self.assertEqual((executed, missing), (2, 1))


class CoveragePathEtEntrypointTestCase(AidlcTestCase):
    """Les deux fonctions de chemin, sans mesure ni sous-processus."""

    def test_coverage_path_vit_sous_aidlc_dir(self):
        self.assertEqual(coverage_path(self.root),
                         aidlc_dir(self.root) / "coverage.json")

    def test_entrypoint_vit_sous_scripts_du_harnais(self):
        self.assertEqual(entrypoint(), self.root / "scripts" / "aidlc.py")


class CoverageRunPremierPassageTestCase(AidlcTestCase):
    """Premier passage : rien de fige encore, on cree la baseline."""

    def test_premier_passage_est_une_baseline(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            result = coverage_run(self.root)
        self.assertTrue(result["baseline"])

    def test_premier_passage_passe_si_la_suite_passe(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            result = coverage_run(self.root)
        self.assertTrue(result["passed"])
        self.assertEqual(result["regressions"], [])

    def test_premier_passage_ecrit_le_fichier_de_plancher(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            coverage_run(self.root)
        self.assertTrue(coverage_path(self.root).exists())
        state = json.loads(read_text(coverage_path(self.root)))
        self.assertTrue(state["baseline"])
        self.assertEqual(state["modules"]["util"], 90.0)
        self.assertEqual(state["total"], 90.0)


class CoverageRunNominalTestCase(AidlcTestCase):
    """Deuxieme passage sans regression : stable ou en hausse, plancher releve."""

    def setUp(self):
        super().setUp()
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            coverage_run(self.root)

    def test_couverture_stable_nest_plus_une_baseline_et_passe(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            result = coverage_run(self.root)
        self.assertFalse(result["baseline"])
        self.assertTrue(result["passed"])

    def test_couverture_en_hausse_releve_le_plancher(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(95.0, {"util": _module(95.0)})):
            result = coverage_run(self.root)
        self.assertTrue(result["passed"])
        state = json.loads(read_text(coverage_path(self.root)))
        self.assertEqual(state["modules"]["util"], 95.0)

    def test_une_baisse_a_la_limite_exacte_de_tolerance_passe(self):
        limite = 90.0 - TOLERANCE
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(limite, {"util": _module(limite)})):
            result = coverage_run(self.root)
        self.assertTrue(result["passed"])
        self.assertEqual(result["regressions"], [])
        # Le plancher fige ne redescend jamais malgre l'ecriture : le maximum est garde.
        state = json.loads(read_text(coverage_path(self.root)))
        self.assertEqual(state["modules"]["util"], 90.0)


class CoverageRunRegressionTestCase(AidlcTestCase):
    """Baisse au-dela de TOLERANCE : refusee, plancher intact, hint present."""

    def setUp(self):
        super().setUp()
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            coverage_run(self.root)
        self.baseline_state = json.loads(read_text(coverage_path(self.root)))

    def test_une_baisse_au_dela_de_la_tolerance_echoue(self):
        juste_sous_la_limite = 90.0 - TOLERANCE - 0.1
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(juste_sous_la_limite,
                                       {"util": _module(juste_sous_la_limite)})):
            result = coverage_run(self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["regressions"]), 1)
        regression = result["regressions"][0]
        self.assertEqual(regression["module"], "util")
        self.assertEqual(regression["before"], 90.0)
        self.assertAlmostEqual(regression["after"], juste_sous_la_limite)
        self.assertEqual(regression["reason"], "couverture en baisse")

    def test_une_regression_porte_un_hint(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(80.0, {"util": _module(80.0)})):
            result = coverage_run(self.root)
        self.assertIn("hint", result)
        self.assertIn("ne descend jamais", result["hint"])

    def test_le_fichier_de_plancher_nest_pas_reecrit_en_cas_de_regression(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(80.0, {"util": _module(80.0)})):
            coverage_run(self.root)
        state_apres = json.loads(read_text(coverage_path(self.root)))
        self.assertEqual(state_apres, self.baseline_state)

    def test_un_module_disparu_de_la_mesure_est_une_regression(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {})):
            result = coverage_run(self.root)
        self.assertFalse(result["passed"])
        regression = result["regressions"][0]
        self.assertEqual(regression["module"], "util")
        self.assertIsNone(regression["after"])
        self.assertEqual(regression["reason"], "module disparu de la mesure")


class CoverageRunFichierMalformeTestCase(AidlcTestCase):
    """Un .aidlc/coverage.json illisible replie sur une nouvelle baseline plutot que
    de faire echouer le ratchet."""

    def test_un_coverage_json_malforme_redemarre_a_zero(self):
        ensure_dir(aidlc_dir(self.root))
        coverage_path(self.root).write_text("{ pas du json valide", encoding="utf-8")
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            result = coverage_run(self.root)
        self.assertTrue(result["baseline"])
        self.assertTrue(result["passed"])
        state = json.loads(read_text(coverage_path(self.root)))
        self.assertEqual(state["modules"]["util"], 90.0)


class CoverageRunSuiteRougeTestCase(AidlcTestCase):
    """Quand measure() rapporte une suite rouge : passed est faux et un hint dedie
    apparait. ATTENTION (bug suspecte, voir notes) : le plancher est neanmoins
    reecrit tant qu'aucune regression de pourcentage n'est detectee, malgre le hint
    qui affirme le contraire."""

    def setUp(self):
        super().setUp()
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            coverage_run(self.root)

    def test_suite_rouge_sans_regression_de_pourcentage_echoue_quand_meme(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)},
                                       suite_passed=False)):
            result = coverage_run(self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(result["regressions"], [])

    def test_suite_rouge_porte_le_hint_dedie(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)},
                                       suite_passed=False)):
            result = coverage_run(self.root)
        self.assertIn("hint", result)
        self.assertIn("suite elle-meme est rouge", result["hint"])

    def test_bug_suspecte_le_plancher_monte_meme_suite_rouge(self):
        # Comportement REEL du moteur : rien ne conditionne l'ecriture du plancher a
        # suite_passed, seule l'absence de regression compte. Une suite rouge dont la
        # couverture mesuree grimpe fait donc monter le plancher fige, en
        # contradiction avec le hint ("Le plancher n'est pas mis a jour tant qu'elle
        # ne passe pas."). Voir notes de rendu.
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(95.0, {"util": _module(95.0)},
                                       suite_passed=False)):
            result = coverage_run(self.root)
        self.assertFalse(result["passed"])
        state = json.loads(read_text(coverage_path(self.root)))
        self.assertEqual(state["modules"]["util"], 95.0)


class CoverageResetTestCase(AidlcTestCase):
    """coverage_reset : rebase explicite, refus si la suite est rouge."""

    def test_reset_rebase_sur_letat_courant(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            coverage_run(self.root)
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(40.0, {"util": _module(40.0)})):
            result = coverage_reset(self.root)
        self.assertEqual(result["modules"]["util"], 40.0)
        state = json.loads(read_text(coverage_path(self.root)))
        self.assertEqual(state["modules"]["util"], 40.0)
        self.assertTrue(state["baseline"])

    def test_reset_horodate_reset_at(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            result = coverage_reset(self.root)
        self.assertIn("reset_at", result)
        state = json.loads(read_text(coverage_path(self.root)))
        self.assertEqual(state["reset_at"], result["reset_at"])
        self.assertEqual(state["ts"], result["reset_at"])

    def test_reset_refuse_si_la_suite_est_rouge(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)},
                                       suite_passed=False)):
            with self.assertRaises(ValueError):
                coverage_reset(self.root)

    def test_reset_refuse_ne_touche_pas_un_plancher_existant(self):
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(90.0, {"util": _module(90.0)})):
            coverage_run(self.root)
        avant = json.loads(read_text(coverage_path(self.root)))
        with patch("_aidlc.coverage.measure",
                   return_value=_fresh(10.0, {"util": _module(10.0)},
                                       suite_passed=False)):
            with self.assertRaises(ValueError):
                coverage_reset(self.root)
        apres = json.loads(read_text(coverage_path(self.root)))
        self.assertEqual(avant, apres)


def _extract_coverdir(command: list) -> str:
    marker = "--coverdir="
    return next(arg[len(marker):] for arg in command if arg.startswith(marker))


class MeasureTestCase(AidlcTestCase):
    """measure() lui-meme : sous-processus et fichiers .cover substitues, jamais la
    vraie suite. Chaque test fabrique ses propres .cover dans le coverdir demande par
    la commande interceptee."""

    def setUp(self):
        super().setUp()
        # entrypoint() doit exister pour que measure() ne s'arrete pas plus tot.
        self.write("scripts/aidlc.py", "# faux point d'entree pour la mesure\n")

    def _patched_run(self, writer):
        """Renvoie un faux subprocess.run qui ecrit des .cover via `writer(coverdir)`
        puis simule un run reussi (returncode 0)."""
        def fake_run(command, **kwargs):
            coverdir = _extract_coverdir(command)
            writer(Path(coverdir))
            return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")
        return fake_run

    def test_mesure_nominale_rend_les_modules_et_le_total(self):
        def writer(coverdir):
            (coverdir / "_aidlc.util.cover").write_text(
                "    9: import os\n>>>>>>     def morte():\n", encoding="utf-8")

        with patch("subprocess.run", side_effect=self._patched_run(writer)):
            result = measure()
        self.assertTrue(result["suite_passed"])
        self.assertIn("util", result["modules"])
        self.assertEqual(result["modules"]["util"], {"executed": 1, "missing": 1, "pct": 50.0})
        self.assertEqual(result["executed"], 1)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(result["total"], 50.0)

    def test_les_modules_exclus_sont_filtres(self):
        def writer(coverdir):
            (coverdir / "_aidlc.util.cover").write_text("    1: x = 1\n", encoding="utf-8")
            (coverdir / "_aidlc.tests.test_util.cover").write_text(
                "    1: x = 1\n", encoding="utf-8")
            (coverdir / "_aidlc.selftest.cover").write_text(
                "    1: x = 1\n", encoding="utf-8")
            (coverdir / "_aidlc.__init__.cover").write_text(
                "    1: x = 1\n", encoding="utf-8")

        with patch("subprocess.run", side_effect=self._patched_run(writer)):
            result = measure()
        self.assertEqual(set(result["modules"]), {"util"})

    def test_un_module_sans_aucune_ligne_mesuree_est_ignore(self):
        def writer(coverdir):
            (coverdir / "_aidlc.util.cover").write_text("    1: x = 1\n", encoding="utf-8")
            (coverdir / "_aidlc.vide.cover").write_text("\n\n", encoding="utf-8")

        with patch("subprocess.run", side_effect=self._patched_run(writer)):
            result = measure()
        self.assertNotIn("vide", result["modules"])

    def test_une_suite_qui_echoue_est_rapportee_suite_passed_faux(self):
        def writer(coverdir):
            (coverdir / "_aidlc.util.cover").write_text("    1: x = 1\n", encoding="utf-8")

        def fake_run(command, **kwargs):
            coverdir = _extract_coverdir(command)
            writer(Path(coverdir))
            return subprocess.CompletedProcess(command, returncode=1, stdout="",
                                               stderr="echec")
        with patch("subprocess.run", side_effect=fake_run):
            result = measure()
        self.assertFalse(result["suite_passed"])

    def test_aucune_donnee_produite_leve_runtimeerror(self):
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, returncode=1, stdout="",
                                               stderr="boum, rien nulle part")
        with patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(RuntimeError) as ctx:
                measure()
        self.assertIn("boum, rien nulle part", str(ctx.exception))

    def test_le_select_est_transmis_en_argument_k(self):
        commandes = []

        def fake_run(command, **kwargs):
            commandes.append(command)
            coverdir = _extract_coverdir(command)
            Path(coverdir, "_aidlc.util.cover").write_text(
                "    1: x = 1\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            measure(select="test_truc")
        self.assertIn("-k", commandes[0])
        self.assertIn("test_truc", commandes[0])

    def test_point_dentree_absent_leve_filenotfounderror(self):
        (self.root / "scripts" / "aidlc.py").unlink()
        with self.assertRaises(FileNotFoundError):
            measure()
