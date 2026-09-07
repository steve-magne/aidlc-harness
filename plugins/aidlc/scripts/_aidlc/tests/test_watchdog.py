from __future__ import annotations

import json

from unittest import mock

from .harness import AidlcTestCase
from ..util import aidlc_dir
from ..watchdog import WATCHDOG_DEFAULTS
from ..watchdog import _detections
from ..watchdog import _events
from ..watchdog import _watchdog_config
from ..watchdog import _write_counts
from ..watchdog import watchdog_check
from ..watchdog import watchdog_touched

"""Watchdog : detecteurs de stagnation sur les journaux JSONL de session.

Trois detecteurs (validation_failures, write_loop, rerun_storm), chacun avec son
seuil configurable depuis pipeline.json ; les haltes alimentent la file
d'amelioration (kind: watchdog), dedoublonnees par (detector, stage, file,
session_id) ; le mode hook (`watchdog_touched`) n'interrompt jamais une session.
"""


# ------------------------------------------------------------------------ helpers
# Aucun de ces helpers n'existe dans harness.py : ils sont locaux a ce fichier.

def _jsonl(events: list) -> str:
    """Serialise une liste de dicts en corps de fichier .jsonl (une ligne par evenement,
    terminee par un retour a la ligne final)."""
    return "\n".join(json.dumps(event) for event in events) + "\n"


def _write_event(ts: str, session_id: str, file_path: str,
                 tool_name: str = "Write") -> dict:
    """Un evenement PostToolUse d'ecriture, tel que journalise par le hook."""
    return {"ts": ts, "event": "PostToolUse", "session_id": session_id,
            "payload": {"tool_name": tool_name,
                        "tool_input": {"file_path": file_path}}}


def _rerun_event(ts: str, session_id: str, stage_id: str) -> dict:
    """Un evenement UserPromptSubmit, tel que journalise a chaque relance humaine."""
    return {"ts": ts, "event": "UserPromptSubmit", "session_id": session_id,
            "stage": stage_id}


def _write_loop_events(session_id: str, file_path: str, count: int,
                       start: int = 0) -> list:
    return [_write_event(f"2026-01-01T00:00:{start + i:02d}", session_id, file_path)
            for i in range(count)]


class TestWatchdogConfig(AidlcTestCase):
    """_watchdog_config : defauts du moteur, surchargeables par pipeline.json['watchdog']."""

    def test_sans_bloc_watchdog_rend_les_defauts(self):
        self.assertEqual(_watchdog_config({}), WATCHDOG_DEFAULTS)

    def test_bloc_watchdog_none_rend_les_defauts(self):
        self.assertEqual(_watchdog_config({"watchdog": None}), WATCHDOG_DEFAULTS)

    def test_surcharge_un_seuil_entier(self):
        config = _watchdog_config({"watchdog": {"write_loop_threshold": 3}})
        self.assertEqual(config["write_loop_threshold"], 3)
        # les autres seuils restent aux defauts
        self.assertEqual(config["rerun_threshold"], WATCHDOG_DEFAULTS["rerun_threshold"])

    def test_valeur_flottante_est_convertie_en_entier(self):
        config = _watchdog_config({"watchdog": {"window": 12.9}})
        self.assertEqual(config["window"], 12)
        self.assertIsInstance(config["window"], int)

    def test_valeur_zero_est_ignoree(self):
        config = _watchdog_config({"watchdog": {"rerun_threshold": 0}})
        self.assertEqual(config["rerun_threshold"], WATCHDOG_DEFAULTS["rerun_threshold"])

    def test_valeur_negative_est_ignoree(self):
        config = _watchdog_config({"watchdog": {"validation_failures_threshold": -5}})
        self.assertEqual(config["validation_failures_threshold"],
                         WATCHDOG_DEFAULTS["validation_failures_threshold"])

    def test_valeur_non_numerique_est_ignoree(self):
        config = _watchdog_config({"watchdog": {"write_loop_threshold": "beaucoup"}})
        self.assertEqual(config["write_loop_threshold"],
                         WATCHDOG_DEFAULTS["write_loop_threshold"])

    def test_cle_inconnue_du_bloc_watchdog_est_sans_effet(self):
        config = _watchdog_config({"watchdog": {"seuil_invente": 99}})
        self.assertEqual(config, WATCHDOG_DEFAULTS)

    def test_toutes_les_cles_sont_surchargeables_ensemble(self):
        surcharge = {"validation_failures_threshold": 2, "write_loop_threshold": 3,
                    "rerun_threshold": 4, "window": 10}
        self.assertEqual(_watchdog_config({"watchdog": surcharge}), surcharge)


