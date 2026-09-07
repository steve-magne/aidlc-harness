from __future__ import annotations

import json

from .harness import AidlcTestCase
from .harness import manifest
from .. import doctor
from ..util import write_json

"""Diagnostic d'installation (_aidlc.doctor) : la derive entre un projet et la version
installee du harnais. Ce qui est teste ici, c'est ce que la passe VOIT — un harnais qui
bouge sous les pieds d'un projet ne casse rien sur le coup, il ment plus tard."""


class TestHarnessVersion(AidlcTestCase):
    """La version se lit dans le manifeste du plugin installe, jamais ailleurs."""

    def test_version_du_manifeste_est_lue(self):
        write_json(self.root / ".claude-plugin/plugin.json",
                   {"name": "aidlc", "version": "9.9.9"})
        self.assertEqual(doctor.harness_version(), "9.9.9")

    def test_manifeste_absent_rend_une_chaine_vide(self):
        self.assertEqual(doctor.harness_version(), "")

    def test_manifeste_illisible_rend_une_chaine_vide(self):
        path = self.root / ".claude-plugin/plugin.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ pas du json", encoding="utf-8")
        self.assertEqual(doctor.harness_version(), "")

    def test_manifeste_sans_version_rend_une_chaine_vide(self):
        write_json(self.root / ".claude-plugin/plugin.json", {"name": "aidlc"})
        self.assertEqual(doctor.harness_version(), "")


class TestProjetNonAmorce(AidlcTestCase):
    """Sans aidlc.json, rien ne peut fonctionner : c'est le seul bloquant qui a une
    reponse en un geste."""

    def test_config_absente_est_bloquante(self):
        report = doctor.diagnose(self.root, stamp=False)
        self.assertFalse(report["ok"])
        self.assertEqual(report["findings"][0]["severity"], "blocking")
        self.assertIn("aidlc.json", report["findings"][0]["message"])

    def test_le_correctif_propose_est_la_commande_d_amorcage(self):
        report = doctor.diagnose(self.root, stamp=False)
        self.assertIn("init", report["findings"][0]["fix"])


class TestGouvernanceDouteuse(AidlcTestCase):
    """Une cle mal orthographiee dans aidlc.json survit des trimestres : le projet
    tourne alors sur les seuils du harnais en croyant tenir les siens."""

    def test_cle_inconnue_est_un_ecart_pas_un_bloquant(self):
        write_json(self.root / "aidlc.json", {"seuil_de_maturite": 4.5})
        report = doctor.diagnose(self.root, stamp=False)
        self.assertTrue(report["ok"])
        self.assertTrue(any(f["severity"] == "warning" and "inconnue" in f["message"]
                            for f in report["findings"]))

    def test_config_saine_ne_produit_aucun_ecart_de_gouvernance(self):
        write_json(self.root / "aidlc.json", {"maturity_threshold": 4.0})
        report = doctor.diagnose(self.root, stamp=False)
        self.assertEqual([f for f in report["findings"] if "aidlc.json" in f["message"]],
                         [])


class TestAgentBrancheSansPlugin(AidlcTestCase):
    """Le cas qui motive la commande : une equipe retire son plugin, le workflow le
    reclame toujours, et la porte refuse sans jamais nommer la cause."""

    def test_agent_inconnu_du_registre_est_bloquant(self):
        write_json(self.root / "aidlc.json", {"agents": ["plan", "fantome"]})
        report = doctor.diagnose(self.root, stamp=False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("fantome" in f["message"] for f in report["findings"]))

    def test_le_correctif_nomme_la_commande_de_debranchement(self):
        write_json(self.root / "aidlc.json", {"agents": ["fantome"]})
        report = doctor.diagnose(self.root, stamp=False)
        fix = next(f["fix"] for f in report["findings"] if "fantome" in f["message"])
        self.assertIn("workflow --remove fantome", fix)

    def test_agents_tous_installes_ne_bloquent_rien(self):
        write_json(self.root / "aidlc.json", {"agents": ["plan", "design"]})
        report = doctor.diagnose(self.root, stamp=False)
        self.assertTrue(report["ok"], report["findings"])


