from __future__ import annotations

import json
import tempfile

from pathlib import Path
from unittest import mock

from .harness import AidlcTestCase
from .harness import GOOD_SECTIONS
from .harness import document
from .harness import manifest
from .. import hookslog
from .. import registry
from ..commands import cmd_guard
from ..commands import cmd_log
from ..maturity import maturity_path
from ..util import MAX_FIELD
from ..util import aidlc_dir

"""Journalisation JSONL (handle_log, journal_bundle_write) et garde-fou d'ecriture
PreToolUse (guard_decision) : le module ne doit jamais lever, meme sur une entree
hostile ou malformee, et doit deviner l'etape en jeu par le chemin de fichier, jamais
en fouillant la prose d'un prompt."""


# --------------------------------------------------------------- current_stage_id

class TestCurrentStageId(AidlcTestCase):
    """L'etape courante : la premiere qui n'a pas encore de livrable valide."""

    def test_repere_la_premiere_etape_dont_le_livrable_est_absent(self):
        self.assertEqual(hookslog.current_stage_id(self.root, self.pipeline), "plan")

    def test_repere_l_etape_dont_le_livrable_echoue_la_validation(self):
        self.plan_intent()
        self.write("deliverables/design/spec.md", "un contenu invalide, sans forme.")
        self.assertEqual(hookslog.current_stage_id(self.root, self.pipeline), "design")

    def test_rend_la_derniere_etape_quand_toutes_sont_validees(self):
        self.plan_intent()
        self.write("deliverables/design/spec.md", document(
            sections={"## Contexte": "Conception basee sur deliverables/plan/intent.md, "
                                     "avec assez de details pour etre utile a l'equipe."},
            front={"stage": "design", "version": "1", "status": "draft",
                   "author": "Steve", "date": "2026-09-03"}))
        self.assertEqual(hookslog.current_stage_id(self.root, self.pipeline), "design")

    def test_absorbe_une_exception_du_registre(self):
        with mock.patch.object(registry, "stages", side_effect=RuntimeError("boom")):
            self.assertIsNone(hookslog.current_stage_id(self.root, self.pipeline))


class TestCurrentStageIdSansAgent(AidlcTestCase):
    """Sans aucun agent gouverne, il n'y a aucune etape courante a designer."""

    seed_agents = False

    def test_rend_none_sans_aucun_agent_gouverne(self):
        self.assertIsNone(hookslog.current_stage_id(self.root, self.pipeline))


# -------------------------------------------------------------- stage_from_payload

class TestStageFromPayload(AidlcTestCase):
    """L'etape portee par l'evenement lui-meme : le chemin de fichier qu'il touche."""

    def test_rend_none_sans_aucun_chemin_dans_la_charge(self):
        self.assertIsNone(hookslog.stage_from_payload(self.root, {}))

    def test_associe_le_chemin_exact_d_un_livrable_a_son_agent(self):
        intent = self.plan_intent()
        data = {"tool_input": {"file_path": str(intent)}}
        self.assertEqual(hookslog.stage_from_payload(self.root, data), "plan")

    def test_accepte_un_chemin_porte_par_notebook_path(self):
        intent = self.plan_intent()
        data = {"tool_input": {"notebook_path": str(intent)}}
        self.assertEqual(hookslog.stage_from_payload(self.root, data), "plan")

    def test_associe_une_annexe_du_repertoire_du_livrable_a_son_agent(self):
        annexe = self.write("deliverables/plan/annexe.md", "annexe")
        data = {"tool_input": {"file_path": str(annexe)}}
        self.assertEqual(hookslog.stage_from_payload(self.root, data), "plan")

    def test_rend_none_pour_un_fichier_hors_de_tout_livrable(self):
        ailleurs = self.write("ailleurs.md", "rien a voir")
        data = {"tool_input": {"file_path": str(ailleurs)}}
        self.assertIsNone(hookslog.stage_from_payload(self.root, data))

    def test_absorbe_une_erreur_os_de_resolution_de_chemin(self):
        data = {"tool_input": {"file_path": "quelque/chose"}}
        with mock.patch.object(Path, "resolve", autospec=True, side_effect=OSError("boom")):
            self.assertIsNone(hookslog.stage_from_payload(self.root, data))


# ---------------------------------------------------------------- last_known_stage

