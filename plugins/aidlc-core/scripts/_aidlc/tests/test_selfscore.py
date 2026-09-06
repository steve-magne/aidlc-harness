from __future__ import annotations

from unittest import mock

from .harness import AidlcTestCase
from .harness import manifest
from .. import selfscore
from ..coverage import TOLERANCE
from ..selfscore import MAX
from ..selfscore import axis_contracts
from ..selfscore import axis_coverage
from ..selfscore import axis_hygiene
from ..selfscore import axis_knowledge
from ..selfscore import axis_tests
from ..selfscore import band
from ..selfscore import coverage_floors
from ..selfscore import module_test_gaps
from ..selfscore import selfscore_run

"""Suite du score de maturite du harnais (plugins/aidlc-core/scripts/_aidlc/selfscore.py).

Chaque axe est une fonction pure d'un arbre de fichiers : ils sont testes sur le projet
temporaire, jamais sur le depot reel. La seule dependance couteuse est `coverage.measure`,
qui relancerait la suite entiere en sous-processus : elle est **toujours** substituee ici —
un test qui l'appellerait pour de vrai relancerait la suite depuis la suite.
"""


def fresh(total=99.0, modules=None, suite_passed=True):
    """Retour de measure() pret a etre injecte : le contrat minimal que lisent les axes."""
    modules = {"util": {"executed": 99, "missing": 1, "pct": 99.0}} \
        if modules is None else modules
    return {"suite_passed": suite_passed, "modules": modules, "total": total,
            "executed": 99, "missing": 1}


def module(pct):
    return {"executed": int(pct), "missing": int(100 - pct), "pct": pct}


class TestAxeHygiene(AidlcTestCase):
    """Regle 6 notee : tout Python compile, tout JSON parse. Binaire par construction —
    un depot qui ne se charge pas n'a pas de qualite partielle."""

    def test_un_projet_sain_vaut_la_note_maximale(self):
        self.write("scripts/outil.py", "def f():\n    return 1\n")
        self.assertEqual(axis_hygiene(self.root)["score"], MAX)

    def test_un_python_qui_ne_compile_pas_effondre_l_axe(self):
        self.write("scripts/casse.py", "def f(:\n")
        self.assertEqual(axis_hygiene(self.root)["score"], 0.0)

    def test_le_fichier_python_fautif_est_nomme(self):
        self.write("scripts/casse.py", "def f(:\n")
        self.assertTrue(any("scripts/casse.py" in finding
                            for finding in axis_hygiene(self.root)["findings"]))

    def test_un_json_qui_ne_parse_pas_effondre_l_axe(self):
        self.write("config/casse.json", "{ pas du json")
        self.assertEqual(axis_hygiene(self.root)["score"], 0.0)

    def test_le_detail_compte_les_deux_familles_de_fichiers(self):
        self.write("scripts/outil.py", "x = 1\n")
        detail = axis_hygiene(self.root)["detail"]
        self.assertIn("fichiers Python compiles", detail)
        self.assertIn("fichiers JSON parses", detail)


