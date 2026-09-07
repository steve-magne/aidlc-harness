from __future__ import annotations

import contextlib
import io
import json

from unittest.mock import patch
from pathlib import Path

from .harness import AidlcTestCase
from .harness import repo_root
from ..commands import cmd_check_okf
from ..improve import improve
from ..okf import OKF_RESERVED
from ..okf import _INDEX_LINK
from ..okf import _concept_front_values
from ..okf import _concept_title
from ..okf import _fallback_title
from ..okf import _flow_balanced
from ..okf import _frontmatter_shape_problems
from ..okf import _index_entry_line
from ..okf import _okf_proposals
from ..okf import _write_in_bundle
from ..okf import okf_bundle_errors
from ..okf import okf_frontmatter_fix
from ..okf import okf_index_proposal
from ..okf import okf_report
from ..okf import okf_split_frontmatter
from ..util import aidlc_dir
from ..util import read_text

"""Conformance OKF v0.2 des bundles de connaissance : decoupe du frontmatter, forme du
sous-ensemble YAML du depot, erreurs structurelles, correctifs proposes (frontmatter,
sommaire), et les commandes qui gatent un bundle (check-okf, ses modes --touched/--stop,
et leur remontee dans improve)."""


# --------------------------------------------------------------- okf_split_frontmatter

class TestOkfSplitFrontmatter(AidlcTestCase):
    """Decoupe (frontmatter, corps, etat) d'un fichier Markdown."""

    def test_texte_sans_marqueur_est_etat_absent(self):
        front, body, state = okf_split_frontmatter("# Titre\ncorps\n")
        self.assertEqual((front, state), ("", "absent"))
        self.assertEqual(body, "# Titre\ncorps\n")

    def test_marqueur_ouvrant_et_fermant_est_etat_ferme(self):
        front, body, state = okf_split_frontmatter("---\ntype: Reference\n---\ncorps\n")
        self.assertEqual(state, "ferme")
        self.assertEqual(front, "type: Reference")
        self.assertEqual(body, "corps")

    def test_marqueur_ouvrant_jamais_referme_est_etat_ouvert(self):
        front, body, state = okf_split_frontmatter("---\ntype: Reference\ncorps sans fin")
        self.assertEqual(state, "ouvert")
        self.assertEqual(front, "")
        self.assertEqual(body, "---\ntype: Reference\ncorps sans fin")


# -------------------------------------------------------------------- _flow_balanced

class TestFlowBalanced(AidlcTestCase):
    """Equilibre de [], {} et des guillemets dans une valeur de flux sur une ligne."""

    def test_flux_equilibre_est_accepte(self):
        self.assertTrue(_flow_balanced("[1, 2, {a: 1}]"))

    def test_parenthese_fermante_sans_ouverture_correspondante_est_refusee(self):
        self.assertFalse(_flow_balanced("(]"))

    def test_crochet_dans_une_chaine_entre_guillemets_est_ignore(self):
        # Le ']' entre guillemets ne doit pas etre compte comme une fermeture de flux :
        # le '[' d'ouverture ne se referme qu'au ']' final, hors guillemets.
        self.assertTrue(_flow_balanced('["a]b"]'))


# ----------------------------------------------------------- _frontmatter_shape_problems

class TestFrontmatterShapeProblems(AidlcTestCase):
    """Problemes de forme du sous-ensemble YAML autorise dans le frontmatter d'un bundle."""

    def test_frontmatter_conforme_ne_leve_aucun_probleme(self):
        self.assertEqual(_frontmatter_shape_problems("type: Reference\ntitle: X"), [])

    def test_ligne_vide_au_milieu_du_frontmatter_est_ignoree(self):
        self.assertEqual(
            _frontmatter_shape_problems("type: Reference\n\ndescription: X"), [])

    def test_valeur_de_flux_desequilibree_est_signalee(self):
        problems = _frontmatter_shape_problems("liste: [1, 2")
        self.assertEqual(len(problems), 1)
        self.assertIn("valeur de flux desequilibree", problems[0])

    def test_item_de_liste_desequilibre_est_signale(self):
        problems = _frontmatter_shape_problems("items:\n- [1, 2")
        self.assertEqual(len(problems), 1)
        self.assertIn("item de liste desequilibre", problems[0])

    def test_ligne_hors_sous_ensemble_yaml_du_depot_est_signalee(self):
        problems = _frontmatter_shape_problems("juste du texte libre")
        self.assertEqual(len(problems), 1)
        self.assertIn("forme YAML hors sous-ensemble du depot", problems[0])


