from __future__ import annotations

import json

from .harness import AidlcTestCase
from ..experiment import EFFECT_MARGIN
from ..experiment import MIN_RUNS_AFTER
from ..experiment import TARGETS
from ..experiment import effects
from ..experiment import experiments_path
from ..experiment import load_experiments
from ..experiment import record
from ..improve import improve

"""Memoire de la boucle d'amelioration : une correction du harnais est datee, la mesure
d'avant est figee, et les runs suivants rendent le verdict."""


def _run(number: int, **axes) -> dict:
    """Un run note : les quatre axes a la meme valeur sauf ceux passes nommement."""
    scores = {"completeness": 4, "precision": 4, "traceability": 4, "autonomy": 4}
    scores.update(axes)
    return {"run": number, "scores": scores,
            "overall": round(sum(scores.values()) / 4, 1), "verdict": "accepted"}


class ExperimentCase(AidlcTestCase):
    """Socle des tests d'experience : une etape `plan` dont on choisit l'historique."""

    def seed_runs(self, *runs, stage: str = "plan"):
        self.write_json(".aidlc/maturity.json", {"stages": {stage: {"runs": list(runs)}}})

    def record_plan(self, target: str = "precision", cause: str = "SKILL trop vague",
                    path: str = "plugins/aidlc-plan/checks.json") -> dict:
        return record(self.root, "plan", target, path, cause)


# ------------------------------------------------------------------------- record

class TestRecord(ExperimentCase):
    """`record` refuse ce qu'il ne peut pas mesurer, et fige l'avant au moment exact
    ou la correction est appliquee."""

    def test_fige_la_moyenne_de_l_axe_vise_et_le_nombre_de_runs(self):
        self.seed_runs(_run(1, precision=2), _run(2, precision=3))
        entry = self.record_plan()
        self.assertEqual(entry["baseline"], 2.5)
        self.assertEqual(entry["baseline_runs"], 2)
        self.assertEqual(entry["stage"], "plan")
        self.assertEqual(entry["file"], "plugins/aidlc-plan/checks.json")

    def test_cible_overall_est_mesuree_sur_la_note_globale(self):
        self.seed_runs(_run(1, precision=2), _run(2, precision=4))
        self.assertEqual(self.record_plan(target="overall")["baseline"], 3.75)

    def test_sans_run_prealable_la_mesure_d_avant_est_nulle(self):
        entry = self.record_plan()
        self.assertIsNone(entry["baseline"])
        self.assertEqual(entry["baseline_runs"], 0)

    def test_axe_inconnu_est_refuse(self):
        with self.assertRaises(ValueError) as raised:
            self.record_plan(target="elegance")
        self.assertIn("elegance", str(raised.exception))

    def test_etape_hors_registre_est_refusee(self):
        with self.assertRaises(ValueError):
            record(self.root, "fantome", "precision", "f.json", "cause")

    def test_cause_vide_est_refusee(self):
        with self.assertRaises(ValueError):
            self.record_plan(cause="   ")

    def test_rien_n_est_ecrit_quand_l_enregistrement_est_refuse(self):
        with self.assertRaises(ValueError):
            self.record_plan(target="elegance")
        self.assertFalse(experiments_path(self.root).exists())

    def test_deux_tentatives_sur_la_meme_cible_sont_deux_lignes(self):
        """Reessayer apres un echec est legitime : le registre n'est pas dedoublonne,
        contrairement a la file des refus."""
        self.record_plan(cause="premiere tentative")
        self.seed_runs(_run(1), _run(2))
        self.record_plan(cause="seconde tentative")
        lignes = experiments_path(self.root).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lignes), 2)
        self.assertEqual(json.loads(lignes[1])["baseline_runs"], 2)


# ------------------------------------------------------------------ load_experiments

class TestLoadExperiments(ExperimentCase):
    """Le registre se relit sans jamais casser, et se filtre par etape."""

    def test_registre_absent_rend_une_liste_vide(self):
        self.assertEqual(load_experiments(self.root), [])

    def test_ligne_corrompue_est_ignoree_sans_perdre_les_autres(self):
        self.record_plan()
        with experiments_path(self.root).open("a", encoding="utf-8") as handle:
            handle.write("pas du json\n")
        self.assertEqual(len(load_experiments(self.root)), 1)

    def test_filtre_par_etape(self):
        self.record_plan()
        record(self.root, "design", "precision", "f.json", "autre cause")
        self.assertEqual([e["stage"] for e in load_experiments(self.root, "design")],
                         ["design"])


# ------------------------------------------------------------------------- effects