class TestEvents(AidlcTestCase):
    """_events : les N derniers evenements JSONL de chaque journal, fusionnes et
    tries chronologiquement."""

    def test_repertoire_logs_absent_rend_liste_vide(self):
        self.assertEqual(_events(self.root, 60), [])

    def test_repertoire_logs_vide_rend_liste_vide(self):
        (aidlc_dir(self.root) / "logs").mkdir(parents=True)
        self.assertEqual(_events(self.root, 60), [])

    def test_lignes_vides_sont_ignorees(self):
        self.write(".aidlc/logs/s1.jsonl", "\n\n" + _jsonl([_write_event(
            "2026-01-01T00:00:00", "s1", "a.md")]) + "\n\n")
        self.assertEqual(len(_events(self.root, 60)), 1)

    def test_ligne_json_invalide_est_ignoree_sans_planter(self):
        body = "pas du json {{{\n" + _jsonl([_write_event(
            "2026-01-01T00:00:00", "s1", "a.md")])
        self.write(".aidlc/logs/s1.jsonl", body)
        events = _events(self.root, 60)
        self.assertEqual(len(events), 1)

    def test_valeur_json_non_dict_est_ignoree(self):
        body = "42\n" + json.dumps(["une", "liste"]) + "\n" + _jsonl(
            [_write_event("2026-01-01T00:00:00", "s1", "a.md")])
        self.write(".aidlc/logs/s1.jsonl", body)
        events = _events(self.root, 60)
        self.assertEqual(len(events), 1)

    def test_la_fenetre_ne_garde_que_les_dernieres_lignes_du_journal(self):
        events = [{"ts": "", "n": i} for i in range(5)]
        self.write(".aidlc/logs/s1.jsonl", _jsonl(events))
        kept = _events(self.root, 2)
        self.assertEqual([e["n"] for e in kept], [3, 4])

    def test_plusieurs_journaux_sont_fusionnes_et_tries_par_ts(self):
        self.write(".aidlc/logs/a.jsonl", _jsonl([
            {"ts": "2026-01-01T00:00:03", "who": "a-tard"},
            {"ts": "2026-01-01T00:00:01", "who": "a-tot"},
        ]))
        self.write(".aidlc/logs/b.jsonl", _jsonl([
            {"ts": "2026-01-01T00:00:02", "who": "b-milieu"},
        ]))
        ordered = [e["who"] for e in _events(self.root, 60)]
        self.assertEqual(ordered, ["a-tot", "b-milieu", "a-tard"])

    def test_evenement_sans_ts_est_trie_en_premier(self):
        self.write(".aidlc/logs/s1.jsonl", _jsonl([
            {"ts": "2026-01-01T00:00:00", "who": "avec-ts"},
            {"who": "sans-ts"},
        ]))
        ordered = [e["who"] for e in _events(self.root, 60)]
        self.assertEqual(ordered[0], "sans-ts")


