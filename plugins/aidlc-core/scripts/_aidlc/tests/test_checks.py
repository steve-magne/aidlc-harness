from __future__ import annotations

import json
import os

from unittest import mock

from .harness import AidlcTestCase
from .harness import CHECKS
from .harness import GOOD_SECTIONS
from .harness import document
from .harness import manifest
from .harness import repo_root
from .. import checks
from ..util import read_text

"""Validation declarative des livrables (checks.py) : sections, frontmatter, mots
interdits, min_words/min_items, must_reference_inputs, preuve d'execution (evidence),
holdout (le livrable ne cite pas son propre metre), perimetre (item hors perimetre
amont exclu en aval), et resolution du checks.json d'un agent."""


# ------------------------------------------------------- scenarios migres (1 a 8)

class TestSectionsRequises(AidlcTestCase):
    """Une section obligatoire absente du livrable invalide l'etape."""

    def test_une_section_manquante_doit_invalider(self):
        sections = dict(GOOD_SECTIONS)
        sections.pop("## Probleme")
        self.plan_intent(sections)
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertFalse(res["ok"])

    def test_l_erreur_doit_nommer_la_section(self):
        sections = dict(GOOD_SECTIONS)
        sections.pop("## Probleme")
        self.plan_intent(sections)
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("## Probleme" in e for e in res["errors"]))


class TestMotifsInterdits(AidlcTestCase):
    """Un motif de forbidden_patterns present dans le livrable invalide l'etape."""

    def test_un_motif_interdit_doit_invalider(self):
        bad = dict(GOOD_SECTIONS)
        bad["## Probleme"] = "Probleme a preciser, TODO plus tard."
        self.plan_intent(bad)
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertFalse(res["ok"])
        self.assertTrue(any("interdit" in e for e in res["errors"]))


class TestFrontmatterIncomplet(AidlcTestCase):
    """Une cle de required_frontmatter manquante invalide l'etape."""

    def test_un_frontmatter_incomplet_doit_invalider(self):
        self.plan_intent(front={"stage": "plan", "version": "1"})
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("Frontmatter" in e for e in res["errors"]))


class TestMinItemsParSection(AidlcTestCase):
    """min_items_per_section compte les puces d'une section precise."""

    def test_min_items_per_section_doit_compter_les_puces(self):
        few = dict(GOOD_SECTIONS)
        few["## Criteres d'acceptation"] = "- Un seul critere."
        self.plan_intent(few)
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("minimum 3" in e for e in res["errors"]))


class TestMinWords(AidlcTestCase):
    """min_words invalide un livrable trop court une fois le frontmatter retire."""

    def test_min_words_doit_invalider(self):
        self.plan_intent(filler=0)
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("trop court" in e for e in res["errors"]))


class TestLivrableConforme(AidlcTestCase):
    """Un livrable qui satisfait toutes les regles declarees passe, et chaque regle
    declaree est bien comptee dans checks_run."""

    def test_le_livrable_conforme_doit_passer(self):
        self.plan_intent()
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(res["ok"], res["errors"])

    def test_toutes_les_regles_declarees_doivent_etre_comptees(self):
        self.plan_intent()
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertGreaterEqual(res["checks_run"], 5)