# ------------------------------------------------------------------- okf_bundle_errors

class TestOkfBundleErrors(AidlcTestCase):
    """Conformance OKF v0.2 structurelle d'un bundle : index.md, log.md, concepts."""

    def test_bundle_conforme_ne_leve_aucune_erreur(self):
        bundle = self.write("kb/index.md",
                            "---\nokf_version: \"0.2\"\n---\n"
                            "# KB\n* [Concept](concept.md)\n").parent
        self.write("kb/concept.md",
                   "---\ntype: Reference\n---\n# Concept\ncorps.\n")
        self.assertEqual(okf_bundle_errors(bundle), [])

    def test_index_avec_une_cle_de_frontmatter_hors_okf_version_est_refuse(self):
        bundle = self.write("kb/index.md",
                            "---\ntitle: KB\n---\n# KB\n* [Concept](concept.md)\n").parent
        errors = okf_bundle_errors(bundle)
        self.assertTrue(any("sans frontmatter, sauf okf_version" in e for e in errors))

    def test_index_sans_liste_en_liens_markdown_est_refuse(self):
        bundle = self.write("kb/index.md",
                            "---\nokf_version: \"0.2\"\n---\n# KB\nAucun lien ici.\n").parent
        errors = okf_bundle_errors(bundle)
        self.assertTrue(any("liens markdown" in e for e in errors))

    def test_index_au_frontmatter_non_ferme_est_refuse(self):
        bundle = self.write("kb/index.md", "---\nokf_version: \"0.2\"\n# KB\n").parent
        errors = okf_bundle_errors(bundle)
        self.assertTrue(any("frontmatter non ferme" in e for e in errors))

    def test_log_avec_frontmatter_est_refuse(self):
        bundle = self.write("kb/index.md",
                            "---\nokf_version: \"0.2\"\n---\n"
                            "# KB\n* [Concept](concept.md)\n").parent
        self.write("kb/concept.md", "---\ntype: Reference\n---\n# Concept\ncorps.\n")
        self.write("kb/log.md", "---\ntype: Reference\n---\n## 2026-09-05\nentree\n")
        errors = okf_bundle_errors(bundle)
        self.assertTrue(any("log.md ne porte pas de frontmatter" in e for e in errors))

    def test_log_avec_un_titre_de_date_non_iso_8601_est_refuse(self):
        bundle = self.write("kb/index.md",
                            "---\nokf_version: \"0.2\"\n---\n"
                            "# KB\n* [Concept](concept.md)\n").parent
        self.write("kb/concept.md", "---\ntype: Reference\n---\n# Concept\ncorps.\n")
        self.write("kb/log.md", "## pas une date\nentree\n")
        errors = okf_bundle_errors(bundle)
        self.assertTrue(any("titre de date non ISO 8601" in e for e in errors))

    def test_index_sans_frontmatter_du_tout_n_est_pas_verifie_pour_ses_liens(self):
        # Comportement reel observe : la verification du sommaire en liens markdown ne
        # s'applique qu'a un index.md dont le frontmatter est ferme (etat 'ferme'). Un
        # index.md sans frontmatter du tout (etat 'absent') n'est pas controle du tout,
        # meme sans aucun lien.
        bundle = self.write("kb/index.md", "# KB\nAucun lien ici.\n").parent
        self.assertEqual(okf_bundle_errors(bundle), [])

    def test_concept_au_frontmatter_ferme_sans_cle_type_est_refuse(self):
        bundle = self.write("kb/index.md",
                            "---\nokf_version: \"0.2\"\n---\n"
                            "# KB\n* [Concept](concept.md)\n").parent
        self.write("kb/concept.md", "---\ntitle: X\n---\n# X\ncorps.\n")
        errors = okf_bundle_errors(bundle)
        self.assertTrue(any("sans cle 'type' non vide" in e for e in errors))

    def test_conformance_du_bundle_docs_reel_du_depot(self):
        bundle = repo_root() / "docs"
        if not (bundle / "index.md").exists():
            self.skipTest("docs/ absent de ce checkout")
        errors = okf_bundle_errors(bundle)
        self.assertEqual(errors, [], f"conformance OKF v0.2 de docs/ : {errors[:3]}")

    def test_conformance_du_bundle_knowledge_reel_du_depot(self):
        bundle = repo_root() / "knowledge"
        if not (bundle / "index.md").exists():
            self.skipTest("knowledge/ absent de ce checkout")
        errors = okf_bundle_errors(bundle)
        self.assertEqual(errors, [], f"conformance OKF v0.2 de knowledge/ : {errors[:3]}")


