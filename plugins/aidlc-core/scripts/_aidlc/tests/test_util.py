from __future__ import annotations

import json
import os

from pathlib import Path
from unittest import mock

from .harness import AidlcTestCase
from ..util import MAX_FIELD
from ..util import digest
from ..util import harness_root
from ..util import PROJECT_CONFIG
from ..util import load_pipeline
from ..util import project_config
from ..util import project_config_path
from ..util import now_iso
from ..util import sanitize_session_id
from ..util import truncate
from ..util import workspace_root
from .. import util as harness_module

"""Socle du moteur : resolution des deux racines, IO, troncature."""


class TestRoots(AidlcTestCase):
    """Les deux racines, resolues separement : le harnais porte pipeline.json, le
    projet consommateur porte deliverables/ et .aidlc/."""

    def test_workspace_suit_claude_project_dir(self):
        self.assertEqual(workspace_root(), self.root)

    def test_workspace_ignore_une_valeur_qui_n_est_pas_un_repertoire(self):
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.root / "nulle-part")
        self.assertEqual(workspace_root(), Path.cwd().resolve())

    def test_harness_root_prioritaire_sur_plugin_root(self):
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(self.root / "autre")
        self.assertEqual(harness_root(), self.root)

    def test_harness_root_suit_plugin_root_s_il_porte_le_pipeline(self):
        os.environ.pop("AIDLC_HARNESS_ROOT")
        plugin = self.root / "cache-plugin"
        self.write_json("cache-plugin/pipeline.json", {"version": 2})
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(plugin)
        self.assertEqual(harness_root(), plugin.resolve())

    def test_harness_root_ignore_un_plugin_root_sans_pipeline(self):
        """Repli sur l'auto-localisation : le script trouve le pipeline du depot."""
        os.environ.pop("AIDLC_HARNESS_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(self.root / "vide")
        self.assertTrue((harness_root() / "pipeline.json").exists())

    def test_sans_pipeline_nulle_part_le_repli_est_le_repertoire_du_moteur(self):
        """Repli ultime : aucune variable d'environnement utilisable et aucun
        pipeline.json en remontant l'arborescence. Le moteur doit rendre un chemin
        plutot que lever — c'est ce qui garde une invocation depuis un repertoire
        inattendu diagnosticable au lieu de la faire exploser."""
        os.environ.pop("AIDLC_HARNESS_ROOT")
        moteur = Path(harness_module.__file__).resolve().parent
        with mock.patch.object(Path, "exists", return_value=False):
            self.assertEqual(harness_root(), moteur.parent)

    def test_load_pipeline_lit_la_gouvernance_du_harnais(self):
        self.assertEqual(load_pipeline()["maturity_threshold"], 4.0)


class TestSessionId(AidlcTestCase):
    """L'identifiant de session nomme un fichier : il ne doit jamais s'evader."""

    def test_caracteres_hostiles_neutralises(self):
        self.assertEqual(sanitize_session_id("../../etc/passwd"), "______etc_passwd")

    def test_tronque_a_quatre_vingts_caracteres(self):
        self.assertEqual(len(sanitize_session_id("a" * 200)), 80)

    def test_accepte_une_valeur_non_texte(self):
        self.assertEqual(sanitize_session_id(42), "42")


class TestDigest(AidlcTestCase):
    """L'empreinte detecte qu'une entree amont a bouge depuis la revue de l'aval."""

    def test_empreinte_stable_et_courte(self):
        path = self.write("amont.md", "contenu")
        self.assertEqual(len(digest(path)), 16)
        self.assertEqual(digest(path), digest(path))

    def test_empreinte_change_avec_le_contenu(self):
        path = self.write("amont.md", "contenu")
        before = digest(path)
        path.write_text("contenu modifie", encoding="utf-8")
        self.assertNotEqual(before, digest(path))

    def test_fichier_absent_rend_une_empreinte_vide(self):
        self.assertEqual(digest(self.root / "absent.md"), "")

    def test_repertoire_rend_une_empreinte_vide_sans_lever(self):
        self.assertEqual(digest(self.root), "")


class TestTruncate(AidlcTestCase):
    """Les champs journalises sont plafonnes : un journal ne gonfle pas sans borne."""

    def test_texte_court_intact(self):
        self.assertEqual(truncate("court"), "court")

    def test_texte_long_tronque_et_marque(self):
        out = truncate("a" * (MAX_FIELD + 10))
        self.assertTrue(out.endswith(" ...[tronque]"))
        self.assertEqual(len(out), MAX_FIELD + len(" ...[tronque]"))

    def test_descend_dans_les_dictionnaires_et_plafonne_les_cles(self):
        out = truncate({str(i): "a" * (MAX_FIELD + 1) for i in range(60)})
        self.assertEqual(len(out), 50)
        self.assertTrue(all(v.endswith("[tronque]") for v in out.values()))

    def test_descend_dans_les_listes_et_plafonne_les_elements(self):
        self.assertEqual(len(truncate(["x"] * 60)), 50)

    def test_laisse_passer_les_scalaires_non_textuels(self):
        self.assertEqual(truncate(7), 7)
        self.assertIsNone(truncate(None))


class TestHorodatage(AidlcTestCase):
    def test_now_iso_est_en_utc_a_la_seconde(self):
        stamp = now_iso()
        self.assertTrue(stamp.endswith("+00:00"), stamp)
        self.assertNotIn(".", stamp)


class TestProjectConfig(AidlcTestCase):
    """La gouvernance du projet consommateur (aidlc.json), recouvrement du harnais.

    Sans elle, une initiative ne pouvait ni fixer son exigence ni declarer son workflow :
    les seuils vivaient dans la copie installee du harnais, que le garde-fou protege
    justement de toute ecriture. Un projet subissait donc le pipeline de la machine.
    """

    def test_sans_fichier_la_gouvernance_du_projet_est_vide(self):
        self.assertEqual(project_config(), {})

    def test_le_chemin_pointe_la_racine_du_projet(self):
        self.assertEqual(project_config_path(), self.root / PROJECT_CONFIG)

    def test_une_cle_reconnue_est_rendue(self):
        self.write_json(PROJECT_CONFIG, {"maturity_threshold": 3.5})
        self.assertEqual(project_config(), {"maturity_threshold": 3.5})

    def test_une_cle_inconnue_est_ecartee_et_ne_pollue_pas_la_gouvernance(self):
        self.write_json(PROJECT_CONFIG, {"maturity_treshold": 3.5, "agents": ["plan"]})
        self.assertEqual(project_config(), {"agents": ["plan"]})

    def test_un_json_invalide_remonte_au_lieu_d_etre_avale(self):
        self.write(PROJECT_CONFIG, "{ pas du json")
        with self.assertRaises(json.JSONDecodeError):
            project_config()

    def test_un_json_qui_n_est_pas_un_objet_remonte(self):
        self.write(PROJECT_CONFIG, "[1, 2]")
        with self.assertRaises(json.JSONDecodeError):
            project_config()


class TestPipelineRecouvert(AidlcTestCase):
    """load_pipeline rend la gouvernance **effective** : harnais recouvert par projet."""

    def test_sans_fichier_projet_la_gouvernance_est_celle_du_harnais(self):
        self.assertEqual(load_pipeline()["maturity_threshold"], 4.0)

    def test_le_projet_recouvre_le_seuil_du_harnais(self):
        self.write_json(PROJECT_CONFIG, {"maturity_threshold": 4.8})
        self.assertEqual(load_pipeline()["maturity_threshold"], 4.8)

    def test_une_cle_absente_du_projet_reste_celle_du_harnais(self):
        self.write_json(PROJECT_CONFIG, {"maturity_threshold": 4.8})
        self.assertEqual(load_pipeline()["consecutive_runs_to_autonomy"], 3)

    def test_le_projet_declare_sa_propre_feuille_de_route(self):
        self.write_json(PROJECT_CONFIG,
                        {"planned_stages": [{"id": "deploy", "name": "Deploy"}]})
        self.assertEqual([s["id"] for s in load_pipeline()["planned_stages"]], ["deploy"])