class TestAxeContracts(AidlcTestCase):
    """Manifestes et contrats du depot courant. La severite est asymetrique : un
    manifeste casse chez une equipe voisine n'entre pas dans notre note."""

    def test_des_agents_valides_valent_la_note_maximale(self):
        self.assertEqual(axis_contracts(self.root)["score"], MAX)

    def test_un_manifeste_invalide_du_depot_effondre_l_axe(self):
        self.write_json("plugins/aidlc-casse/agent.json", {"id": "casse"})
        self.assertEqual(axis_contracts(self.root)["score"], 0.0)

    def test_le_manifeste_invalide_est_nomme_dans_les_constats(self):
        self.write_json("plugins/aidlc-casse/agent.json", {"id": "casse"})
        self.assertTrue(any("aidlc-casse" in finding
                            for finding in axis_contracts(self.root)["findings"]))

    def test_un_manifeste_invalide_hors_depot_ne_baisse_pas_la_note(self):
        """La CI d'un consommateur ne rougit pas pour le manifeste d'une autre equipe."""
        voisin = self.root.parent / "depot-voisin"
        self.write_json("../depot-voisin/aidlc-autre/agent.json", {"id": "autre"})
        self.addCleanup(lambda: [p.unlink() for p in voisin.rglob("*.json")])
        self.agent_path(self.root / "plugins", voisin)
        self.assertEqual(axis_contracts(self.root)["score"], MAX)

    def test_un_cycle_entre_agents_effondre_l_axe(self):
        """Un cycle producteur -> consommateur rend l'ordre des etapes indefini : c'est
        toujours notre affaire, d'ou qu'il vienne."""
        self.write_agent("aidlc-a", manifest("a", "Equipe", "deliverables/a/a.md",
                                             ["deliverables/b/b.md"]), {})
        self.write_agent("aidlc-b", manifest("b", "Equipe", "deliverables/b/b.md",
                                             ["deliverables/a/a.md"]), {})
        axis = axis_contracts(self.root)
        self.assertEqual(axis["score"], 0.0)
        self.assertTrue(any("circulaires" in finding for finding in axis["findings"]))


class TestModuleTestGaps(AidlcTestCase):
    """Regle 8 lue sur l'arborescence reelle du moteur : un module = un test en face."""

    def test_chaque_module_du_moteur_a_son_test_en_face(self):
        """Dogfood : ce depot tient la regle qu'il note. Ajouter un module sans son
        test fait tomber ce test avant meme de faire baisser la note."""
        self.assertEqual(module_test_gaps()[1], [])

    def test_le_paquet_lui_meme_n_est_pas_compte_comme_module(self):
        self.assertNotIn("__init__", module_test_gaps()[0])

    def test_le_moteur_expose_ses_modules_connus(self):
        modules = module_test_gaps()[0]
        for name in ("checks", "maturity", "registry", "selfscore"):
            self.assertIn(name, modules)


class TestAxeTests(AidlcTestCase):
    """La suite passe (sinon 0), et un point de moins par module orphelin."""

    def test_une_suite_rouge_effondre_l_axe(self):
        self.assertEqual(axis_tests(fresh(suite_passed=False))["score"], 0.0)

    def test_une_suite_rouge_le_dit_dans_les_constats(self):
        axis = axis_tests(fresh(suite_passed=False))
        self.assertTrue(any("rouge" in finding for finding in axis["findings"]))

    def test_une_suite_verte_sans_trou_vaut_la_note_maximale(self):
        with mock.patch.object(selfscore, "module_test_gaps",
                               return_value=(["util", "checks"], [])):
            self.assertEqual(axis_tests(fresh())["score"], MAX)

    def test_un_module_orphelin_coute_un_point(self):
        with mock.patch.object(selfscore, "module_test_gaps",
                               return_value=(["util", "checks"], ["checks"])):
            self.assertEqual(axis_tests(fresh())["score"], MAX - 1)

    def test_le_module_orphelin_est_nomme(self):
        with mock.patch.object(selfscore, "module_test_gaps",
                               return_value=(["util", "checks"], ["checks"])):
            axis = axis_tests(fresh())
        self.assertEqual(axis["findings"], ["checks : aucun tests/test_checks.py en face"])

    def test_la_note_ne_descend_jamais_sous_zero(self):
        gaps = [f"module{n}" for n in range(9)]
        with mock.patch.object(selfscore, "module_test_gaps", return_value=(gaps, gaps)):
            self.assertEqual(axis_tests(fresh())["score"], 0.0)