class TestEffects(ExperimentCase):
    """Le verdict est mesure sur les seuls runs posterieurs a la correction."""

    def test_sans_assez_de_runs_le_verdict_reste_en_attente(self):
        self.seed_runs(_run(1, precision=2))
        self.record_plan()
        self.seed_runs(_run(1, precision=2), _run(2, precision=5))
        result = effects(self.root)[0]
        self.assertEqual(result["verdict"], "pending")
        self.assertEqual(result["runs_after"], 1)

    def test_axe_qui_monte_au_dela_de_la_marge_est_une_amelioration(self):
        self.seed_runs(_run(1, precision=2), _run(2, precision=2))
        self.record_plan()
        self.seed_runs(_run(1, precision=2), _run(2, precision=2),
                       _run(3, precision=4), _run(4, precision=4))
        result = effects(self.root)[0]
        self.assertEqual(result["verdict"], "improved")
        self.assertEqual(result["measured"], 4.0)
        self.assertEqual(result["delta"], 2.0)

    def test_axe_qui_baisse_est_une_regression(self):
        self.seed_runs(_run(1, precision=4), _run(2, precision=4))
        self.record_plan()
        self.seed_runs(_run(1, precision=4), _run(2, precision=4),
                       _run(3, precision=2), _run(4, precision=2))
        self.assertEqual(effects(self.root)[0]["verdict"], "regressed")

    def test_mouvement_sous_la_marge_ne_conclut_rien(self):
        self.seed_runs(_run(1, precision=3), _run(2, precision=3))
        self.record_plan()
        moved = 3 + (EFFECT_MARGIN / 2)
        self.seed_runs(_run(1, precision=3), _run(2, precision=3),
                       _run(3, precision=moved), _run(4, precision=moved))
        self.assertEqual(effects(self.root)[0]["verdict"], "no_effect")

    def test_correction_appliquee_avant_tout_run_n_a_rien_a_comparer(self):
        self.record_plan()
        self.seed_runs(_run(1), _run(2))
        result = effects(self.root)[0]
        self.assertEqual(result["verdict"], "no_baseline")
        self.assertIsNone(result["delta"])
        self.assertEqual(result["measured"], 4.0)

    def test_les_runs_anterieurs_a_la_correction_ne_comptent_pas(self):
        """Un run faible d'avant ne doit pas peser sur l'apres : c'est precisement ce
        que `baseline_runs` separe."""
        self.seed_runs(_run(1, precision=0), _run(2, precision=0))
        self.record_plan()
        self.seed_runs(_run(1, precision=0), _run(2, precision=0),
                       _run(3, precision=5), _run(4, precision=5))
        self.assertEqual(effects(self.root)[0]["measured"], 5.0)

    def test_etape_sans_aucun_run_reste_en_attente(self):
        self.record_plan()
        result = effects(self.root)[0]
        self.assertEqual(result["verdict"], "pending")
        self.assertIsNone(result["measured"])

    def test_seuil_de_runs_est_celui_du_module(self):
        self.seed_runs(_run(1, precision=2), _run(2, precision=2))
        self.record_plan()
        posterieurs = [_run(n + 3, precision=4) for n in range(MIN_RUNS_AFTER)]
        self.seed_runs(_run(1, precision=2), _run(2, precision=2), *posterieurs)
        self.assertNotEqual(effects(self.root)[0]["verdict"], "pending")


# --------------------------------------------------------------- branchement improve

class TestExperimentsDansLeDiagnostic(ExperimentCase):
    """Le diagnostic porte les experiences : c'est la qu'un agent lit ce qui a deja
    ete tente avant de proposer autre chose."""

    def test_le_diagnostic_expose_les_experiences_mesurees(self):
        self.seed_runs(_run(1, precision=2), _run(2, precision=2))
        self.record_plan()
        self.seed_runs(_run(1, precision=2), _run(2, precision=2),
                       _run(3, precision=4), _run(4, precision=4))
        diag = improve(self.root, self.pipeline)
        self.assertEqual([e["verdict"] for e in diag["experiments"]], ["improved"])

    def test_le_filtre_d_etape_du_diagnostic_s_applique_aux_experiences(self):
        self.record_plan()
        record(self.root, "design", "precision", "f.json", "autre cause")
        diag = improve(self.root, self.pipeline, "design")
        self.assertEqual([e["stage"] for e in diag["experiments"]], ["design"])

    def test_toutes_les_cibles_declarees_sont_mesurables(self):
        for target in TARGETS:
            with self.subTest(target=target):
                self.assertIsNone(self.record_plan(target=target)["baseline"])