# ------------------------------------------------------------------------ okf_report

class TestOkfReport(AidlcTestCase):
    """Rapport de conformance OKF v0.2 d'un bundle, sans aucune sortie."""

    def test_rapport_nomme_le_fichier_fautif(self):
        bundle = self.write("kb/index.md",
                            "---\nokf_version: \"0.2\"\n---\n"
                            "# KB\n* [Concept](concept.md)\n").parent
        self.write("kb/concept.md", "---\ntype: Reference\n---\n# Concept\ncorps.\n")
        self.write("kb/orphelin.md", "# Sans frontmatter\n")
        report = okf_report(bundle)
        self.assertFalse(report["ok"])
        self.assertTrue(any("orphelin.md" in e for e in report["errors"]))
        self.assertEqual(report["checked"], 3)


# -------------------------------------------------------------------- _fallback_title

class TestFallbackTitle(AidlcTestCase):
    """Titre humanise derive du nom de fichier quand rien d'autre n'est disponible."""

    def test_tirets_et_underscores_deviennent_des_espaces_capitalises(self):
        self.assertEqual(_fallback_title("mon-concept_cle.md"), "Mon concept cle")

    def test_stem_vide_apres_nettoyage_retombe_sur_le_nom_de_fichier(self):
        self.assertEqual(_fallback_title("-.md"), "-.md")


# --------------------------------------------------------------- _concept_front_values

class TestConceptFrontValues(AidlcTestCase):
    """(titre, description) declares dans le frontmatter d'un concept."""

    def test_valeurs_entre_guillemets_sont_depouillees(self):
        bundle = self.write("kb/concept.md",
                            "---\ntype: Reference\ntitle: \"Mon Titre\"\n"
                            "description: 'Une description'\n---\ncorps\n").parent
        title, description = _concept_front_values(bundle, "concept.md")
        self.assertEqual((title, description), ("Mon Titre", "Une description"))

    def test_valeur_en_forme_de_flux_n_est_pas_retenue_comme_titre(self):
        bundle = self.write("kb/concept.md",
                            "---\ntype: Reference\ntitle: [Pas un titre]\n"
                            "---\ncorps\n").parent
        title, description = _concept_front_values(bundle, "concept.md")
        self.assertEqual((title, description), ("", ""))

    def test_frontmatter_absent_ne_donne_aucune_valeur(self):
        bundle = self.write("kb/concept.md", "# Sans frontmatter\ncorps\n").parent
        self.assertEqual(_concept_front_values(bundle, "concept.md"), ("", ""))


# --------------------------------------------------------------------- _concept_title

class TestConceptTitle(AidlcTestCase):
    """Titre lisible d'un concept : frontmatter, sinon H1, sinon nom de fichier."""

    def test_titre_du_frontmatter_est_priorise(self):
        bundle = self.write("kb/concept.md",
                            "---\ntype: Reference\ntitle: Titre Declare\n---\n"
                            "# Autre titre en H1\ncorps\n").parent
        self.assertEqual(_concept_title(bundle, "concept.md"), "Titre Declare")

    def test_sans_frontmatter_ni_titre_h1_retombe_sur_le_nom_de_fichier(self):
        bundle = self.write("kb/mon-concept.md", "Corps sans titre du tout.\n").parent
        self.assertEqual(_concept_title(bundle, "mon-concept.md"), "Mon concept")


# ------------------------------------------------------------------- _write_in_bundle