class TestContratIncoherent(AidlcTestCase):
    """Un contrat casse est un bloquant qui appartient a une AUTRE equipe : le
    diagnostic doit nommer laquelle, sinon il envoie corriger au mauvais endroit."""

    def test_contrat_absent_est_bloquant(self):
        self.write_agent("aidlc-nu", manifest("nu", "Equipe Nue",
                                              "deliverables/nu/doc.md"))
        write_json(self.root / "aidlc.json", {"agents": ["nu"]})
        report = doctor.diagnose(self.root, stamp=False)
        self.assertFalse(report["ok"])

    def test_le_correctif_nomme_l_equipe_proprietaire(self):
        self.write_agent("aidlc-nu", manifest("nu", "Equipe Nue",
                                              "deliverables/nu/doc.md"))
        write_json(self.root / "aidlc.json", {"agents": ["nu"]})
        report = doctor.diagnose(self.root, stamp=False)
        self.assertTrue(any("Equipe Nue" in f["fix"] for f in report["findings"]))


class TestLivrableOrphelin(AidlcTestCase):
    """Une equipe change le `produces` de son agent : l'ancien fichier reste, et plus
    personne ne sait lequel des deux fait foi."""

    def test_fichier_qu_aucun_manifeste_ne_reclame_est_signale(self):
        write_json(self.root / "aidlc.json", {"agents": ["plan"]})
        self.write("deliverables/plan/ancien-intent.md", "un livrable d'avant")
        report = doctor.diagnose(self.root, stamp=False)
        self.assertTrue(any("ancien-intent.md" in f["message"]
                            for f in report["findings"]))

    def test_livrable_declare_n_est_pas_signale(self):
        write_json(self.root / "aidlc.json", {"agents": ["plan"]})
        self.plan_intent()
        report = doctor.diagnose(self.root, stamp=False)
        self.assertEqual([f for f in report["findings"] if "intent.md" in f["message"]],
                         [])

    def test_fichier_cache_n_est_pas_un_orphelin(self):
        write_json(self.root / "aidlc.json", {"agents": ["plan"]})
        self.write("deliverables/.gitkeep", "")
        report = doctor.diagnose(self.root, stamp=False)
        self.assertEqual(report["findings"], [])

    def test_sans_dossier_de_livrables_la_passe_ne_signale_rien(self):
        write_json(self.root / "aidlc.json", {})
        self.assertEqual(doctor.diagnose(self.root, stamp=False)["findings"], [])

    def test_l_initiative_deplace_le_dossier_inspecte(self):
        """Sans le decalage, le diagnostic signalerait comme orphelins les livrables
        de l'initiative precedente, et raterait ceux de la courante."""
        write_json(self.root / "aidlc.json",
                   {"agents": ["plan"], "initiative": "reco-panier"})
        self.write("deliverables/reco-panier/plan/vieux.md", "orphelin de l'initiative")
        report = doctor.diagnose(self.root, stamp=False)
        self.assertTrue(any("vieux.md" in f["message"] for f in report["findings"]))


class TestBundleOkf(AidlcTestCase):
    """Un bundle non conforme est un ecart, pas un bloquant : le pipeline tourne."""

    def test_bundle_casse_est_signale_avec_la_commande_de_detail(self):
        write_json(self.root / "aidlc.json", {})
        self.write("knowledge/concept.md", "Aucun frontmatter ici.\n")
        report = doctor.diagnose(self.root, stamp=False)
        finding = next(f for f in report["findings"] if "knowledge/" in f["message"])
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("check-okf knowledge", finding["fix"])

    def test_bundle_absent_n_est_pas_un_ecart(self):
        write_json(self.root / "aidlc.json", {})
        self.assertEqual(doctor.diagnose(self.root, stamp=False)["findings"], [])


