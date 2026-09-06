from __future__ import annotations

import os
import tempfile

from pathlib import Path
from unittest import mock

from .harness import AidlcTestCase
from .harness import manifest
from .. import registry
from ..util import ensure_dir

"""Registre ouvert des agents : decouverte par manifeste, validation de forme, ordre
derive de la chaine produces/consumes, catalogue filtre, frontieres projet/hors-projet."""


def _valid_manifest(**overrides) -> dict:
    """Manifeste minimal et valide, a muter champ par champ pour les tests de rejet."""
    base = {
        "manifest_version": 1, "id": "agent-x", "team": "Equipe",
        "description": "Un agent de test.", "capabilities": ["sdlc:x"],
        "invocation": {"claude-code": "aidlc-x:x"},
    }
    base.update(overrides)
    return base


class TestPlateformeParDefaut(AidlcTestCase):
    """La plateforme d'invocation courante : neutre par defaut, jamais devinee."""

    seed_agents = False

    def test_par_defaut_cest_claude_code(self):
        self.assertEqual(registry.default_platform(), "claude-code")

    def test_suit_la_variable_denvironnement(self):
        os.environ["AIDLC_PLATFORM"] = "codex"
        self.assertEqual(registry.default_platform(), "codex")

    def test_est_nettoyee_des_espaces(self):
        os.environ["AIDLC_PLATFORM"] = "  codex  "
        self.assertEqual(registry.default_platform(), "codex")


class TestRacinesExplicites(AidlcTestCase):
    """AIDLC_AGENT_PATH : la precedence maximale de decouverte."""

    seed_agents = False

    def test_ignore_les_segments_vides(self):
        os.environ["AIDLC_AGENT_PATH"] = f"{self.root}{os.pathsep}{os.pathsep}  {os.pathsep}"
        self.assertEqual(registry._env_roots(), [self.root])

    def test_vide_quand_la_variable_est_absente(self):
        os.environ.pop("AIDLC_AGENT_PATH", None)
        self.assertEqual(registry._env_roots(), [])

    def test_developpe_le_repertoire_utilisateur(self):
        os.environ["AIDLC_AGENT_PATH"] = "~/un-dossier-de-test-aidlc"
        self.assertEqual(registry._env_roots(),
                         [Path("~/un-dossier-de-test-aidlc").expanduser()])


class TestRepoRoots(AidlcTestCase):
    """plugins/ du depot auteur (voisin du noyau) et du projet consommateur."""

    seed_agents = False

    def test_ajoute_le_parent_du_harnais_quand_il_sappelle_plugins(self):
        harness_dir = ensure_dir(self.root / "plugins" / "aidlc-core")
        os.environ["AIDLC_HARNESS_ROOT"] = str(harness_dir)
        roots = registry._repo_roots()
        self.assertIn(harness_dir.resolve().parent, roots)

    def test_najoute_pas_le_parent_du_harnais_hors_dune_arborescence_plugins(self):
        # setUp place AIDLC_HARNESS_ROOT = self.root, dont le parent n'est pas "plugins".
        self.assertEqual(registry._repo_roots(), [self.root / "plugins"])


class TestInstalledRoots(AidlcTestCase):
    """Plugins installes par Claude Code : lu au mieux, jamais porteur d'exception."""

    seed_agents = False

    def setUp(self):
        super().setUp()
        self.config = Path(os.environ["CLAUDE_CONFIG_DIR"])

    def test_lit_les_installpath_valides_et_ignore_les_entrees_malformees(self):
        good = ensure_dir(self.root / "installed" / "acme-security")
        data = {"plugins": {
            "marketplace-un": [
                {"installPath": str(good)},
                {"sans-installpath": True},
                "pas-un-objet",
            ],
            "marketplace-deux": "pas-une-liste",
        }}
        self.write_json("fake-config/plugins/installed_plugins.json", data)
        self.assertEqual(registry._installed_roots(), [good])

    def test_replie_sur_le_cache_quand_le_fichier_declare_est_absent(self):
        cache_dir = ensure_dir(
            self.config / "plugins" / "cache" / "acme" / "aidlc-security" / "1.0.0")
        self.assertEqual(registry._installed_roots(), [cache_dir])

    def test_erreur_oserror_du_glob_de_secours_ne_leve_pas(self):
        with mock.patch.object(Path, "glob", side_effect=OSError("boom")):
            self.assertEqual(registry._installed_roots(), [])


