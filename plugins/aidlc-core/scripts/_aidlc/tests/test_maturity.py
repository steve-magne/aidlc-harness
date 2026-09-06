from __future__ import annotations

import json
import os

from unittest import mock

from .harness import AidlcTestCase
from .harness import GOOD_SECTIONS
from .harness import document
from .harness import manifest
from .. import maturity as maturity_module
from ..maturity import compute_autonomy
from ..maturity import enqueue_improvement
from ..maturity import gate_stage
from ..maturity import history
from ..maturity import human_review
from ..maturity import load_maturity
from ..maturity import maturity_path
from ..maturity import recall
from ..maturity import record_score
from ..maturity import render_history
from ..maturity import render_recall
from ..maturity import render_status
from ..maturity import authoring
from ..maturity import review_request
from ..maturity import sign_review
from ..maturity import upstream_blockers
from ..maturity import stage_maturity
from ..maturity import stale_deliverable
from ..maturity import status_data
from ..util import aidlc_dir
from ..util import now_iso
from ..util import read_text
from ..util import write_json

"""Maturite : score recalcule, autonomie, porte (gate), revue humaine, tableau de bord."""

SCORES_HAUTS = {"completeness": 5, "precision": 5, "traceability": 5, "autonomy": 5}
SCORES_BAS = {"completeness": 2, "precision": 2, "traceability": 2, "autonomy": 2}
#: Sous le seuil de moyenne (4.0) mais tous les axes au plancher (3.0).
SCORES_MOYENS = {"completeness": 3, "precision": 3, "traceability": 3, "autonomy": 3}


def _review(root, stage_id, run, approved, reviewer="Steve", justification="Conforme."):
    write_json(aidlc_dir(root) / "reviews" / f"{stage_id}-{run}.json", {
        "stage": stage_id, "run": run, "approved": approved, "reviewer": reviewer,
        "justification": justification, "ts": now_iso(),
    })


class TestLoadMaturity(AidlcTestCase):
    """load_maturity ne casse jamais, quel que soit l'etat du fichier sur disque."""

    def test_absence_de_fichier_rend_une_structure_vide(self):
        self.assertEqual(load_maturity(self.root), {"stages": {}})

    def test_json_illisible_rend_une_structure_vide(self):
        self.write(".aidlc/maturity.json", "pas du json {{{")
        self.assertEqual(load_maturity(self.root), {"stages": {}})

    def test_fichier_valide_est_charge_tel_quel(self):
        self.write_json(".aidlc/maturity.json",
                        {"stages": {"plan": {"runs": [], "autonomous": True}}})
        self.assertTrue(load_maturity(self.root)["stages"]["plan"]["autonomous"])

    def test_stages_absent_du_fichier_est_ajoute(self):
        self.write_json(".aidlc/maturity.json", {})
        self.assertEqual(load_maturity(self.root), {"stages": {}})


class TestStageMaturity(AidlcTestCase):
    def test_cree_une_entree_par_defaut_pour_une_etape_inconnue(self):
        maturity = {"stages": {}}
        entry = stage_maturity(maturity, "plan")
        self.assertEqual(entry, {"runs": [], "autonomous": False})
        self.assertIs(maturity["stages"]["plan"], entry)


class TestHumanReview(AidlcTestCase):
    """La revue humaine est lue depuis .aidlc/reviews/, jamais devinee."""

    def test_absence_de_revue_rend_none(self):
        self.assertIsNone(human_review(self.root, "plan", 1))

    def test_revue_illisible_rend_none(self):
        self.write(".aidlc/reviews/plan-1.json", "{ pas du json")
        self.assertIsNone(human_review(self.root, "plan", 1))

    def test_revue_valide_est_chargee(self):
        _review(self.root, "plan", 1, approved=True)
        self.assertTrue(human_review(self.root, "plan", 1)["approved"])


class TestComputeAutonomy(AidlcTestCase):
    """Autonomie = les N derniers runs au-dessus du seuil ET humainement approuves."""

    def test_faux_avant_d_atteindre_la_fenetre_de_runs(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True)
        self.assertFalse(
            compute_autonomy(self.root, self.pipeline, "plan", load_maturity(self.root)))

    def test_faux_si_un_run_de_la_fenetre_est_rejete(self):
        self.plan_intent()
        for run in (1, 2):
            record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
            _review(self.root, "plan", run, approved=True)
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_BAS})
        _review(self.root, "plan", 3, approved=True)
        self.assertFalse(
            compute_autonomy(self.root, self.pipeline, "plan", load_maturity(self.root)))

    def test_faux_si_un_run_de_la_fenetre_n_a_pas_de_revue_approuvee(self):
        self.plan_intent()
        for run in (1, 2, 3):
            record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True)
        _review(self.root, "plan", 2, approved=True)
        # run 3 : aucune revue humaine sur disque, et aucune revue en memoire du run.
        self.assertFalse(
            compute_autonomy(self.root, self.pipeline, "plan", load_maturity(self.root)))

    def test_vrai_quand_les_n_derniers_runs_sont_acceptes_et_approuves(self):
        self.plan_intent()
        for run in (1, 2, 3):
            record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
            _review(self.root, "plan", run, approved=True)
        self.assertTrue(
            compute_autonomy(self.root, self.pipeline, "plan", load_maturity(self.root)))

    def test_un_run_produit_en_mode_autonome_n_attend_pas_de_signature(self):
        """Sinon l'autonomie s'annulait au premier run qui en beneficiait : la fenetre
        glissante y trouvait un run sans revue humaine — alors que c'est precisement le
        mode autonome qui n'en avait pas demande — et l'etape repassait sous
        surveillance apres exactement un run."""
        self.plan_intent()
        for run in (1, 2, 3):
            record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
            _review(self.root, "plan", run, approved=True)
        # La derniere signature arrive apres la note : c'est `gate` qui constate la serie.
        self.assertTrue(gate_stage(self.root, self.pipeline, "plan")["autonomous"])
        record = record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        self.assertFalse(record["supervised"])
        self.assertTrue(load_maturity(self.root)["stages"]["plan"]["autonomous"])

    def test_un_run_supervise_sans_revue_retire_l_autonomie(self):
        """Le pendant du precedent : tant que l'etape est sous surveillance, un run non
        signe casse la serie. Un run anterieur au champ `supervised` est lu ainsi."""
        self.plan_intent()
        for run in (1, 2, 3):
            record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
            _review(self.root, "plan", run, approved=True)
        maturity = load_maturity(self.root)
        maturity["stages"]["plan"]["runs"][-1].pop("supervised")
        maturity["stages"]["plan"]["runs"][-1]["human_review"] = None
        (aidlc_dir(self.root) / "reviews" / "plan-3.json").unlink()
        self.assertFalse(compute_autonomy(self.root, self.pipeline, "plan", maturity))

    def test_un_run_autonome_sous_le_seuil_casse_quand_meme_la_serie(self):
        """L'exemption ne porte que sur la signature humaine, jamais sur la note."""
        runs = [{"run": n, "verdict": "accepted", "overall": 5.0, "supervised": False}
                for n in (1, 2)]
        runs.append({"run": 3, "verdict": "rejected", "overall": 2.0, "supervised": False})
        maturity = {"stages": {"plan": {"runs": runs, "autonomous": True}}}
        self.assertFalse(compute_autonomy(self.root, self.pipeline, "plan", maturity))

    def test_la_revue_en_memoire_du_run_suffit_sans_relire_le_disque(self):
        self.plan_intent()
        maturity = {"stages": {"plan": {"runs": [], "autonomous": False}}}
        for run in (1, 2, 3):
            record = {"run": run, "verdict": "accepted", "overall": 5.0,
                      "human_review": {"approved": True}}
            maturity["stages"]["plan"]["runs"].append(record)
        self.assertTrue(
            compute_autonomy(self.root, self.pipeline, "plan", maturity))


