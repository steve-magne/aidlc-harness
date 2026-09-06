from __future__ import annotations

import json

from .harness import AidlcTestCase
from .harness import document
from .harness import manifest
from ..improve import feedback
from ..improve import improve
from ..improve import render_feedback
from ..improve import iter_log_events
from ..maturity import record_score
from ..util import now_iso

"""Diagnostic d'auto-amelioration : relecture des journaux, agregation de la maturite,
file d'amelioration (refus humains, refus OKF, haltes du watchdog) et correlation des
refus OKF avec les sessions qui ont ecrit dans le bundle fautif."""


def _line(**kwargs) -> str:
    """Une ligne JSONL de journal ou de file d'amelioration, prete a etre ecrite."""
    return json.dumps(kwargs, ensure_ascii=False)


# ------------------------------------------------------------------ iter_log_events

class TestIterLogEvents(AidlcTestCase):
    """Le generateur qui relit .aidlc/logs/*.jsonl ne casse jamais sur une ligne
    corrompue et balaie tous les fichiers de session presents."""

    def test_repertoire_de_logs_absent_ne_rend_rien(self):
        self.assertEqual(list(iter_log_events(self.root)), [])

    def test_lignes_vides_et_illisibles_sont_ignorees(self):
        self.write(".aidlc/logs/s1.jsonl",
                   "\n" + _line(event="UserPromptSubmit") + "\npas du json\n   \n")
        self.assertEqual(list(iter_log_events(self.root)),
                         [{"event": "UserPromptSubmit"}])

    def test_plusieurs_fichiers_de_session_sont_tous_lus(self):
        self.write(".aidlc/logs/s1.jsonl", _line(session_id="s1") + "\n")
        self.write(".aidlc/logs/s2.jsonl", _line(session_id="s2") + "\n")
        events = list(iter_log_events(self.root))
        self.assertEqual({e["session_id"] for e in events}, {"s1", "s2"})


# -------------------------------------------------------------- comptages d'evenements

class TestImproveComptages(AidlcTestCase):
    """Sessions, evenements, tours de dialogue, outils et repartition par etape :
    tout derive d'une seule passe sur les journaux."""

    def _seed_logs(self):
        lines = [
            _line(session_id="s1", event="UserPromptSubmit", stage="plan"),
            _line(session_id="s1", event="PostToolUse", stage="plan",
                 payload={"tool_name": "Write"}),
            _line(session_id="s1", event="PostToolUse", stage="plan",
                 payload={"tool_name": "Read"}),
            _line(session_id="s2", event="PostToolUse", stage="design",
                 payload={"tool_name": "Write"}),
            _line(session_id=None, event="Notification"),
        ]
        self.write(".aidlc/logs/mix.jsonl", "\n".join(lines) + "\n")

    def test_compte_sessions_evenements_tours_et_outils(self):
        self._seed_logs()
        diag = improve(self.root, self.pipeline)
        self.assertEqual(diag["events"], 5)
        self.assertEqual(diag["sessions"], 2)
        self.assertEqual(diag["turns"], 1)
        self.assertEqual(diag["top_tools"], [("Write", 2), ("Read", 1)])
        self.assertEqual(diag["events_per_stage"], {"plan": 3, "design": 1})

    def test_scope_par_defaut_est_all(self):
        diag = improve(self.root, self.pipeline)
        self.assertEqual(diag["scope"], "all")

    def test_stage_filter_restreint_les_evenements_et_les_sessions(self):
        self._seed_logs()
        diag = improve(self.root, self.pipeline, stage_filter="design")
        self.assertEqual(diag["scope"], "design")
        self.assertEqual(diag["events"], 1)
        self.assertEqual(diag["sessions"], 1)
        self.assertEqual(diag["events_per_stage"], {"design": 1})


# -------------------------------------------------------------------------- validation