class TestWriteCounts(AidlcTestCase):
    """_write_counts : ecritures groupees par (session, fichier) et par fichier,
    d'apres les evenements PostToolUse Write/Edit/MultiEdit."""

    def test_compte_par_paire_et_par_fichier(self):
        events = (_write_loop_events("s1", "a.md", 2)
                 + _write_loop_events("s2", "a.md", 1)
                 + _write_loop_events("s1", "b.md", 3))
        per_pair, per_file = _write_counts(events)
        self.assertEqual(per_pair[("s1", "a.md")], 2)
        self.assertEqual(per_pair[("s2", "a.md")], 1)
        self.assertEqual(per_pair[("s1", "b.md")], 3)
        self.assertEqual(per_file["a.md"], 3)
        self.assertEqual(per_file["b.md"], 3)

    def test_edit_et_multiedit_comptent_comme_write(self):
        events = [_write_event("2026-01-01T00:00:00", "s1", "a.md", "Edit"),
                 _write_event("2026-01-01T00:00:01", "s1", "a.md", "MultiEdit")]
        per_pair, _ = _write_counts(events)
        self.assertEqual(per_pair[("s1", "a.md")], 2)

    def test_outil_hors_ecriture_est_ignore(self):
        events = [_write_event("2026-01-01T00:00:00", "s1", "a.md", "Read"),
                 _write_event("2026-01-01T00:00:01", "s1", "a.md", "Bash")]
        per_pair, per_file = _write_counts(events)
        self.assertEqual(per_pair, {})
        self.assertEqual(per_file, {})

    def test_file_path_absent_est_ignore(self):
        events = [{"payload": {"tool_name": "Write", "tool_input": {}}}]
        per_pair, per_file = _write_counts(events)
        self.assertEqual(per_pair, {})

    def test_payload_absent_ne_plante_pas(self):
        per_pair, per_file = _write_counts([{"session_id": "s1"}])
        self.assertEqual(per_pair, {})
        self.assertEqual(per_file, {})

    def test_session_id_absent_est_regroupe_sous_point_d_interrogation(self):
        events = [{"payload": {"tool_name": "Write",
                              "tool_input": {"file_path": "a.md"}}}]
        per_pair, _ = _write_counts(events)
        self.assertEqual(per_pair[("?", "a.md")], 1)


class TestDetectionsSansEvenements(AidlcTestCase):
    def test_aucun_journal_aucune_detection(self):
        self.assertEqual(_detections(self.root, self.pipeline), [])


class TestDetectionValidationFailures(AidlcTestCase):
    """Detecteur 1 : ecritures qui s'acharnent sur un livrable encore en echec."""

    def _fail_plan(self):
        return self.write("deliverables/plan/intent.md", "pas un livrable conforme\n")

    def test_livrable_absent_aucune_detection_meme_avec_beaucoup_d_ecritures(self):
        target = str((self.root / "deliverables/plan/intent.md"))
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", target, 5)))
        detections = _detections(self.root, self.pipeline)
        self.assertFalse(any(d["detector"] == "validation_failures" for d in detections))

    def test_livrable_valide_aucune_detection(self):
        self.plan_intent()  # document conforme : validate_stage rendra ok=True
        target = str((self.root / "deliverables/plan/intent.md").resolve())
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", target, 10)))
        detections = _detections(self.root, self.pipeline)
        self.assertFalse(any(d["detector"] == "validation_failures" for d in detections))

    def test_sous_le_seuil_par_defaut_rien_ne_se_declenche(self):
        self._fail_plan()
        target = str((self.root / "deliverables/plan/intent.md").resolve())
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", target, 4)))
        detections = _detections(self.root, self.pipeline)
        self.assertFalse(any(d["detector"] == "validation_failures" for d in detections))

    def test_au_seuil_par_defaut_la_halte_tombe(self):
        self._fail_plan()
        target = str((self.root / "deliverables/plan/intent.md").resolve())
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", target, 5)))
        detections = _detections(self.root, self.pipeline)
        hits = [d for d in detections if d["detector"] == "validation_failures"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["stage"], "plan")
        self.assertEqual(hits[0]["count"], 5)
        self.assertEqual(hits[0]["threshold"], 5)

    def test_seuil_configurable_via_pipeline(self):
        self._fail_plan()
        target = str((self.root / "deliverables/plan/intent.md").resolve())
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", target, 2)))
        pipe = dict(self.pipeline)
        pipe["watchdog"] = {"validation_failures_threshold": 2}
        detections = _detections(self.root, pipe)
        self.assertTrue(any(d["detector"] == "validation_failures" for d in detections))