class TestRecordScore(AidlcTestCase):
    """La moyenne est toujours recalculee ; la valeur fournie par le reviewer est ignoree."""

    def test_overall_fourni_est_ignore_et_recalcule(self):
        record = record_score(self.root, self.pipeline, "plan",
                              {"scores": SCORES_HAUTS, "overall": 1.0, "verdict": "accepted"})
        self.assertEqual(record["overall"], 5.0)

    def test_le_premier_run_est_numerote_un_et_les_suivants_s_incrementent(self):
        first = record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        second = record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        self.assertEqual((first["run"], second["run"]), (1, 2))

    def test_maturity_json_est_ecrit_sur_disque(self):
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        self.assertTrue(maturity_path(self.root).exists())

    def test_axe_manquant_leve_value_error(self):
        incomplete = dict(SCORES_HAUTS)
        incomplete.pop("precision")
        with self.assertRaises(ValueError) as ctx:
            record_score(self.root, self.pipeline, "plan", {"scores": incomplete})
        self.assertIn("precision", str(ctx.exception))

    def test_score_hors_bornes_leve_value_error(self):
        hors_bornes = dict(SCORES_HAUTS, completeness=6)
        with self.assertRaises(ValueError) as ctx:
            record_score(self.root, self.pipeline, "plan", {"scores": hors_bornes})
        self.assertIn("completeness", str(ctx.exception))

    def test_note_fractionnaire_leve_value_error(self):
        """La grille est ordinale : 0 absent, 1 brouillon ... 5 exemplaire. Un 2,5 ne
        designe aucun niveau, et juste sous le plancher il ouvre une negociation."""
        with self.assertRaises(ValueError) as ctx:
            record_score(self.root, self.pipeline, "plan",
                         {"scores": dict(SCORES_HAUTS, precision=2.5)})
        self.assertIn("precision", str(ctx.exception))

    def test_une_note_entiere_ecrite_en_flottant_reste_acceptee(self):
        """Le JSON d'un reviewer peut porter 4.0 : c'est le niveau 4, pas une demi-note."""
        record = record_score(self.root, self.pipeline, "plan",
                              {"scores": dict(SCORES_HAUTS, precision=4.0)})
        self.assertEqual(record["scores"]["precision"], 4.0)

    def test_verdict_explicite_du_reviewer_est_respecte_meme_sous_le_seuil(self):
        """Le reviewer garde la main sous le seuil de moyenne — tant qu'aucun axe n'est
        effondre. SCORES_MOYENS est sous le seuil global (4.0) mais chaque axe reste au
        plancher (3.0) : c'est exactement le cas ou le jugement du reviewer prime."""
        record = record_score(self.root, self.pipeline, "plan",
                              {"scores": SCORES_MOYENS, "verdict": "accepted"})
        self.assertLess(record["overall"], self.pipeline["maturity_threshold"])
        self.assertEqual(record["verdict"], "accepted")

    def test_verdict_invalide_est_recalcule_depuis_le_seuil(self):
        record = record_score(self.root, self.pipeline, "plan",
                              {"scores": SCORES_HAUTS, "verdict": "peut-etre"})
        self.assertEqual(record["verdict"], "accepted")

    def test_score_sous_le_seuil_sans_verdict_est_rejete(self):
        record = record_score(self.root, self.pipeline, "plan", {"scores": SCORES_BAS})
        self.assertEqual((record["overall"], record["verdict"]), (2.0, "rejected"))

    def test_le_run_fige_l_empreinte_de_ses_entrees_amont(self):
        self.plan_intent()
        record = record_score(self.root, self.pipeline, "design", {"scores": SCORES_HAUTS})
        self.assertIn("deliverables/plan/intent.md", record["inputs"])

    def test_findings_et_recommandations_sont_tronques_avant_stockage(self):
        record = record_score(self.root, self.pipeline, "plan",
                              {"scores": SCORES_HAUTS, "findings": ["x"] * 60})
        self.assertEqual(len(record["findings"]), 50)


class TestEnqueueImprovement(AidlcTestCase):
    """Seul ecrivain de la file d'amelioration ; dedoublonne par (kind, dedupe_keys)."""

    def test_une_premiere_entree_est_ajoutee(self):
        added = enqueue_improvement(self.root, {"kind": "human_review", "stage": "plan",
                                                "run": 1}, ("stage", "run"))
        self.assertTrue(added)

    def test_une_entree_identique_sur_les_cles_de_dedoublonnage_est_ignoree(self):
        enqueue_improvement(self.root, {"kind": "human_review", "stage": "plan", "run": 1,
                                        "justification": "premiere"}, ("stage", "run"))
        added = enqueue_improvement(self.root, {"kind": "human_review", "stage": "plan",
                                                "run": 1, "justification": "seconde"},
                                    ("stage", "run"))
        self.assertFalse(added)
        queue = self.read(".aidlc/improvement-queue.jsonl")
        self.assertEqual(len(queue.strip().splitlines()), 1)

    def test_un_kind_different_n_est_jamais_un_doublon(self):
        enqueue_improvement(self.root, {"kind": "human_review", "stage": "plan", "run": 1},
                            ("stage", "run"))
        added = enqueue_improvement(self.root, {"kind": "watchdog", "stage": "plan", "run": 1},
                                    ("stage", "run"))
        self.assertTrue(added)

    def test_une_ligne_de_journal_corrompue_est_ignoree_sans_lever(self):
        path = aidlc_dir(self.root) / "improvement-queue.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pas du json {{{\n", encoding="utf-8")
        added = enqueue_improvement(self.root, {"kind": "human_review", "stage": "plan",
                                                "run": 1}, ("stage", "run"))
        self.assertTrue(added)
        lignes = self.read(".aidlc/improvement-queue.jsonl").strip().splitlines()
        self.assertEqual(len(lignes), 2)