class TestImproveValidation(AidlcTestCase):
    """La validation deterministe n'est rejouee que pour les etapes dont le livrable
    existe deja ; les erreurs recurrentes sont normalisees (chiffres -> N) et comptees."""

    def test_ne_valide_que_les_etapes_dont_le_livrable_existe(self):
        self.plan_intent()
        diag = improve(self.root, self.pipeline)
        self.assertEqual(set(diag["validation"]), {"plan"})
        self.assertTrue(diag["validation"]["plan"]["ok"])

    def test_recurring_errors_normalise_les_nombres_et_agrege_entre_etapes(self):
        self.plan_intent(filler=0)
        self.write("deliverables/design/spec.md", document(
            {"## Contexte": "Contexte issu de deliverables/plan/intent.md."},
            front={"stage": "design", "version": "1", "status": "draft",
                  "author": "Steve", "date": "2026-09-03"}, filler=0))
        diag = improve(self.root, self.pipeline)
        self.assertFalse(diag["validation"]["plan"]["ok"])
        self.assertFalse(diag["validation"]["design"]["ok"])
        counts = dict(diag["recurring_errors"])
        key = next(k for k in counts if "trop court" in k)
        self.assertNotRegex(key, r"\d")
        self.assertEqual(counts[key], 2)

    def test_stage_filter_restreint_la_validation(self):
        self.plan_intent(filler=0)
        self.write("deliverables/design/spec.md", document(
            {"## Contexte": "Contexte issu de deliverables/plan/intent.md."},
            front={"stage": "design", "version": "1", "status": "draft",
                  "author": "Steve", "date": "2026-09-03"}, filler=0))
        diag = improve(self.root, self.pipeline, stage_filter="plan")
        self.assertEqual(set(diag["validation"]), {"plan"})


# --------------------------------------------------------------------------- maturite

class TestImproveMaturite(AidlcTestCase):
    """Moyennes par axe, tendance, axes les plus faibles et taux de refus : agreges
    depuis .aidlc/maturity.json, etape par etape."""

    def _seed_maturity(self):
        self.write_json(".aidlc/maturity.json", {"stages": {
            "plan": {"autonomous": True, "runs": [
                {"run": 1, "overall": 3.0, "verdict": "rejected",
                 "scores": {"completeness": 4, "precision": 2,
                           "traceability": 3, "autonomy": 3}},
                {"run": 2, "overall": 4.5, "verdict": "accepted",
                 "scores": {"completeness": 5, "precision": 4,
                           "traceability": 5, "autonomy": 4}},
            ]},
            "design": {"runs": []},
        }})

    def test_agrege_moyennes_tendance_et_axes_faibles(self):
        self._seed_maturity()
        plan = improve(self.root, self.pipeline)["maturity"]["plan"]
        self.assertEqual(plan["runs"], 2)
        self.assertEqual(plan["last_overall"], 4.5)
        self.assertEqual(plan["trend"], [3.0, 4.5])
        self.assertEqual(plan["axis_means"],
                         {"completeness": 4.5, "precision": 3.0,
                          "traceability": 4.0, "autonomy": 3.5})
        self.assertEqual(plan["weakest_axes"], ["precision", "autonomy"])
        self.assertTrue(plan["autonomous"])
        self.assertEqual(plan["rejected_runs"], 1)

    def test_une_etape_sans_run_est_ignoree(self):
        self._seed_maturity()
        diag = improve(self.root, self.pipeline)
        self.assertNotIn("design", diag["maturity"])

    def test_stage_filter_restreint_la_maturite(self):
        self._seed_maturity()
        diag = improve(self.root, self.pipeline, stage_filter="plan")
        self.assertEqual(set(diag["maturity"]), {"plan"})


# ------------------------------------------------------------- file d'amelioration

