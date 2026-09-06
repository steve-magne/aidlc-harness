from __future__ import annotations

import json
import os

from pathlib import Path

from .harness import AidlcTestCase
from .. import registry
from ..util import ensure_dir
from ..util import read_text
from ..scaffold import SCAFFOLD_SECTIONS
from ..scaffold import authoring_root
from ..scaffold import planned_stage
from ..scaffold import scaffold
from ..checks import contract_problems

"""Generation du plugin d'une etape planifiee : arborescence complete, inscription au
marketplace, et l'invariant central du depot -- le noyau n'est jamais modifie."""


class TestAuthoringRoot(AidlcTestCase):
    """La racine ou ecrire un nouveau plugin : jamais la copie installee."""

    def test_depot_auteur_directement_a_la_racine_du_harnais(self):
        """Dans les tests (et dans le depot auteur), AIDLC_HARNESS_ROOT porte deja
        plugins/ et le marketplace : authoring_root() ne remonte pas d'un cran."""
        self.assertEqual(authoring_root(), self.root)

    def test_copie_installee_remonte_a_la_racine_du_depot(self):
        """Quand la racine du harnais est .../plugins/aidlc-core (forme de la copie
        installee par Claude Code), authoring_root() remonte de deux crans jusqu'au
        depot qui porte le marketplace."""
        installed = self.root / "ailleurs" / "plugins" / "aidlc-core"
        ensure_dir(installed)
        os.environ["AIDLC_HARNESS_ROOT"] = str(installed)
        self.assertEqual(authoring_root(), self.root / "ailleurs")


class TestPlannedStage(AidlcTestCase):
    """La feuille de route consultative : un pre-remplissage, jamais une condition."""

    def test_etape_presente_rend_ses_champs(self):
        stage = planned_stage(self.pipeline, "design")
        self.assertEqual(stage["name"], "Design")
        self.assertEqual(stage["team"], "Architecture")

    def test_etape_absente_rend_un_dictionnaire_vide(self):
        self.assertEqual(planned_stage(self.pipeline, "inexistante"), {})

    def test_rend_une_copie_jamais_l_entree_partagee(self):
        stage = planned_stage(self.pipeline, "design")
        stage["name"] = "Sabotage"
        self.assertEqual(planned_stage(self.pipeline, "design")["name"], "Design")


class TestScaffoldArborescence(AidlcTestCase):
    """L'arborescence complete produite pour une etape prevue par planned_stages."""

    seed_agents = False

    def setUp(self):
        super().setUp()
        self.info = scaffold(self.pipeline, "design")
        self.plugin_dir = self.root / "plugins" / "aidlc-design"

    def test_cree_huit_fichiers_dont_le_manifeste_et_la_rubrique(self):
        self.assertEqual(len(self.info["created"]), 8)
        self.assertEqual(self.info["manifest"], "plugins/aidlc-design/agent.json")

    def test_plugin_json_est_du_json_valide_sans_accolades_residuelles(self):
        raw = self.read("plugins/aidlc-design/.claude-plugin/plugin.json")
        self.assertNotIn("{{", raw)
        data = json.loads(raw)
        self.assertEqual(data["name"], "aidlc-design")
        self.assertIn("deliverables/design/spec.md", data["description"])

    def test_agent_md_cite_le_role_et_le_livrable(self):
        content = self.read("plugins/aidlc-design/agents/design-analyst.md")
        self.assertIn("Architecte", content)
        self.assertIn("deliverables/design/spec.md", content)

    def test_skill_md_liste_les_inputs_de_l_etape(self):
        content = self.read("plugins/aidlc-design/skills/design/SKILL.md")
        self.assertIn("- `deliverables/plan/intent.md`", content)

    def test_gabarit_du_livrable_nomme_d_apres_le_deliverable(self):
        self.assertTrue((self.plugin_dir / "templates" / "spec.md").exists())
        self.assertEqual(self.info["template"], "spec.md")

    def test_checks_json_porte_les_sections_et_les_planchers_du_scaffold(self):
        checks = self.read_json("plugins/aidlc-design/checks.json")
        self.assertEqual(checks["required_sections"], SCAFFOLD_SECTIONS)
        self.assertEqual(checks["min_items_per_section"],
                          {"## Critères d'acceptation": 3, "## Contraintes": 2})
        self.assertTrue(checks["must_reference_inputs"],
                         "l'etape design a des inputs : ils doivent etre cites")

    def test_manifeste_reprend_la_feuille_de_route(self):
        manifest = self.read_json("plugins/aidlc-design/agent.json")
        self.assertEqual(manifest["team"], "Architecture")
        self.assertEqual(manifest["produces"], "deliverables/design/spec.md")
        self.assertEqual(manifest["consumes"], ["deliverables/plan/intent.md"])
        self.assertEqual(manifest["capabilities"], ["sdlc:design"])
        self.assertEqual(manifest["invocation"], {"claude-code": "aidlc-design:design"})

    def test_marketplace_cree_et_inscrit_le_plugin(self):
        market = self.read_json(".claude-plugin/marketplace.json")
        self.assertEqual(market["name"], "aidlc")
        entries = [p for p in market["plugins"] if p["name"] == "aidlc-design"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "./plugins/aidlc-design")

    def test_registre_voit_immediatement_le_nouvel_agent(self):
        """scaffold() vide le cache lui-meme : pas besoin de reset_cache manuel."""
        self.assertIsNotNone(registry.find_agent("design"))