class TestGateStage(AidlcTestCase):
    """La porte de qualite : ce qui bloque, ce qui la franchit, ce qui la rouvre."""

    def test_un_agent_inconnu_du_registre_bloque(self):
        decision = gate_stage(self.root, self.pipeline, "fantome")
        self.assertFalse(decision["passed"])
        self.assertTrue(any("Agent inconnu du registre" in b for b in decision["blocking"]))

    def test_un_agent_consultatif_n_a_aucune_porte(self):
        self.write_agent("aidlc-conseil", manifest("conseil", "Conseil"))
        decision = gate_stage(self.root, self.pipeline, "conseil")
        self.assertFalse(decision["passed"])
        self.assertTrue(any("consultatif" in b for b in decision["blocking"]))

    def test_une_validation_deterministe_en_echec_bloque(self):
        self.plan_intent(sections={"## Contexte": "trop court"})
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("Validation déterministe en échec" in b
                            for b in decision["blocking"]))

    def test_aucun_score_enregistre_bloque_et_ne_calcule_pas_le_reste(self):
        self.plan_intent()
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertFalse(decision["passed"])
        self.assertIsNone(decision["run"])
        self.assertTrue(any("Aucun score de maturité" in b for b in decision["blocking"]))

    def test_bloque_sans_revue_humaine(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertFalse(decision["passed"])
        self.assertTrue(decision["human_review_required"])
        self.assertTrue(any("Revue humaine requise" in b for b in decision["blocking"]))
        self.assertEqual(decision["next_stage"], "design")

    def test_passe_avec_une_revue_humaine_approuvee(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True)
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(decision["passed"], decision["blocking"])

    def test_verdict_rejected_explicite_bloque_meme_avec_un_score_haut(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan",
                     {"scores": SCORES_HAUTS, "verdict": "rejected"})
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("Verdict du reviewer" in b for b in decision["blocking"]))
        self.assertNotIn("Maturite", " ".join(decision["blocking"]))

    def test_score_sous_le_seuil_bloque_meme_avec_verdict_accepted_force(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan",
                     {"scores": SCORES_BAS, "verdict": "accepted"})
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("sous le seuil" in b for b in decision["blocking"]))

    def test_un_refus_humain_bloque_et_alimente_la_file_d_amelioration(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=False, justification="Criteres non chiffres.")
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertFalse(decision["passed"])
        self.assertTrue(any("Revue humaine refusée" in b for b in decision["blocking"]))
        queue = self.read(".aidlc/improvement-queue.jsonl")
        self.assertIn("Criteres non chiffres.", queue)

    def test_un_refus_humain_relu_ne_double_pas_la_file(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=False, justification="Criteres non chiffres.")
        gate_stage(self.root, self.pipeline, "plan")
        gate_stage(self.root, self.pipeline, "plan")
        queue = self.read(".aidlc/improvement-queue.jsonl")
        self.assertEqual(len(queue.strip().splitlines()), 1)

    def test_une_entree_amont_modifiee_rouvre_la_porte_aval(self):
        intent = self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True)
        self.write("deliverables/design/spec.md",
                   document({"## Contexte": "Contexte issu de deliverables/plan/intent.md."},
                           front={"stage": "design", "version": "1", "status": "draft",
                                  "author": "Steve", "date": "2026-09-03"}))
        record_score(self.root, self.pipeline, "design", {"scores": SCORES_HAUTS})
        _review(self.root, "design", 1, approved=True)
        self.assertTrue(gate_stage(self.root, self.pipeline, "design")["passed"])

        # Le PO revise son cadrage, puis le fait renoter et resigner : sa propre porte
        # se referme, mais la note de design porte toujours sur la version disparue.
        intent.write_text(document(GOOD_SECTIONS, filler=4), encoding="utf-8")
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 2, approved=True)
        decision = gate_stage(self.root, self.pipeline, "design")
        self.assertFalse(decision["passed"])
        self.assertEqual(decision["stale_inputs"], ["deliverables/plan/intent.md"])
        self.assertTrue(any("Entrée amont modifiée" in b for b in decision["blocking"]))

        # Le tableau de bord doit remettre design a faire tant que la porte reste ouverte.
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                  if r["stage"] == "design")
        self.assertIn("Entrée amont modifiée", row["next_action"])

        # Une nouvelle revue notee sur l'entree a jour referme la porte.
        record_score(self.root, self.pipeline, "design", {"scores": SCORES_HAUTS})
        _review(self.root, "design", 2, approved=True)
        self.assertTrue(gate_stage(self.root, self.pipeline, "design")["passed"])

    def test_l_autonomie_se_recalcule_a_chaque_appel_de_gate(self):
        # NB : `human_review_required` est lu depuis l'ancien `entry["autonomous"]" avant
        # le recalcul de ce meme appel (comportement reel observe, cf. notes) — seul
        # `decision["autonomous"]` (recalcule en fin de fonction) reflete l'etat a jour.
        self.plan_intent()
        for run in (1, 2, 3):
            record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
            _review(self.root, "plan", run, approved=True)
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(decision["passed"], decision["blocking"])
        self.assertTrue(decision["autonomous"])


class TestReviewRequest(AidlcTestCase):
    def test_un_agent_inconnu_leve_value_error(self):
        with self.assertRaises(ValueError):
            review_request(self.root, self.pipeline, "fantome")

    def test_un_agent_consultatif_leve_value_error(self):
        self.write_agent("aidlc-conseil", manifest("conseil", "Conseil"))
        with self.assertRaises(ValueError):
            review_request(self.root, self.pipeline, "conseil")

    def test_ecrit_un_gabarit_pour_le_premier_run(self):
        with self.muted():
            request = review_request(self.root, self.pipeline, "plan")
        self.assertEqual(request["run"], 1)
        self.assertTrue((self.root / request["template"]).exists())
        template = self.read_json(request["template"])
        self.assertFalse(template["approved"])

    def test_le_run_cible_suit_le_dernier_score_enregistre(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        with self.muted():
            request = review_request(self.root, self.pipeline, "plan")
        self.assertEqual(request["run"], 1)
        self.assertEqual(request["deliverable"], "deliverables/plan/intent.md")


class TestStatusData(AidlcTestCase):
    """Le tableau de bord derive du registre, jamais d'une liste figee."""

    def test_ne_couvre_que_les_agents_qui_produisent_un_livrable(self):
        data = status_data(self.root, self.pipeline)
        self.assertEqual([row["stage"] for row in data["stages"]], ["plan", "design"])

    def test_chaque_etape_porte_l_equipe_proprietaire_de_l_agent(self):
        row = status_data(self.root, self.pipeline)["stages"][0]
        self.assertEqual(row["team"], "Produit")

    def test_prochaine_action_produire_le_livrable_quand_il_est_absent(self):
        row = status_data(self.root, self.pipeline)["stages"][0]
        self.assertEqual(row["next_action"], "Produire le livrable : aidlc-plan:plan")

    def test_prochaine_action_signale_un_agent_non_invocable(self):
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md",
                                                invocation={"codex": "prompts/plan.md"}),
                         base=self.root / "plugins")
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                  if r["stage"] == "plan")
        self.assertIn("Agent non invocable", row["next_action"])

    def test_prochaine_action_signale_une_validation_en_echec(self):
        self.plan_intent(sections={"## Contexte": "trop court"})
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                  if r["stage"] == "plan")
        self.assertIn("erreur(s) de validation", row["next_action"])

    def test_prochaine_action_demande_de_lancer_le_reviewer(self):
        self.plan_intent()
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                  if r["stage"] == "plan")
        self.assertEqual(row["next_action"], "Lancer le reviewer (agent aidlc-core:reviewer)")

    def test_prochaine_action_demande_de_reprendre_un_livrable_rejete(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_BAS})
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                  if r["stage"] == "plan")
        self.assertEqual(row["next_action"], "Reprendre le livrable puis relancer le reviewer")

    def test_prochaine_action_demande_une_revue_humaine(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                  if r["stage"] == "plan")
        self.assertEqual(row["next_action"], "Revue humaine : aidlc.py review-request plan")

    def test_prochaine_action_etape_franchie_quand_tout_est_vert(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True)
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                  if r["stage"] == "plan")
        self.assertEqual(row["next_action"], "Étape franchie")

    def test_producteur_absent_signale_une_entree_sans_producteur_installe(self):
        self.write_agent("aidlc-orphelin",
                         manifest("orphelin", "Produit", "deliverables/orphelin/out.md",
                                  ["deliverables/inexistant/amont.md"]))
        data = status_data(self.root, self.pipeline)
        self.assertTrue(any(hole["input"] == "deliverables/inexistant/amont.md"
                            for hole in data["missing_producers"]))

    def test_un_agent_consultatif_est_liste_a_part(self):
        self.write_agent("aidlc-conseil", manifest("conseil", "Conseil",
                                                    capabilities=["conseil:avis"]))
        data = status_data(self.root, self.pipeline)
        self.assertTrue(any(a["id"] == "conseil" for a in data["advisors"]))
        self.assertFalse(any(s["stage"] == "conseil" for s in data["stages"]))

    def test_une_etape_prevue_sans_plugin_installe_reste_visible(self):
        data = status_data(self.root, self.pipeline)
        self.assertTrue(any(stage["id"] == "build" for stage in data["planned"]))

    def test_l_etape_courante_est_la_premiere_qui_n_est_pas_franchie(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True)
        data = status_data(self.root, self.pipeline)
        self.assertEqual(data["current_stage"], "design")