class TestImproveFileAmelioration(AidlcTestCase):
    """.aidlc/improvement-queue.jsonl se lit en trois sections selon le `kind` de
    chaque entree : refus humain (kind absent), refus du gate OKF (okf_stop, sa propre
    section), halte du watchdog (watchdog, sa propre section). Seuls les refus humains
    sont restreints par --stage."""

    def test_file_absente_rend_des_sections_vides(self):
        diag = improve(self.root, self.pipeline)
        self.assertEqual(diag["human_rejections"], [])
        self.assertEqual(diag["watchdog"]["halts"], [])
        self.assertEqual(diag["okf"]["refusals"], [])

    def test_lignes_json_invalides_de_la_file_sont_ignorees(self):
        self.write(".aidlc/improvement-queue.jsonl",
                   "pas du json\n"
                   + _line(stage="plan", run=1, justification="Incomplet.") + "\n")
        diag = improve(self.root, self.pipeline)
        self.assertEqual(len(diag["human_rejections"]), 1)

    def test_refus_humain_va_dans_human_rejections(self):
        self.write(".aidlc/improvement-queue.jsonl",
                   _line(stage="plan", run=2,
                        justification="Criteres non chiffres.") + "\n")
        diag = improve(self.root, self.pipeline)
        self.assertEqual(diag["human_rejections"][0]["justification"],
                         "Criteres non chiffres.")

    def test_watchdog_va_dans_sa_propre_section_jamais_dans_les_refus_humains(self):
        self.write(".aidlc/improvement-queue.jsonl",
                   _line(kind="watchdog", detector="acharnement", stage="plan") + "\n")
        diag = improve(self.root, self.pipeline)
        self.assertEqual(len(diag["watchdog"]["halts"]), 1)
        self.assertEqual(diag["human_rejections"], [])

    def test_okf_stop_va_dans_okf_refusals_jamais_dans_les_refus_humains(self):
        self.write(".aidlc/improvement-queue.jsonl",
                   _line(kind="okf_stop", session_id="s1", bundle="knowledge",
                        files=["concept.md"]) + "\n")
        diag = improve(self.root, self.pipeline)
        self.assertEqual(len(diag["okf"]["refusals"]), 1)
        self.assertEqual(diag["human_rejections"], [])

    def test_stage_filter_ne_s_applique_qu_aux_refus_humains(self):
        self.write(".aidlc/improvement-queue.jsonl", "\n".join([
            _line(kind="okf_stop", session_id="s1", bundle="knowledge",
                 files=["a.md"]),
            _line(kind="watchdog", detector="x", stage="design"),
            _line(stage="plan", run=1, justification="Pas assez precis."),
            _line(stage="design", run=1, justification="Autre etape."),
        ]) + "\n")
        diag = improve(self.root, self.pipeline, stage_filter="plan")
        self.assertEqual(len(diag["okf"]["refusals"]), 1)
        self.assertEqual(len(diag["watchdog"]["halts"]), 1)
        self.assertEqual(len(diag["human_rejections"]), 1)
        self.assertEqual(diag["human_rejections"][0]["justification"],
                         "Pas assez precis.")


# --------------------------------------------------------- correlation des refus OKF