class TestMustReferenceInputs(AidlcTestCase):
    """must_reference_inputs detecte l'absence de citation d'une entree amont, et
    citer l'input (chemin ou nom de fichier) leve l'erreur de tracabilite."""

    def test_must_reference_inputs_doit_detecter_l_absence_de_citation(self):
        self.plan_intent()
        self.write("deliverables/design/spec.md",
                   document({"## Contexte": "Un contexte sans citation d'amont."},
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        res = checks.validate_stage(self.root, self.pipeline, "design")
        self.assertTrue(any("Input non reference" in e for e in res["errors"]))

    def test_citer_l_input_doit_lever_l_erreur_de_tracabilite(self):
        self.plan_intent()
        self.write("deliverables/design/spec.md",
                   document({"## Contexte": "Contexte issu de deliverables/plan/intent.md."},
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        res = checks.validate_stage(self.root, self.pipeline, "design")
        self.assertTrue(res["ok"], res["errors"])


class TestEtapeInconnue(AidlcTestCase):
    """Un id d'etape absent du registre est invalide, pas une exception."""

    def test_une_etape_inconnue_est_invalide(self):
        res = checks.validate_stage(self.root, self.pipeline, "inconnue")
        self.assertFalse(res["ok"])


class TestAgentConsultatifSansLivrable(AidlcTestCase):
    """Un agent consultatif (sans champ 'produces') n'a rien a valider : validate_stage
    le refuse explicitement plutot que d'essayer de deviner un chemin de livrable."""

    def test_un_agent_sans_produces_est_invalide_avec_un_message_explicite(self):
        self.write_agent("acme-security",
                         manifest("security-review", "AppSec"))
        res = checks.validate_stage(self.root, self.pipeline, "security-review")
        self.assertFalse(res["ok"])
        self.assertIsNone(res["file"])
        self.assertTrue(any("ne produit pas de livrable" in e for e in res["errors"]))


# ------------------------------------------------------------- scenarios 30 a 32

class TestProofOfRun(AidlcTestCase):
    """proof_of_run (evidence, not claims) : une section declaree preuve doit citer
    une valeur observee concrete ; reformuler l'attendu ne suffit pas."""

    def _write_proof_checks(self):
        proof_checks = dict(CHECKS)
        proof_checks["required_sections"] = ["## Contexte"]
        proof_checks["min_items_per_section"] = {}
        proof_checks["proof_of_run"] = ["## Criteres d'acceptation"]
        self.write_json("plugins/aidlc-design/checks.json", proof_checks)

    def test_proof_of_run_doit_rejeter_une_section_sans_valeur_observee(self):
        self._write_proof_checks()
        self.plan_intent()
        fail_sections = dict(GOOD_SECTIONS)
        fail_sections["## Contexte"] = "Conception sans valeur observee, seulement des intentions."
        fail_sections["## Criteres d'acceptation"] = (
            "- Le systeme doit repondre dans les temps.\n"
            "- L'interface doit etre claire.\n"
            "- La documentation doit etre complete.")
        self.write("deliverables/design/spec.md",
                   document(fail_sections,
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        res = checks.validate_stage(self.root, self.pipeline, "design")
        self.assertTrue(any("Preuve d'execution absente" in e for e in res["errors"]))

    def test_proof_of_run_doit_accepter_une_valeur_observee(self):
        self._write_proof_checks()
        self.plan_intent()
        pass_sections = dict(GOOD_SECTIONS)
        pass_sections["## Contexte"] = "Conception issue de deliverables/plan/intent.md."
        pass_sections["## Criteres d'acceptation"] = (
            "- p95 mesure a 420 ms sous 200 r/s sur le run 1.\n"
            "- Couverture de tests portee a 80 %.\n"
            "- Latence mediane observee : 120 ms.")
        self.write("deliverables/design/spec.md",
                   document(pass_sections,
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        res = checks.validate_stage(self.root, self.pipeline, "design")
        self.assertTrue(res["ok"], res["errors"])

    def test_proof_of_run_doit_rejeter_une_section_de_preuve_totalement_absente(self):
        """Si la section visee par proof_of_run n'existe meme pas dans le livrable,
        l'erreur est la meme que pour une section obligatoire manquante (pas de
        recherche de preuve dans un corps qui n'existe pas)."""
        self._write_proof_checks()
        self.plan_intent()
        sections_sans_criteres = {"## Contexte": "Conception issue de deliverables/plan/intent.md."}
        self.write("deliverables/design/spec.md",
                   document(sections_sans_criteres,
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        res = checks.validate_stage(self.root, self.pipeline, "design")
        self.assertTrue(any("Section obligatoire absente : '## Criteres d'acceptation'" in e
                            for e in res["errors"]))
        self.assertFalse(any("Preuve d'execution absente" in e for e in res["errors"]))


class TestHoldout(AidlcTestCase):
    """checks_do_not_self_reference (holdout) : le livrable ne doit pas citer une
    ligne de son propre checks.json — travailler sur l'ouvrage, pas sur le metre."""

    def _write_holdout_checks(self):
        holdout_checks = dict(CHECKS)
        holdout_checks["required_sections"] = ["## Contexte"]
        holdout_checks["min_items_per_section"] = {}
        holdout_checks["checks_do_not_self_reference"] = True
        self.write_json("plugins/aidlc-design/checks.json", holdout_checks)

    def test_checks_do_not_self_reference_doit_detecter_la_citation_du_metre(self):
        self._write_holdout_checks()
        self.plan_intent()
        leaked = '    "min_words": 60,'
        self.write("deliverables/design/spec.md",
                   document({"## Contexte": f"Contrat vise : {leaked} (extrait du checks.json)."},
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        res = checks.validate_stage(self.root, self.pipeline, "design")
        self.assertTrue(any("Holdout" in e for e in res["errors"]))

    def test_un_livrable_honnete_ne_declenche_pas_le_holdout(self):
        self._write_holdout_checks()
        self.plan_intent()
        self.write("deliverables/design/spec.md",
                   document({"## Contexte": "Conception honnete, aucune regle de validation citee."},
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        res = checks.validate_stage(self.root, self.pipeline, "design")
        self.assertFalse(any("Holdout" in e for e in res["errors"]))


class TestPerimetre(AidlcTestCase):
    """must_not_violate_scope : un item hors perimetre du plan amont doit rester
    exclu (ou non mentionne) dans le livrable aval."""

    def _write_scope_checks(self):
        scope_checks = dict(CHECKS)
        scope_checks["must_not_violate_scope"] = {"section": "## Hors perimetre"}
        scope_checks["required_sections"] = ["## Contexte", "## Hors perimetre"]
        scope_checks["min_items_per_section"] = {}
        self.write_json("plugins/aidlc-design/checks.json", scope_checks)

    def test_must_not_violate_scope_doit_detecter_la_violation_d_un_item_du_plan(self):
        self._write_scope_checks()
        plan_scope = dict(GOOD_SECTIONS)
        plan_scope["## Hors perimetre"] = "- Facturation a l'unite.\n- Integration ERP."
        self.plan_intent(plan_scope)
        self.write("deliverables/design/spec.md",
                   document({"## Contexte": "Conception incluant la facturation a l'unite.\n\n"
                                            "## Hors perimetre\nRien de plus a exclure."},
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        res = checks.validate_stage(self.root, self.pipeline, "design")
        self.assertTrue(any("Perimetre : l'item" in e for e in res["errors"]))

    def test_le_perimetre_respecte_doit_passer(self):
        self._write_scope_checks()
        plan_scope = dict(GOOD_SECTIONS)
        plan_scope["## Hors perimetre"] = "- Facturation a l'unite.\n- Integration ERP."
        self.plan_intent(plan_scope)
        honest_sections = dict(GOOD_SECTIONS)
        honest_sections["## Contexte"] = (
            "Conception issue de deliverables/plan/intent.md, sans la facturation.")
        honest_sections["## Hors perimetre"] = (
            "- Facturation a l'unite : exclu, reporte.\n"
            "- Integration ERP : non couvert par cette version.")
        self.write("deliverables/design/spec.md",
                   document(honest_sections,
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        res = checks.validate_stage(self.root, self.pipeline, "design")
        self.assertTrue(res["ok"], res["errors"])


# --------------------------------------------------------------------- scenario 36

class TestContratReelPlan(AidlcTestCase):
    """Le contrat reel de plugins/aidlc-plan/checks.json porte les regles anti-derive
    adoptees : preuve d'execution (Contexte, Solution proposee, Criteres) et holdout.
    Ce bloc garde l'adoption elle-meme : si les regles sortent du checks.json de plan,
    ces tests cassent — et un intent conforme a ce contrat reel doit passer."""

    PLAN_INTENT = {
        "## Contexte": ("Demande issue du comite produit 2026-09-01 ; 42 % des dossiers "
                        "repassent en saisie manuelle (mesure SAP du T3)."),
        "## Problème": "Le cadrage des demandes est lent et sans trace.",
        "## Utilisateurs impactés": ("- Product Owner : 12 personnes, cadrage hebdomadaire.\n"
                                     "- Conformite : 3 personnes, controle a chaque release."),
        "## Solution proposée": ("Un pipeline agentique a portes deterministes.\n\n"
                                 "- Reduire le retraitement : 42 % aujourd'hui, cible 15 % "
                                 "au 31/03.\n"
                                 "- Diviser par deux le delai de cadrage : 12 j, cible 6 j."),
        "## Contraintes": "- Python stdlib seulement.\n- Aucune dependance externe.",
        "## Critères d'acceptation": ("- p95 < 300 ms sur le run 2.\n"
                                      "- Couverture des tests portee a 80 %.\n"
                                      "- 100 % de conformite OKF v0.2."),
        "## Hors périmètre": "- Facturation a l'unite.\n- Integration de l'ERP.",
        "## Sources et références": ("Source : knowledge/conventions.md ; entretien P.O. "
                                     "du 2026-09-02."),
    }

    def _real_checks_path(self):
        return repo_root() / "plugins" / "aidlc-plan" / "checks.json"

    def _load_real_checks(self):
        return json.loads(read_text(self._real_checks_path()))

    def _apply_real_checks(self):
        real = self._load_real_checks()
        self.write_json("plugins/aidlc-plan/checks.json", real)
        return real

    def test_le_contrat_de_plan_doit_vivre_dans_son_propre_plugin_sans_miroir(self):
        self.assertTrue(self._real_checks_path().exists())

    def test_le_contrat_de_l_etape_plan_doit_porter_proof_of_run_et_checks_do_not_self_reference(self):
        real = self._load_real_checks()
        self.assertIn("proof_of_run", real)
        self.assertIn("checks_do_not_self_reference", real)

    def test_proof_of_run_de_plan_doit_cibler_contexte_solution_proposee_et_criteres(self):
        real = self._load_real_checks()
        self.assertEqual(real["proof_of_run"],
                         ["## Contexte", "## Solution proposée", "## Critères d'acceptation"])

    def test_le_contrat_de_plan_doit_exiger_des_personas_et_des_benefices_enumeres(self):
        real = self._load_real_checks()
        self.assertEqual(real["min_items_per_section"].get("## Utilisateurs impactés"), 2)
        self.assertEqual(real["min_items_per_section"].get("## Solution proposée"), 2)

    def test_l_intent_conforme_au_contrat_reel_plan_doit_passer(self):
        self._apply_real_checks()
        self.plan_intent(self.PLAN_INTENT, filler=8)
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(res["ok"], res["errors"][:3])

    def test_proof_of_run_doit_exiger_une_valeur_observee_dans_le_contexte(self):
        self._apply_real_checks()
        weak_context = dict(self.PLAN_INTENT)
        weak_context["## Contexte"] = "La demande vient de plusieurs equipes, sans mesure ni source."
        self.plan_intent(weak_context, filler=8)
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("Preuve d'execution absente" in e and "## Contexte" in e
                            for e in res["errors"]))

    def test_proof_of_run_doit_exiger_des_criteres_chiffres(self):
        self._apply_real_checks()
        vague_criteria = dict(self.PLAN_INTENT)
        vague_criteria["## Critères d'acceptation"] = (
            "- Le systeme doit repondre rapidement.\n"
            "- L'interface doit etre claire.\n"
            "- La documentation doit etre complete.")
        self.plan_intent(vague_criteria, filler=8)
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("Preuve d'execution absente" in e and "## Critères d'acceptation" in e
                            for e in res["errors"]))

    def test_checks_do_not_self_reference_doit_rejeter_un_intent_qui_cite_son_contrat(self):
        self._apply_real_checks()
        overflow = dict(self.PLAN_INTENT)
        overflow["## Sources et références"] = (
            'Contrat vise : "min_words": 250, (extrait du checks.json).')
        self.plan_intent(overflow, filler=8)
        res = checks.validate_stage(self.root, self.pipeline, "plan")
        self.assertTrue(any("Holdout" in e for e in res["errors"]))


# ------------------------------------------------------- fonctions internes pures

class TestFrontmatterSansFermeture(AidlcTestCase):
    """Un bloc frontmatter jamais referme n'est pas un frontmatter : split_frontmatter
    renvoie ce qu'il a pu lire, mais colle au texte d'origine en entier comme corps."""

    def test_bloc_qui_ne_se_referme_jamais_renvoie_le_frontmatter_partiel_et_le_texte_entier(self):
        text = "---\nstage: plan\nversion: 1\nSuite du texte sans jamais fermer le bloc."
        front, body = checks.split_frontmatter(text)
        self.assertEqual(front, {"stage": "plan", "version": "1"})
        self.assertEqual(body, text)


class TestResolveChecksPath(AidlcTestCase):
    """Resolution du checks.json d'une etape : sans regle declaree, relativement a la
    racine du pipeline, ou par repli sur l'ancien miroir <plugin>/checks.json."""

    def test_renvoie_none_sans_regle_checks_declaree(self):
        self.assertIsNone(checks.resolve_checks_path(self.root, {"id": "x"}))

    def test_resout_relativement_a_la_racine_du_pipeline_sans_champ_root(self):
        target = self.write_json("checks/plan.json", {"min_words": 1})
        result = checks.resolve_checks_path(self.root, {"checks": "checks/plan.json"})
        self.assertEqual(result, target)

    def test_retombe_sur_le_miroir_du_plugin_quand_le_chemin_relatif_est_absent(self):
        pipe_root = self.root / "core"
        fallback_target = self.write_json("aidlc-plan/checks.json", {"min_words": 1})
        result = checks.resolve_checks_path(
            pipe_root, {"checks": "checks.json", "plugin": "aidlc-plan"})
        self.assertEqual(result, fallback_target)

    def test_renvoie_le_chemin_calcule_meme_introuvable_en_dernier_recours(self):
        pipe_root = self.root / "core"
        result = checks.resolve_checks_path(pipe_root, {"checks": "checks.json"})
        self.assertEqual(result, pipe_root / "checks.json")


class TestRunChecksCasLimites(AidlcTestCase):
    """Chemins d'erreur de run_checks non couverts par les scenarios de bout en bout :
    livrable absent, etape sans regle, checks.json introuvable ou illisible, regle
    inconnue, max_words, et regex invalide dans forbidden/required_patterns."""

    def test_livrable_absent_produit_une_erreur_et_court_circuite(self):
        stage = {"id": "plan", "checks": "checks.json"}
        missing = self.root / "deliverables/plan/absent.md"
        res = checks.run_checks(self.root, stage, missing)
        self.assertEqual(res["errors"],
                         [f"Livrable absent : {os.path.relpath(missing, self.root)}"])
        self.assertEqual(res["checks_run"], 0)

    def test_etape_sans_regle_declaree_est_acceptee_avec_avertissement(self):
        livrable = self.write("deliverables/plan/intent.md", "contenu minimal")
        stage = {"id": "plan", "checks": None}
        res = checks.run_checks(self.root, stage, livrable)
        self.assertTrue(res["ok"])
        self.assertIn("Aucun fichier de checks declare pour cette etape.", res["warnings"])

    def test_fichier_de_checks_introuvable_produit_une_erreur(self):
        livrable = self.write("livrable.md", "contenu")
        stage = {"id": "plan", "checks": "absent.json", "root": str(self.root / "vide")}
        res = checks.run_checks(self.root, stage, livrable)
        self.assertFalse(res["ok"])
        self.assertTrue(any("introuvable" in e for e in res["errors"]))

    def test_checks_json_illisible_produit_une_erreur(self):
        livrable = self.write("livrable.md", "contenu")
        checks_dir = self.root / "custom"
        self.write("custom/checks.json", "{ ceci n'est pas du json")
        stage = {"id": "plan", "checks": "checks.json", "root": str(checks_dir)}
        res = checks.run_checks(self.root, stage, livrable)
        self.assertFalse(res["ok"])
        self.assertTrue(any("illisible" in e for e in res["errors"]))

    def test_regle_inconnue_produit_un_avertissement_sans_bloquer(self):
        livrable = self.write("livrable.md", "contenu quelconque suffisant.")
        checks_dir = self.root / "custom2"
        self.write_json("custom2/checks.json", {"bogus_rule": True})
        stage = {"id": "plan", "checks": "checks.json", "root": str(checks_dir)}
        res = checks.run_checks(self.root, stage, livrable)
        self.assertTrue(res["ok"])
        self.assertIn("Regle inconnue ignoree : bogus_rule", res["warnings"])
        self.assertEqual(res["checks_run"], 0)

    def test_max_words_produit_un_avertissement_pas_une_erreur(self):
        livrable = self.write("livrable.md",
                              "un deux trois quatre cinq six sept huit neuf dix")
        checks_dir = self.root / "custom3"
        self.write_json("custom3/checks.json", {"max_words": 3})
        stage = {"id": "plan", "checks": "checks.json", "root": str(checks_dir)}
        res = checks.run_checks(self.root, stage, livrable)
        self.assertTrue(res["ok"])
        self.assertEqual(res["errors"], [])
        self.assertTrue(any("Livrable long" in w for w in res["warnings"]))

    def test_regex_invalide_dans_forbidden_patterns_produit_un_avertissement(self):
        livrable = self.write("livrable.md", "contenu quelconque.")
        checks_dir = self.root / "custom4"
        self.write_json("custom4/checks.json", {"forbidden_patterns": ["("]})
        stage = {"id": "plan", "checks": "checks.json", "root": str(checks_dir)}
        res = checks.run_checks(self.root, stage, livrable)
        self.assertTrue(res["ok"])
        self.assertEqual(res["checks_run"], 1)
        self.assertTrue(any("Regex invalide" in w for w in res["warnings"]))

    def test_required_patterns_absent_produit_une_erreur(self):
        livrable = self.write("livrable.md", "contenu sans le motif attendu.")
        checks_dir = self.root / "custom5"
        self.write_json("custom5/checks.json", {"required_patterns": ["pattern_absent_xyz"]})
        stage = {"id": "plan", "checks": "checks.json", "root": str(checks_dir)}
        res = checks.run_checks(self.root, stage, livrable)
        self.assertFalse(res["ok"])
        self.assertTrue(any("Motif obligatoire absent" in e for e in res["errors"]))


class TestRequiredInputSection(AidlcTestCase):
    """required_input_section est plus strict que must_reference_inputs : l'input doit
    etre cite DANS la section designee, pas seulement quelque part dans le livrable."""

    def _stage(self):
        checks_dir = self.root / "custom-ris"
        self.write_json("custom-ris/checks.json",
                        {"required_input_section": {
                            "deliverables/plan/intent.md": "## Contexte"}})
        return {"id": "design", "checks": "checks.json", "root": str(checks_dir)}

    def test_section_de_citation_absente_produit_une_erreur(self):
        livrable = self.write("livrable.md", "## Autre\nContenu sans la section attendue.\n")
        res = checks.run_checks(self.root, self._stage(), livrable)
        self.assertFalse(res["ok"])
        self.assertTrue(any("Section obligatoire absente" in e and "## Contexte" in e
                            for e in res["errors"]))

    def test_input_non_cite_dans_la_section_dediee_produit_une_erreur(self):
        livrable = self.write("livrable.md", "## Contexte\nDes propos generaux sans citation.\n")
        res = checks.run_checks(self.root, self._stage(), livrable)
        self.assertFalse(res["ok"])
        self.assertTrue(any("Input non reference dans '## Contexte'" in e
                            for e in res["errors"]))

    def test_input_bien_cite_dans_la_section_dediee_passe(self):
        livrable = self.write("livrable.md",
                              "## Contexte\nIssu de deliverables/plan/intent.md.\n")
        res = checks.run_checks(self.root, self._stage(), livrable)
        self.assertTrue(res["ok"], res["errors"])


class TestMustNotViolateScopeCasLimites(AidlcTestCase):
    """Branches d'echappement de must_not_violate_scope : entree amont absente ou sans
    item hors perimetre (ignorees), et section hors perimetre manquante en aval alors
    que l'amont en declare une (bloquant)."""

    def _stage(self, consumes):
        checks_dir = self.root / "custom-scope"
        self.write_json("custom-scope/checks.json",
                        {"must_not_violate_scope": {"section": "## Hors perimetre"}})
        return {"id": "design", "checks": "checks.json", "root": str(checks_dir),
                "consumes": consumes}

    def test_entree_amont_absente_est_ignoree(self):
        livrable = self.write("livrable.md", "## Contexte\nRien de particulier.\n")
        res = checks.run_checks(self.root, self._stage(["deliverables/plan/absent.md"]),
                                livrable)
        self.assertTrue(res["ok"])
        self.assertEqual(res["errors"], [])

    def test_entree_sans_item_hors_perimetre_est_ignoree(self):
        self.write("deliverables/plan/intent.md",
                   "## Hors perimetre\nAucun item liste ici.\n")
        livrable = self.write("livrable.md", "## Contexte\nRien de particulier.\n")
        res = checks.run_checks(
            self.root, self._stage(["deliverables/plan/intent.md"]), livrable)
        self.assertTrue(res["ok"])
        self.assertEqual(res["errors"], [])

    def test_section_hors_perimetre_manquante_en_aval_est_bloquante(self):
        self.write("deliverables/plan/intent.md",
                   "## Hors perimetre\n- Facturation a l'unite.\n")
        livrable = self.write("livrable.md",
                              "## Contexte\nAucune section hors perimetre ici.\n")
        res = checks.run_checks(
            self.root, self._stage(["deliverables/plan/intent.md"]), livrable)
        self.assertFalse(res["ok"])
        self.assertTrue(any("est obligatoire quand" in e for e in res["errors"]))


class TestHoldoutLectureImpossible(AidlcTestCase):
    """Si le checks.json devient illisible entre la lecture des regles et la relecture
    pour le holdout, l'erreur est avalee silencieusement : le holdout ne se declenche
    simplement pas plutot que de faire planter la validation."""

    def test_fichier_de_regles_devenu_illisible_neutralise_le_holdout(self):
        checks_dir = self.root / "custom-holdout"
        checks_path = self.write_json("custom-holdout/checks.json",
                                      {"checks_do_not_self_reference": True})
        stage = {"id": "design", "checks": "checks.json", "root": str(checks_dir)}
        leaked_line = '"checks_do_not_self_reference": true'
        livrable = self.write("livrable.md", f"Extrait cite : {leaked_line}\n")

        real_read_text = checks.read_text
        calls = {"n": 0}

        def flaky(path):
            if path == checks_path:
                calls["n"] += 1
                if calls["n"] > 1:
                    raise OSError("verrou simule")
            return real_read_text(path)

        with mock.patch.object(checks, "read_text", side_effect=flaky):
            res = checks.run_checks(self.root, stage, livrable)

        self.assertTrue(res["ok"])
        self.assertFalse(any("Holdout" in e for e in res["errors"]))


class TestScopeRespected(AidlcTestCase):
    """scope_respected : une ligne qui ne mentionne pas l'item ne tranche pas — seule
    une ligne qui le mentionne decide, et une marque d'exclusion la neutralise."""

    def test_une_ligne_qui_ne_mentionne_pas_l_item_laisse_decider_la_suivante(self):
        text = ("Premiere ligne neutre qui ne mentionne rien.\n"
               "Facturation a l'unite : exclu, reporte au prochain cycle.\n")
        self.assertTrue(checks.scope_respected(text, "Facturation a l'unite"))


class TestStageForFile(AidlcTestCase):
    """stage_for_file delegue entierement au registre : le noyau ne tient plus de
    liste d'etapes propre a checks.py."""

    def test_delegue_au_registre_pour_trouver_l_agent_du_fichier(self):
        intent = self.plan_intent()
        stage = checks.stage_for_file(self.root, self.pipeline, str(intent))
        self.assertEqual(stage["id"], "plan")

    def test_renvoie_none_si_aucun_agent_ne_produit_ce_fichier(self):
        self.assertIsNone(
            checks.stage_for_file(self.root, self.pipeline, str(self.root / "ailleurs.md")))