class TestBandesDeCouverture(AidlcTestCase):
    """La note de couverture se lit dans une table, elle ne se recalcule pas."""

    def test_une_couverture_quasi_totale_vaut_cinq(self):
        self.assertEqual(band(99.7), 5.0)

    def test_le_seuil_d_une_bande_appartient_a_la_bande_haute(self):
        self.assertEqual(band(95.0), 5.0)

    def test_juste_sous_le_seuil_fait_perdre_un_point(self):
        self.assertEqual(band(94.9), 4.0)

    def test_les_bandes_intermediaires_sont_tenues(self):
        self.assertEqual([band(90.0), band(80.0), band(70.0), band(50.0)],
                         [4.0, 3.0, 2.0, 1.0])

    def test_une_couverture_indigente_vaut_zero(self):
        self.assertEqual(band(49.9), 0.0)


class TestAxeCouverture(AidlcTestCase):
    """La mesure fraiche confrontee au plancher fige. Lecture seule : l'axe ne touche
    jamais .aidlc/coverage.json — c'est `aidlc.py coverage` qui l'ecrit."""

    def freeze(self, modules: dict):
        self.write_json(".aidlc/coverage.json", {"ts": "2026-01-01", "modules": modules})

    def test_sans_plancher_fige_seule_la_bande_compte(self):
        self.assertEqual(axis_coverage(self.root, fresh(91.0))["score"], 4.0)

    def test_un_plancher_tenu_laisse_la_bande_decider(self):
        self.freeze({"util": 99.0})
        axis = axis_coverage(self.root, fresh(99.0, {"util": module(99.0)}))
        self.assertEqual(axis["score"], 5.0)

    def test_une_regression_sous_le_plancher_effondre_l_axe(self):
        self.freeze({"util": 99.0})
        axis = axis_coverage(self.root, fresh(96.0, {"util": module(96.0)}))
        self.assertEqual(axis["score"], 0.0)

    def test_la_regression_nomme_le_module_et_son_plancher(self):
        self.freeze({"util": 99.0})
        axis = axis_coverage(self.root, fresh(96.0, {"util": module(96.0)}))
        self.assertEqual(axis["findings"],
                         ["util : 96.0 % sous le plancher de 99.0 %"])

    def test_une_baisse_dans_la_tolerance_n_est_pas_une_regression(self):
        self.freeze({"util": 99.0})
        proche = 99.0 - TOLERANCE / 2
        axis = axis_coverage(self.root, fresh(proche, {"util": module(proche)}))
        self.assertEqual(axis["findings"], [])

    def test_un_module_disparu_de_la_mesure_est_une_regression(self):
        self.freeze({"util": 99.0, "supprime": 90.0})
        axis = axis_coverage(self.root, fresh(99.0, {"util": module(99.0)}))
        self.assertEqual(axis["score"], 0.0)
        self.assertTrue(any("supprime" in finding for finding in axis["findings"]))

    def test_un_plancher_illisible_n_est_pas_oppose_a_la_mesure(self):
        self.write(".aidlc/coverage.json", "{ pas du json")
        self.assertEqual(coverage_floors(self.root), {})
        self.assertEqual(axis_coverage(self.root, fresh(99.0))["score"], 5.0)

    def test_le_detail_rend_le_taux_mesure(self):
        self.assertIn("99.0 %", axis_coverage(self.root, fresh(99.0))["detail"])


class TestAxeKnowledge(AidlcTestCase):
    """Conformance OKF v0.2 des bundles du projet, notee bundle par bundle."""

    CONCEPT = "---\ntype: Reference\ntitle: Un concept\n---\n\n# Un concept\n"
    INDEX = '---\nokf_version: "0.2"\n---\n# Sommaire\n\n* [Un concept](c.md)\n'

    def bundle(self, name: str, conforme: bool = True):
        self.write(f"{name}/index.md", self.INDEX)
        self.write(f"{name}/c.md", self.CONCEPT if conforme else "# Sans frontmatter\n")

    def test_sans_bundle_l_axe_n_est_pas_applicable(self):
        """Un projet consommateur qui ne porte aucun bundle n'est pas puni pour ca."""
        self.assertIsNone(axis_knowledge(self.root)["score"])

    def test_un_bundle_conforme_vaut_la_note_maximale(self):
        self.bundle("knowledge")
        self.assertEqual(axis_knowledge(self.root)["score"], MAX)

    def test_un_bundle_sur_deux_non_conforme_vaut_la_moitie(self):
        self.bundle("knowledge")
        self.bundle("docs", conforme=False)
        self.assertEqual(axis_knowledge(self.root)["score"], MAX / 2)

    def test_le_constat_prefixe_l_erreur_du_nom_du_bundle(self):
        self.bundle("docs", conforme=False)
        self.assertTrue(any(finding.startswith("docs/c.md")
                            for finding in axis_knowledge(self.root)["findings"]))

    def test_le_detail_compte_les_bundles_conformes(self):
        self.bundle("knowledge")
        self.assertIn("1/1 bundles conformes", axis_knowledge(self.root)["detail"])