class TestRenderStatus(AidlcTestCase):
    """Le rendu texte du tableau de bord (aidlc.py status)."""

    def test_le_rendu_nomme_les_equipes(self):
        data = status_data(self.root, self.pipeline)
        self.assertIn("ÉQUIPE", render_status(data))

    def test_la_colonne_d_attente_nomme_le_role_humain_de_l_etape_courante(self):
        data = status_data(self.root, self.pipeline)
        rendered = render_status(data)
        self.assertIn("EN ATTENTE DE", rendered)
        self.assertIn("Role de test", rendered)

    def test_un_role_humain_absent_affiche_un_tiret_sans_casser_la_colonne(self):
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md",
                                                human_role=None))
        data = status_data(self.root, self.pipeline)
        row = next(r for r in data["stages"] if r["stage"] == "plan")
        self.assertIsNone(row["waiting_for"])
        self.assertIn("EN ATTENTE DE", render_status(data))

    def test_un_role_humain_trop_long_est_tronque_pour_ne_pas_pousser_l_action(self):
        self.write_agent(
            "aidlc-plan",
            manifest("plan", "Produit", "deliverables/plan/intent.md",
                     human_role="Product Owner / Business Analyst du domaine Facturation"))
        rendered = render_status(status_data(self.root, self.pipeline))
        self.assertIn("Product Owner / Busines...", rendered)

    def test_un_blocage_amont_est_annonce_sous_le_tableau(self):
        rendered = render_status(status_data(self.root, self.pipeline))
        self.assertIn("Bloqué : design attend deliverables/plan/intent.md", rendered)

    def test_la_gouvernance_affichee_nomme_le_fichier_du_projet_quand_il_existe(self):
        self.write_json("aidlc.json", {"maturity_threshold": 3.5})
        rendered = render_status(status_data(self.root, self.pipeline))
        self.assertIn("Gouvernance : aidlc.json", rendered)

    def test_la_gouvernance_affichee_retombe_sur_le_harnais_sans_fichier_projet(self):
        rendered = render_status(status_data(self.root, self.pipeline))
        self.assertIn("Gouvernance : harnais (pipeline.json)", rendered)

    def test_un_agent_consultatif_est_annonce_avec_ses_capacites(self):
        self.write_agent("aidlc-conseil", manifest("conseil", "Conseil",
                                                    capabilities=["conseil:avis"]))
        data = status_data(self.root, self.pipeline)
        self.assertIn("Agent consultatif : conseil", render_status(data))

    def test_un_producteur_absent_est_annonce_dans_le_rendu(self):
        self.write_agent("aidlc-orphelin",
                         manifest("orphelin", "Produit", "deliverables/orphelin/out.md",
                                  ["deliverables/inexistant/amont.md"]))
        data = status_data(self.root, self.pipeline)
        self.assertIn("Producteur absent", render_status(data))

    def test_une_etape_prevue_est_annoncee_avec_la_commande_scaffold(self):
        data = status_data(self.root, self.pipeline)
        self.assertIn("aidlc.py scaffold build", render_status(data))

    def test_un_cycle_de_dependances_est_annonce_dans_le_rendu(self):
        self.write_agent("aidlc-a", manifest("a", "Equipe A", "deliverables/a/out.md",
                                             ["deliverables/b/out.md"]))
        self.write_agent("aidlc-b", manifest("b", "Equipe B", "deliverables/b/out.md",
                                             ["deliverables/a/out.md"]))
        data = status_data(self.root, self.pipeline)
        self.assertEqual(sorted(data["cycle"]), ["a", "b"])
        self.assertIn("Cycle de dépendances entre agents", render_status(data))

    def test_un_avertissement_de_doublon_est_annonce_dans_le_rendu(self):
        external = self.root / "externe"
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md"),
                         base=external)
        self.agent_path(self.root / "plugins", external)
        data = status_data(self.root, self.pipeline)
        self.assertTrue(data["warnings"])
        self.assertIn("Avertissement :", render_status(data))

    def test_un_manifeste_rejete_est_annonce_dans_le_rendu(self):
        self.write_json("plugins/aidlc-invalide/agent.json", {"manifest_version": 1})
        data = status_data(self.root, self.pipeline)
        self.assertTrue(data["problems"])
        self.assertIn("Manifeste rejeté :", render_status(data))


class TestPlancherParAxe(AidlcTestCase):
    """Une moyenne flatteuse ne rachete pas un axe effondre. Un livrable complet,
    precis et rapide mais sans aucune tracabilite reste un livrable qu'on ne peut pas
    auditer — et il servira d'entree a toute l'aval. La regle vivait dans le prompt du
    reviewer et nulle part dans le moteur : un reviewer complaisant, ou un modele qui
    derive, la contournait sans que rien ne le voie. C'est `record_score` qui la tient.
    """

    #: Moyenne 4.0 (au seuil), mais la tracabilite s'effondre a 1.
    SCORES_DESEQUILIBRES = {"completeness": 5, "precision": 5,
                            "traceability": 1, "autonomy": 5}

    #: Meme moyenne, meme effondrement — mais sur l'axe de procede. Le plancher ne le
    #: retient pas : `autonomy` mesure un cout deja paye, qu'aucune reprise du livrable
    #: ne peut rattraper.
    SCORES_COUTEUX = {"completeness": 5, "precision": 5,
                      "traceability": 5, "autonomy": 1}

    def _score(self, scores, verdict="accepted"):
        return record_score(self.root, self.pipeline, "plan",
                            {"stage": "plan", "scores": scores, "verdict": verdict})

    def test_la_moyenne_reste_au_dessus_du_seuil(self):
        """Sans cela le cas ne prouverait rien : c'est bien le plancher par axe, et non
        la moyenne, qui doit faire basculer le verdict."""
        record = self._score(self.SCORES_DESEQUILIBRES)
        self.assertEqual(record["overall"], 4.0)
        self.assertGreaterEqual(record["overall"], self.pipeline["maturity_threshold"])

    def test_un_axe_sous_le_plancher_force_le_rejet(self):
        record = self._score(self.SCORES_DESEQUILIBRES, verdict="accepted")
        self.assertEqual(record["verdict"], "rejected")

    def test_l_axe_fautif_est_nomme(self):
        self.assertEqual(self._score(self.SCORES_DESEQUILIBRES)["weak_axes"],
                         ["traceability"])

    def test_l_autonomie_effondree_ne_ferme_pas_la_porte(self):
        """Le plancher juge le livrable, pas son cout de production. Rejeter un livrable
        irreprochable parce qu'il a demande des reprises fermerait une porte sans action
        de sortie : le run ne peut pas defaire les tours deja passes, et le seul remede
        serait de moins se corriger. L'autonomie pese toujours un quart de la moyenne, et
        c'est la serie de runs (compute_autonomy) qui en tire les consequences."""
        record = self._score(self.SCORES_COUTEUX, verdict="accepted")
        self.assertEqual(record["weak_axes"], [])
        self.assertEqual(record["verdict"], "accepted")

    def test_l_autonomie_effondree_pese_quand_meme_sur_la_moyenne(self):
        """Elle n'est pas neutralisee : sans trois axes parfaits pour la compenser, la
        moyenne passe sous le seuil et le verdict tombe de lui-meme."""
        record = self._score(dict(self.SCORES_COUTEUX, completeness=4), verdict="accepted")
        self.assertLess(record["overall"], self.pipeline["maturity_threshold"])

    def test_la_porte_bloque_en_nommant_le_plancher(self):
        """`gate` ne doit pas se contenter de dire « rejete » : l'orchestrateur a besoin
        de savoir que c'est un plancher, sinon il relance a l'aveugle."""
        self._score(self.SCORES_DESEQUILIBRES)
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertFalse(decision["passed"])
        self.assertTrue(any("plancher" in b for b in decision["blocking"]),
                        decision["blocking"])

    def test_la_porte_expose_l_axe_effondre(self):
        """Pour que l'orchestrateur sache quoi reprendre, pas seulement qu'il a echoue."""
        self._score(self.SCORES_DESEQUILIBRES)
        self.assertEqual(gate_stage(self.root, self.pipeline, "plan").get("weak_axes"),
                         ["traceability"])

    def test_un_axe_exactement_au_plancher_passe(self):
        """Le plancher est inclusif : 3.0 n'est pas « sous 3.0 »."""
        record = self._score(SCORES_MOYENS)
        self.assertEqual(record["weak_axes"], [])
        self.assertEqual(record["verdict"], "accepted")

    def test_aucun_axe_faible_n_expose_la_clef_dans_la_porte(self):
        """`weak_axes` n'apparait dans la decision que s'il y a matiere : on ne pollue
        pas la sortie machine avec une liste vide."""
        self._score(SCORES_HAUTS)
        self.assertNotIn("weak_axes", gate_stage(self.root, self.pipeline, "plan"))

    def test_le_plancher_est_lu_dans_la_gouvernance(self):
        """Le seuil est une decision de gouvernance, pas une constante enfouie."""
        pipe = dict(self.pipeline, min_axis_score=1.0)
        record = record_score(self.root, pipe, "plan",
                              {"stage": "plan", "scores": self.SCORES_DESEQUILIBRES,
                               "verdict": "accepted"})
        self.assertEqual(record["weak_axes"], [])
        self.assertEqual(record["verdict"], "accepted")