class TestScanInterne(AidlcTestCase):
    """Manifestes trouves sous une racine, a la profondeur 1 au maximum."""

    seed_agents = False

    def test_une_racine_absente_ne_leve_pas(self):
        self.assertEqual(registry._scan(self.root / "n-existe-pas"), [])

    def test_trouve_un_manifeste_directement_a_la_racine(self):
        target = ensure_dir(self.root / "direct")
        self.write_json("direct/agent.json", manifest("x", "T"))
        self.assertEqual(registry._scan(target), [target / "agent.json"])

    def test_trouve_les_manifestes_dans_les_sous_dossiers_immediats(self):
        target = ensure_dir(self.root / "plugins")
        self.write_json("plugins/aidlc-x/agent.json", manifest("x", "T"))
        self.assertEqual(registry._scan(target), [target / "aidlc-x" / "agent.json"])

    def test_erreur_oserror_pendant_literation_est_ignoree(self):
        target = ensure_dir(self.root / "racine")
        with mock.patch.object(Path, "iterdir", side_effect=OSError("boom")):
            self.assertEqual(registry._scan(target), [])


class TestValidateManifest(AidlcTestCase):
    """Forme d'un manifeste : chaque champ invalide doit etre nomme, jamais devine."""

    seed_agents = False

    def test_rejette_une_valeur_qui_nest_pas_un_objet_json(self):
        problems = registry.validate_manifest(["pas", "un", "objet"], "src")
        self.assertTrue(any("objet JSON" in p for p in problems))

    def test_rejette_none(self):
        problems = registry.validate_manifest(None, "src")
        self.assertTrue(any("objet JSON" in p for p in problems))

    def test_rejette_une_version_de_manifeste_non_supportee(self):
        problems = registry.validate_manifest(_valid_manifest(manifest_version=2), "src")
        self.assertTrue(any("manifest_version" in p for p in problems))

    def test_signale_chaque_champ_obligatoire_manquant_sauf_la_version(self):
        problems = registry.validate_manifest({"manifest_version": 1}, "src")
        for field in ("id", "team", "description", "capabilities", "invocation"):
            self.assertTrue(any(f"'{field}'" in p for p in problems), field)

    def test_rejette_un_champ_obligatoire_vide(self):
        problems = registry.validate_manifest(_valid_manifest(team=""), "src")
        self.assertTrue(any("'team'" in p for p in problems))

    def test_rejette_un_identifiant_invalide(self):
        problems = registry.validate_manifest(_valid_manifest(id="Agent_X"), "src")
        self.assertTrue(any("id 'Agent_X' invalide" in p for p in problems))

    def test_accepte_un_identifiant_avec_tiret_et_underscore(self):
        problems = registry.validate_manifest(_valid_manifest(id="agent-x_2"), "src")
        self.assertEqual(problems, [])

    def test_rejette_des_capacites_qui_ne_sont_pas_une_liste(self):
        problems = registry.validate_manifest(_valid_manifest(capabilities="sdlc:x"), "src")
        self.assertTrue(any("'capabilities'" in p for p in problems))

    def test_rejette_une_capacite_de_forme_invalide(self):
        problems = registry.validate_manifest(_valid_manifest(capabilities=["SDLC X!"]), "src")
        self.assertTrue(any("capacite invalide" in p for p in problems))

    def test_rejette_une_capacite_qui_nest_pas_une_chaine(self):
        problems = registry.validate_manifest(_valid_manifest(capabilities=[42]), "src")
        self.assertTrue(any("capacite invalide" in p for p in problems))

    def test_rejette_une_invocation_qui_nest_pas_un_objet(self):
        problems = registry.validate_manifest(_valid_manifest(invocation="aidlc-x:x"), "src")
        self.assertTrue(any("'invocation'" in p for p in problems))

    def test_rejette_une_invocation_vide_pour_une_plateforme(self):
        problems = registry.validate_manifest(
            _valid_manifest(invocation={"claude-code": "   "}), "src")
        self.assertTrue(any("invocation['claude-code']" in p for p in problems))

    def test_rejette_une_invocation_qui_nest_pas_une_chaine(self):
        problems = registry.validate_manifest(
            _valid_manifest(invocation={"claude-code": 7}), "src")
        self.assertTrue(any("invocation['claude-code']" in p for p in problems))

    def test_rejette_consumes_qui_nest_pas_une_liste(self):
        problems = registry.validate_manifest(_valid_manifest(consumes="x.md"), "src")
        self.assertTrue(any("'consumes'" in p for p in problems))

    def test_rejette_requires_qui_nest_pas_une_liste(self):
        problems = registry.validate_manifest(_valid_manifest(requires="y"), "src")
        self.assertTrue(any("'requires'" in p for p in problems))

    def test_rejette_un_produces_qui_nest_pas_une_chaine(self):
        problems = registry.validate_manifest(_valid_manifest(produces=["a", "b"]), "src")
        self.assertTrue(any("'produces'" in p for p in problems))

    def test_accepte_un_manifeste_minimal_valide(self):
        self.assertEqual(registry.validate_manifest(_valid_manifest(), "src"), [])