class TestScaffoldSansEtapePrevue(AidlcTestCase):
    """Une etape absente de planned_stages nait quand meme, avec des valeurs par defaut."""

    seed_agents = False

    def test_valeurs_par_defaut_sans_input_ni_role_ni_equipe(self):
        info = scaffold(self.pipeline, "ops")
        self.assertEqual(info["template"], "ops.md")
        manifest = self.read_json("plugins/aidlc-ops/agent.json")
        self.assertEqual(manifest["produces"], "deliverables/ops/ops.md")
        self.assertEqual(manifest["consumes"], [])
        self.assertEqual(manifest["human_role"], "role metier a preciser")
        self.assertEqual(manifest["team"], "<equipe proprietaire de cet agent>")
        checks = self.read_json("plugins/aidlc-ops/checks.json")
        self.assertFalse(checks["must_reference_inputs"])
        skill = self.read("plugins/aidlc-ops/skills/ops/SKILL.md")
        self.assertIn("- Aucun input amont.", skill)
        template = self.read("plugins/aidlc-ops/templates/ops.md")
        self.assertIn("aucun", template)


class TestScaffoldErreurs(AidlcTestCase):
    """Cas d'erreur : jamais d'ecrasement silencieux, jamais de doublon."""

    def test_refuse_un_agent_deja_enregistre_sans_force(self):
        with self.assertRaises(ValueError) as ctx:
            scaffold(self.pipeline, "design")
        self.assertIn("--force", str(ctx.exception))

    def test_force_ecrase_l_agent_deja_enregistre(self):
        avant = read_text(self.root / "plugins/aidlc-design/checks.json")
        info = scaffold(self.pipeline, "design", force=True)
        apres = read_text(self.root / "plugins/aidlc-design/checks.json")
        self.assertEqual(info["stage"], "design")
        # le scaffold regenere le contrat generique : il n'est plus celui de la fixture
        self.assertNotEqual(avant, apres)

    def test_refuse_un_repertoire_deja_present_meme_sans_manifeste(self):
        """Le repertoire du plugin existe (autre chose qu'un agent) : le registre ne le
        voit pas, mais le scaffold doit tout de meme refuser d'ecrire dedans."""
        orphelin = self.root / "plugins" / "aidlc-ops"
        self.write("plugins/aidlc-ops/README.txt", "rien a voir")
        self.assertIsNone(registry.find_agent("ops"))
        with self.assertRaises(ValueError) as ctx:
            scaffold(self.pipeline, "ops")
        self.assertIn(str(orphelin.name), str(ctx.exception))
        self.assertIn("--force", str(ctx.exception))

    def test_force_construit_quand_meme_dans_un_repertoire_orphelin(self):
        self.write("plugins/aidlc-ops/README.txt", "rien a voir")
        scaffold(self.pipeline, "ops", force=True)
        self.assertTrue((self.root / "plugins/aidlc-ops/agent.json").exists())

    def test_le_noyau_n_est_jamais_modifie(self):
        """Invariant central du depot (scenario 20 de l'ancien selftest) : meme un
        scaffold --force sur un agent deja enregistre n'ecrit rien dans pipeline.json.
        Une equipe publie son agent sans jamais toucher a l'orchestrateur."""
        avant = read_text(self.root / "pipeline.json")
        scaffold(self.pipeline, "design", force=True)
        apres = read_text(self.root / "pipeline.json")
        self.assertEqual(avant, apres)