class TestEmpreinteDeVersion(AidlcTestCase):
    """La version vue au dernier passage est ce qui permet de dire « le harnais a
    change depuis » — sans elle, une mise a jour du plugin est invisible."""

    def setUp(self):
        super().setUp()
        write_json(self.root / ".claude-plugin/plugin.json", {"version": "1.0.0"})
        write_json(self.root / "aidlc.json", {})

    def test_premier_passage_date_la_version_sans_rien_signaler(self):
        report = doctor.diagnose(self.root)
        self.assertEqual(report["findings"], [])
        self.assertEqual(
            json.loads(doctor.stamp_path(self.root).read_text())["version"], "1.0.0")

    def test_version_inchangee_ne_dit_rien(self):
        doctor.diagnose(self.root)
        self.assertEqual(doctor.diagnose(self.root)["findings"], [])

    def test_version_changee_est_signalee_en_info(self):
        doctor.diagnose(self.root)
        write_json(self.root / ".claude-plugin/plugin.json", {"version": "2.0.0"})
        report = doctor.diagnose(self.root)
        self.assertTrue(report["ok"])
        finding = report["findings"][0]
        self.assertEqual(finding["severity"], "info")
        self.assertIn("1.0.0", finding["message"])
        self.assertIn("2.0.0", finding["message"])

    def test_no_stamp_laisse_l_empreinte_intacte(self):
        doctor.diagnose(self.root)
        write_json(self.root / ".claude-plugin/plugin.json", {"version": "2.0.0"})
        doctor.diagnose(self.root, stamp=False)
        self.assertEqual(
            json.loads(doctor.stamp_path(self.root).read_text())["version"], "1.0.0")

    def test_empreinte_illisible_est_ignoree_sans_lever(self):
        path = doctor.stamp_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ pas du json", encoding="utf-8")
        self.assertEqual(doctor.diagnose(self.root, stamp=False)["findings"], [])

    def test_l_empreinte_ne_suit_jamais_l_initiative(self):
        """Elle date le harnais, pas une idee du projet : la ranger sous l'initiative
        ferait croire a une mise a jour a chaque changement d'idee."""
        write_json(self.root / "aidlc.json", {"initiative": "reco-panier"})
        doctor.diagnose(self.root)
        self.assertTrue((self.root / ".aidlc/harness.json").is_file())
        self.assertFalse((self.root / ".aidlc/reco-panier/harness.json").is_file())


class TestOrdreEtRendu(AidlcTestCase):
    """Le rendu humain est ce que l'utilisateur lit : il montre les gestes, il ne les
    joue pas."""

    def test_les_bloquants_arrivent_en_tete(self):
        write_json(self.root / "aidlc.json", {"agents": ["fantome"],
                                              "cle_inconnue": 1})
        self.write("knowledge/concept.md", "Aucun frontmatter ici.\n")
        severites = [f["severity"]
                     for f in doctor.diagnose(self.root, stamp=False)["findings"]]
        self.assertEqual(severites, sorted(severites,
                                           key=doctor.SEVERITIES.index))

    def test_projet_sain_le_dit_en_clair(self):
        write_json(self.root / "aidlc.json", {})
        rendu = doctor.render(doctor.diagnose(self.root, stamp=False))
        self.assertIn("Rien a signaler", rendu)

    def test_le_rendu_montre_le_correctif_de_chaque_constat(self):
        rendu = doctor.render(doctor.diagnose(self.root, stamp=False))
        self.assertIn("BLOQUANT", rendu)
        self.assertIn("/aidlc init", rendu)

    def test_le_rendu_nomme_l_initiative_quand_il_y_en_a_une(self):
        write_json(self.root / "aidlc.json", {"initiative": "reco-panier"})
        rendu = doctor.render(doctor.diagnose(self.root, stamp=False))
        self.assertIn("reco-panier", rendu)

    def test_un_constat_sans_correctif_ne_rend_pas_de_ligne_vide(self):
        report = {"harness_version": "1.0.0", "project_root": "/x", "initiative": "",
                  "state_dir": "/x/.aidlc", "ok": True,
                  "findings": [{"severity": "info", "message": "un fait", "fix": ""}]}
        self.assertNotIn("      ->", doctor.render(report))