class TestNormalisation(AidlcTestCase):
    """Manifeste valide -> entree de catalogue : frontieres et valeurs par defaut."""

    def test_un_agent_du_projet_est_marque_in_project(self):
        agent = registry.find_agent("plan")
        self.assertTrue(agent["in_project"])

    def test_un_agent_hors_projet_nest_pas_marque_in_project(self):
        # Un vrai repertoire hors de self.root : self.root est a la fois le harnais
        # et le projet consommateur, donc un sous-dossier de self.root resterait
        # "in_project" quel que soit son nom.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.write_agent("acme", manifest("dehors", "Externe"), base=Path(tmp.name))
        self.agent_path(self.root / "plugins", Path(tmp.name))
        agent = registry.find_agent("dehors")
        self.assertFalse(agent["in_project"])

    def test_consumes_et_requires_par_defaut_sont_des_listes_vides(self):
        external = self.root / "external"
        self.write_agent("acme", manifest("dehors", "Externe"), base=external)
        self.agent_path(self.root / "plugins", external)
        agent = registry.find_agent("dehors")
        self.assertEqual(agent["consumes"], [])
        self.assertEqual(agent["requires"], [])

    def test_un_agent_consultatif_na_ni_checks_ni_role_humain(self):
        plan = registry.find_agent("plan")
        self.assertEqual(plan["checks"], "checks.json")
        external = self.root / "external"
        self.write_agent("acme", manifest("dehors", "Externe"), base=external)
        self.agent_path(self.root / "plugins", external)
        advisor = registry.find_agent("dehors")
        self.assertIsNone(advisor["checks"])
        self.assertIsNone(advisor["human_role"])


class TestDeduplicationDesRacines(AidlcTestCase):
    """Deux racines qui menent au meme fichier reel ne comptent l'agent qu'une fois."""

    def test_un_meme_manifeste_atteint_par_deux_racines_nest_compte_quune_fois(self):
        real_manifest = self.root / "plugins" / "aidlc-plan" / "agent.json"
        mirror_dir = ensure_dir(self.root / "external" / "mirror")
        os.symlink(real_manifest, mirror_dir / "agent.json")
        self.agent_path(self.root / "plugins", self.root / "external")
        report = registry.discover()
        self.assertEqual(len([a for a in report["agents"] if a["id"] == "plan"]), 1)
        self.assertEqual(report["warnings"], [])