class TestWriteInBundle(AidlcTestCase):
    """Un Write/Edit journalise touche-t-il le fichier rel du bundle bundle_name ?"""

    def test_cible_vide_rend_faux(self):
        self.assertFalse(_write_in_bundle("", self.root, "knowledge", "concept.md"))
        self.assertFalse(_write_in_bundle(None, self.root, "knowledge", "concept.md"))

    def test_chemin_absolu_resolu_correspondant_rend_vrai(self):
        target = str(self.root / "knowledge" / "concept.md")
        self.assertTrue(_write_in_bundle(target, self.root, "knowledge", "concept.md"))

    def test_chemin_relatif_egal_au_fichier_rend_vrai(self):
        self.assertTrue(_write_in_bundle("concept.md", self.root, "knowledge",
                                         "concept.md"))

    def test_chemin_prefixe_du_nom_de_bundle_rend_vrai(self):
        self.assertTrue(_write_in_bundle("knowledge/concept.md", self.root, "knowledge",
                                         "concept.md"))

    def test_chemin_se_terminant_par_bundle_et_fichier_rend_vrai(self):
        self.assertTrue(_write_in_bundle("/ailleurs/knowledge/concept.md", self.root,
                                         "knowledge", "concept.md"))

    def test_chemin_sans_rapport_rend_faux(self):
        self.assertFalse(_write_in_bundle("/ailleurs/autre.md", self.root, "knowledge",
                                          "concept.md"))

    def test_erreur_systeme_a_la_resolution_retombe_sur_la_comparaison_normalisee(self):
        # Path.resolve() peut lever OSError (boucle de symlien, systeme de fichiers
        # exotique) : la fonction doit alors se rabattre sur la comparaison de chemins
        # normalises plutot que de laisser l'exception se propager.
        with patch("pathlib.Path.resolve", side_effect=OSError("boom")):
            self.assertTrue(_write_in_bundle("concept.md", self.root, "knowledge",
                                             "concept.md"))


# --------------------------------------------------------------- okf_frontmatter_fix

class TestOkfFrontmatterFix(AidlcTestCase):
    """Correctif deterministe du frontmatter d'un concept non conforme."""

    def test_sans_erreur_signalee_aucun_correctif_n_est_propose(self):
        bundle = self.write("kb/concept.md", "# Sans frontmatter\ncorps\n").parent
        self.assertIsNone(okf_frontmatter_fix(bundle, "concept.md", []))

    def test_frontmatter_absent_est_ajoute_en_tete(self):
        bundle = self.write("kb/concept.md", "# Mon Concept\ncorps.\n").parent
        fix = okf_frontmatter_fix(bundle, "concept.md", ["un concept s'ouvre par..."])
        self.assertIsNotNone(fix)
        self.assertEqual(fix["preview"][0], "---")
        self.assertIn("type: Reference", fix["preview"][1])

    def test_frontmatter_ouvert_jamais_ferme_est_referme_avant_le_corps(self):
        bundle = self.write(
            "kb/concept.md",
            "---\ntype: Reference\ntitle: Test\n\n# Heading\nBody text.\n").parent
        fix = okf_frontmatter_fix(bundle, "concept.md", ["frontmatter non ferme"])
        self.assertIsNotNone(fix)
        self.assertEqual(fix["edits"], [{"at": 4, "insert": "---\n"}])

    def test_frontmatter_ouvert_dont_toutes_les_lignes_restantes_sont_valides_ferme_en_fin_de_fichier(self):
        # Aucune ligne apres l'ouverture ne rompt le sous-ensemble cle/item/vide : le
        # marqueur fermant est insere en toute fin de fichier (close_at = len(lines)),
        # la boucle de detection n'a jamais eu a s'arreter en cours de route.
        bundle = self.write("kb/concept.md", "---\ntype: Reference\ntitle: Test\n").parent
        fix = okf_frontmatter_fix(bundle, "concept.md", ["frontmatter non ferme"])
        self.assertIsNotNone(fix)
        self.assertEqual(fix["edits"], [{"at": 3, "insert": "---\n"}])

    def test_frontmatter_ouvert_sans_cle_type_recoit_le_type_par_defaut(self):
        bundle = self.write(
            "kb/concept.md", "---\ntitle: Test\n\nBody paragraph\n").parent
        fix = okf_frontmatter_fix(bundle, "concept.md", ["frontmatter non ferme"])
        self.assertIsNotNone(fix)
        self.assertEqual(len(fix["edits"]), 2)
        self.assertIn({"at": 1, "insert": "type: Reference\n"}, fix["edits"])

    def test_probleme_de_forme_irreparable_ne_produit_aucun_correctif(self):
        bundle = self.write(
            "kb/concept.md", "---\ntype: Reference\nbad: [1, 2\n---\ncorps\n").parent
        fix = okf_frontmatter_fix(bundle, "concept.md",
                                  ["ligne 3 : valeur de flux desequilibree"])
        self.assertIsNone(fix)


