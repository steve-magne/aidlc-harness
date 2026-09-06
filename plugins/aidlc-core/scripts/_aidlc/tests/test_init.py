from __future__ import annotations

import json
import unittest.mock

from pathlib import Path

from .. import registry
from .harness import AidlcTestCase
from ..util import PROJECT_CONFIG
from ..init import compose_workflow
from ..init import GITIGNORE_LINES
from ..init import _gitignore_additions
from ..init import config_problems
from ..init import init_project
from ..init import render_concept
from ..init import render_config
from ..init import render_init
from ..init import scan_sources
from ..okf import okf_report

"""Amorcage d'un projet consommateur : inventaire du depot d'accueil, gouvernance de
projet, bundle OKF pose conforme, et relecture de l'aidlc.json ecrit a la main."""


class TestScanSources(AidlcTestCase):
    """L'inventaire du depot d'accueil : des chemins, jamais un contenu."""

    def test_un_projet_nu_ne_rend_aucune_source(self):
        found = scan_sources(self.root)
        self.assertEqual(found, {"documentation": [], "manifests": [], "decisions": []})

    def test_le_readme_de_la_racine_est_inventorie(self):
        self.write("README.md", "# Le projet")
        self.assertEqual(scan_sources(self.root)["documentation"], ["README.md"])

    def test_un_manifeste_de_dependances_dit_la_pile_technique(self):
        self.write("pyproject.toml", "[project]\nname = 'facturation'\n")
        self.assertEqual(scan_sources(self.root)["manifests"], ["pyproject.toml"])

    def test_les_documents_d_un_dossier_de_docs_sont_inventories(self):
        self.write("docs/adr-0001-choix-du-socle.md", "# ADR 1")
        self.assertEqual(scan_sources(self.root)["decisions"],
                         ["docs/adr-0001-choix-du-socle.md"])

    def test_un_fichier_non_documentaire_du_dossier_docs_est_ignore(self):
        self.write("docs/schema.png", "binaire")
        self.assertEqual(scan_sources(self.root)["decisions"], [])

    def test_un_sous_dossier_de_docs_n_est_pas_parcouru_recursivement(self):
        self.write("docs/archive/vieux.md", "# vieux")
        self.assertEqual(scan_sources(self.root)["decisions"], [])

    def test_un_dossier_de_docs_illisible_ne_fait_pas_echouer_l_inventaire(self):
        self.write("docs/adr.md", "# ADR")
        with unittest.mock.patch.object(Path, "iterdir", side_effect=OSError("EACCES")):
            self.assertEqual(scan_sources(self.root)["decisions"], [])

    def test_l_inventaire_est_trie_donc_reproductible(self):
        self.write("docs/b.md", "b")
        self.write("docs/a.md", "a")
        self.assertEqual(scan_sources(self.root)["decisions"], ["docs/a.md", "docs/b.md"])


class TestRenderConcept(AidlcTestCase):
    """Le concept OKF de l'inventaire : des liens relatifs traversables."""

    def test_les_sources_sont_liees_depuis_le_dossier_sources_du_bundle(self):
        rendered = render_concept({"documentation": ["README.md"], "manifests": [],
                                   "decisions": []}, "2026-09-06T00:00:00+00:00")
        self.assertIn("* [README.md](../../README.md)", rendered)

    def test_une_famille_vide_le_dit_au_lieu_de_disparaitre(self):
        rendered = render_concept({"documentation": [], "manifests": [], "decisions": []},
                                  "2026-09-06T00:00:00+00:00")
        self.assertEqual(rendered.count("Aucun fichier de cette famille"), 3)

    def test_les_trois_familles_ont_chacune_leur_titre(self):
        rendered = render_concept({"documentation": [], "manifests": [], "decisions": []},
                                  "2026-09-06T00:00:00+00:00")
        for title in ("## Documentation du dépôt", "## Pile technique déclarée",
                      "## Documentation et decisions"):
            self.assertIn(title, rendered)