class TestPeremptionDuLivrableNote(AidlcTestCase):
    """Une note porte sur un contenu, pas sur un nom de fichier.

    `stale_inputs` fermait deja la fenetre amont : une entree revisee apres la revue de
    l'aval rouvre la porte. La meme fenetre restait ouverte sur le livrable lui-meme —
    il pouvait etre reecrit apres avoir ete note et signe, et franchir la porte sur la
    note d'une version disparue. `validate` n'y voit rien : il ne juge que la forme.
    """

    def _score_and_sign(self, run):
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", run, approved=True)

    def test_le_run_fige_l_empreinte_du_livrable_note(self):
        self.plan_intent()
        record = record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        self.assertTrue(record["deliverable"])

    def test_un_livrable_reecrit_apres_la_note_rouvre_la_porte(self):
        intent = self.plan_intent()
        self._score_and_sign(1)
        self.assertTrue(gate_stage(self.root, self.pipeline, "plan")["passed"])

        intent.write_text(document(GOOD_SECTIONS, filler=4), encoding="utf-8")
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertFalse(decision["passed"])
        self.assertTrue(decision["stale_deliverable"])

    def test_la_porte_nomme_la_cause_plutot_qu_un_refus_nu(self):
        intent = self.plan_intent()
        self._score_and_sign(1)
        intent.write_text(document(GOOD_SECTIONS, filler=4), encoding="utf-8")
        self.assertTrue(any("Livrable modifié" in b for b in
                            gate_stage(self.root, self.pipeline, "plan")["blocking"]))

    def test_le_tableau_de_bord_remet_l_etape_a_faire(self):
        intent = self.plan_intent()
        self._score_and_sign(1)
        intent.write_text(document(GOOD_SECTIONS, filler=4), encoding="utf-8")
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                   if r["stage"] == "plan")
        self.assertTrue(row["stale_deliverable"])
        self.assertIn("Livrable modifié", row["next_action"])

    def test_une_nouvelle_revue_sur_la_version_courante_referme_la_porte(self):
        intent = self.plan_intent()
        self._score_and_sign(1)
        intent.write_text(document(GOOD_SECTIONS, filler=4), encoding="utf-8")
        self._score_and_sign(2)
        self.assertTrue(gate_stage(self.root, self.pipeline, "plan")["passed"])

    def test_un_run_note_avant_l_empreinte_ne_perime_rien(self):
        """Compatibilite ascendante, comme pour l'empreinte des entrees amont."""
        self.plan_intent()
        self._score_and_sign(1)
        maturity = load_maturity(self.root)
        maturity["stages"]["plan"]["runs"][-1].pop("deliverable")
        write_json(maturity_path(self.root), maturity)
        self.assertTrue(gate_stage(self.root, self.pipeline, "plan")["passed"])

    def test_un_agent_sans_livrable_ne_perime_jamais(self):
        """Un manifeste consultatif n'a pas de `produces` : il n'y a rien a comparer."""
        self.assertFalse(stale_deliverable(self.root, {}, {"deliverable": "abc"}))


class TestRecall(AidlcTestCase):
    """Reprise d'une etape : ce que le projet a deja reproche au livrable precedent."""

    def setUp(self):
        super().setUp()
        self.plan_intent()

    def test_etape_inconnue_du_registre_leve(self):
        with self.assertRaises(ValueError):
            recall(self.root, "inexistante")

    def test_sans_aucun_run_la_liste_est_vide(self):
        self.assertEqual(recall(self.root, "plan")["runs"], [])

    def test_les_reproches_du_reviewer_sont_rendus(self):
        record_score(self.root, self.pipeline, "plan",
                     {"scores": SCORES_BAS, "findings": ["Criteres non chiffres."]})
        self.assertEqual(recall(self.root, "plan")["runs"][0]["findings"],
                         ["Criteres non chiffres."])

    def test_les_recommandations_du_reviewer_sont_rendues(self):
        record_score(self.root, self.pipeline, "plan",
                     {"scores": SCORES_BAS, "recommendations": ["Chiffrer la cible."]})
        self.assertEqual(recall(self.root, "plan")["runs"][0]["recommendations"],
                         ["Chiffrer la cible."])

    def test_les_axes_sous_plancher_sont_rendus(self):
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_BAS})
        self.assertIn("precision", recall(self.root, "plan")["runs"][0]["weak_axes"])

    def test_le_refus_humain_est_rendu_sans_attendre_la_porte(self):
        # La justification n'est recopiee dans le run que par `gate` : la relire sur
        # disque est ce qui rend visible un refus signe apres la derniere porte.
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        write_json(aidlc_dir(self.root) / "reviews" / "plan-1.json",
                   {"approved": False, "reviewer": "Steve",
                    "justification": "Le besoin reel n'est pas celui-la."})
        run = recall(self.root, "plan")["runs"][0]
        self.assertFalse(run["human_approved"])
        self.assertEqual(run["human_justification"], "Le besoin reel n'est pas celui-la.")

    def test_sans_signature_humaine_l_approbation_est_indeterminee(self):
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        self.assertIsNone(recall(self.root, "plan")["runs"][0]["human_approved"])

    def test_la_limite_ne_garde_que_les_derniers_runs(self):
        for _ in range(4):
            record_score(self.root, self.pipeline, "plan", {"scores": SCORES_BAS})
        data = recall(self.root, "plan", limit=2)
        self.assertEqual([r["run"] for r in data["runs"]], [3, 4])
        self.assertEqual(data["total_runs"], 4)

    def test_une_limite_nulle_garde_quand_meme_le_dernier_run(self):
        # Rappeler zero run n'a aucun sens pour une reprise : le plancher est 1.
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_BAS})
        self.assertEqual(len(recall(self.root, "plan", limit=0)["runs"]), 1)

    def test_le_rendu_humain_annonce_l_absence_de_tentative(self):
        self.assertIn("rien à reprendre", render_recall(recall(self.root, "plan")))

    def test_le_rendu_humain_porte_le_reproche_et_le_refus(self):
        record_score(self.root, self.pipeline, "plan",
                     {"scores": SCORES_BAS, "findings": ["Criteres non chiffres."]})
        write_json(aidlc_dir(self.root) / "reviews" / "plan-1.json",
                   {"approved": False, "reviewer": "Steve", "justification": "Hors sujet."})
        rendu = render_recall(recall(self.root, "plan"))
        self.assertIn("Criteres non chiffres.", rendu)
        self.assertIn("Hors sujet.", rendu)

    def test_le_rendu_humain_porte_les_recommandations(self):
        record_score(self.root, self.pipeline, "plan",
                     {"scores": SCORES_BAS, "recommendations": ["Chiffrer la cible."]})
        self.assertIn("à faire  : Chiffrer la cible.",
                      render_recall(recall(self.root, "plan")))

    def test_un_refus_sans_justification_reste_lisible(self):
        # Le fichier de revue est rempli a la main : l'absence de justification ne doit
        # pas rendre le rappel muet sur le refus lui-meme.
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        write_json(aidlc_dir(self.root) / "reviews" / "plan-1.json",
                   {"approved": False, "reviewer": "Steve"})
        self.assertIn("sans justification", render_recall(recall(self.root, "plan")))

    def test_le_rendu_humain_place_le_run_le_plus_recent_en_premier(self):
        record_score(self.root, self.pipeline, "plan",
                     {"scores": SCORES_BAS, "findings": ["Ancien reproche."]})
        record_score(self.root, self.pipeline, "plan",
                     {"scores": SCORES_BAS, "findings": ["Reproche recent."]})
        rendu = render_recall(recall(self.root, "plan"))
        self.assertLess(rendu.index("Reproche recent."), rendu.index("Ancien reproche."))