class TestDetectionWriteLoop(AidlcTestCase):
    """Detecteur 2 : meme session, meme fichier, au-dela du seuil — independant de
    l'etat de validation du fichier vise."""

    def test_sous_le_seuil_par_defaut_rien_ne_se_declenche(self):
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", "x.md", 5)))
        detections = _detections(self.root, self.pipeline)
        self.assertFalse(any(d["detector"] == "write_loop" for d in detections))

    def test_au_seuil_par_defaut_la_halte_tombe(self):
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", "x.md", 6)))
        detections = _detections(self.root, self.pipeline)
        hits = [d for d in detections if d["detector"] == "write_loop"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["session_id"], "s1")
        self.assertEqual(hits[0]["file"], "x.md")
        self.assertEqual(hits[0]["count"], 6)

    def test_deux_sessions_sous_le_seuil_chacune_ne_s_additionnent_pas(self):
        events = (_write_loop_events("s1", "x.md", 4)
                 + _write_loop_events("s2", "x.md", 4, start=4))
        self.write(".aidlc/logs/multi.jsonl", _jsonl(events))
        detections = _detections(self.root, self.pipeline)
        self.assertFalse(any(d["detector"] == "write_loop" for d in detections))

    def test_tri_par_nombre_d_ecritures_decroissant(self):
        events = (_write_loop_events("s1", "a.md", 8)
                 + _write_loop_events("s2", "b.md", 6, start=8))
        self.write(".aidlc/logs/multi.jsonl", _jsonl(events))
        hits = [d for d in _detections(self.root, self.pipeline)
               if d["detector"] == "write_loop"]
        self.assertEqual([h["count"] for h in hits], [8, 6])

    def test_seuil_configurable_via_pipeline(self):
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", "x.md", 3)))
        pipe = dict(self.pipeline)
        pipe["watchdog"] = {"write_loop_threshold": 3}
        detections = _detections(self.root, pipe)
        self.assertTrue(any(d["detector"] == "write_loop" for d in detections))


class TestDetectionRerunStorm(AidlcTestCase):
    """Detecteur 3 : rafale de relances humaines (UserPromptSubmit) sur la meme etape."""

    def test_sous_le_seuil_par_defaut_rien_ne_se_declenche(self):
        events = [_rerun_event(f"2026-01-01T00:00:{i:02d}", "s1", "design")
                 for i in range(4)]
        self.write(".aidlc/logs/s1.jsonl", _jsonl(events))
        detections = _detections(self.root, self.pipeline)
        self.assertFalse(any(d["detector"] == "rerun_storm" for d in detections))

    def test_au_seuil_par_defaut_la_halte_tombe(self):
        events = [_rerun_event(f"2026-01-01T00:00:{i:02d}", "s1", "design")
                 for i in range(5)]
        self.write(".aidlc/logs/s1.jsonl", _jsonl(events))
        hits = [d for d in _detections(self.root, self.pipeline)
               if d["detector"] == "rerun_storm"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["stage"], "design")
        self.assertEqual(hits[0]["count"], 5)

    def test_evenements_hors_userpromptsubmit_sont_ignores(self):
        events = [_write_event(f"2026-01-01T00:00:{i:02d}", "s1", "a.md")
                 for i in range(10)]
        self.write(".aidlc/logs/s1.jsonl", _jsonl(events))
        detections = _detections(self.root, self.pipeline)
        self.assertFalse(any(d["detector"] == "rerun_storm" for d in detections))

    def test_userpromptsubmit_sans_stage_est_ignore(self):
        events = [{"ts": f"2026-01-01T00:00:{i:02d}", "event": "UserPromptSubmit",
                  "session_id": "s1"} for i in range(10)]
        self.write(".aidlc/logs/s1.jsonl", _jsonl(events))
        detections = _detections(self.root, self.pipeline)
        self.assertFalse(any(d["detector"] == "rerun_storm" for d in detections))

    def test_tri_alphabetique_par_etape(self):
        events = ([_rerun_event(f"2026-01-01T00:00:{i:02d}", "s1", "zeta")
                  for i in range(5)]
                 + [_rerun_event(f"2026-01-01T00:01:{i:02d}", "s1", "alpha")
                    for i in range(5)])
        self.write(".aidlc/logs/s1.jsonl", _jsonl(events))
        hits = [d for d in _detections(self.root, self.pipeline)
               if d["detector"] == "rerun_storm"]
        self.assertEqual([h["stage"] for h in hits], ["alpha", "zeta"])

    def test_seuil_configurable_via_pipeline(self):
        events = [_rerun_event(f"2026-01-01T00:00:{i:02d}", "s1", "design")
                 for i in range(2)]
        self.write(".aidlc/logs/s1.jsonl", _jsonl(events))
        pipe = dict(self.pipeline)
        pipe["watchdog"] = {"rerun_threshold": 2}
        detections = _detections(self.root, pipe)
        self.assertTrue(any(d["detector"] == "rerun_storm" for d in detections))