# ------------------------------------------------------------------- _index_entry_line

class TestIndexEntryLine(AidlcTestCase):
    """Ligne de sommaire generee pour un concept."""

    def test_description_avec_crochets_est_nettoyee(self):
        bundle = self.write(
            "kb/concept.md",
            "---\ntype: Reference\ntitle: Mon Titre\n"
            "description: Une description [avec crochets]\n---\ncorps\n").parent
        line = _index_entry_line(bundle, "concept.md")
        self.assertEqual(line,
                         "* [Mon Titre](concept.md) - Une description avec crochets")


# ------------------------------------------------------------------ okf_index_proposal

class TestOkfIndexProposal(AidlcTestCase):
    """Proposition d'ajout des concepts orphelins au sommaire index.md."""

    def test_bundle_sans_index_ne_propose_rien(self):
        bundle = self.write("kb/concept.md", "---\ntype: Reference\n---\ncorps\n").parent
        self.assertIsNone(okf_index_proposal(bundle))

    def test_index_au_frontmatter_ouvert_ne_propose_rien(self):
        bundle = self.write("kb/index.md", "---\nokf_version: \"0.2\"\n# KB\n").parent
        self.write("kb/concept.md", "---\ntype: Reference\n---\ncorps\n")
        self.assertIsNone(okf_index_proposal(bundle))

    def test_index_au_frontmatter_avec_cle_hors_okf_version_ne_propose_rien(self):
        bundle = self.write("kb/index.md", "---\ntitle: KB\n---\n# KB\n").parent
        self.write("kb/concept.md", "---\ntype: Reference\n---\ncorps\n")
        self.assertIsNone(okf_index_proposal(bundle))

    def test_aucun_orphelin_ne_propose_rien(self):
        bundle = self.write("kb/index.md",
                            "---\nokf_version: \"0.2\"\n---\n"
                            "# KB\n* [Concept](concept.md)\n").parent
        self.write("kb/concept.md", "---\ntype: Reference\n---\ncorps\n")
        self.assertIsNone(okf_index_proposal(bundle))

    def test_orphelin_present_est_propose_en_queue_de_sommaire(self):
        bundle = self.write("kb/index.md",
                            "---\nokf_version: \"0.2\"\n---\n"
                            "# KB\n* [Concept](concept.md)\n").parent
        self.write("kb/concept.md", "---\ntype: Reference\n---\ncorps\n")
        self.write("kb/nouveau.md", "---\ntype: Reference\ntitle: Nouveau\n---\ncorps\n")
        proposal = okf_index_proposal(bundle)
        self.assertIsNotNone(proposal)
        self.assertIn("nouveau.md", proposal["problem"])
        self.assertEqual(proposal["preview"], ["* [Nouveau](nouveau.md)"])

    def test_proposition_incoherente_apres_application_n_est_pas_emise(self):
        # Un nom de fichier avec des parentheses casse le format `* [Titre](rel)` du
        # sommaire (le lien genere ne se referme pas la ou on l'attend) : la verification
        # en memoire doit alors refuser la proposition plutot que d'en emettre une
        # fausse.
        bundle = self.write("kb/index.md", "# KB\n").parent
        self.write("kb/weird(name).md", "Corps sans titre ni frontmatter.\n")
        self.assertIsNone(okf_index_proposal(bundle))


# ----------------------------------------------------------------------- _okf_proposals