class TestImproveCorrelationOkf(AidlcTestCase):
    """Un refus du gate OKF est correle aux ecritures journalisees dans le fichier
    fautif : meme session en priorite, sinon n'importe quelle ecriture correspondante,
    et la plus recente est retenue quand plusieurs candidats existent."""

    def _okf_stop(self, session_id=None, bundle="knowledge", files=("concept.md",)):
        return _line(kind="okf_stop", ts=now_iso(), session_id=session_id,
                    bundle=bundle, files=list(files),
                    errors=["concept.md : sans frontmatter."])

    def test_aucune_ecriture_journalisee_laisse_implicated_vide(self):
        self.write(".aidlc/improvement-queue.jsonl", self._okf_stop() + "\n")
        diag = improve(self.root, self.pipeline)
        self.assertEqual(diag["okf"]["refusals"][0]["implicated"], [])

    def test_une_ecriture_write_ou_edit_correspondante_est_correlee(self):
        self.write(".aidlc/improvement-queue.jsonl",
                   self._okf_stop(session_id="s1") + "\n")
        target = str(self.root / "knowledge" / "concept.md")
        self.write(".aidlc/logs/mix.jsonl", "\n".join([
            # ignore : ni Write, ni Edit, ni MultiEdit
            _line(session_id="s1", event="PostToolUse",
                 payload={"tool_name": "Read", "tool_input": {"file_path": target}}),
            # ignore : pas de file_path dans tool_input
            _line(session_id="s1", event="PostToolUse",
                 payload={"tool_name": "Write", "tool_input": {}}),
            # correspond
            _line(session_id="s1", event="PostToolUse", ts="2026-01-01T00:00:00+00:00",
                 payload={"tool_name": "Edit", "tool_input": {"file_path": target}}),
        ]) + "\n")
        diag = improve(self.root, self.pipeline)
        implicated = diag["okf"]["refusals"][0]["implicated"]
        self.assertEqual(implicated,
                         [{"file": "concept.md", "session_id": "s1",
                           "ts": "2026-01-01T00:00:00+00:00"}])

    def test_plusieurs_candidats_de_la_meme_session_retient_le_plus_recent(self):
        self.write(".aidlc/improvement-queue.jsonl",
                   self._okf_stop(session_id="s1") + "\n")
        target = str(self.root / "knowledge" / "concept.md")
        self.write(".aidlc/logs/mix.jsonl", "\n".join([
            _line(session_id="s1", event="PostToolUse", ts="2026-01-01T00:00:00+00:00",
                 payload={"tool_name": "Write", "tool_input": {"file_path": target}}),
            _line(session_id="s1", event="PostToolUse", ts="2026-01-02T00:00:00+00:00",
                 payload={"tool_name": "Edit", "tool_input": {"file_path": target}}),
        ]) + "\n")
        diag = improve(self.root, self.pipeline)
        implicated = diag["okf"]["refusals"][0]["implicated"][0]
        self.assertEqual(implicated["ts"], "2026-01-02T00:00:00+00:00")

    def test_la_session_du_refus_est_privilegiee_sur_une_autre_session_plus_recente(self):
        self.write(".aidlc/improvement-queue.jsonl",
                   self._okf_stop(session_id="s1") + "\n")
        target = str(self.root / "knowledge" / "concept.md")
        self.write(".aidlc/logs/mix.jsonl", "\n".join([
            _line(session_id="s2", event="PostToolUse", ts="2026-01-05T00:00:00+00:00",
                 payload={"tool_name": "Write", "tool_input": {"file_path": target}}),
            _line(session_id="s1", event="PostToolUse", ts="2026-01-01T00:00:00+00:00",
                 payload={"tool_name": "Write", "tool_input": {"file_path": target}}),
        ]) + "\n")
        diag = improve(self.root, self.pipeline)
        implicated = diag["okf"]["refusals"][0]["implicated"][0]
        self.assertEqual(implicated["session_id"], "s1")
        self.assertEqual(implicated["ts"], "2026-01-01T00:00:00+00:00")

    def test_sans_session_dans_le_refus_toute_ecriture_correspondante_convient(self):
        self.write(".aidlc/improvement-queue.jsonl",
                   self._okf_stop(session_id=None) + "\n")
        target = str(self.root / "knowledge" / "concept.md")
        self.write(".aidlc/logs/mix.jsonl",
                   _line(session_id="s2", event="PostToolUse",
                        ts="2026-01-01T00:00:00+00:00",
                        payload={"tool_name": "Write",
                                "tool_input": {"file_path": target}}) + "\n")
        diag = improve(self.root, self.pipeline)
        implicated = diag["okf"]["refusals"][0]["implicated"][0]
        self.assertEqual(implicated["session_id"], "s2")


# ---------------------------------------------------- migration du scenario 19 (selftest)

class TestScenario19MigreDuSelftest(AidlcTestCase):
    """Migration du scenario 19 de selftest.py (lignes 410-416) : chaque check()
    d'origine devient une methode dediee qui reprend son libelle. Le diagnostic improve
    doit voir les logs, agreger la maturite, remonter le refus humain et classer les
    axes faibles."""

    def setUp(self):
        super().setUp()
        self.write(".aidlc/logs/s1.jsonl",
                   _line(session_id="s1", event="UserPromptSubmit", stage="plan") + "\n")
        record_score(self.root, self.pipeline, "plan", {
            "stage": "plan", "scores": {"completeness": 5, "precision": 2,
                                        "traceability": 3, "autonomy": 4},
            "verdict": "accepted"})
        self.write(".aidlc/improvement-queue.jsonl",
                   _line(stage="plan", run=1,
                        justification="Criteres non chiffres.") + "\n")
        self.diag = improve(self.root, self.pipeline)

    def test_improve_doit_voir_les_logs(self):
        self.assertGreaterEqual(self.diag["events"], 1)
        self.assertGreaterEqual(self.diag["sessions"], 1)

    def test_improve_doit_agreger_la_maturite(self):
        self.assertIn("plan", self.diag["maturity"])

    def test_improve_doit_remonter_le_refus_humain(self):
        self.assertEqual(len(self.diag["human_rejections"]), 1)

    def test_improve_doit_classer_les_axes_faibles(self):
        self.assertTrue(self.diag["maturity"]["plan"]["weakest_axes"])


