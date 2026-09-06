from __future__ import annotations

import json

from .harness import AidlcTestCase
from .harness import GOOD_SECTIONS
from .harness import document
from .harness import manifest
from ..maturity import compute_autonomy
from ..maturity import enqueue_improvement
from ..maturity import gate_stage
from ..maturity import human_review
from ..maturity import load_maturity
from ..maturity import maturity_path
from ..maturity import record_score
from ..maturity import render_status
from ..maturity import review_request
from ..maturity import stage_maturity
from ..maturity import status_data
from ..util import aidlc_dir
from ..util import now_iso
from ..util import write_json

"""Maturite : score recalcule, autonomie, porte (gate), revue humaine, tableau de bord."""

SCORES_HAUTS = {"completeness": 5, "precision": 5, "traceability": 5, "autonomy": 5}
SCORES_BAS = {"completeness": 2, "precision": 2, "traceability": 2, "autonomy": 2}


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

    def test_verdict_explicite_du_reviewer_est_respecte_meme_sous_le_seuil(self):
        record = record_score(self.root, self.pipeline, "plan",
                              {"scores": SCORES_BAS, "verdict": "accepted"})
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
        self.assertTrue(any("Validation deterministe en echec" in b
                            for b in decision["blocking"]))

    def test_aucun_score_enregistre_bloque_et_ne_calcule_pas_le_reste(self):
        self.plan_intent()
        decision = gate_stage(self.root, self.pipeline, "plan")
        self.assertFalse(decision["passed"])
        self.assertIsNone(decision["run"])
        self.assertTrue(any("Aucun score de maturite" in b for b in decision["blocking"]))

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
        self.assertTrue(any("Revue humaine refusee" in b for b in decision["blocking"]))
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

        intent.write_text(document(GOOD_SECTIONS, filler=4), encoding="utf-8")
        decision = gate_stage(self.root, self.pipeline, "design")
        self.assertFalse(decision["passed"])
        self.assertEqual(decision["stale_inputs"], ["deliverables/plan/intent.md"])
        self.assertTrue(any("Entree amont modifiee" in b for b in decision["blocking"]))

        # Le tableau de bord doit remettre design a faire tant que la porte reste ouverte.
        row = next(r for r in status_data(self.root, self.pipeline)["stages"]
                  if r["stage"] == "design")
        self.assertIn("Entree amont modifiee", row["next_action"])

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
        self.assertEqual(row["next_action"], "Etape franchie")

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
        self.assertIn("EQUIPE", render_status(data))

    def test_aucun_role_humain_declare_est_annonce_explicitement(self):
        self.write_agent("aidlc-plan", manifest("plan", "Produit",
                                                "deliverables/plan/intent.md",
                                                human_role=None))
        self.write_agent("aidlc-design", manifest("design", "Architecture",
                                                   "deliverables/design/spec.md",
                                                   ["deliverables/plan/intent.md"],
                                                   human_role=None))
        data = status_data(self.root, self.pipeline)
        self.assertIn("Roles humains : aucun declare", render_status(data))

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
        self.assertIn("Cycle de dependances entre agents", render_status(data))

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
        self.assertIn("Manifeste rejete :", render_status(data))
