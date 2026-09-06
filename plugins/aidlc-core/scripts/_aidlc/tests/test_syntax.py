from __future__ import annotations

import os

from .harness import AidlcTestCase
from ..syntax import json_report
from ..syntax import python_report

"""Hygiene syntaxique du depot (regle 6) : python_report et json_report sont des
rapports purs, sans sortie ni ecriture. Chaque test isole son propre sous-repertoire
`scan/` sous la racine temporaire pour que le compte de fichiers ne soit jamais
perturbe par pipeline.json ou les manifestes d'agents ecrits par le socle."""


class TestPythonReport(AidlcTestCase):
    """python_report : tout le Python sous un repertoire compile-t-il ?"""

    seed_agents = False

    def test_repertoire_vide_est_conforme(self):
        vide = self.root / "vide"
        vide.mkdir()
        self.assertEqual(python_report(vide),
                         {"dir": str(vide), "ok": True, "checked": 0, "errors": []})

    def test_repertoire_inexistant_est_conforme_sans_rien_verifier(self):
        report = python_report(self.root / "absent")
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 0)

    def test_fichiers_conformes_sont_tous_comptes_y_compris_en_sous_repertoire(self):
        self.write("scan/a.py", "x = 1\n")
        self.write("scan/sous/b.py", "y = 2\n")
        report = python_report(self.root / "scan")
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 2)
        self.assertEqual(report["errors"], [])

    def test_fichier_casse_est_nomme_avec_sa_ligne(self):
        self.write("scan/bon.py", "x = 1\n")
        self.write("scan/casse.py", "def casse(:\n")
        report = python_report(self.root / "scan")
        self.assertFalse(report["ok"])
        self.assertEqual(report["checked"], 2)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["errors"][0],
                         "casse.py : erreur de syntaxe ligne 1 : invalid syntax")

    def test_plusieurs_fichiers_casses_sont_tous_rapportes_en_ordre_trie(self):
        self.write("scan/b_casse.py", "def a(:\n")
        self.write("scan/a_casse.py", "def a(:\n")
        report = python_report(self.root / "scan")
        self.assertEqual(len(report["errors"]), 2)
        self.assertTrue(report["errors"][0].startswith("a_casse.py :"))
        self.assertTrue(report["errors"][1].startswith("b_casse.py :"))

    def test_repertoires_git_et_pycache_sont_ignores(self):
        self.write("scan/.git/objects/pack.py", "def a(:\n")
        self.write("scan/__pycache__/module.py", "def b(:\n")
        self.write("scan/ok.py", "x = 1\n")
        report = python_report(self.root / "scan")
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 1)

    def test_un_repertoire_non_liste_dans_skip_dirs_est_bien_parcouru(self):
        """SKIP_DIRS ne contient que .git et __pycache__ (commentaire du module :
        "on saute .git et __pycache__ et rien d'autre") : node_modules, par exemple,
        est parcouru comme n'importe quel autre sous-repertoire."""
        self.write("scan/node_modules/paquet/casse.py", "def a(:\n")
        report = python_report(self.root / "scan")
        self.assertFalse(report["ok"])
        self.assertEqual(report["checked"], 1)
        self.assertIn("node_modules", report["errors"][0])

    def test_sous_repertoire_propre_reste_conforme_meme_si_le_reste_est_casse(self):
        self.write("scan/casse.py", "def casse(:\n")
        self.write("scan/propre/ok.py", "x = 1\n")
        report = python_report(self.root / "scan" / "propre")
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 1)

    def test_encodage_non_utf8_est_signale_comme_erreur_de_syntaxe(self):
        scan = self.root / "scan"
        scan.mkdir(parents=True, exist_ok=True)
        (scan / "binaire.py").write_bytes(b"\xff\xfe garbage not utf8")
        report = python_report(scan)
        self.assertFalse(report["ok"])
        self.assertIn("binaire.py", report["errors"][0])
        self.assertIn("erreur de syntaxe ligne", report["errors"][0])

    def test_erreur_de_compilation_sans_numero_de_ligne_retombe_sur_le_message_brut(self):
        """Un octet nul dans la source leve un SyntaxError dont l'attribut `lineno`
        est None : la condition `detail.lineno` de _python_problem est fausse, la
        branche formattee ("erreur de syntaxe ligne N") ne s'applique pas et le
        message brut de l'exception est renvoye tel quel (str(exc))."""
        scan = self.root / "scan"
        scan.mkdir(parents=True, exist_ok=True)
        (scan / "nul.py").write_bytes(b"x = 1\x00\n")
        report = python_report(scan)
        self.assertFalse(report["ok"])
        self.assertIn("nul.py", report["errors"][0])
        self.assertNotIn("erreur de syntaxe ligne", report["errors"][0])
        self.assertIn("null bytes", report["errors"][0])

    def test_fichier_illisible_est_signale_sans_planter(self):
        """Un lien symbolique casse (cible absente) fait echouer py_compile par une
        OSError brute, hors de tout PyCompileError : la porte doit le nommer plutot
        que de laisser l'exception se propager et interrompre le rapport."""
        scan = self.root / "scan"
        scan.mkdir(parents=True, exist_ok=True)
        os.symlink(scan / "absent.py", scan / "lien-casse.py")
        report = python_report(scan)
        self.assertFalse(report["ok"])
        self.assertEqual(report["checked"], 1)
        self.assertIn("lien-casse.py", report["errors"][0])
        self.assertIn("illisible", report["errors"][0])