class TestRenderConfig(AidlcTestCase):
    """La gouvernance du projet est recopiee, pas laissee implicite."""

    def test_les_seuils_du_harnais_sont_recopies_pour_etre_discutables(self):
        config = render_config({"maturity_threshold": 4.5, "min_axis_score": 3.5,
                                "consecutive_runs_to_autonomy": 5}, ["plan"])
        self.assertEqual(config["maturity_threshold"], 4.5)
        self.assertEqual(config["min_axis_score"], 3.5)
        self.assertEqual(config["consecutive_runs_to_autonomy"], 5)

    def test_les_agents_decouverts_composent_le_workflow_declare(self):
        self.assertEqual(render_config({}, ["plan", "design"])["agents"],
                         ["plan", "design"])

    def test_une_gouvernance_muette_retombe_sur_les_defauts_du_moteur(self):
        config = render_config({}, [])
        self.assertEqual(config["maturity_threshold"], 4.0)
        self.assertEqual(config["planned_stages"], [])

    def test_une_etape_deja_installee_sort_de_la_feuille_de_route(self):
        """Ce qui est prevu, c'est ce qu'il reste a installer. Recopier `design` en
        « prevu » alors que son plugin est la ferait lire au projet une feuille de route
        qui decrit son present."""
        pipe = {"planned_stages": [{"id": "design"}, {"id": "build"}]}
        config = render_config(pipe, ["plan", "design"])
        self.assertEqual([s["id"] for s in config["planned_stages"]], ["build"])


class TestGitignore(AidlcTestCase):
    def test_sans_gitignore_les_deux_caches_sont_a_ajouter(self):
        self.assertEqual(_gitignore_additions(self.root), list(GITIGNORE_LINES))

    def test_une_ligne_deja_presente_n_est_pas_reproposee(self):
        self.write(".gitignore", ".aidlc/tmp/\n")
        self.assertEqual(_gitignore_additions(self.root), [".aidlc/logs/"])

    def test_un_gitignore_complet_ne_propose_plus_rien(self):
        self.write(".gitignore", "\n".join(GITIGNORE_LINES) + "\n")
        self.assertEqual(_gitignore_additions(self.root), [])


class TestInitProject(AidlcTestCase):
    """L'amorcage pose la table et ne detruit jamais rien."""

    def test_les_fichiers_d_amorcage_sont_crees(self):
        result = init_project(self.root, self.pipeline)
        for rel in ("aidlc.json", "deliverables/.gitkeep", "knowledge-sources.json",
                    "knowledge/index.md", "knowledge/log.md",
                    "knowledge/sources/projet-existant.md"):
            self.assertIn(rel, result["created"])
            self.assertTrue((self.root / rel).exists(), rel)

    def test_le_bundle_pose_est_conforme_okf_v0_2(self):
        init_project(self.root, self.pipeline)
        report = okf_report(self.root / "knowledge")
        self.assertTrue(report["ok"], report["errors"])

    def test_la_gouvernance_posee_declare_les_agents_decouverts(self):
        init_project(self.root, self.pipeline)
        self.assertEqual(self.read_json("aidlc.json")["agents"], ["plan", "design"])

    def test_la_gouvernance_posee_est_relue_par_le_moteur(self):
        init_project(self.root, self.pipeline)
        self.assertEqual(config_problems(self.root), [])

    def test_un_fichier_existant_est_garde_tel_quel(self):
        self.write_json("aidlc.json", {"maturity_threshold": 2.0})
        result = init_project(self.root, self.pipeline)
        self.assertIn("aidlc.json", result["kept"])
        self.assertNotIn("aidlc.json", result["created"])
        self.assertEqual(self.read_json("aidlc.json")["maturity_threshold"], 2.0)

    def test_relancer_l_amorcage_ne_cree_plus_rien(self):
        init_project(self.root, self.pipeline)
        second = init_project(self.root, self.pipeline)
        self.assertEqual(second["created"], [])
        self.assertIn("knowledge/index.md", second["kept"])

    def test_les_caches_jetables_sont_ajoutes_au_gitignore(self):
        init_project(self.root, self.pipeline)
        content = self.read(".gitignore")
        for line in GITIGNORE_LINES:
            self.assertIn(line, content)

    def test_un_gitignore_existant_est_complete_sans_etre_ecrase(self):
        self.write(".gitignore", "node_modules/\n")
        init_project(self.root, self.pipeline)
        content = self.read(".gitignore")
        self.assertIn("node_modules/", content)
        self.assertIn(".aidlc/logs/", content)

    def test_un_gitignore_deja_complet_n_est_pas_touche(self):
        self.write(".gitignore", "\n".join(GITIGNORE_LINES) + "\n")
        result = init_project(self.root, self.pipeline)
        self.assertFalse(any(rel.startswith(".gitignore") for rel in result["created"]))

    def test_les_sources_du_projet_existant_entrent_dans_le_concept(self):
        self.write("README.md", "# Facturation")
        self.write("go.mod", "module facturation")
        init_project(self.root, self.pipeline)
        concept = self.read("knowledge/sources/projet-existant.md")
        self.assertIn("../../README.md", concept)
        self.assertIn("../../go.mod", concept)

    def test_l_inventaire_est_rendu_dans_le_resultat(self):
        self.write("README.md", "# Facturation")
        result = init_project(self.root, self.pipeline)
        self.assertEqual(result["sources"]["documentation"], ["README.md"])

    def test_le_resultat_nomme_le_fichier_de_gouvernance_pose(self):
        self.assertEqual(init_project(self.root, self.pipeline)["config"], "aidlc.json")