class TestLastKnownStage(AidlcTestCase):
    """Continuite d'etape au sein d'une meme session, relue depuis la queue du journal."""

    def test_rend_none_si_le_journal_de_la_session_n_existe_pas(self):
        self.assertIsNone(hookslog.last_known_stage(self.root, "jamais-vue"))

    def test_retrouve_la_derniere_etape_malgre_une_ligne_de_journal_corrompue(self):
        self.write(".aidlc/logs/sess-1.jsonl",
                  json.dumps({"stage": "plan"}) + "\n"
                  + "pas du json valide\n")
        self.assertEqual(hookslog.last_known_stage(self.root, "sess-1"), "plan")

    def test_rend_none_si_aucune_ligne_ne_porte_d_etape(self):
        self.write(".aidlc/logs/sess-2.jsonl",
                  "pas du json valide\n"
                  + json.dumps({"stage": None}) + "\n"
                  + json.dumps({"event": "UserPromptSubmit"}) + "\n")
        self.assertIsNone(hookslog.last_known_stage(self.root, "sess-2"))


# --------------------------------------------------------------------- guess_stage

class TestGuessStage(AidlcTestCase):
    """Fiabilite decroissante : chemin de l'evenement, puis session, puis pipeline."""

    def test_absorbe_une_exception(self):
        with mock.patch.object(hookslog, "stage_from_payload",
                               side_effect=RuntimeError("boom")):
            self.assertIsNone(
                hookslog.guess_stage(self.root, self.pipeline, {}, "sess-x"))


# ------------------------------------------------------------------------ handle_log