SCORES = {"completeness": 4, "precision": 4, "traceability": 4, "autonomy": 4}


class TestSignauxDeWorkflow(AidlcTestCase):
    """Ce qui se juge au niveau de la chaine, et qu'aucun correctif de plugin ne repare."""

    def test_une_etape_jamais_jouee_est_nommee(self):
        diag = improve(self.root, self.pipeline)
        self.assertIn("plan", diag["workflow"]["never_ran"])

    def test_une_etape_jouee_sort_de_cette_liste(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES})
        diag = improve(self.root, self.pipeline)
        self.assertNotIn("plan", diag["workflow"]["never_ran"])

    def test_le_cout_de_l_etape_compte_ses_tentatives(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES})
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES})
        diag = improve(self.root, self.pipeline)
        self.assertEqual(diag["workflow"]["cost_per_stage"]["plan"]["runs"], 2)

    def test_le_cout_retient_le_run_qui_a_ete_accepte(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan",
                     {"scores": {"completeness": 2, "precision": 2,
                                 "traceability": 2, "autonomy": 2}})
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES})
        diag = improve(self.root, self.pipeline)
        self.assertEqual(diag["workflow"]["cost_per_stage"]["plan"]["runs_to_accept"], 2)

    def test_un_maillon_manquant_de_la_chaine_remonte(self):
        self.write_agent("aidlc-orphelin",
                         manifest("orphelin", "Qualite", "deliverables/qa/plan.md",
                                  ["deliverables/inexistant/rien.md"]),
                         {"required_sections": ["## Contexte"]})
        diag = improve(self.root, self.pipeline)
        self.assertTrue(diag["workflow"]["missing_producers"])

    def test_un_agent_publie_mais_non_branche_remonte(self):
        self.write_json("aidlc.json", {"agents": ["plan"]})
        diag = improve(self.root, self.pipeline)
        self.assertEqual(diag["workflow"]["undeclared"], ["design"])


class TestReservesSeparees(AidlcTestCase):
    """Une approbation motivee n'est pas un refus : elle ne se lit pas comme tel."""

    def _file(self, kind=None):
        item = {"ts": now_iso(), "stage": "plan", "run": 1, "reviewer": "Marie",
                "justification": "Les KPI restent mous.", "source": "human_review"}
        if kind:
            item["kind"] = kind
        self.write(".aidlc/improvement-queue.jsonl", json.dumps(item) + "\n")

    def test_une_reserve_ne_compte_pas_comme_un_refus(self):
        self._file(kind="reserve")
        self.assertEqual(improve(self.root, self.pipeline)["human_rejections"], [])

    def test_une_reserve_a_sa_propre_section(self):
        self._file(kind="reserve")
        self.assertEqual(len(improve(self.root, self.pipeline)["human_reserves"]), 1)

    def test_un_refus_reste_dans_les_refus(self):
        self._file()
        self.assertEqual(len(improve(self.root, self.pipeline)["human_rejections"]), 1)