class TestSelfscoreRun(AidlcTestCase):
    """La passe complete : une seule execution de la suite, cinq axes, un verdict."""

    def passe(self, pipe=None, **kwargs):
        with mock.patch.object(selfscore, "measure", return_value=fresh(**kwargs)) as fake:
            report = selfscore_run(self.root, pipe or self.pipeline)
        self.measure = fake
        return report

    def test_la_suite_n_est_mesuree_qu_une_fois_pour_deux_axes(self):
        """`tests` et `coverage` sont deux lectures de la meme mesure : mesurer deux
        fois doublerait le temps de la porte pre-commit."""
        self.passe()
        self.measure.assert_called_once_with()

    def test_un_depot_sain_franchit_la_porte(self):
        self.assertTrue(self.passe()["passed"])

    def test_les_cinq_axes_sont_rendus_dans_l_ordre_de_la_grille(self):
        self.assertEqual([axis["axis"] for axis in self.passe()["axes"]],
                         ["hygiene", "contracts", "tests", "coverage", "knowledge"])

    def test_un_axe_non_applicable_ne_pese_pas_dans_la_moyenne(self):
        """Sans bundle OKF, `knowledge` vaut n/a : la moyenne porte sur quatre axes."""
        report = self.passe()
        self.assertIsNone(report["axes"][4]["score"])
        self.assertEqual(report["overall"], 5.0)

    def test_un_axe_effondre_bloque_malgre_une_moyenne_suffisante(self):
        """4 axes a 5 et un a 0 donnent 3,75 — mais c'est bien le plancher par axe qui
        parle : un axe effondre ne se compense pas."""
        self.write("casse.py", "def f(:\n")
        report = self.passe()
        self.assertEqual(report["weak_axes"], ["hygiene"])
        self.assertFalse(report["passed"])

    def test_la_moyenne_sous_le_seuil_bloque_sans_axe_faible(self):
        """Couverture a 80 % : l'axe vaut 3, pile au plancher, donc aucun axe n'est
        faible — mais la moyenne des quatre axes applicables tombe a 4,5 et la
        gouvernance exige 4,6. Le seuil et le plancher sont deux regles distinctes."""
        report = self.passe({"maturity_threshold": 4.6, "min_axis_score": 3.0},
                            total=80.0)
        self.assertEqual(report["overall"], 4.5)
        self.assertEqual(report["weak_axes"], [])
        self.assertFalse(report["passed"])
        self.assertLess(report["overall"], report["threshold"])

    def test_les_seuils_rendus_sont_ceux_de_la_gouvernance(self):
        report = self.passe()
        self.assertEqual(report["threshold"],
                         float(self.pipeline["maturity_threshold"]))
        self.assertEqual(report["min_axis_score"], 3.0)

    def test_la_passe_n_ecrit_rien(self):
        """La note mesure, elle ne fige pas : un `git commit` ne doit pas laisser
        derriere lui un plancher de couverture modifie hors du commit."""
        avant = sorted(p.relative_to(self.root).as_posix()
                       for p in self.root.rglob("*") if p.is_file())
        self.passe()
        apres = sorted(p.relative_to(self.root).as_posix()
                       for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(avant, apres)