class TestScaffoldMarketplace(AidlcTestCase):
    """L'inscription au marketplace : ni doublon, ni ecrasement d'une entree existante."""

    seed_agents = False

    def test_n_inscrit_pas_deux_fois_la_meme_entree(self):
        self.write_json(".claude-plugin/marketplace.json",
                        {"name": "aidlc", "owner": {"name": "Steve"},
                         "plugins": [{"name": "aidlc-design", "source": "deja-la",
                                      "description": "entree preexistante"}]})
        scaffold(self.pipeline, "design")
        market = self.read_json(".claude-plugin/marketplace.json")
        entries = [p for p in market["plugins"] if p["name"] == "aidlc-design"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["source"], "deja-la",
                         "une entree deja presente n'est jamais reecrite")

    def test_marketplace_malforme_leve_une_erreur_explicite(self):
        """Un marketplace.json illisible est une erreur d'auteur, pas un plantage :
        meme forme que les deux autres gardes de scaffold — un ValueError qui nomme
        le fichier et le geste correctif, que cmd_scaffold rend sur stderr."""
        self.write(".claude-plugin/marketplace.json", "{ceci n'est pas du json")
        with self.assertRaises(ValueError) as raised:
            scaffold(self.pipeline, "design")
        message = str(raised.exception)
        self.assertIn("marketplace.json", message)
        self.assertIn("illisible", message)

    def test_marketplace_malforme_ne_laisse_aucun_plugin_a_moitie_genere(self):
        """Le marketplace est lu avant la moindre ecriture : un scaffold qui echoue
        ne laisse pas derriere lui un plugin partiel que le registre decouvrirait."""
        self.write(".claude-plugin/marketplace.json", "{ceci n'est pas du json")
        with self.assertRaises(ValueError):
            scaffold(self.pipeline, "design")
        self.assertFalse((self.root / "plugins/aidlc-design/agent.json").exists())
        self.assertFalse((self.root / "plugins/aidlc-design/checks.json").exists())

    def test_marketplace_malforme_rend_un_message_humain_et_exit_1(self):
        """Bout en bout : le contrat CLI de cette erreur — rien sur stdout, un
        message francais sur stderr, code 1."""
        self.write(".claude-plugin/marketplace.json", "{ceci n'est pas du json")
        result = self.run_cli("scaffold", "design")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("illisible", result.stderr)


class TestScaffoldRubriqueEtContrat(AidlcTestCase):
    """Le plugin genere doit etre coherent des la premiere seconde : gabarit et
    checks.json sont ecrits ensemble, ils ne doivent jamais diverger, et la rubrique de
    revue de l'equipe est posee avec le reste."""

    seed_agents = False

    def setUp(self):
        super().setUp()
        self.info = scaffold(self.pipeline, "design")

    def test_la_rubrique_de_revue_de_l_equipe_est_creee(self):
        self.assertTrue((self.root / "plugins/aidlc-design/review.md").exists())

    def test_le_manifeste_genere_designe_la_rubrique_de_revue(self):
        self.assertEqual(self.read_json("plugins/aidlc-design/agent.json")["review"],
                         "review.md")

    def test_un_plugin_fraichement_scaffolde_passe_le_controle_de_contrat(self):
        """Le test qui compte : gabarit et contrat generes ensemble ne divergent pas.
        Sans lui, `scaffold` pourrait produire un plugin que `agents --strict` refuse."""
        registry.reset_cache()
        self.assertEqual(contract_problems(registry.find_agent("design")), [])