DESIGN_SPEC = {"## Contexte": "Contexte issu de deliverables/plan/intent.md."}
DESIGN_FRONT = {"stage": "design", "version": "1", "status": "draft",
                "author": "Steve", "date": "2026-09-03"}


def _spec(case):
    return case.write("deliverables/design/spec.md",
                      document(DESIGN_SPEC, front=DESIGN_FRONT))


def _franchir(case, stage_id, run=1):
    """Amene une etape jusqu'a porte ouverte : note haute puis signature approuvee."""
    record_score(case.root, case.pipeline, stage_id, {"scores": SCORES_HAUTS})
    _review(case.root, stage_id, run, approved=True)


class TestPorteAmont(AidlcTestCase):
    """Le chainage de bout en bout, tenu par la porte et non par un prompt.

    C'etait la promesse centrale du harnais et elle n'etait ecrite nulle part dans le
    moteur : `gate design` rendait `passed: true` alors que `deliverables/plan/intent.md`
    n'avait jamais ete ecrit — le livrable aval n'avait qu'a mentionner le chemin de son
    entree pour que `must_reference_inputs` soit satisfait. Seule la skill `run` verifiait
    l'amont, en prose, et n'importe quel appel direct ou en CI la contournait.
    """

    def test_une_entree_amont_absente_ferme_la_porte_aval(self):
        _spec(self)
        _franchir(self, "design")
        decision = gate_stage(self.root, self.pipeline, "design")
        self.assertFalse(decision["passed"])
        self.assertTrue(any("Entrée amont absente" in b for b in decision["blocking"]),
                        decision["blocking"])

    def test_le_blocage_amont_nomme_l_agent_a_lancer_d_abord(self):
        _spec(self)
        _franchir(self, "design")
        decision = gate_stage(self.root, self.pipeline, "design")
        self.assertTrue(any("l'agent « plan »" in b for b in decision["blocking"]))

    def test_une_entree_que_personne_ne_produit_le_dit(self):
        self.write_agent("aidlc-orphelin",
                         manifest("orphelin", "Produit", "deliverables/orphelin/out.md",
                                  ["deliverables/inexistant/amont.md"]),
                         {"required_sections": ["## Contexte"]})
        decision = gate_stage(self.root, self.pipeline, "orphelin")
        self.assertTrue(any("son plugin manque" in b for b in decision["blocking"]),
                        decision["blocking"])

    def test_une_porte_amont_fermee_ferme_la_porte_aval(self):
        self.plan_intent()          # l'amont existe...
        _spec(self)
        _franchir(self, "design")   # ...mais il n'a jamais ete note ni signe
        decision = gate_stage(self.root, self.pipeline, "design")
        self.assertFalse(decision["passed"])
        self.assertTrue(any("Porte amont fermée" in b for b in decision["blocking"]),
                        decision["blocking"])

    def test_le_blocage_amont_relaie_le_motif_de_l_amont(self):
        self.plan_intent()
        _spec(self)
        _franchir(self, "design")
        decision = gate_stage(self.root, self.pipeline, "design")
        self.assertTrue(any("Aucun score de maturité" in b for b in decision["blocking"]),
                        decision["blocking"])

    def test_une_chaine_complete_franchit_la_porte_aval(self):
        self.plan_intent()
        _franchir(self, "plan")
        _spec(self)
        _franchir(self, "design")
        decision = gate_stage(self.root, self.pipeline, "design")
        self.assertTrue(decision["passed"], decision["blocking"])
        self.assertNotIn("upstream", decision)

    def test_le_bloquant_amont_precede_les_autres_motifs(self):
        _spec(self)
        decision = gate_stage(self.root, self.pipeline, "design")
        self.assertIn("Entrée amont absente", decision["blocking"][0])

    def test_les_bloquants_amont_sont_rendus_a_part(self):
        _spec(self)
        decision = gate_stage(self.root, self.pipeline, "design")
        self.assertEqual(len(decision["upstream"]), 1)

    def test_une_etape_sans_entree_amont_n_est_jamais_bloquee_par_l_amont(self):
        self.plan_intent()
        _franchir(self, "plan")
        self.assertTrue(gate_stage(self.root, self.pipeline, "plan")["passed"])

    def test_un_cycle_de_dependances_ne_fait_pas_recurser_indefiniment(self):
        """Le registre signale le cycle par ailleurs ; la porte, elle, doit rendre la
        main. `seen` coupe la remontee au deuxieme passage sur le meme agent."""
        contract = {"required_sections": ["## Contexte"]}
        self.write_agent("aidlc-a", manifest("a", "A", "deliverables/a/out.md",
                                             ["deliverables/b/out.md"]), contract)
        self.write_agent("aidlc-b", manifest("b", "B", "deliverables/b/out.md",
                                             ["deliverables/a/out.md"]), contract)
        self.write("deliverables/a/out.md", "## Contexte\nDu contenu.\n")
        self.write("deliverables/b/out.md", "## Contexte\nDu contenu.\n")
        decision = gate_stage(self.root, self.pipeline, "a")
        self.assertFalse(decision["passed"])


class TestUpstreamBlockers(AidlcTestCase):
    """La fonction seule, hors de la porte."""

    def test_sans_entree_amont_il_n_y_a_aucun_bloquant(self):
        stage = {"id": "plan", "consumes": []}
        self.assertEqual(upstream_blockers(self.root, self.pipeline, stage, set()), [])

    def test_un_amont_deja_visite_n_est_pas_re_evalue(self):
        stage = {"id": "design", "consumes": ["deliverables/plan/intent.md"]}
        self.plan_intent()
        self.assertEqual(
            upstream_blockers(self.root, self.pipeline, stage, {"design", "plan"}), [])