class TestHandleLog(AidlcTestCase):
    """Journalisation JSONL qui ne casse jamais et devine l'etape par le chemin, jamais
    en fouillant la prose du prompt (scenarios 15 et 15bis de l'ancien selftest)."""

    def setUp(self):
        super().setUp()
        self.intent = self.plan_intent()

    def _write_event(self, session_id="sess-1", **extra):
        payload = {"session_id": session_id, "hook_event_name": "PostToolUse"}
        payload.update(extra)
        return hookslog.handle_log(self.root, json.dumps(payload))

    def test_le_session_id_doit_etre_assaini(self):
        entry = self._write_event(session_id="abc/../123",
                                  tool_name="Write",
                                  tool_input={"file_path": str(self.intent)})
        self.assertEqual(entry["session_id"], "abc____123")

    def test_le_stage_doit_etre_devine_depuis_le_chemin(self):
        entry = self._write_event(tool_name="Write",
                                  tool_input={"file_path": str(self.intent)})
        self.assertEqual(entry["stage"], "plan")

    def test_les_gros_champs_doivent_etre_tronques(self):
        entry = self._write_event(tool_name="Write", prompt="x" * 5000,
                                  tool_input={"file_path": str(self.intent)})
        self.assertLessEqual(len(entry["payload"]["prompt"]), MAX_FIELD + 20)

    def test_le_contenu_ecrit_n_entre_jamais_dans_le_journal(self):
        # Le journal est relu par fenetre (LOG_TAIL_BYTES) : y recopier le contenu des
        # fichiers ecrits la consommerait en quelques evenements, et mettrait le travail
        # en clair dans .aidlc/logs/. Seuls les chemins sont relus.
        entry = self._write_event(tool_name="Write",
                                  tool_input={"file_path": str(self.intent),
                                              "content": "secret" * 500})
        self.assertEqual(entry["payload"]["tool_input"], {"file_path": str(self.intent)})

    def test_le_chemin_d_un_notebook_est_conserve(self):
        entry = self._write_event(tool_name="Write",
                                  tool_input={"notebook_path": str(self.intent),
                                              "new_source": "du code"})
        self.assertEqual(entry["payload"]["tool_input"],
                         {"notebook_path": str(self.intent)})

    def test_un_tool_input_non_dictionnaire_est_laisse_tel_quel(self):
        entry = self._write_event(tool_name="Bash", tool_input="ls -la")
        self.assertEqual(entry["payload"]["tool_input"], "ls -la")

    def test_le_motif_d_une_notification_est_journalise(self):
        # Sans `notification_type`, une permission demandee et une session inactive se
        # ressemblent dans le journal — or l'une dit le cout du procede, pas l'autre.
        entry = self._write_event(hook_event_name="Notification",
                                  notification_type="permission_prompt")
        self.assertEqual(entry["payload"]["notification_type"], "permission_prompt")

    def test_l_erreur_d_un_outil_est_journalisee(self):
        entry = self._write_event(hook_event_name="PostToolUseFailure",
                                  tool_name="Write", tool_error="permission refusee")
        self.assertEqual(entry["payload"]["tool_error"], "permission refusee")

    def test_la_sortie_d_un_outil_n_est_jamais_journalisee(self):
        # `tool_output` est le plus gros champ du payload (un Read entier) et aucun
        # diagnostic ne le relit : le journaliser gonflerait la fenetre pour rien.
        entry = self._write_event(tool_name="Read", tool_output="x" * 5000)
        self.assertNotIn("tool_output", entry["payload"])

    def test_accepte_un_session_id_non_textuel(self):
        entry = self._write_event(session_id=42)
        self.assertEqual(entry["session_id"], "42")

    def test_log_sort_zero_sur_une_entree_vide(self):
        self.assertEqual(cmd_log(self.root, ""), 0)

    def test_log_sort_zero_sur_du_json_invalide(self):
        self.assertEqual(cmd_log(self.root, "pas du json {{{"), 0)

    def test_log_sort_zero_sur_une_liste_json(self):
        self.assertEqual(cmd_log(self.root, json.dumps([1, 2, 3])), 0)

    def test_log_sort_zero_sur_un_dict_json_minimal(self):
        self.assertEqual(cmd_log(self.root, json.dumps({"a": 1})), 0)

    def test_prerequis_l_etape_courante_est_design_une_fois_plan_franchie(self):
        self.assertEqual(hookslog.current_stage_id(self.root, self.pipeline), "design")

    def test_un_prompt_qui_nomme_une_etape_dans_sa_prose_ne_la_designe_pas(self):
        prose = self._write_event(
            session_id="sess-prose", hook_event_name="UserPromptSubmit",
            prompt="revois le plan de charge, puis lance les test unitaires")
        self.assertEqual(prose["stage"], "design")

    def test_une_ecriture_dans_le_repertoire_d_un_livrable_revient_a_son_agent(self):
        annexe = self.write("deliverables/plan/annexe.md", "annexe")
        near = self._write_event(session_id="sess-annexe", tool_name="Write",
                                 tool_input={"file_path": str(annexe)})
        self.assertEqual(near["stage"], "plan")

    def test_un_evenement_sans_chemin_herite_de_la_derniere_etape_de_sa_session(self):
        self._write_event(session_id="sess-suite", tool_name="Write",
                          tool_input={"file_path": str(self.intent)})
        suite = self._write_event(session_id="sess-suite",
                                  hook_event_name="UserPromptSubmit", prompt="continue")
        self.assertEqual(suite["stage"], "plan")

    def test_la_continuite_ne_franchit_pas_les_sessions(self):
        self._write_event(session_id="sess-suite-2", tool_name="Write",
                          tool_input={"file_path": str(self.intent)})
        autre = self._write_event(session_id="sess-neuve",
                                  hook_event_name="UserPromptSubmit", prompt="continue")
        self.assertEqual(autre["stage"], "design")

    def test_illisible_le_pipeline_replie_sur_une_liste_d_etapes_vide(self):
        (self.root / "pipeline.json").unlink()
        entry = self._write_event(tool_name="Write",
                                  tool_input={"file_path": str(self.intent)})
        self.assertEqual(entry["stage"], "plan")


# ---------------------------------------------------------------- journal_bundle_write