class TestErreursDeResolutionIgnorees(AidlcTestCase):
    """Un chemin en erreur pendant la resolution ne fait jamais planter la decouverte."""

    def test_une_racine_dont_la_resolution_echoue_est_ignoree(self):
        broken = self.root / "broken-root"
        self.agent_path(self.root / "plugins", broken)
        original_resolve = Path.resolve

        def flaky(path_self, *a, **kw):
            if path_self == broken:
                raise OSError("simulated")
            return original_resolve(path_self, *a, **kw)

        with mock.patch.object(Path, "resolve", flaky):
            report = registry.discover(refresh=True)
        self.assertTrue(any(a["id"] == "plan" for a in report["agents"]))

    def test_un_manifeste_dont_la_resolution_echoue_est_ignore(self):
        broken_manifest = self.root / "plugins" / "aidlc-broken" / "agent.json"
        self.write_json("plugins/aidlc-broken/agent.json", manifest("broken", "T"))
        original_resolve = Path.resolve

        def flaky(path_self, *a, **kw):
            if path_self == broken_manifest:
                raise OSError("simulated")
            return original_resolve(path_self, *a, **kw)

        with mock.patch.object(Path, "resolve", flaky):
            report = registry.discover(refresh=True)
        self.assertFalse(any(a["id"] == "broken" for a in report["agents"]))
        self.assertTrue(any(a["id"] == "plan" for a in report["agents"]))


class TestDecouverteRejetsEtAnomalies(AidlcTestCase):
    """Manifestes de forme invalide, identifiants dupliques, cycles, producteurs
    absents : le registre signale proprement, jamais ne plante ni ne se corrompt."""

    def test_un_manifeste_incomplet_nentre_jamais_au_registre(self):
        self.write_json("plugins/aidlc-bad/agent.json", {"manifest_version": 1, "id": "bad"})
        registry.reset_cache()
        report = registry.discover()
        self.assertFalse(any(a["id"] == "bad" for a in report["agents"]))

    def test_le_rejet_nomme_le_champ_obligatoire_manquant(self):
        self.write_json("plugins/aidlc-bad/agent.json", {"manifest_version": 1, "id": "bad"})
        registry.reset_cache()
        report = registry.discover()
        self.assertTrue(any("'team'" in p for p in report["problems"]))

    def test_une_version_de_manifeste_non_supportee_est_refusee(self):
        self.write_json("plugins/aidlc-bad/agent.json",
                        dict(manifest("bad", "X"), manifest_version=2))
        registry.reset_cache()
        report = registry.discover()
        self.assertTrue(any("manifest_version" in p for p in report["problems"]))
        self.assertFalse(any(a["id"] == "bad" for a in report["agents"]))

    def test_un_manifeste_illisible_est_signale_sans_arreter_la_decouverte(self):
        self.write("plugins/aidlc-bad/agent.json", "{ ceci n'est pas du JSON")
        registry.reset_cache()
        report = registry.discover()
        self.assertTrue(any("illisible" in p for p in report["problems"]))
        self.assertTrue(any(a["id"] == "plan" for a in report["agents"]))

    def test_un_identifiant_en_double_est_signale_avec_les_deux_equipes(self):
        self.write_json("plugins/aidlc-bad/agent.json", manifest("plan", "Equipe concurrente"))
        registry.reset_cache()
        report = registry.discover()
        self.assertTrue(any("Equipe concurrente" in w and "plan" in w
                            for w in report["warnings"]))

    def test_un_identifiant_en_double_ne_dedouble_pas_lagent(self):
        self.write_json("plugins/aidlc-bad/agent.json", manifest("plan", "Equipe concurrente"))
        registry.reset_cache()
        report = registry.discover()
        self.assertEqual(len([a for a in report["agents"] if a["id"] == "plan"]), 1)

    def test_un_cycle_de_dependances_est_detecte_et_nomme(self):
        self.write_json("plugins/aidlc-bad/agent.json",
                        manifest("boucle-a", "X", "deliverables/a.md", ["deliverables/b.md"]))
        self.write_json("plugins/aidlc-bad2/agent.json",
                        manifest("boucle-b", "X", "deliverables/b.md", ["deliverables/a.md"]))
        registry.reset_cache()
        self.assertEqual(sorted(registry.catalog()["cycle"]), ["boucle-a", "boucle-b"])

    def test_une_entree_sans_producteur_installe_remonte_dans_missing_producers(self):
        self.write_json("plugins/aidlc-bad/agent.json",
                        manifest("orphelin", "X", "deliverables/o.md",
                                 ["deliverables/jamais.md"]))
        registry.reset_cache()
        holes = registry.catalog()["missing_producers"]
        self.assertTrue(any(h["agent"] == "orphelin" and h["input"] == "deliverables/jamais.md"
                            for h in holes))