class TestRetourDUsage(AidlcTestCase):
    """Ce que le projet a mesure sur un agent, a rendre a l'equipe qui le maintient."""

    def test_chaque_agent_du_registre_a_sa_ligne(self):
        ids = [report["agent"] for report in feedback(self.root)["agents"]]
        self.assertEqual(sorted(ids), ["design", "plan"])

    def test_le_rapport_nomme_l_equipe_proprietaire(self):
        report = next(r for r in feedback(self.root)["agents"] if r["agent"] == "plan")
        self.assertEqual(report["team"], "Produit")

    def test_le_filtre_ne_garde_qu_un_agent(self):
        self.assertEqual(len(feedback(self.root, "plan")["agents"]), 1)

    def test_la_serie_de_notes_est_rendue(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES})
        report = next(r for r in feedback(self.root)["agents"] if r["agent"] == "plan")
        self.assertEqual(report["trend"], [4.0])

    def test_l_axe_faible_est_nomme_quand_les_notes_different(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan",
                     {"scores": {"completeness": 5, "precision": 5,
                                 "traceability": 2, "autonomy": 5}})
        report = next(r for r in feedback(self.root)["agents"] if r["agent"] == "plan")
        self.assertEqual(report["weakest_axes"][0], "traceability")

    def test_des_notes_toutes_egales_n_ont_pas_d_axe_faible(self):
        # Nommer deux axes « les plus faibles » quand tout est a 4 envoie l'equipe
        # corriger ce qui va bien.
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES})
        report = next(r for r in feedback(self.root)["agents"] if r["agent"] == "plan")
        self.assertEqual(report["weakest_axes"], [])

    def test_le_motif_ecrit_par_l_humain_est_transmis(self):
        self.write(".aidlc/improvement-queue.jsonl", json.dumps({
            "ts": now_iso(), "stage": "plan", "run": 1, "reviewer": "Marie",
            "justification": "Perimetre flou.", "source": "human_review"}) + "\n")
        report = next(r for r in feedback(self.root)["agents"] if r["agent"] == "plan")
        self.assertEqual(report["human_rejections"][0]["justification"], "Perimetre flou.")

    def test_le_rendu_humain_annonce_un_agent_jamais_note(self):
        self.assertIn("aucun run noté", render_feedback(feedback(self.root)))

    def test_le_rendu_humain_porte_la_version_de_l_agent(self):
        self.plan_intent()
        record_score(self.root, self.pipeline, "plan", {"scores": SCORES})
        self.assertIn("v0.1.0", render_feedback(feedback(self.root)))


class TestRetourDUsageSansAgent(AidlcTestCase):
    seed_agents = False

    def test_un_registre_vide_le_dit(self):
        self.assertIn("Aucun agent", render_feedback(feedback(self.root)))


class TestRenduDuRetourDUsage(AidlcTestCase):
    """Les branches du rapport que seul un projet deja passe par la boucle fait sortir."""

    def _note(self, scores, verdict=None):
        self.plan_intent()
        review = {"scores": scores}
        if verdict:
            review["verdict"] = verdict
        record_score(self.root, self.pipeline, "plan", review)

    def test_un_run_refuse_est_compte_dans_le_rendu(self):
        self._note({"completeness": 2, "precision": 2,
                    "traceability": 2, "autonomy": 2})
        self.assertIn("refusé(s)", render_feedback(feedback(self.root)))

    def test_l_axe_faible_apparait_dans_le_rendu(self):
        self._note({"completeness": 5, "precision": 5,
                    "traceability": 2, "autonomy": 5})
        self.assertIn("axes les plus faibles", render_feedback(feedback(self.root)))

    def test_un_refus_humain_est_cite_avec_son_auteur(self):
        self._note({"completeness": 4, "precision": 4,
                    "traceability": 4, "autonomy": 4})
        self.write(".aidlc/improvement-queue.jsonl", json.dumps({
            "ts": now_iso(), "stage": "plan", "run": 1, "reviewer": "Marie",
            "justification": "Perimetre flou.", "source": "human_review"}) + "\n")
        self.assertIn("refus (Marie)", render_feedback(feedback(self.root)))

    def test_une_reserve_est_citee_a_part(self):
        self._note({"completeness": 4, "precision": 4,
                    "traceability": 4, "autonomy": 4})
        self.write(".aidlc/improvement-queue.jsonl", json.dumps({
            "ts": now_iso(), "stage": "plan", "run": 1, "reviewer": "Marie",
            "justification": "Les KPI restent mous.", "source": "human_review",
            "kind": "reserve"}) + "\n")
        self.assertIn("réserve (Marie)", render_feedback(feedback(self.root)))

    def test_une_ligne_illisible_de_la_file_est_ignoree_sans_casser(self):
        self.write(".aidlc/improvement-queue.jsonl", "{ pas du json\n")
        self.assertEqual(feedback(self.root)["agents"][0]["human_rejections"], [])