class TestOkfProposals(AidlcTestCase):
    """Correctifs proposes sur l'etat courant des bundles du projet."""

    def test_les_fichiers_reserves_n_obtiennent_jamais_de_correctif_de_frontmatter(self):
        self.write("knowledge/index.md",
                   "---\nokf_version: \"0.2\"\n---\n# KB\n* [Concept](concept.md)\n")
        self.write("knowledge/concept.md", "---\ntype: Reference\n---\ncorps\n")
        # log.md non conforme (frontmatter present, interdit sur ce fichier) : le
        # fichier reserve doit etre saute par la boucle des correctifs de frontmatter.
        self.write("knowledge/log.md", "---\ntype: Reference\n---\n## 2026-09-05\nx\n")
        proposals = _okf_proposals(self.root)
        self.assertFalse(any(p.get("file") == "log.md" for p in proposals))

    def test_bundle_absent_du_projet_ne_produit_aucune_proposition(self):
        self.assertEqual(_okf_proposals(self.root), [])

    def test_correctif_irreparable_n_est_pas_ajoute_aux_propositions(self):
        self.write("knowledge/index.md",
                   "---\nokf_version: \"0.2\"\n---\n# KB\n* [Concept](concept.md)\n")
        # frontmatter deja ferme, cle 'type' presente, mais une ligne hors sous-ensemble
        # YAML du depot : okf_frontmatter_fix ne sait pas la reparer et rend None.
        self.write("knowledge/concept.md",
                   "---\ntype: Reference\nbad: [1, 2\n---\n# Concept\ncorps.\n")
        proposals = _okf_proposals(self.root)
        self.assertFalse(any(p.get("file") == "concept.md" for p in proposals))


# ============================================================ scenarios migres (21-26)
# selftest.py historique (avant decoupage en suite unittest), lignes 452-623.

class TestConformanceDepotScenario21(AidlcTestCase):
    """21. Conformance OKF v0.2 des bundles de connaissance du depot lui-meme (docs/,
    knowledge/), ancres sur la racine du depot reel (au-dessus du paquet de scripts)."""

    def test_conformance_okf_v0_2_de_knowledge(self):
        bundle = repo_root() / "knowledge"
        if not (bundle / "index.md").exists():
            self.skipTest("knowledge/ absent de ce checkout")
        errors = okf_bundle_errors(bundle)
        self.assertEqual(errors, [], f"conformance OKF v0.2 de knowledge/ : {errors[:3]}")

    def test_conformance_okf_v0_2_de_docs(self):
        bundle = repo_root() / "docs"
        if not (bundle / "index.md").exists():
            self.skipTest("docs/ absent de ce checkout")
        errors = okf_bundle_errors(bundle)
        self.assertEqual(errors, [], f"conformance OKF v0.2 de docs/ : {errors[:3]}")


class TestSousCommandeCheckOkfScenario22(AidlcTestCase):
    """22. Sous-commande check-okf : gate un bundle arbitraire, JSON sur stdout, exit 1
    si non conforme."""

    def setUp(self):
        super().setUp()
        self.kb = self.write(
            "kb/index.md",
            "---\nokf_version: \"0.2\"\n---\n# KB\n* [Concept](concept.md) - conforme.\n"
        ).parent
        self.write(
            "kb/concept.md",
            "---\ntype: Reference\ntitle: Concept\n"
            "generated: { by: process:selftest, at: 2026-09-04T00:00:00Z }\n"
            "---\n# Concept\nCorps du concept.\n")

    def _run(self, **kwargs):
        args = type("Args", (), {"dir": None, "touched": False, "stop": False,
                                  "file": None})()
        for key, value in kwargs.items():
            setattr(args, key, value)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cmd_check_okf(self.root, args)
        return code, out.getvalue(), err.getvalue()

    def test_accepte_un_bundle_conforme(self):
        code, _, _ = self._run(dir=str(self.kb))
        self.assertEqual(code, 0)

    def test_refuse_un_concept_sans_frontmatter(self):
        self.write("kb/orphelin.md", "# Sans frontmatter\n")
        code, _, _ = self._run(dir=str(self.kb))
        self.assertEqual(code, 1)

    def test_le_rapport_nomme_le_fichier_fautif(self):
        self.write("kb/orphelin.md", "# Sans frontmatter\n")
        report = okf_report(self.kb)
        self.assertFalse(report["ok"])
        self.assertTrue(any("orphelin.md" in e for e in report["errors"]))