class TestStatusChainage(AidlcTestCase):
    """Le tableau de bord chaine sans rappeler la porte : l'ordre topologique du
    registre suffit a savoir qu'un amont n'est pas franchi."""

    def test_une_etape_dont_l_amont_manque_attend_au_lieu_de_produire(self):
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                   if r["stage"] == "design")
        self.assertEqual(row["next_action"], "En attente de l'amont : plan")

    def test_le_blocage_amont_est_rendu_en_detail(self):
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                   if r["stage"] == "design")
        self.assertEqual(row["blocked_by"], [{
            "input": "deliverables/plan/intent.md", "producer": "plan",
            "reason": "livrable pas encore produit"}])

    def test_un_amont_produit_mais_non_franchi_bloque_toujours_l_aval(self):
        self.plan_intent()
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                   if r["stage"] == "design")
        self.assertEqual(row["blocked_by"][0]["reason"], "porte amont non franchie")

    def test_un_amont_franchi_libere_l_aval(self):
        self.plan_intent()
        _franchir(self, "plan")
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                   if r["stage"] == "design")
        self.assertEqual(row["blocked_by"], [])
        self.assertEqual(row["next_action"], "Produire le livrable : aidlc-design:design")

    def test_une_entree_sans_producteur_installe_est_nommee_comme_telle(self):
        self.write_agent("aidlc-orphelin",
                         manifest("orphelin", "Produit", "deliverables/orphelin/out.md",
                                  ["deliverables/inexistant/amont.md"]))
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                   if r["stage"] == "orphelin")
        self.assertEqual(row["blocked_by"][0]["reason"],
                         "aucun agent installé ne le produit")
        self.assertIn("amont.md", row["next_action"])

    def test_l_etape_courante_reste_l_amont_quand_l_aval_est_bloque(self):
        _spec(self)
        _franchir(self, "design")
        self.assertEqual(status_data(self.root, self.pipeline)["current_stage"], "plan")


class TestColonneEnAttente(AidlcTestCase):
    """Qui doit agir maintenant — la question que le tableau de bord ne repondait pas."""

    def test_l_etape_courante_attend_son_role_humain(self):
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                   if r["stage"] == "plan")
        self.assertEqual(row["waiting_for"], "Role de test")

    def test_une_etape_bloquee_par_l_amont_n_attend_personne(self):
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                   if r["stage"] == "design")
        self.assertIsNone(row["waiting_for"])

    def test_une_etape_franchie_n_attend_personne(self):
        self.plan_intent()
        _franchir(self, "plan")
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                   if r["stage"] == "plan")
        self.assertIsNone(row["waiting_for"])


class TestAuthoring(AidlcTestCase):
    """Une etape prevue se scaffolde chez l'auteur et s'attend chez le consommateur :
    proposer `scaffold` a une equipe projet, c'est lui proposer d'ecrire dans une copie
    que le garde-fou protege."""

    def test_le_depot_auteur_est_reconnu_quand_le_harnais_y_vit(self):
        self.assertTrue(authoring(self.root))

    def test_un_projet_consommateur_n_est_pas_un_depot_auteur(self):
        harness = self.root / "ailleurs" / "aidlc-core"
        self.write_json("ailleurs/aidlc-core/pipeline.json", {"version": 2})
        os.environ["AIDLC_HARNESS_ROOT"] = str(harness)
        self.assertFalse(authoring(self.root / "projet"))

    def test_le_consommateur_se_voit_proposer_d_attendre_la_publication(self):
        data = status_data(self.root, self.pipeline)
        data["authoring"] = False
        self.assertIn("à publier par l'équipe Ingenierie", render_status(data))


class TestSignReview(AidlcTestCase):
    """Signer sans manipuler de JSON : la commande tient les exigences que le fichier
    ne sait pas tenir."""

    def _pret(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})

    def test_un_agent_inconnu_leve_value_error(self):
        with self.assertRaises(ValueError):
            sign_review(self.root, self.pipeline, "fantome", True, "Steve", "ok")

    def test_un_agent_consultatif_n_a_rien_a_signer(self):
        self.write_agent("aidlc-conseil", manifest("conseil", "Conseil"))
        with self.assertRaises(ValueError):
            sign_review(self.root, self.pipeline, "conseil", True, "Steve", "ok")

    def test_sans_score_enregistre_il_n_y_a_rien_a_signer(self):
        self.plan_intent()
        with self.assertRaises(ValueError) as raised:
            sign_review(self.root, self.pipeline, "plan", True, "Steve", "ok")
        self.assertIn("Aucun score", str(raised.exception))

    def test_un_relecteur_anonyme_est_refuse(self):
        self._pret()
        with self.assertRaises(ValueError) as raised:
            sign_review(self.root, self.pipeline, "plan", True, "  ", "ok")
        self.assertIn("relecteur", str(raised.exception))

    def test_une_approbation_sans_justification_est_refusee(self):
        self._pret()
        with self.assertRaises(ValueError) as raised:
            sign_review(self.root, self.pipeline, "plan", True, "Steve", "")
        self.assertIn("justification", str(raised.exception))

    def test_un_refus_sans_justification_est_refuse(self):
        self._pret()
        with self.assertRaises(ValueError):
            sign_review(self.root, self.pipeline, "plan", False, "Steve", "   ")

    def test_la_signature_ecrit_la_revue_du_dernier_run(self):
        self._pret()
        signed = sign_review(self.root, self.pipeline, "plan", True, "Steve",
                             "Criteres chiffres et testables.")
        self.assertEqual(signed["run"], 1)
        review = self.read_json(".aidlc/reviews/plan-1.json")
        self.assertTrue(review["approved"])
        self.assertEqual(review["reviewer"], "Steve")
        self.assertTrue(review["ts"].endswith("+00:00"))

    def test_la_signature_ouvre_la_porte(self):
        self._pret()
        sign_review(self.root, self.pipeline, "plan", True, "Steve", "Conforme.")
        self.assertTrue(gate_stage(self.root, self.pipeline, "plan")["passed"])

    def test_un_refus_signe_ferme_la_porte_et_alimente_la_boucle(self):
        self._pret()
        sign_review(self.root, self.pipeline, "plan", False, "Steve",
                    "Criteres d'acceptation non chiffres.")
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertFalse(decision["passed"])
        self.assertIn("Criteres d'acceptation non chiffres.",
                      self.read(".aidlc/improvement-queue.jsonl"))

    def test_une_signature_ne_se_reecrit_pas(self):
        self._pret()
        sign_review(self.root, self.pipeline, "plan", True, "Steve", "Conforme.")
        with self.assertRaises(ValueError) as raised:
            sign_review(self.root, self.pipeline, "plan", False, "Autre", "Non.")
        self.assertIn("déjà signé par Steve", str(raised.exception))

    def test_force_permet_de_revenir_sur_une_signature(self):
        self._pret()
        sign_review(self.root, self.pipeline, "plan", True, "Steve", "Conforme.")
        sign_review(self.root, self.pipeline, "plan", False, "Steve",
                    "Je me suis trompe.", force=True)
        self.assertFalse(self.read_json(".aidlc/reviews/plan-1.json")["approved"])

    def test_les_espaces_autour_du_nom_et_du_motif_sont_retires(self):
        self._pret()
        signed = sign_review(self.root, self.pipeline, "plan", True, "  Steve  ",
                             "  Conforme.  ")
        self.assertEqual(signed["reviewer"], "Steve")
        self.assertEqual(self.read_json(".aidlc/reviews/plan-1.json")["justification"],
                         "Conforme.")