class TestRenderInit(AidlcTestCase):
    """Le compte rendu dit ce qui vient de changer chez l'utilisateur."""

    def test_le_rendu_distingue_ce_qui_est_cree_de_ce_qui_est_garde(self):
        self.write_json("aidlc.json", {})
        rendered = render_init(init_project(self.root, self.pipeline))
        self.assertIn("créé   knowledge/index.md", rendered)
        self.assertIn("gardé  aidlc.json", rendered)

    def test_le_rendu_annonce_le_workflow_declare(self):
        rendered = render_init(init_project(self.root, self.pipeline))
        self.assertIn("Workflow déclaré dans aidlc.json : plan, design", rendered)

    def test_le_rendu_compte_les_sources_inventoriees(self):
        self.write("README.md", "# Projet")
        self.write("package.json", "{}")
        rendered = render_init(init_project(self.root, self.pipeline))
        self.assertIn("2 source(s)", rendered)


class TestConfigProblems(AidlcTestCase):
    """Une cle mal orthographiee dans aidlc.json ferait tourner le projet sur les
    seuils du harnais en croyant tenir les siens."""

    def test_sans_fichier_il_n_y_a_aucun_probleme(self):
        self.assertEqual(config_problems(self.root), [])

    def test_un_json_invalide_est_signale(self):
        self.write("aidlc.json", "{ pas du json")
        self.assertTrue(any("JSON invalide" in p for p in config_problems(self.root)))

    def test_un_json_qui_n_est_pas_un_objet_est_signale(self):
        self.write("aidlc.json", json.dumps([1, 2, 3]))
        self.assertTrue(any("objet JSON" in p for p in config_problems(self.root)))

    def test_une_cle_inconnue_est_signalee_comme_ignoree(self):
        self.write_json("aidlc.json", {"maturity_treshold": 3.0})
        self.assertTrue(any("maturity_treshold" in p
                            for p in config_problems(self.root)))

    def test_une_cle_de_commentaire_est_toleree(self):
        self.write_json("aidlc.json", {"_comment": "notre exigence"})
        self.assertEqual(config_problems(self.root), [])

    def test_agents_doit_etre_une_liste(self):
        self.write_json("aidlc.json", {"agents": "plan"})
        self.assertTrue(any("'agents' doit etre une liste" in p
                            for p in config_problems(self.root)))

    def test_un_seuil_non_numerique_est_signale(self):
        self.write_json("aidlc.json", {"maturity_threshold": "quatre"})
        self.assertTrue(any("maturity_threshold" in p
                            for p in config_problems(self.root)))

    def test_un_plancher_non_numerique_est_signale(self):
        self.write_json("aidlc.json", {"min_axis_score": None})
        self.assertTrue(any("min_axis_score" in p
                            for p in config_problems(self.root)))

    def test_une_gouvernance_valide_ne_remonte_rien(self):
        self.write_json("aidlc.json", {"maturity_threshold": 3.5, "agents": ["plan"]})
        self.assertEqual(config_problems(self.root), [])


class TestRenderInitSansAgent(AidlcTestCase):
    """Projet nu : aucun plugin d'agent installe, aucun manifeste decouvert."""

    seed_agents = False

    def test_sans_aucun_agent_le_rendu_dit_quoi_faire(self):
        rendered = render_init(init_project(self.root, self.pipeline))
        self.assertIn("Aucun agent découvert", rendered)

    def test_le_workflow_declare_reste_vide_plutot_qu_invente(self):
        init_project(self.root, self.pipeline)
        self.assertEqual(self.read_json("aidlc.json")["agents"], [])


