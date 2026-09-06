from __future__ import annotations

import json
import os

from unittest import mock

from .harness import AidlcTestCase
from .harness import document
from .harness import manifest
from .. import cli
from .. import tests as tests_module

"""Contrat public de aidlc.py : ce que consomment les hooks et les skills, teste en
sous-processus via self.run_cli(...). On ne reteste pas ici la logique metier de
chaque commande (deja couverte module par module) : on verifie que le parseur et la
bascule (cli.py) exposent chaque sous-commande, respectent les codes de sortie promis,
separent stdout (machine) de stderr (humain), et attrapent les exceptions d'IO/JSON
qui remontent d'un handler."""


class TestAbsenceDeCommande(AidlcTestCase):
    """Sans sous-commande, l'aide est un message pour un humain, pas un flux machine."""

    def test_sans_commande_l_aide_part_sur_stderr(self):
        result = self.run_cli()
        self.assertIn("usage", result.stderr.lower())

    def test_sans_commande_stdout_reste_vide(self):
        result = self.run_cli()
        self.assertEqual(result.stdout, "")

    def test_sans_commande_le_code_de_sortie_est_un(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)


class TestCommandeInconnue(AidlcTestCase):
    """argparse refuse une sous-commande qui n'existe pas avant meme d'atteindre main()."""

    def test_commande_inconnue_echoue(self):
        result = self.run_cli("nimportequoi")
        self.assertNotEqual(result.returncode, 0)

    def test_commande_inconnue_message_sur_stderr(self):
        result = self.run_cli("nimportequoi")
        self.assertIn("invalid choice", result.stderr.lower())


class TestOptionSelftest(AidlcTestCase):
    """--selftest est l'alias historique de `test` : c'est ce que la CI, les hooks et
    les consommateurs appellent depuis toujours. On verifie qu'il ROUTE vers la suite,
    on ne la relance pas — la suite qui se relance elle-meme ne termine jamais. Le
    runner porte un garde-fou de reentrance pour la meme raison ; il est teste ici.
    """

    def test_selftest_route_vers_le_runner_de_la_suite(self):
        with mock.patch("_aidlc.cli.tests_run", return_value=0) as runner:
            code = cli.main(["--selftest"])
        self.assertEqual(code, 0)
        runner.assert_called_once_with()

    def test_selftest_propage_l_echec_de_la_suite(self):
        with mock.patch("_aidlc.cli.tests_run", return_value=1):
            self.assertEqual(cli.main(["--selftest"]), 1)

    def test_selftest_court_circuite_les_sous_commandes(self):
        """Meme accompagne d'une sous-commande, --selftest gagne et rien d'autre ne
        s'execute : c'est ce qui rend l'alias sur pour les hooks."""
        with mock.patch("_aidlc.cli.tests_run", return_value=0) as runner, \
                mock.patch("_aidlc.cli.cmd_status") as status:
            cli.main(["--selftest", "status"])
        runner.assert_called_once_with()
        status.assert_not_called()

    def test_une_suite_imbriquee_est_refusee_et_non_executee(self):
        """Le garde-fou : un sous-processus lance depuis la suite n'a pas le droit de
        relancer la suite. Sans lui, `aidlc.py test` recurse a l'infini. On arme le
        verrou explicitement plutot que de dependre de la facon dont la suite courante
        a ete lancee — le test doit valoir aussi sous `python3 -m unittest`."""
        with mock.patch.dict(os.environ, {tests_module._REENTRANCY: "1"}):
            result = self.run_cli("test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("imbriquee ignoree", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_le_garde_fou_est_leve_hors_suite(self):
        """Hors execution de suite, la variable de reentrance n'existe pas : le verrou
        ne fuit jamais dans l'environnement de l'appelant."""
        from _aidlc.tests import _REENTRANCY
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_REENTRANCY, None)
            with mock.patch("_aidlc.tests._run", return_value=0) as inner:
                self.assertEqual(tests_module.run(), 0)
            inner.assert_called_once()
            self.assertNotIn(_REENTRANCY, os.environ)


class TestCommandeLog(AidlcTestCase):
    """log est lu sur stdin (jamais un argument) et journalise l'evenement du hook."""

    def test_log_accepte_un_payload_valide_et_journalise(self):
        payload = json.dumps({"session_id": "abc123", "hook_event_name": "SessionStart"})
        result = self.run_cli("log", stdin=payload)
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.root / ".aidlc/logs/abc123.jsonl").exists())

    def test_log_ne_casse_jamais_sur_un_payload_illisible(self):
        result = self.run_cli("log", stdin="{ceci n'est pas du json")
        self.assertEqual(result.returncode, 0)

    def test_log_ne_produit_rien_sur_stdout(self):
        result = self.run_cli("log", stdin="{}")
        self.assertEqual(result.stdout, "")