class TestWatchdogCheck(AidlcTestCase):
    """watchdog_check : passe de diagnostic — detecte, enregistre dans la file
    d'amelioration, rapporte. Migre le scenario 35 de selftest.py."""

    def _queue_text(self) -> str:
        path = aidlc_dir(self.root) / "improvement-queue.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_sans_detection_halted_faux_et_file_vide(self):
        result = watchdog_check(self.root, self.pipeline)
        self.assertFalse(result["halted"])
        self.assertEqual(result["detections"], [])
        self.assertTrue(result["watchdog"])
        self.assertIn("generated_at", result)
        self.assertEqual(self._queue_text(), "")

    def test_acharnement_et_boucle_d_ecriture_ensemble(self):
        """Scenario migre : un meme fichier design en echec de validation, ecrit 6
        fois par la meme session, declenche a la fois validation_failures et
        write_loop, et alimente la file d'amelioration avec au moins deux entrees."""
        self.plan_intent()
        spec = self.write("deliverables/design/spec.md", "pas un livrable conforme\n")
        target = str(spec.resolve())
        self.write(".aidlc/logs/sess-watch.jsonl",
                  _jsonl(_write_loop_events("sess-watch", target, 6)))
        result = watchdog_check(self.root, self.pipeline)
        self.assertTrue(result["halted"])
        detectors = {d["detector"] for d in result["detections"]}
        self.assertEqual(detectors, {"validation_failures", "write_loop"})
        queue_text = self._queue_text()
        self.assertGreaterEqual(queue_text.count('"kind": "watchdog"'), 2)

    def test_rejoue_ne_duplique_pas_dans_la_file(self):
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", "x.md", 6)))
        watchdog_check(self.root, self.pipeline)
        premier_compte = self._queue_text().count('"kind": "watchdog"')
        self.assertEqual(premier_compte, 1)
        # rejoue avec exactement le meme detecteur/fichier/session : deduplique
        watchdog_check(self.root, self.pipeline)
        self.assertEqual(self._queue_text().count('"kind": "watchdog"'), premier_compte)

    def test_rejoue_avec_plus_d_ecritures_ne_met_pas_a_jour_le_compte_enregistre(self):
        """Le dedoublonnage porte sur (detector, stage, file, session_id), pas sur le
        compte : une seconde passe avec plus d'ecritures ne remplace pas l'entree deja
        en file, elle reste au compte de la premiere detection."""
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", "x.md", 6)))
        watchdog_check(self.root, self.pipeline)
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", "x.md", 9)))
        watchdog_check(self.root, self.pipeline)
        lines = [json.loads(line) for line in self._queue_text().splitlines() if line]
        write_loop_entries = [e for e in lines if e.get("detector") == "write_loop"]
        self.assertEqual(len(write_loop_entries), 1)
        self.assertEqual(write_loop_entries[0]["count"], 6)

    def test_detections_distinctes_produisent_des_entrees_distinctes(self):
        events = (_write_loop_events("s1", "a.md", 6)
                 + _write_loop_events("s2", "b.md", 6, start=6))
        self.write(".aidlc/logs/multi.jsonl", _jsonl(events))
        watchdog_check(self.root, self.pipeline)
        self.assertEqual(self._queue_text().count('"kind": "watchdog"'), 2)

    def test_session_id_du_detecteur_write_loop_prime_sur_celui_de_l_appel(self):
        """Le detecteur write_loop porte sa propre session (celle qui a ecrit en
        boucle) : elle ecrase le session_id passe a watchdog_check dans l'entree
        enregistree, puisque `item.update(detection)` applique la cle du detecteur."""
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", "x.md", 6)))
        watchdog_check(self.root, self.pipeline, session_id="session-appelante")
        lines = [json.loads(line) for line in self._queue_text().splitlines() if line]
        self.assertEqual(lines[0]["session_id"], "s1")

    def test_session_id_de_l_appel_sert_pour_les_detecteurs_sans_session_propre(self):
        """rerun_storm ne porte pas de session dans sa detection : l'entree en file
        garde alors le session_id transmis a watchdog_check."""
        events = [_rerun_event(f"2026-01-01T00:00:{i:02d}", "s1", "design")
                 for i in range(5)]
        self.write(".aidlc/logs/s1.jsonl", _jsonl(events))
        watchdog_check(self.root, self.pipeline, session_id="session-appelante")
        lines = [json.loads(line) for line in self._queue_text().splitlines() if line]
        rerun_entries = [e for e in lines if e.get("detector") == "rerun_storm"]
        self.assertEqual(rerun_entries[0]["session_id"], "session-appelante")