class TestCompositionDuWorkflow(AidlcTestCase):
    """« Voici les agents de nos equipes, voici notre chaine » — le geste d'entree.

    Il se faisait en editant aidlc.json a la main : le garde-fou l'interdit a un agent,
    ce qui est juste, mais n'obligeait pas a le laisser sans outil."""

    def setUp(self):
        super().setUp()
        self.write_json(PROJECT_CONFIG,
                        {"_comment": "garde-moi", "maturity_threshold": 4.0,
                         "agents": ["plan"]})

    def test_un_agent_decouvert_se_branche(self):
        result = compose_workflow(self.root, add=["design"])
        self.assertEqual(result["agents"], ["plan", "design"])

    def test_l_ajout_est_ecrit_dans_la_gouvernance(self):
        compose_workflow(self.root, add=["design"])
        self.assertEqual(self.read_json(PROJECT_CONFIG)["agents"], ["plan", "design"])

    def test_les_cles_etrangeres_du_fichier_sont_preservees(self):
        # Relire par project_config (qui filtre sur PROJECT_KEYS) puis reecrire
        # amputerait le fichier du commentaire et de toute cle propre a l'equipe.
        compose_workflow(self.root, add=["design"])
        self.assertEqual(self.read_json(PROJECT_CONFIG)["_comment"], "garde-moi")

    def test_un_agent_se_retire(self):
        result = compose_workflow(self.root, remove=["plan"])
        self.assertEqual(result["agents"], [])

    def test_retirer_un_producteur_avertit_ceux_qui_le_consomment(self):
        compose_workflow(self.root, add=["design"])
        result = compose_workflow(self.root, remove=["plan"])
        self.assertIn("design", " ".join(result["warnings"]))

    def test_un_agent_inconnu_du_registre_est_refuse(self):
        with self.assertRaises(ValueError):
            compose_workflow(self.root, add=["fantome"])

    def test_le_refus_liste_ce_qui_est_disponible(self):
        with self.assertRaises(ValueError) as caught:
            compose_workflow(self.root, add=["fantome"])
        self.assertIn("design", str(caught.exception))

    def test_un_agent_deja_branche_ne_double_pas_la_liste(self):
        result = compose_workflow(self.root, add=["plan"])
        self.assertEqual(result["agents"], ["plan"])

    def test_ajouter_un_agent_deja_branche_le_dit(self):
        result = compose_workflow(self.root, add=["plan"])
        self.assertIn("composait déjà", " ".join(result["warnings"]))

    def test_retirer_un_agent_absent_le_dit(self):
        result = compose_workflow(self.root, remove=["design"])
        self.assertIn("ne composait pas", " ".join(result["warnings"]))

    def test_sans_gouvernance_la_commande_renvoie_vers_init(self):
        (self.root / PROJECT_CONFIG).unlink()
        with self.assertRaises(ValueError) as caught:
            compose_workflow(self.root, add=["design"])
        self.assertIn("init", str(caught.exception))

    def test_le_registre_est_relu_apres_ecriture(self):
        # Sans invalidation du cache, `status` juste apres montrerait l'ancien workflow.
        compose_workflow(self.root, add=["design"])
        self.assertIn("design", [agent["id"] for agent in registry.agents_list()])


class TestNommerLInitiative(AidlcTestCase):
    """Un projet vit plus longtemps qu'une idee : la seconde n'ecrase pas la premiere."""

    def setUp(self):
        super().setUp()
        self.write_json(PROJECT_CONFIG, {"agents": ["plan", "design"]})

    def test_l_initiative_est_ecrite_dans_la_gouvernance(self):
        compose_workflow(self.root, initiative="reco-panier")
        self.assertEqual(self.read_json(PROJECT_CONFIG)["initiative"], "reco-panier")

    def test_le_changement_annonce_ou_partent_les_livrables(self):
        result = compose_workflow(self.root, initiative="reco-panier")
        self.assertIn("deliverables/reco-panier/", " ".join(result["warnings"]))

    def test_une_chaine_vide_revient_a_plat(self):
        compose_workflow(self.root, initiative="reco-panier")
        compose_workflow(self.root, initiative="")
        self.assertNotIn("initiative", self.read_json(PROJECT_CONFIG))

    def test_le_retour_a_plat_ne_promet_pas_un_chemin_vide(self):
        compose_workflow(self.root, initiative="reco-panier")
        result = compose_workflow(self.root, initiative="")
        self.assertIn("retour à plat", " ".join(result["warnings"]))

    def test_un_nom_reserve_sous_aidlc_est_refuse(self):
        # « logs » rendrait l'etat runtime indiscernable de la garde qui le protege.
        with self.assertRaises(ValueError):
            compose_workflow(self.root, initiative="logs")

    def test_renommer_a_l_identique_ne_change_rien(self):
        compose_workflow(self.root, initiative="reco")
        result = compose_workflow(self.root, initiative="reco")
        self.assertEqual(result["changed"], [])

    def test_les_livrables_suivent_l_initiative(self):
        compose_workflow(self.root, initiative="reco")
        self.assertEqual(registry.find_agent("plan")["produces"],
                         "deliverables/reco/plan/intent.md")