class TestCheckOkfToucheScenario23(AidlcTestCase):
    """23. check-okf --touched : mode hook PostToolUse, jamais bloquant."""

    def setUp(self):
        super().setUp()
        self.write("knowledge/index.md",
                   "---\nokf_version: \"0.2\"\n---\n# KB\n"
                   "* [Concept](concept.md) - conforme.\n")
        self.write("knowledge/concept.md",
                   "---\ntype: Reference\ntitle: Concept\n---\n# Concept\ncorps.\n")

    def _run_touched(self, file_path):
        args = type("Args", (), {"touched": True, "file": file_path, "dir": None,
                                  "stop": False})()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cmd_check_okf(self.root, args)
        return code, out.getvalue()

    def test_une_ecriture_hors_bundle_reste_muette(self):
        code, feedback = self._run_touched(str(self.root / "README.md"))
        self.assertEqual(code, 0)
        self.assertEqual(feedback, "")

    def test_un_concept_non_conforme_est_signale_en_contexte_sans_casser_la_session(self):
        target = self.write("knowledge/sans-frontmatter.md", "# Orphelin\n")
        code, feedback = self._run_touched(str(target))
        self.assertEqual(code, 0)
        self.assertIn("sans-frontmatter.md", feedback)


class TestCheckOkfStopScenario24(AidlcTestCase):
    """24. check-okf --stop : hook Stop, porte dure de fin de session."""

    def setUp(self):
        super().setUp()
        self.consumer = self.write(
            "consumer/knowledge/index.md",
            "---\nokf_version: \"0.2\"\n---\n# KB\n"
            "* [Concept](concept.md) - conforme.\n").parent.parent
        self.write("consumer/knowledge/concept.md",
                   "---\ntype: Reference\ntitle: Concept\n---\n# Concept\ncorps.\n")
        self.bare = self.write("bare/.keep", "").parent

    def _run_stop(self, root):
        args = type("Args", (), {"stop": True, "touched": False, "file": None,
                                  "dir": None})()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cmd_check_okf(root, args)
        return code, out.getvalue()

    def test_bundle_conforme_laisse_fermer_la_session(self):
        code, out = self._run_stop(self.consumer)
        self.assertEqual((code, out), (0, ""))

    def test_projet_sans_bundle_ne_bloque_jamais_l_arret(self):
        code, out = self._run_stop(self.bare)
        self.assertEqual((code, out), (0, ""))

    def test_bundle_non_conforme_refuse_l_arret_en_nommant_le_fichier_fautif(self):
        self.write("consumer/knowledge/sans-frontmatter.md", "# Orphelin\n")
        code, out = self._run_stop(self.consumer)
        decision = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(decision["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertEqual(decision["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("sans-frontmatter.md",
                      decision["hookSpecificOutput"]["permissionDecisionReason"])


class TestRefusStopAlimenteImproveScenario25(AidlcTestCase):
    """25. Le refus du gate Stop alimente la file d'amelioration ; improve le correle
    aux sessions et propose un correctif de frontmatter deterministe."""

    def setUp(self):
        super().setUp()
        self.consumer = self.write(
            "consumer/knowledge/index.md",
            "---\nokf_version: \"0.2\"\n---\n# KB\n"
            "* [Concept](concept.md) - conforme.\n").parent.parent
        self.write("consumer/knowledge/concept.md",
                   "---\ntype: Reference\ntitle: Concept\n---\n# Concept\ncorps.\n")
        self.write("consumer/knowledge/sans-frontmatter.md", "# Orphelin\n")
        self.queue_path = aidlc_dir(self.consumer) / "improvement-queue.jsonl"

    def _run_stop(self):
        args = type("Args", (), {"stop": True, "touched": False, "file": None,
                                  "dir": None})()
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            return cmd_check_okf(self.consumer, args)

    def test_un_refus_stop_alimente_la_file_d_amelioration_une_fois(self):
        self._run_stop()
        queue_text = read_text(self.queue_path)
        self.assertEqual(queue_text.count("okf_stop"), 1)

    def test_un_stop_rejoue_ne_doublonne_pas_dans_la_file(self):
        self._run_stop()
        self._run_stop()
        queue_text = read_text(self.queue_path)
        self.assertEqual(queue_text.count("okf_stop"), 1)

    def test_improve_remonte_le_refus_du_gate_okf(self):
        self._run_stop()
        diag = improve(self.consumer, self.pipeline)
        self.assertEqual(len(diag["okf"]["refusals"]), 1)

    def test_le_refus_okf_n_est_pas_compte_comme_refus_humain(self):
        self._run_stop()
        diag = improve(self.consumer, self.pipeline)
        self.assertEqual(diag["human_rejections"], [])

    def test_improve_propose_un_correctif_de_frontmatter_avec_apercu(self):
        self._run_stop()
        diag = improve(self.consumer, self.pipeline)
        fixes = [p for p in diag["okf"]["proposals"] if p["file"] == "sans-frontmatter.md"]
        self.assertTrue(fixes)
        self.assertTrue(fixes[0]["edits"])
        self.assertEqual(fixes[0]["preview"][0], "---")

    def test_le_correctif_propose_rend_le_concept_conforme_une_fois_applique(self):
        self._run_stop()
        diag = improve(self.consumer, self.pipeline)
        fixes = [p for p in diag["okf"]["proposals"] if p["file"] == "sans-frontmatter.md"]
        target = self.consumer / "knowledge" / "sans-frontmatter.md"
        repaired = read_text(target).splitlines()
        for edit in sorted(fixes[0]["edits"], key=lambda e: -e["at"]):
            repaired[edit["at"]:edit["at"]] = edit["insert"].rstrip("\n").split("\n")
        front, _, state = okf_split_frontmatter("\n".join(repaired))
        self.assertEqual(state, "ferme")
        self.assertRegex(front, r"(?m)^type\s*:\s*\S")
        self.assertEqual(_frontmatter_shape_problems(front), [])


class TestSommaireRecoitLesOrphelinsScenario26(AidlcTestCase):
    """26. Le sommaire index.md (fichier reserve) recoit les concepts orphelins."""

    def setUp(self):
        super().setUp()
        self.consumer = self.write(
            "consumer/knowledge/index.md",
            "---\nokf_version: \"0.2\"\n---\n# KB\n"
            "* [Concept](concept.md) - conforme.\n").parent.parent
        self.write("consumer/knowledge/concept.md",
                   "---\ntype: Reference\ntitle: Concept\n---\n# Concept\ncorps.\n")
        self.write("consumer/knowledge/sans-frontmatter.md", "# Orphelin\n")
        args = type("Args", (), {"stop": True, "touched": False, "file": None,
                                  "dir": None})()
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            cmd_check_okf(self.consumer, args)
        self.diag = improve(self.consumer, self.pipeline)

    def test_improve_propose_les_concepts_orphelins_au_sommaire(self):
        idx = [p for p in self.diag["okf"]["proposals"] if p["kind"] == "index_entries"]
        self.assertTrue(idx)
        self.assertIn("sans-frontmatter.md", idx[0]["problem"])

    def test_appliquee_la_proposition_index_md_ne_laisse_aucun_orphelin(self):
        idx = [p for p in self.diag["okf"]["proposals"] if p["kind"] == "index_entries"]
        idx_lines = read_text(self.consumer / "knowledge/index.md").splitlines()
        for edit in sorted(idx[0]["edits"], key=lambda e: -e["at"]):
            idx_lines[edit["at"]:edit["at"]] = edit["insert"].rstrip("\n").split("\n")
        concepts = sorted(str(p.relative_to(self.consumer / "knowledge"))
                          for p in (self.consumer / "knowledge").rglob("*.md")
                          if p.name not in OKF_RESERVED)
        listed = set()
        for line in idx_lines:
            m = _INDEX_LINK.match(line)
            if m:
                listed.add(m.group(1).split("#", 1)[0])
        self.assertTrue(all(rel in listed for rel in concepts))