class TestJournalBundleWrite(AidlcTestCase):
    """Journalise l'ecriture fautive dans un bundle OKF, dedoublonnee par session et
    par fichier (scenario 27 de l'ancien selftest)."""

    def test_une_ecriture_repetee_dans_la_meme_session_ne_produit_qu_une_entree(self):
        target = self.write("knowledge/sans-frontmatter.md", "sans frontmatter")
        hookslog.journal_bundle_write(self.root, "sess-ecrivain", target, "Write")
        hookslog.journal_bundle_write(self.root, "sess-ecrivain", target, "Write")
        log = self.read(".aidlc/logs/sess-ecrivain.jsonl")
        self.assertEqual(log.count("PostToolUse"), 1)

    def test_l_entree_journalisee_nomme_le_fichier_fautif(self):
        target = self.write("knowledge/sans-frontmatter.md", "sans frontmatter")
        hookslog.journal_bundle_write(self.root, "sess-ecrivain", target, "Write")
        log = self.read(".aidlc/logs/sess-ecrivain.jsonl")
        self.assertIn("sans-frontmatter.md", log)

    def test_aucune_ecriture_sans_session_id(self):
        target = self.write("knowledge/x.md", "x")
        hookslog.journal_bundle_write(self.root, None, target, "Write")
        self.assertFalse((self.root / ".aidlc" / "logs").exists())

    def test_absorbe_une_erreur_de_resolution_du_fichier_cible(self):
        target = self.root / "knowledge" / "y.md"
        with mock.patch.object(Path, "resolve", autospec=True, side_effect=OSError("boom")):
            hookslog.journal_bundle_write(self.root, "sess-y", target, "Write")
        self.assertFalse((self.root / ".aidlc" / "logs").exists())

    def test_ignore_une_ligne_de_journal_illisible_et_ecrit_quand_meme(self):
        target = self.write("knowledge/note.md", "note")
        self.write(".aidlc/logs/sess-bad.jsonl", "pas du json\n")
        hookslog.journal_bundle_write(self.root, "sess-bad", target, "Write")
        log = self.read(".aidlc/logs/sess-bad.jsonl")
        self.assertEqual(log.count("note.md"), 1)

    def test_ignore_une_entree_ecrite_par_un_autre_outil(self):
        target = self.write("knowledge/note2.md", "note")
        self.write(".aidlc/logs/sess-skip.jsonl", json.dumps(
            {"payload": {"tool_name": "Read",
                        "tool_input": {"file_path": str(target)}}}) + "\n")
        hookslog.journal_bundle_write(self.root, "sess-skip", target, "Write")
        log = self.read(".aidlc/logs/sess-skip.jsonl")
        self.assertEqual(log.count("PostToolUse"), 1)

    def test_ignore_une_entree_sans_chemin_de_fichier(self):
        target = self.write("knowledge/note3.md", "note")
        self.write(".aidlc/logs/sess-skip2.jsonl", json.dumps(
            {"payload": {"tool_name": "Write", "tool_input": {}}}) + "\n")
        hookslog.journal_bundle_write(self.root, "sess-skip2", target, "Write")
        log = self.read(".aidlc/logs/sess-skip2.jsonl")
        self.assertEqual(log.count("PostToolUse"), 1)

    def test_dedouble_via_normpath_si_la_resolution_du_chemin_journalise_echoue(self):
        target = self.root / "knowledge" / "dup.md"
        (target.parent).mkdir(parents=True, exist_ok=True)
        target.write_text("dup", encoding="utf-8")
        self.write(".aidlc/logs/sess-dup.jsonl", json.dumps(
            {"payload": {"tool_name": "Write",
                        "tool_input": {"file_path": str(target)}}}) + "\n")
        original_resolve = Path.resolve

        def fake_resolve(self_path, *a, **kw):
            if self_path is target:
                return original_resolve(self_path, *a, **kw)
            raise OSError("boom")

        with mock.patch.object(Path, "resolve", autospec=True, side_effect=fake_resolve):
            hookslog.journal_bundle_write(self.root, "sess-dup", target, "Write")
        log = self.read(".aidlc/logs/sess-dup.jsonl")
        self.assertEqual(log.count("PostToolUse"), 0)


# ------------------------------------------------------------------- guard_decision