class TestOrdreDerive(AidlcTestCase):
    """L'ordre d'invocation se derive de produces/consumes et de requires, jamais
    d'une position dans un fichier."""

    seed_agents = False

    @staticmethod
    def _agent(agent_id, produces=None, consumes=(), requires=()):
        return {"id": agent_id, "produces": produces, "consumes": list(consumes),
               "requires": list(requires)}

    def test_le_producteur_precede_son_consommateur(self):
        a = self._agent("a", produces="x.md")
        b = self._agent("b", consumes=["x.md"])
        ordered, cycle = registry.order([b, a])
        self.assertEqual([x["id"] for x in ordered], ["a", "b"])
        self.assertEqual(cycle, [])

    def test_requires_explicite_est_respecte(self):
        a = self._agent("a")
        b = self._agent("b", requires=["a"])
        ordered, _ = registry.order([b, a])
        self.assertEqual([x["id"] for x in ordered], ["a", "b"])

    def test_les_agents_independants_sont_departages_par_id(self):
        ordered, _ = registry.order([self._agent("z"), self._agent("a"), self._agent("m")])
        self.assertEqual([x["id"] for x in ordered], ["a", "m", "z"])

    def test_un_cycle_est_detecte_et_nomme_sans_boucle_infinie(self):
        a = self._agent("a", requires=["b"])
        b = self._agent("b", requires=["a"])
        ordered, cycle = registry.order([a, b])
        self.assertEqual(ordered, [])
        self.assertEqual(sorted(cycle), ["a", "b"])

    def test_une_dependance_vers_un_agent_absent_du_catalogue_nimmobilise_rien(self):
        a = self._agent("a", requires=["fantome"])
        ordered, cycle = registry.order([a])
        self.assertEqual([x["id"] for x in ordered], ["a"])
        self.assertEqual(cycle, [])

    def test_lauto_reference_est_ignoree(self):
        a = self._agent("a", requires=["a"])
        ordered, cycle = registry.order([a])
        self.assertEqual([x["id"] for x in ordered], ["a"])
        self.assertEqual(cycle, [])


class TestProducteursManquants(AidlcTestCase):
    """Entrees attendues que personne ne produit : le plugin producteur n'est pas
    installe."""

    seed_agents = False

    def test_signale_une_entree_sans_producteur_installe(self):
        agent = {"id": "a", "consumes": ["x.md"]}
        self.assertEqual(registry.missing_producers([agent]),
                         [{"agent": "a", "input": "x.md"}])

    def test_ne_signale_rien_quand_le_producteur_existe(self):
        producer = {"id": "a", "produces": "x.md", "consumes": []}
        consumer = {"id": "b", "produces": None, "consumes": ["x.md"]}
        self.assertEqual(registry.missing_producers([producer, consumer]), [])