class TestWatchdogTouched(AidlcTestCase):
    """watchdog_touched : mode hook PostToolUse, jamais bloquant."""

    def _queue_text(self) -> str:
        path = aidlc_dir(self.root) / "improvement-queue.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_muet_et_sans_ecriture_sans_detection(self):
        result = watchdog_touched(self.root, self.pipeline, {"session_id": "s1"})
        self.assertIsNone(result)
        self.assertEqual(self._queue_text(), "")

    def test_enregistre_une_halte_sans_jamais_lever(self):
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", "x.md", 6)))
        watchdog_touched(self.root, self.pipeline, {"session_id": "s1"})
        self.assertIn('"kind": "watchdog"', self._queue_text())

    def test_session_id_absent_du_payload_n_empeche_pas_la_detection(self):
        """Le detecteur write_loop porte sa propre session_id (celle qui a ecrit en
        boucle) : elle ecrase toujours celle deduite du payload, donc ce cas ne peut
        pas a lui seul montrer qu'un payload sans session_id produit None -- on
        verifie ici seulement que l'appel n'a pas leve et a bien enregistre la halte.
        Voir test_session_id_absent_du_payload_devient_none_sans_session_propre pour
        la verification reelle du None."""
        self.write(".aidlc/logs/s1.jsonl",
                  _jsonl(_write_loop_events("s1", "x.md", 6)))
        watchdog_touched(self.root, self.pipeline, {})
        lines = [json.loads(line) for line in self._queue_text().splitlines() if line]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["detector"], "write_loop")
        self.assertEqual(lines[0]["session_id"], "s1")

    def test_session_id_absent_du_payload_devient_none_sans_session_propre(self):
        """rerun_storm ne porte pas de session dans sa detection : avec un payload
        sans session_id du tout, l'entree enregistree en file porte bien None (pas
        une chaine vide, pas une cle absente)."""
        events = [_rerun_event(f"2026-01-01T00:00:{i:02d}", "s1", "design")
                 for i in range(5)]
        self.write(".aidlc/logs/s1.jsonl", _jsonl(events))
        watchdog_touched(self.root, self.pipeline, {})
        lines = [json.loads(line) for line in self._queue_text().splitlines() if line]
        rerun_entries = [e for e in lines if e.get("detector") == "rerun_storm"]
        self.assertEqual(len(rerun_entries), 1)
        self.assertIsNone(rerun_entries[0]["session_id"])

    def test_exception_interne_est_avalee(self):
        """Un watchdog qui casse une session vaut moins que pas de watchdog : toute
        exception levee pendant la detection est silencieusement ignoree."""
        with mock.patch("_aidlc.watchdog._detections", side_effect=RuntimeError("boom")):
            result = watchdog_touched(self.root, self.pipeline, {"session_id": "s1"})
        self.assertIsNone(result)
        self.assertEqual(self._queue_text(), "")