class TestCommandeGuard(AidlcTestCase):
    """guard est lu sur stdin et decide (JSON hookSpecificOutput) sans jamais lever."""

    def test_guard_refuse_une_ecriture_dans_aidlc(self):
        cible = self.root / ".aidlc" / "maturity.json"
        payload = json.dumps({"tool_input": {"file_path": str(cible)}})
        result = self.run_cli("guard", stdin=payload)
        self.assertEqual(result.returncode, 0)
        data = self.assertJson(result)
        self.assertEqual(
            data["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_guard_silencieux_sur_une_ecriture_anodine(self):
        cible = self.root / "deliverables" / "plan" / "intent.md"
        payload = json.dumps({"tool_input": {"file_path": str(cible)}})
        result = self.run_cli("guard", stdin=payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_guard_ne_casse_jamais_sur_un_payload_illisible(self):
        result = self.run_cli("guard", stdin="pas du json")
        self.assertEqual(result.returncode, 0)


class TestBascculeVersLesHandlers(AidlcTestCase):
    """Chaque entree de la table `handlers` de cli.py est bien cablee vers sa commande :
    on invoque chacune une fois et on verifie qu'elle repond comme son module promet."""

    def test_validate_repond(self):
        result = self.run_cli("validate", "plan", "--json")
        self.assertEqual(result.returncode, 1)  # intent.md absent
        data = self.assertJson(result)
        self.assertFalse(data["ok"])

    def test_score_repond(self):
        review = self.write_json("review.json", {
            "stage": "plan", "approved": True, "reviewer": "Steve",
            "justification": "Conforme.",
            "scores": {"completeness": 5, "precision": 5, "traceability": 5,
                      "autonomy": 5},
        })
        result = self.run_cli("score", "plan", "--file", str(review))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertJson(result)

    def test_gate_repond_et_bloque_si_le_livrable_est_absent(self):
        result = self.run_cli("gate", "plan")
        self.assertEqual(result.returncode, 2)
        data = self.assertJson(result)
        self.assertFalse(data["passed"])

    def test_agents_repond(self):
        result = self.run_cli("agents", "--json")
        data = self.assertJson(result)
        self.assertIn("aidlc-plan"[len("aidlc-"):], [a["id"] for a in data["agents"]])

    def test_review_request_repond(self):
        result = self.run_cli("review-request", "plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertJson(result)

    def test_review_request_echoue_sur_un_agent_inconnu(self):
        result = self.run_cli("review-request", "fantome")
        self.assertEqual(result.returncode, 1)

    def test_status_repond(self):
        result = self.run_cli("status", "--json")
        self.assertEqual(result.returncode, 0)
        data = self.assertJson(result)
        self.assertIn("stages", data)

    def test_scaffold_repond(self):
        # "design" est deja un agent enregistre (fixture par defaut) ; "build" ne
        # figure que dans la feuille de route consultative (planned_stages) et n'a
        # pas encore de plugin : c'est le cas nominal du scaffold.
        result = self.run_cli("scaffold", "build")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.assertJson(result)
        self.assertTrue((self.root / "plugins/aidlc-build/agent.json").exists())
        self.assertIn("created", data)

    def test_improve_repond(self):
        result = self.run_cli("improve")
        self.assertEqual(result.returncode, 0)
        self.assertJson(result)

    def test_knowledge_repond(self):
        result = self.run_cli("knowledge", "index")
        self.assertEqual(result.returncode, 1)  # aucune source declaree

    def test_check_okf_repond(self):
        result = self.run_cli("check-okf", str(self.root / "absent"))
        self.assertEqual(result.returncode, 1)

    def test_check_python_repond(self):
        self.write("ok.py", "x = 1\n")
        result = self.run_cli("check-python")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_json_repond(self):
        result = self.run_cli("check-json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ratchet_repond(self):
        result = self.run_cli("ratchet")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.assertJson(result)
        self.assertTrue(data["baseline"])

    def test_watchdog_repond(self):
        result = self.run_cli("watchdog")
        self.assertIn(result.returncode, (0, 2))
        data = self.assertJson(result)
        # Les cles du contrat watchdog (pas seulement "un JSON, un code plausible") :
        # un mauvais cablage vers un autre handler stateless produirait aussi un JSON
        # et un code dans (0, 2) sans jamais porter "halted"/"detections".
        self.assertIn("halted", data)
        self.assertIn("detections", data)

    def test_coverage_repond(self):
        """coverage delegue a measure(), qui relancerait aidlc.py test en
        sous-processus si son entrypoint existait. Dans l'environnement isole du
        test, harness_root() vise le repertoire temporaire (sans scripts/aidlc.py) :
        measure() echoue avant meme de songer a lancer un sous-processus. On arme
        quand meme le verrou de reentrance par prudence, comme pour `test`
        ci-dessus : ce test ne doit jamais dependre d'un accident de resolution de
        chemin pour rester sans danger."""
        with mock.patch.dict(os.environ, {tests_module._REENTRANCY: "1"}):
            result = self.run_cli("coverage")
        self.assertEqual(result.returncode, 1)
        self.assertIn("introuvable", result.stderr.lower())

    def test_selfscore_repond(self):
        """Meme precaution que pour `coverage` : selfscore mesure la couverture, donc
        relancerait la suite en sous-processus si son entrypoint existait. Dans
        l'environnement isole du test, harness_root() vise le repertoire temporaire
        (sans scripts/aidlc.py) : la mesure echoue avant tout sous-processus, et le
        verrou de reentrance est arme par prudence."""
        with mock.patch.dict(os.environ, {tests_module._REENTRANCY: "1"}):
            result = self.run_cli("selfscore")
        self.assertEqual(result.returncode, 1)
        self.assertIn("introuvable", result.stderr.lower())
        self.assertEqual(result.stdout, "")

    def test_watchdog_touched_repond(self):
        result = self.run_cli("watchdog-touched", stdin="{}")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class TestOptionsExperiment(AidlcTestCase):
    """La memoire de la boucle passe par le CLI : le registre n'est ecrit que par
    `experiment record`, et `effect` ne bloque jamais la CI."""

    RECORD = ("experiment", "record", "--stage", "plan", "--target", "precision",
              "--file", "plugins/aidlc-plan/checks.json", "--cause", "SKILL trop vague")

    def test_action_inconnue_est_refusee_par_le_parseur(self):
        result = self.run_cli("experiment", "oublier")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr.lower())

    def test_record_repond_et_ecrit_le_registre(self):
        result = self.run_cli(*self.RECORD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.assertJson(result)["target"], "precision")
        self.assertIn('"stage": "plan"', self.read(".aidlc/experiments.jsonl"))

    def test_record_avec_un_axe_inconnu_sort_en_erreur(self):
        argv = list(self.RECORD)
        argv[argv.index("precision")] = "elegance"
        result = self.run_cli(*argv)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_effect_repond_zero_meme_sans_experience(self):
        result = self.run_cli("experiment", "effect")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.assertJson(result), [])


class TestOptionsSelfscore(AidlcTestCase):
    """Le score de maturite du harnais est la porte du hook pre-commit et de la CI :
    son contrat public est un code de sortie, pas un texte. On verifie le routage et
    la propagation du code sans jamais declencher la mesure reelle."""

    def test_la_sous_commande_est_routee_vers_son_handler(self):
        with mock.patch("_aidlc.cli.cmd_selfscore", return_value=0) as handler:
            self.assertEqual(cli.main(["selfscore"]), 0)
        handler.assert_called_once()

    def test_le_code_bloquant_remonte_tel_quel(self):
        """2 = sous le seuil. C'est ce code que le hook pre-commit lit pour refuser le
        commit ; le confondre avec 1 (panne) rendrait la porte muette."""
        with mock.patch("_aidlc.cli.cmd_selfscore", return_value=2):
            self.assertEqual(cli.main(["selfscore"]), 2)

    def test_json_seul_est_une_option_du_parseur(self):
        self.assertTrue(cli.build_parser().parse_args(["selfscore", "--json"]).json)

    def test_une_option_inconnue_est_refusee(self):
        result = self.run_cli("selfscore", "--vite")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class TestSeparationStdoutStderr(AidlcTestCase):
    """La sortie machine (JSON) et le commentaire humain ne se melangent jamais dans le
    meme flux : stdout parse toujours comme JSON pour une commande a sortie machine."""

    def test_status_json_est_pur_sur_stdout(self):
        result = self.run_cli("status", "--json")
        self.assertJson(result)

    def test_status_humain_va_sur_stdout_en_texte(self):
        result = self.run_cli("status")
        self.assertEqual(result.returncode, 0)
        self.assertIn("AI-DLC", result.stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(result.stdout)

    def test_validate_json_est_pur_sur_stdout_meme_en_echec(self):
        result = self.run_cli("validate", "plan", "--json")
        data = self.assertJson(result)
        self.assertIn("errors", data)
        self.assertEqual(result.stderr, "")

    def test_validate_sans_json_ajoute_le_detail_humain_sur_stderr(self):
        result = self.run_cli("validate", "plan")
        self.assertJson(result)
        self.assertIn("erreur", result.stderr.lower())

    def test_gate_bloquant_detaille_sur_stderr(self):
        result = self.run_cli("gate", "plan")
        self.assertEqual(result.returncode, 2)
        self.assertIn("bloquant", result.stderr.lower())


class TestExceptionsAttrapeesParMain(AidlcTestCase):
    """FileNotFoundError et json.JSONDecodeError levees par un handler ne remontent
    jamais en traceback : main() les attrape et rend un message francais sur stderr."""

    def test_fichier_introuvable_rend_un_message_francais(self):
        result = self.run_cli("score", "plan", "--file",
                              str(self.root / "n-existe-pas.json"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Fichier introuvable", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_json_invalide_rend_un_message_francais(self):
        bad = self.write("revue-corrompue.json", "{ceci n'est pas du json")
        result = self.run_cli("score", "plan", "--file", str(bad))
        self.assertEqual(result.returncode, 1)
        self.assertIn("JSON invalide", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_aucune_trace_python_ne_fuit_sur_une_erreur_geree(self):
        result = self.run_cli("score", "plan", "--file",
                              str(self.root / "n-existe-pas.json"))
        self.assertNotIn("Traceback", result.stderr)


class TestOptionsValidate(AidlcTestCase):
    def test_file_cible_un_livrable_qui_n_est_pas_celui_par_defaut(self):
        autre = self.write("ailleurs/intent.md", document())
        result = self.run_cli("validate", "plan", "--file", str(autre))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_touched_est_silencieux_hors_livrable_gouverne(self):
        payload = json.dumps({"tool_input": {"file_path": str(self.root / "notes.txt")}})
        result = self.run_cli("validate", "--touched", stdin=payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_touched_signale_un_livrable_gouverne_en_contexte_additionnel(self):
        self.plan_intent()
        cible = self.root / "deliverables" / "plan" / "intent.md"
        payload = json.dumps({"tool_input": {"file_path": str(cible)}})
        result = self.run_cli("validate", "--touched", stdin=payload)
        self.assertEqual(result.returncode, 0)
        data = self.assertJson(result)
        self.assertIn("OK", data["hookSpecificOutput"]["additionalContext"])

    def test_sans_stage_ni_touched_usage_sur_stderr(self):
        result = self.run_cli("validate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("usage", result.stderr.lower())


class TestOptionsAgents(AidlcTestCase):
    def test_capability_filtre_le_catalogue(self):
        result = self.run_cli("agents", "--capability", "sdlc:plan", "--json")
        data = self.assertJson(result)
        self.assertEqual([a["id"] for a in data["agents"]], ["plan"])

    def test_capability_absente_rend_un_catalogue_vide(self):
        result = self.run_cli("agents", "--capability", "sdlc:inconnue", "--json")
        data = self.assertJson(result)
        self.assertEqual(data["agents"], [])

    def test_platform_choisit_l_invocation(self):
        result = self.run_cli("agents", "--platform", "codex", "--json")
        data = self.assertJson(result)
        self.assertEqual(data["platform"], "codex")

    def test_strict_ignore_un_manifeste_d_une_autre_equipe(self):
        # Un manifeste casse hors du projet est un avertissement, jamais un echec CI.
        externe = self.root.parent / "plugins-externes"
        self.write_agent("acme-broken", {"id": "sans-team-ni-invocation"},
                         checks=None, base=externe)
        self.agent_path(self.root / "plugins", externe)
        result = self.run_cli("agents", "--strict", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)


class TestOptionsStatus(AidlcTestCase):
    def test_json_rend_une_structure_exploitable(self):
        result = self.run_cli("status", "--json")
        data = self.assertJson(result)
        self.assertIn("maturity_threshold", data)


class TestOptionsScaffold(AidlcTestCase):
    def test_sans_force_refuse_un_plugin_deja_scaffolde(self):
        first = self.run_cli("scaffold", "build")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_cli("scaffold", "build")
        self.assertEqual(second.returncode, 1)

    def test_force_ecrase_un_plugin_deja_scaffolde(self):
        self.run_cli("scaffold", "build")
        result = self.run_cli("scaffold", "build", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)


class TestOptionsKnowledge(AidlcTestCase):
    """Une source locale (repo = dossier existant) evite tout appel reseau."""

    def _declarer_source(self, name="acme"):
        # Sous self.root : un bundle pose dans self.root.parent survit au tempdir et
        # fuit d'un test a l'autre — le fichier d'un test precedent se compte dans le
        # catalogue du suivant.
        source_dir = self.root / "source-okf"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "marge-brute.md").write_text(
            "---\ntitle: Marge brute\ntype: concept\n---\n\nCorps du concept.\n",
            encoding="utf-8")
        self.write_json("knowledge-sources.json",
                        {"sources": [{"name": name, "repo": str(source_dir), "path": ""}]})
        return source_dir

    def test_index_liste_les_concepts_de_la_source_declaree(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "index")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("marge-brute", result.stdout)

    def test_index_json_rend_une_forme_machine(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "index", "--json")
        data = self.assertJson(result)
        self.assertEqual(data["total"], 1)

    def test_search_trouve_par_mot_cle(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "search", "marge")
        self.assertEqual(result.returncode, 0)
        self.assertIn("marge-brute", result.stdout)

    def test_search_sans_terme_est_un_usage_errone(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "search")
        self.assertEqual(result.returncode, 1)
        self.assertIn("usage", result.stderr.lower())

    def test_get_rend_le_corps_du_concept(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "get", "acme/marge-brute")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Corps du concept", result.stdout)
        self.assertIn("contenu externe", result.stderr)

    def test_get_sans_terme_est_un_usage_errone(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "get")
        self.assertEqual(result.returncode, 1)

    def test_get_introuvable_echoue(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "get", "acme/n-existe-pas")
        self.assertEqual(result.returncode, 1)
        self.assertIn("introuvable", result.stderr.lower())

    def test_source_filtre_par_nom(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "index", "--source", "inconnue")
        self.assertEqual(result.returncode, 1)

    def test_refresh_n_echoue_pas_sur_une_source_montee_localement(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "index", "--refresh")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_limit_plafonne_les_lignes_affichees(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "index", "--limit", "0")
        self.assertEqual(result.returncode, 0)
        self.assertIn("non affiche", result.stderr)

    def test_aucune_source_declaree_rappelle_le_format_attendu(self):
        result = self.run_cli("knowledge", "index")
        self.assertEqual(result.returncode, 1)
        self.assertIn("knowledge-sources.json", result.stderr)

    def _declarer_source_liee(self):
        """Deux concepts d'une meme source, le premier citant le second."""
        source_dir = self._declarer_source()
        (source_dir / "marge-brute.md").write_text(
            "---\ntitle: Marge brute\ntype: concept\n---\n\n"
            "Depend du [chiffre d'affaires](ca.md).\n", encoding="utf-8")
        (source_dir / "ca.md").write_text(
            "---\ntitle: Chiffre d'affaires\ntype: concept\n---\n\nCorps.\n",
            encoding="utf-8")
        return source_dir

    def test_links_rend_le_lien_sortant_flechte(self):
        self._declarer_source_liee()
        result = self.run_cli("knowledge", "links", "acme/marge-brute")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-> acme/ca", result.stdout)

    def test_links_rend_le_retrolien_flechte(self):
        self._declarer_source_liee()
        result = self.run_cli("knowledge", "links", "acme/ca")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<- acme/marge-brute", result.stdout)

    def test_links_json_rend_les_deux_sens_separes(self):
        self._declarer_source_liee()
        result = self.run_cli("knowledge", "links", "acme/marge-brute", "--json")
        data = self.assertJson(result)
        self.assertEqual([e["ref"] for e in data["out"]], ["acme/ca"])
        self.assertEqual(data["in"], [])

    def test_links_json_ne_fuit_pas_le_chemin_local(self):
        self._declarer_source_liee()
        data = self.assertJson(
            self.run_cli("knowledge", "links", "acme/marge-brute", "--json"))
        self.assertNotIn("path", data["out"][0])

    def test_links_compte_les_voisins_sur_stderr(self):
        self._declarer_source_liee()
        result = self.run_cli("knowledge", "links", "acme/marge-brute")
        self.assertIn("1 lien(s) sortant(s), 0 retrolien(s)", result.stderr)

    def test_links_sans_terme_est_un_usage_errone(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "links")
        self.assertEqual(result.returncode, 1)
        self.assertIn("usage", result.stderr.lower())

    def test_links_introuvable_echoue(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "links", "acme/n-existe-pas")
        self.assertEqual(result.returncode, 1)
        self.assertIn("introuvable", result.stderr.lower())

    def test_links_d_un_concept_isole_n_ecrit_rien_sur_stdout(self):
        self._declarer_source()
        result = self.run_cli("knowledge", "links", "acme/marge-brute")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


class TestOptionsRecall(AidlcTestCase):
    """Contrat de `recall` : consigne de reprise sur stdout, diagnostic sur stderr."""

    def _noter(self, findings=None, scores=None):
        review = {"scores": scores or {"completeness": 2, "precision": 2,
                                       "traceability": 2, "autonomy": 2},
                  "findings": findings or []}
        self.write_json("review.json", review)
        self.plan_intent()
        return self.run_cli("score", "plan", "--file", "review.json")

    def test_sans_run_annonce_qu_il_n_y_a_rien_a_reprendre(self):
        result = self.run_cli("recall", "plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rien a reprendre", result.stdout)

    def test_etape_inconnue_echoue_avec_le_motif_sur_stderr(self):
        result = self.run_cli("recall", "inexistante")
        self.assertEqual(result.returncode, 1)
        self.assertIn("inexistante", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_rend_le_reproche_du_reviewer_sur_stdout(self):
        self._noter(findings=["Criteres non chiffres."])
        result = self.run_cli("recall", "plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Criteres non chiffres.", result.stdout)

    def test_json_rend_la_forme_machine(self):
        self._noter(findings=["Criteres non chiffres."])
        data = self.assertJson(self.run_cli("recall", "plan", "--json"))
        self.assertEqual(data["stage"], "plan")
        self.assertEqual(data["runs"][0]["findings"], ["Criteres non chiffres."])

    def test_limit_plafonne_les_runs_rappeles(self):
        self._noter()
        self._noter()
        data = self.assertJson(self.run_cli("recall", "plan", "--limit", "1", "--json"))
        self.assertEqual(len(data["runs"]), 1)
        self.assertEqual(data["total_runs"], 2)


class TestOptionsRatchet(AidlcTestCase):
    def test_reset_sans_ratchet_fige_echoue(self):
        result = self.run_cli("ratchet", "--reset", "plan")
        self.assertEqual(result.returncode, 1)

    def test_reset_apres_un_premier_passage_reussit(self):
        self.run_cli("ratchet")
        result = self.run_cli("ratchet", "--reset", "plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.assertJson(result)
        self.assertEqual(data["stage"], "plan")

    def test_reset_d_une_etape_inconnue_echoue(self):
        self.run_cli("ratchet")
        result = self.run_cli("ratchet", "--reset", "etape-fantome")
        self.assertEqual(result.returncode, 1)


class TestOptionsCheckOkf(AidlcTestCase):
    def test_dir_positionnel_sur_un_bundle_conforme(self):
        bundle = self.root / "bundle-conforme"
        self.write("bundle-conforme/index.md", "# Index\n\n- [Un concept](un-concept.md)\n")
        self.write("bundle-conforme/log.md", "# Journal\n")
        self.write("bundle-conforme/un-concept.md",
                   "---\ntitle: Un concept\ntype: concept\n---\n\nCorps.\n")
        result = self.run_cli("check-okf", str(bundle))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sans_dir_ni_touched_ni_stop_usage_sur_stderr(self):
        result = self.run_cli("check-okf")
        self.assertEqual(result.returncode, 1)
        self.assertIn("usage", result.stderr.lower())

    def test_touched_sans_fichier_touche_est_silencieux(self):
        result = self.run_cli("check-okf", "--touched", stdin="{}")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_touched_avec_file_hors_bundle_okf_est_silencieux(self):
        result = self.run_cli("check-okf", "--touched", "--file",
                              str(self.root / "notes.txt"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_stop_sans_bundle_okf_du_projet_est_silencieux(self):
        result = self.run_cli("check-okf", "--stop")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class TestOptionsCheckPython(AidlcTestCase):
    def test_dir_positionnel_sur_du_python_invalide(self):
        casse = self.root / "casse"
        self.write("casse/mauvais.py", "def f(:\n")
        result = self.run_cli("check-python", str(casse))
        self.assertEqual(result.returncode, 1)
        self.assertIn("syntax", result.stderr.lower())

    def test_dir_introuvable_echoue(self):
        result = self.run_cli("check-python", str(self.root / "n-existe-pas"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("introuvable", result.stderr.lower())

    def test_touched_sur_un_py_valide_ajoute_un_contexte_positif(self):
        cible = self.write("bon.py", "x = 1\n")
        result = self.run_cli("check-python", "--touched", "--file", str(cible))
        self.assertEqual(result.returncode, 0)
        data = self.assertJson(result)
        self.assertIn("compile", data["hookSpecificOutput"]["additionalContext"])

    def test_touched_sur_un_fichier_non_python_est_silencieux(self):
        cible = self.write("notes.txt", "bonjour")
        result = self.run_cli("check-python", "--touched", "--file", str(cible))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_touched_sur_du_python_invalide_signale_le_probleme(self):
        cible = self.write("casse.py", "def f(:\n")
        result = self.run_cli("check-python", "--touched", "--file", str(cible))
        self.assertEqual(result.returncode, 0)
        data = self.assertJson(result)
        self.assertIn("NON CONFORME",
                     data["hookSpecificOutput"]["additionalContext"])


class TestOptionsCheckJson(AidlcTestCase):
    def test_dir_positionnel_sur_du_json_invalide(self):
        casse = self.root / "casse"
        self.write("casse/mauvais.json", "{ceci n'est pas du json")
        result = self.run_cli("check-json", str(casse))
        self.assertEqual(result.returncode, 1)

    def test_touched_sur_un_json_valide(self):
        cible = self.write("bon.json", "{}")
        result = self.run_cli("check-json", "--touched", "--file", str(cible))
        self.assertEqual(result.returncode, 0)
        data = self.assertJson(result)
        self.assertIn("parse", data["hookSpecificOutput"]["additionalContext"])

    def test_touched_sur_un_fichier_non_json_est_silencieux(self):
        cible = self.write("notes.txt", "bonjour")
        result = self.run_cli("check-json", "--touched", "--file", str(cible))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class TestCommandesDesHooksJson(AidlcTestCase):
    """hooks.json n'invoque que des sous-commandes qui existent reellement : on rejoue
    chacune, dans le mode ou hooks.json l'appelle, et on verifie qu'elle repond sans
    jamais faire echouer le hook (les hooks sont non bloquants par construction, sauf
    guard/check-okf --stop qui peuvent refuser via permissionDecision, jamais via un
    code de sortie non nul)."""

    def test_log(self):
        self.assertEqual(self.run_cli("log", stdin="{}").returncode, 0)

    def test_check_okf_stop(self):
        self.assertEqual(self.run_cli("check-okf", "--stop").returncode, 0)

    def test_guard(self):
        self.assertEqual(self.run_cli("guard", stdin="{}").returncode, 0)

    def test_validate_touched(self):
        self.assertEqual(
            self.run_cli("validate", "--touched", stdin="{}").returncode, 0)

    def test_check_okf_touched(self):
        self.assertEqual(
            self.run_cli("check-okf", "--touched", stdin="{}").returncode, 0)

    def test_check_python_touched(self):
        self.assertEqual(
            self.run_cli("check-python", "--touched", stdin="{}").returncode, 0)

    def test_check_json_touched(self):
        self.assertEqual(
            self.run_cli("check-json", "--touched", stdin="{}").returncode, 0)

    def test_watchdog_touched(self):
        self.assertEqual(
            self.run_cli("watchdog-touched", stdin="{}").returncode, 0)


class TestAgentsControleDeContrat(AidlcTestCase):
    """`agents --strict` est la porte CI du registre. Depuis que le contrat est
    controle a vide, elle refuse aussi un checks.json incoherent — avec la meme
    severite asymetrique que pour les manifestes : ce qui vient du depot courant fait
    rougir la CI, ce qui vient d'une direction voisine reste un avertissement."""

    INCOHERENT = {"required_sections": ["## Contexte"],
                  "min_items_per_section": {"## Absente": 2}}

    def test_le_catalogue_expose_les_problemes_de_contrat(self):
        result = self.run_cli("agents", "--json")
        self.assertIn("contract_problems", self.assertJson(result))

    def test_un_contrat_incoherent_du_depot_fait_echouer_strict(self):
        self.write_agent("aidlc-lint",
                         manifest("lint", "X", "deliverables/lint/doc.md"),
                         self.INCOHERENT)
        result = self.run_cli("agents", "--strict")
        self.assertEqual(result.returncode, 1)
        self.assertIn("insatisfiable", result.stderr)

    def test_un_contrat_incoherent_d_une_autre_equipe_reste_un_avertissement(self):
        """La CI d'un consommateur ne rougit jamais pour le contrat d'une direction
        voisine : il est signale, il ne bloque pas."""
        externe = self.root.parent / "plugins-externes"
        self.write_agent("acme-lint",
                         manifest("lint", "AppSec", "deliverables/lint/doc.md"),
                         self.INCOHERENT, base=externe)
        self.agent_path(self.root / "plugins", externe)
        result = self.run_cli("agents", "--strict")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("insatisfiable", result.stderr)


class TestContratSign(AidlcTestCase):
    """`sign` en sous-processus : c'est exactement le contexte d'un agent qui lancerait
    la commande par un outil Bash — pas de terminal, donc pas de signature. Ce test-la
    n'est pas une formalite : c'est le garde-fou lui-meme, celui qui distingue
    « l'humain a signe » de « l'agent a ecrit qu'il avait signe »."""

    def test_sans_terminal_la_signature_est_refusee(self):
        result = self.run_cli("sign", "plan", "--approve", "--by", "Steve",
                              "--why", "Conforme.")
        self.assertEqual(result.returncode, 1)
        self.assertIn("geste humain", result.stderr)

    def test_sans_terminal_aucune_revue_n_est_ecrite(self):
        self.run_cli("sign", "plan", "--approve", "--by", "Steve", "--why", "Conforme.")
        self.assertFalse((self.root / ".aidlc" / "reviews").exists())

    def test_sans_terminal_stdout_reste_vide(self):
        result = self.run_cli("sign", "plan", "--approve", "--by", "S", "--why", "w")
        self.assertEqual(result.stdout, "")

    def test_la_sous_commande_est_exposee_par_le_parseur(self):
        result = self.run_cli("sign", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--approve", result.stdout)


class TestContratInit(AidlcTestCase):
    """`init` en sous-processus : machine sur stdout, compte rendu sur stderr."""

    def test_l_amorcage_sort_a_zero_et_rend_du_json(self):
        result = self.run_cli("init")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.assertJson(result)
        self.assertIn("aidlc.json", data["created"])

    def test_le_compte_rendu_humain_part_sur_stderr(self):
        result = self.run_cli("init")
        self.assertIn("Projet amorce", result.stderr)

    def test_le_projet_amorce_est_ensuite_lisible_par_status(self):
        self.run_cli("init")
        result = self.run_cli("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Gouvernance : aidlc.json", result.stdout)


class TestContratChainage(AidlcTestCase):
    """La promesse de bout en bout, vue depuis le contrat public : c'est le code de
    sortie de `gate` qui doit refuser une etape batie sur du vide, pas un prompt."""

    def test_la_porte_aval_refuse_quand_l_amont_n_existe_pas(self):
        self.write("deliverables/design/spec.md",
                   document({"## Contexte": "Issu de deliverables/plan/intent.md."},
                            front={"stage": "design", "version": "1", "status": "draft",
                                   "author": "Steve", "date": "2026-09-03"}))
        review = self.write_json("review.json", {
            "stage": "design", "scores": {"completeness": 5, "precision": 5,
                                          "traceability": 5, "autonomy": 5}})
        self.run_cli("score", "design", "--file", str(review))
        self.write_json(".aidlc/reviews/design-1.json", {
            "stage": "design", "run": 1, "approved": True, "reviewer": "Archi",
            "justification": "ok", "ts": "2026-09-06T10:00:00+00:00"})
        result = self.run_cli("gate", "design")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Entree amont absente", self.assertJson(result)["blocking"][0])

    def test_le_tableau_de_bord_dit_que_l_aval_attend_son_amont(self):
        result = self.run_cli("status")
        self.assertIn("En attente de l'amont : plan", result.stdout)


class TestGouvernanceProjet(AidlcTestCase):
    """Le seuil et le workflow lus depuis l'aidlc.json du projet, en sous-processus :
    c'est la seule facon pour une equipe de fixer son exigence sans ecrire dans la copie
    installee du harnais, que le garde-fou protege."""

    def test_le_seuil_du_projet_recouvre_celui_du_harnais(self):
        self.write_json("aidlc.json", {"maturity_threshold": 4.9})
        result = self.run_cli("status")
        self.assertIn("Seuil de maturite : 4.9", result.stdout)

    def test_le_workflow_declare_restreint_le_tableau_de_bord(self):
        self.write_json("aidlc.json", {"agents": ["plan"]})
        result = self.run_cli("status", "--json")
        self.assertEqual([r["stage"] for r in self.assertJson(result)["stages"]], ["plan"])

    def test_une_cle_mal_orthographiee_est_signalee_au_lieu_d_etre_avalee(self):
        self.write_json("aidlc.json", {"maturity_treshold": 4.9})
        result = self.run_cli("status")
        self.assertIn("Gouvernance du projet", result.stdout)

    def test_une_gouvernance_projet_illisible_fait_sortir_en_erreur(self):
        self.write("aidlc.json", "{ pas du json")
        result = self.run_cli("status")
        self.assertEqual(result.returncode, 1)
        self.assertIn("JSON invalide", result.stderr)


class TestAideDuParseur(AidlcTestCase):
    """L'aide s'ouvre sur ce qu'un humain tape, pas sur les modes de hook."""

    def test_les_modes_de_hook_sont_hors_de_l_aide(self):
        result = self.run_cli("--help")
        self.assertNotIn("watchdog-touched  ", result.stdout)

    def test_les_modes_de_hook_restent_invocables(self):
        result = self.run_cli("watchdog-touched", stdin="{}")
        self.assertEqual(result.returncode, 0)

    def test_l_aide_oriente_entre_piloter_un_projet_et_maintenir_le_harnais(self):
        result = self.run_cli("--help")
        self.assertIn("Piloter un projet", result.stdout)
        self.assertIn("Maintenir le harnais", result.stdout)