class TestGuardDecision(AidlcTestCase):
    """Le garde-fou PreToolUse refuse d'ecrire dans les artefacts de score et dans la
    copie installee du harnais, et laisse passer le reste (scenarios 16 et 33)."""

    def setUp(self):
        super().setUp()
        self.intent = self.plan_intent()

    def _reason(self, tool_name, file_path):
        return hookslog.guard_decision(self.root, json.dumps(
            {"tool_name": tool_name, "tool_input": {"file_path": str(file_path)}}))

    def test_refuse_l_ecriture_de_maturity_json(self):
        self.assertIsNotNone(self._reason("Write", maturity_path(self.root)))

    def test_refuse_l_edition_d_une_revue_humaine(self):
        reason = self._reason("Edit", aidlc_dir(self.root) / "reviews" / "plan-1.json")
        self.assertIsNotNone(reason)

    def test_laisse_passer_un_livrable_normal(self):
        self.assertIsNone(self._reason("Write", self.intent))

    def test_guard_sort_zero_sur_une_entree_cassee(self):
        self.assertEqual(cmd_guard(self.root, "pas du json"), 0)

    def test_refuse_l_ecriture_directe_du_ratchet(self):
        reason = self._reason("Write", aidlc_dir(self.root) / "ratchet.json")
        self.assertIsNotNone(reason)
        self.assertIn("ratchet", reason)

    def test_refuse_l_edition_de_la_file_d_amelioration(self):
        reason = self._reason("Edit", aidlc_dir(self.root) / "improvement-queue.jsonl")
        self.assertIsNotNone(reason)
        self.assertIn("amelioration", reason)

    def test_refuse_l_edition_du_registre_des_experiences(self):
        reason = self._reason("Write", aidlc_dir(self.root) / "experiments.jsonl")
        self.assertIsNotNone(reason)
        self.assertIn("experiment record", reason)

    def test_refuse_l_edition_des_journaux_de_session(self):
        reason = self._reason("Write", aidlc_dir(self.root) / "logs" / "x.jsonl")
        self.assertIsNotNone(reason)
        self.assertIn("journaux", reason)

    def test_le_depot_auteur_reste_editable(self):
        # Les deux racines confondues : editer pipeline.json reste possible.
        self.assertIsNone(self._reason("Write", self.root / "pipeline.json"))

    def test_refuse_l_edition_de_la_copie_installee_depuis_un_consommateur(self):
        consumer = self.root / "consumer-guard"
        consumer.mkdir()
        reason = hookslog.guard_decision(consumer, json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(self.root / "pipeline.json")}}))
        self.assertIsNotNone(reason)
        self.assertIn("liste protégée", reason)

    def test_ne_bloque_pas_les_livrables_du_projet_consommateur(self):
        consumer = self.root / "consumer-guard-2"
        consumer.mkdir()
        reason = hookslog.guard_decision(consumer, json.dumps(
            {"tool_name": "Write",
             "tool_input": {"file_path": str(consumer / "deliverables" / "x.md")}}))
        self.assertIsNone(reason)

    def test_ignore_une_charge_utile_qui_n_est_pas_un_objet(self):
        self.assertIsNone(hookslog.guard_decision(self.root, json.dumps([1, 2, 3])))

    def test_ignore_une_absence_de_chemin_cible(self):
        reason = hookslog.guard_decision(self.root, json.dumps(
            {"tool_name": "Write", "tool_input": {}}))
        self.assertIsNone(reason)

    def test_absorbe_une_erreur_de_resolution_de_chemin(self):
        raw = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "quelque/chose"}})
        with mock.patch.object(Path, "resolve", autospec=True, side_effect=OSError("boom")):
            self.assertIsNone(hookslog.guard_decision(self.root, raw))

    def test_refuse_l_ecriture_dans_le_plugin_d_un_agent_externe(self):
        """Chaine complete de guard_decision jusqu'a _agent_protection_reason : une
        cible hors du projet ET hors du harnais (donc ni protection .aidlc/ ni
        protection du harnais ne s'applique), qui correspond au plugin d'un agent
        d'une autre equipe, est refusee et nomme l'agent et son equipe."""
        with tempfile.TemporaryDirectory() as external_dir:
            external = Path(external_dir)
            self.write_agent(
                "acme-security",
                manifest("security-review", "AppSec",
                        capabilities=["security:review"],
                        invocation={"claude-code": "acme-security:security-review"}),
                checks=None, base=external)
            self.agent_path(self.root / "plugins", external)
            cible = external / "acme-security" / "SKILL.md"
            reason = hookslog.guard_decision(self.root, json.dumps(
                {"tool_name": "Write", "tool_input": {"file_path": str(cible)}}))
            self.assertIsNotNone(reason)
            self.assertIn("security-review", reason)
            self.assertIn("AppSec", reason)


# ------------------------------------------------------------ _aidlc_protection_reason

class TestAidlcProtectionReason(AidlcTestCase):
    """Cible directement le sous-motif .aidlc/ : seuls les artefacts nommes sont
    proteges, le reste du repertoire runtime reste libre."""

    def test_laisse_passer_un_fichier_aidlc_non_protege(self):
        target = (aidlc_dir(self.root) / "cache" / "misc.txt").resolve()
        self.assertIsNone(hookslog._aidlc_protection_reason(self.root, target))


# ------------------------------------------------------------- _agent_protection_reason