class TestCatalogueDesTroisAgents(AidlcTestCase):
    """Le catalogue reference : deux etapes gouvernees (plan, design) et un agent
    consultatif d'une autre equipe, decouvert par AIDLC_AGENT_PATH."""

    def setUp(self):
        super().setUp()
        self.external = self.root / "external"
        self.write_agent(
            "acme-security",
            manifest("security-review", "AppSec",
                    capabilities=["security:review"],
                    invocation={"claude-code": "acme-security:security-review",
                               "codex": "prompts/review.md"}),
            base=self.external)
        self.agent_path(self.root / "plugins", self.external)

    def test_les_trois_agents_sont_decouverts(self):
        ids = sorted(a["id"] for a in registry.catalog()["agents"])
        self.assertEqual(ids, ["design", "plan", "security-review"])

    def test_lagent_qui_consomme_passe_apres_celui_qui_produit(self):
        ids = [a["id"] for a in registry.catalog()["agents"]]
        self.assertLess(ids.index("plan"), ids.index("design"))

    def test_un_agent_sans_produces_est_consultatif_et_porte_son_equipe(self):
        advisor = next(a for a in registry.catalog()["agents"] if a["id"] == "security-review")
        self.assertEqual(advisor["kind"], "capability")
        self.assertEqual(advisor["team"], "AppSec")

    def test_linvocation_lue_est_exactement_celle_du_manifeste(self):
        advisor = next(a for a in registry.catalog()["agents"] if a["id"] == "security-review")
        self.assertEqual(advisor["invoke"], "acme-security:security-review")
        self.assertTrue(advisor["invocable"])

    def test_lindex_des_capacites_pointe_vers_lagent_qui_la_porte(self):
        self.assertEqual(registry.catalog()["capabilities"]["security:review"],
                         ["security-review"])

    def test_le_filtre_par_capacite_restreint_le_catalogue(self):
        ids = [a["id"] for a in registry.catalog(capability="security:review")["agents"]]
        self.assertEqual(ids, ["security-review"])

    def test_agent_for_file_retrouve_lagent_par_son_livrable_exact(self):
        intent = self.plan_intent()
        self.assertEqual(registry.agent_for_file(self.root, str(intent))["id"], "plan")

    def test_une_plateforme_sans_bloc_dinvocation_est_respectee(self):
        os.environ["AIDLC_PLATFORM"] = "codex"
        registry.reset_cache()
        codex = registry.catalog()
        self.assertEqual(codex["platform"], "codex")

    def test_sous_codex_linvocation_vient_du_bloc_codex_du_meme_manifeste(self):
        os.environ["AIDLC_PLATFORM"] = "codex"
        registry.reset_cache()
        codex = registry.catalog()
        advisor = next(a for a in codex["agents"] if a["id"] == "security-review")
        self.assertEqual(advisor["invoke"], "prompts/review.md")

    def test_un_agent_sans_invocation_pour_la_plateforme_nest_pas_invocable(self):
        os.environ["AIDLC_PLATFORM"] = "codex"
        registry.reset_cache()
        codex = registry.catalog()
        plan = next(a for a in codex["agents"] if a["id"] == "plan")
        self.assertFalse(plan["invocable"])


class TestCatalogue(AidlcTestCase):
    """Vue ordonnee et filtree du registre."""

    def test_kind_stage_pour_un_agent_qui_produit_capability_sinon(self):
        rows = {a["id"]: a for a in registry.catalog()["agents"]}
        self.assertEqual(rows["plan"]["kind"], "stage")
        external = self.root / "external"
        self.write_agent("acme", manifest("dehors", "Externe"), base=external)
        self.agent_path(self.root / "plugins", external)
        rows = {a["id"]: a for a in registry.catalog()["agents"]}
        self.assertEqual(rows["dehors"]["kind"], "capability")

    def test_lindex_des_capacites_couvre_tout_le_registre_meme_hors_filtre(self):
        view = registry.catalog(capability="sdlc:plan")
        self.assertIn("sdlc:design", view["capabilities"])