class TestContratIncoherentFermeLaPorte(AidlcTestCase):
    """Une etape gouvernee sans contrat ne franchit rien.

    Sans cette regle, `validate` rendait « ok » avec zero regle appliquee sur un
    livrable que personne n'avait lu : le vert le plus muet du harnais, et il portait
    justement sur l'agent qu'une equipe vient de brancher."""

    def _agent_sans_contrat(self):
        # Le cas reel : l'agent maison d'une equipe, publie sans champ `checks`.
        agent = manifest("solo", "Ingenierie", "deliverables/solo/plan.md")
        agent.pop("checks")
        self.write_agent("aidlc-solo", agent, checks=None)
        self.write("deliverables/solo/plan.md", "trois mots seulement")

    def test_la_porte_bloque_sur_le_contrat_absent(self):
        self._agent_sans_contrat()
        with self.muted():
            decision = gate_stage(self.root, self.pipeline, "solo")
        self.assertFalse(decision["passed"])

    def test_le_bloquant_nomme_l_equipe_qui_doit_corriger(self):
        self._agent_sans_contrat()
        with self.muted():
            decision = gate_stage(self.root, self.pipeline, "solo")
        self.assertIn("Ingenierie", " ".join(decision["blocking"]))

    def test_le_contrat_est_rendu_a_part_pour_la_skill(self):
        self._agent_sans_contrat()
        with self.muted():
            decision = gate_stage(self.root, self.pipeline, "solo")
        self.assertTrue(decision["contract_problems"])

    def test_un_score_flatteur_ne_rachete_pas_le_contrat_absent(self):
        # C'est le scenario reel : le reviewer note ce qu'il veut sur un livrable que
        # rien n'a valide, et la porte s'ouvrait.
        self._agent_sans_contrat()
        record_score(self.root, self.pipeline, "solo", {"scores": SCORES_HAUTS})
        _review(self.root, "solo", 1, approved=True)
        with self.muted():
            decision = gate_stage(self.root, self.pipeline, "solo")
        self.assertFalse(decision["passed"])

    def test_un_agent_dote_de_son_contrat_n_est_pas_gene(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True)
        with self.muted():
            decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertNotIn("contract_problems", decision)


class TestApprobationMotiveeAlimenteLaBoucle(AidlcTestCase):
    """`sign` exige un motif dans les deux sens ; celui de l'approbation etait jete."""

    def _porte_apres_approbation(self, justification):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True, justification=justification)
        with self.muted():
            gate_stage(self.root, self.pipeline, "plan")
        path = aidlc_dir(self.root) / "improvement-queue.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in read_text(path).splitlines() if line]

    def test_l_approbation_motivee_entre_dans_la_file(self):
        items = self._porte_apres_approbation("D'accord, mais les KPI restent mous.")
        self.assertEqual(len(items), 1)

    def test_elle_est_marquee_comme_reserve_et_non_comme_refus(self):
        items = self._porte_apres_approbation("D'accord, mais les KPI restent mous.")
        self.assertEqual(items[0]["kind"], "reserve")

    def test_le_motif_est_conserve_mot_pour_mot(self):
        items = self._porte_apres_approbation("D'accord, mais les KPI restent mous.")
        self.assertEqual(items[0]["justification"], "D'accord, mais les KPI restent mous.")

    def test_une_reserve_ne_bloque_pas_la_porte(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True, justification="Reserve mineure.")
        with self.muted():
            decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(decision["passed"])

    def test_une_approbation_sans_motif_n_encombre_pas_la_file(self):
        self.assertEqual(self._porte_apres_approbation("   "), [])

    def test_un_refus_reste_un_refus_sans_marqueur_de_reserve(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=False, justification="Perimetre flou.")
        with self.muted():
            gate_stage(self.root, self.pipeline, "plan")
        items = [json.loads(line) for line
                 in read_text(aidlc_dir(self.root) / "improvement-queue.jsonl").splitlines()
                 if line]
        self.assertNotIn("kind", items[0])


class TestConsignesDeRevue(AidlcTestCase):
    """La revue humaine se signe par une commande, pas par une copie de gabarit."""

    def test_les_consignes_donnent_la_commande_sign(self):
        self.plan_intent()
        with self.muted() as err:
            review_request(self.root, self.pipeline, "plan")
        self.assertIn("aidlc.py sign plan --approve", err.getvalue())

    def test_les_consignes_gardent_la_voie_manuelle_pour_la_ci(self):
        self.plan_intent()
        with self.muted() as err:
            review_request(self.root, self.pipeline, "plan")
        self.assertIn(".template.json", err.getvalue())

    def test_les_consignes_disent_que_l_approbation_aussi_est_conservee(self):
        self.plan_intent()
        with self.muted() as err:
            review_request(self.root, self.pipeline, "plan")
        self.assertIn("approbation motivée", err.getvalue())


class TestJournalDeLInitiative(AidlcTestCase):
    """Qui a produit, qui a note, qui a signe — la question d'une chaine multi-equipes."""

    def test_sans_run_le_journal_le_dit_au_lieu_de_rendre_un_vide(self):
        self.assertIn("Aucun run noté", render_history(history(self.root)))

    def test_chaque_run_note_devient_un_evenement(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        self.assertEqual(len(history(self.root)["events"]), 1)

    def test_la_signature_humaine_est_rendue_avec_son_auteur(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        _review(self.root, "plan", 1, approved=True, reviewer="Marie")
        with self.muted():
            gate_stage(self.root, self.pipeline, "plan")
        self.assertIn("Marie", render_history(history(self.root)))

    def test_un_run_non_signe_est_annonce_comme_tel(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        self.assertIn("non signé", render_history(history(self.root)))

    def test_les_evenements_sont_ordonnes_dans_le_temps(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_BAS})
        runs = [event["run"] for event in history(self.root)["events"]]
        self.assertEqual(runs, sorted(runs))

    def test_le_journal_nomme_l_initiative_quand_elle_existe(self):
        self.write_json("aidlc.json", {"initiative": "reco"})
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        self.assertIn("reco", render_history(history(self.root)))


class TestTableauDeBordEtAgentsNonDeclares(AidlcTestCase):
    """Un agent ecarte par la liste blanche est installe : ne pas le dire « a publier »."""

    def test_un_agent_ecarte_ne_figure_pas_en_plugin_a_publier(self):
        self.write_json("aidlc.json", {"agents": ["plan"]})
        data = status_data(self.root, self.pipeline)
        self.assertNotIn("design", [stage["id"] for stage in data["planned"]])

    def test_les_ids_ecartes_sont_exposes_au_tableau_de_bord(self):
        self.write_json("aidlc.json", {"agents": ["plan"]})
        self.assertEqual(status_data(self.root, self.pipeline)["undeclared"], ["design"])

    def test_une_etape_vraiment_absente_reste_annoncee_comme_a_publier(self):
        self.write_json("aidlc.json", {"agents": ["plan", "design"]})
        data = status_data(self.root, self.pipeline)
        self.assertIn("build", [stage["id"] for stage in data["planned"]])


class TestRenduDuJournalEtDuTableau(AidlcTestCase):
    """Les branches du rendu que seul un etat particulier fait apparaitre."""

    def test_une_etape_autonome_non_signee_est_annoncee_comme_telle(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES_HAUTS})
        maturity = load_maturity(self.root)
        maturity["stages"]["plan"]["autonomous"] = True
        write_json(maturity_path(self.root), maturity)
        self.assertIn("signature non exigée", render_history(history(self.root)))

    def test_un_axe_sous_le_plancher_est_nomme_au_journal(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan",
                     {"scores": {"completeness": 5, "precision": 5,
                                 "traceability": 1, "autonomy": 5}})
        self.assertIn("traceability", render_history(history(self.root)))

    def test_une_cle_de_gouvernance_inconnue_est_signalee_au_tableau_de_bord(self):
        self.write_json("aidlc.json", {"maturity_treshold": 3.0})
        rendu = render_status(status_data(self.root, self.pipeline))
        self.assertIn("Gouvernance du projet", rendu)

    def test_une_porte_amont_fermee_sans_motif_ne_casse_pas_le_message(self):
        # Chemin defensif : `blocking` vide alors que la porte est fermee ne peut pas
        # arriver aujourd'hui, mais l'index [0] serait fatal si ca changeait.
        self.plan_intent()
        self.write("deliverables/design/spec.md", document(front={"stage": "design"}))
        with mock.patch.object(maturity_module, "gate_stage",
                               return_value={"passed": False, "blocking": []}):
            blockers = upstream_blockers(
                self.root, self.pipeline,
                {"id": "design", "consumes": ["deliverables/plan/intent.md"]}, set())
        self.assertIn("motif indisponible", " ".join(blockers))