class TestAgentProtectionReason(AidlcTestCase):
    """Le plugin d'un agent d'une autre equipe, hors du projet, est protege ; une cible
    qui ne correspond a aucun agent externe ne doit jamais bloquer."""

    def test_ignore_les_agents_dont_le_chemin_ne_correspond_pas(self):
        with tempfile.TemporaryDirectory() as external_dir:
            external = Path(external_dir)
            self.write_agent(
                "acme-security",
                manifest("security-review", "AppSec",
                        capabilities=["security:review"],
                        invocation={"claude-code": "acme-security:security-review"}),
                checks=None, base=external)
            self.agent_path(self.root / "plugins", external)
            autre = (external / "not-this-agent" / "x.md").resolve()
            self.assertIsNone(hookslog._agent_protection_reason(autre))

    def test_absorbe_une_exception_du_registre(self):
        with mock.patch.object(registry, "agents_list", side_effect=RuntimeError("boom")):
            self.assertIsNone(hookslog._agent_protection_reason(self.root / "x"))


class TestDeliverableProtectionReason(AidlcTestCase):
    """Le livrable d'un agent appartient a cet agent : un sous-agent nomme n'ecrit pas
    le `produces` d'un voisin. Sans identite dans le payload, rien ne bloque."""

    def _reason(self, file_path, **payload):
        return hookslog.guard_decision(self.root, json.dumps(
            dict({"tool_name": "Write",
                  "tool_input": {"file_path": str(file_path)}}, **payload)))

    def test_refuse_a_design_d_ecrire_le_livrable_de_plan(self):
        reason = self._reason(self.root / "deliverables" / "plan" / "intent.md",
                              agent_type="aidlc-design:design")
        self.assertIsNotNone(reason)
        self.assertIn("plan", reason)

    def test_le_refus_nomme_l_equipe_proprietaire(self):
        reason = self._reason(self.root / "deliverables" / "plan" / "intent.md",
                              agent_type="aidlc-design:design")
        self.assertIn("Produit", reason)

    def test_laisse_un_agent_ecrire_son_propre_livrable(self):
        self.assertIsNone(self._reason(self.root / "deliverables" / "plan" / "intent.md",
                                       agent_type="aidlc-plan:plan"))

    def test_l_identite_est_reconnue_par_l_id_nu(self):
        # Une plateforme qui nommerait l'agent par son id, pas par son invocation.
        self.assertIsNotNone(self._reason(self.root / "deliverables" / "plan" / "intent.md",
                                          agent_type="design"))

    def test_sans_identite_dans_le_payload_rien_n_est_refuse(self):
        # Session principale : le garde-fou ne devine pas qui ecrit.
        self.assertIsNone(self._reason(self.root / "deliverables" / "plan" / "intent.md"))

    def test_un_agent_inconnu_du_registre_ne_declenche_aucun_refus(self):
        self.assertIsNone(self._reason(self.root / "deliverables" / "plan" / "intent.md",
                                       agent_type="acme-autre:inconnu"))

    def test_une_annexe_du_meme_repertoire_reste_ecrivable(self):
        # Le refus porte sur le `produces` exact, pas sur le repertoire de l'etape :
        # une note de travail voisine n'est le contrat de personne.
        self.assertIsNone(self._reason(self.root / "deliverables" / "plan" / "notes.md",
                                       agent_type="aidlc-design:design"))

    def test_un_agent_consultatif_ne_protege_aucun_chemin(self):
        self.write_agent("acme-security", manifest("security-review", "AppSec"))
        self.assertIsNone(self._reason(self.root / "deliverables" / "design" / "spec.md",
                                       agent_type="aidlc-security:security-review"))

    def test_le_champ_agent_id_vaut_identite_a_defaut_d_agent_type(self):
        self.assertIsNotNone(self._reason(self.root / "deliverables" / "plan" / "intent.md",
                                          agent_id="design"))

    def test_un_produces_au_chemin_illegal_ne_protege_rien(self):
        # Manifeste d'une equipe voisine dont le `produces` ne peut pas etre resolu :
        # il ne doit ni proteger, ni faire tomber le garde-fou pour les autres.
        self.write_agent("acme-casse",
                         manifest("casse", "Acme", "deliverables/x\x00y.md"))
        self.assertIsNone(self._reason(self.root / "deliverables" / "casse.md",
                                       agent_type="aidlc-design:design"))

    def test_absorbe_une_exception_du_registre_a_l_identification(self):
        with mock.patch.object(registry, "agents_list", side_effect=RuntimeError("boom")):
            self.assertIsNone(hookslog._actor_agent_id({"agent_type": "design"}))