class TestListesDerivees(AidlcTestCase):
    """agents_list et stages : successeurs de l'ancien pipeline.json.stages[]."""

    def test_agents_list_suit_lordre_derive(self):
        ids = [a["id"] for a in registry.agents_list()]
        self.assertEqual(ids, ["plan", "design"])

    def test_stages_ne_garde_que_les_agents_qui_produisent(self):
        external = self.root / "external"
        self.write_agent("acme", manifest("dehors", "Externe"), base=external)
        self.agent_path(self.root / "plugins", external)
        ids = [a["id"] for a in registry.stages()]
        self.assertNotIn("dehors", ids)

    def test_find_agent_renvoie_none_si_absent(self):
        self.assertIsNone(registry.find_agent("inconnu"))


class TestEtapeSuivante(AidlcTestCase):
    """next_agent_id : successeur de util.next_stage_id, dans l'ordre derive."""

    def test_renvoie_letape_suivante(self):
        self.assertEqual(registry.next_agent_id("plan"), "design")

    def test_renvoie_none_pour_la_derniere_etape(self):
        self.assertIsNone(registry.next_agent_id("design"))

    def test_renvoie_none_pour_un_identifiant_inconnu(self):
        self.assertIsNone(registry.next_agent_id("inconnu"))


class TestAgentForFile(AidlcTestCase):
    """L'agent dont le livrable est exactement ce fichier."""

    def test_trouve_lagent_par_chemin_exact(self):
        intent = self.plan_intent()
        self.assertEqual(registry.agent_for_file(self.root, str(intent))["id"], "plan")

    def test_renvoie_none_si_aucun_agent_ne_produit_ce_fichier(self):
        autre = self.write("ailleurs.md", "contenu")
        self.assertIsNone(registry.agent_for_file(self.root, str(autre)))

    def test_renvoie_none_si_le_chemin_est_invalide(self):
        marker = "chemin-marqueur-invalide"
        original_resolve = Path.resolve

        def flaky(path_self, *a, **kw):
            if str(path_self) == marker:
                raise OSError("simulated")
            return original_resolve(path_self, *a, **kw)

        with mock.patch.object(Path, "resolve", flaky):
            self.assertIsNone(registry.agent_for_file(self.root, marker))

    def test_ignore_une_etape_dont_le_livrable_resout_en_erreur(self):
        spec = self.write("deliverables/design/spec.md", "contenu design")
        plan_target = self.root / "deliverables" / "plan" / "intent.md"
        original_resolve = Path.resolve

        def flaky(path_self, *a, **kw):
            if path_self == plan_target:
                raise OSError("simulated")
            return original_resolve(path_self, *a, **kw)

        with mock.patch.object(Path, "resolve", flaky):
            found = registry.agent_for_file(self.root, str(spec))
        self.assertEqual(found["id"], "design")


class TestCacheMemoire(AidlcTestCase):
    """Le catalogue est memorise pour la duree du processus, jusqu'a un reset explicite
    ou un refresh demande."""

    def test_discover_memorise_le_resultat_jusqua_un_refresh_explicite(self):
        before = len(registry.discover()["agents"])
        self.write_json("plugins/aidlc-x/agent.json", manifest("x", "T"))
        self.assertEqual(len(registry.discover()["agents"]), before)
        self.assertEqual(len(registry.discover(refresh=True)["agents"]), before + 1)

    def test_reset_cache_oblige_une_nouvelle_decouverte(self):
        before = len(registry.discover()["agents"])
        self.write_json("plugins/aidlc-x/agent.json", manifest("x", "T"))
        registry.reset_cache()
        self.assertEqual(len(registry.discover()["agents"]), before + 1)