class TestJsonReport(AidlcTestCase):
    """json_report : tout le JSON sous un repertoire parse-t-il ?"""

    seed_agents = False

    def test_repertoire_vide_est_conforme(self):
        vide = self.root / "vide"
        vide.mkdir()
        self.assertEqual(json_report(vide),
                         {"dir": str(vide), "ok": True, "checked": 0, "errors": []})

    def test_repertoire_inexistant_est_conforme_sans_rien_verifier(self):
        report = json_report(self.root / "absent")
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 0)

    def test_fichiers_conformes_sont_tous_comptes_y_compris_en_sous_repertoire(self):
        self.write_json("scan/a.json", {"a": 1})
        self.write_json("scan/sous/b.json", [1, 2, 3])
        report = json_report(self.root / "scan")
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 2)
        self.assertEqual(report["errors"], [])

    def test_json_invalide_est_nomme_avec_ligne_et_colonne(self):
        self.write("scan/casse.json", '{"a": }\n')
        report = json_report(self.root / "scan")
        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"],
                         ["casse.json : JSON invalide ligne 1 colonne 7 : Expecting value"])

    def test_repertoires_git_et_pycache_sont_ignores(self):
        self.write("scan/.git/config.json", "{not json")
        self.write("scan/__pycache__/cache.json", "{not json")
        self.write_json("scan/ok.json", {"b": 2})
        report = json_report(self.root / "scan")
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 1)

    def test_sous_repertoire_propre_reste_conforme_meme_si_le_reste_est_casse(self):
        self.write("scan/casse.json", '{"a": }\n')
        self.write_json("scan/propre/ok.json", {"b": 1})
        report = json_report(self.root / "scan" / "propre")
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 1)

    def test_encodage_non_utf8_est_tolere_par_remplacement_de_caractere(self):
        """read_text decode en errors='replace' : un octet hors UTF-8 a l'interieur
        d'une valeur JSON devient un caractere de remplacement, jamais un crash de
        json_report (aucune UnicodeDecodeError ne remonte)."""
        scan = self.root / "scan"
        scan.mkdir(parents=True, exist_ok=True)
        (scan / "latin1.json").write_bytes(b'{"nom": "caf\xe9"}')
        report = json_report(scan)
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 1)

    def test_fichier_illisible_est_signale_sans_planter(self):
        """Meme scenario que pour Python : un lien symbolique casse fait echouer la
        lecture par une OSError, que le rapport doit nommer plutot que propager."""
        scan = self.root / "scan"
        scan.mkdir(parents=True, exist_ok=True)
        os.symlink(scan / "absent.json", scan / "lien-casse.json")
        report = json_report(scan)
        self.assertFalse(report["ok"])
        self.assertEqual(report["checked"], 1)
        self.assertIn("lien-casse.json", report["errors"][0])
        self.assertIn("illisible", report["errors"][0])
