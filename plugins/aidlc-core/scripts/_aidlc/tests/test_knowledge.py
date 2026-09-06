from __future__ import annotations

import subprocess
import unittest.mock

from pathlib import Path

from .harness import AidlcTestCase
from ..util import ensure_dir
from ..util import write_json
from .. import knowledge
from ..knowledge import cache_root
from ..knowledge import catalog
from ..knowledge import concepts
from ..knowledge import front_values
from ..knowledge import load_sources
from ..knowledge import render
from ..knowledge import resolve
from ..knowledge import search
from ..knowledge import sources_path
from ..knowledge import sync

"""Bundles OKF distants : sources declarees, cache local, catalogue, recherche,
resolution. Le champ fonctionnel couvert : knowledge-sources.json (catalogue,
recherche par mots-cles frontmatter puis corps, lecture d'un concept, cache sous
.aidlc/tmp/knowledge), les cas d'erreur (source injoignable, nom non atomique,
fichier de sources absent ou malforme, concept introuvable).

# ponytail: `_make_git_repo` est un helper local (pas dans harness.py) qui cree un
depot git minimal avec configuration locale (pas de dependance a une config git
globale de la machine) pour exercer les branches de clonage/rafraichissement de
`sync()` sans jamais toucher au reseau (protocole file://).
"""


def _make_git_repo(path: Path, branch: str = "main") -> Path:
    """Depot git minimal (config locale, un commit) pret a etre clone via file://."""
    ensure_dir(path)
    run = lambda *args: subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True, check=True)
    run("init", "-q", "-b", branch)
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    (path / "fichier.txt").write_text("contenu initial\n", encoding="utf-8")
    run("add", "fichier.txt")
    run("commit", "-q", "-m", "initial")
    return path


def _add_commit(path: Path, content: str) -> None:
    run = lambda *args: subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True, check=True)
    (path / "fichier.txt").write_text(content, encoding="utf-8")
    run("add", "fichier.txt")
    run("commit", "-q", "-m", "suite")


def _make_bundle(root: Path, with_title: bool = True) -> Path:
    """Bundle OKF minimal : un concept sous metrics/, index.md et log.md reserves."""
    bundle = root / "bundle"
    ensure_dir(bundle / "metrics")
    (bundle / "index.md").write_text("# Sommaire\n\n* [Marge](metrics/marge.md)\n",
                                     encoding="utf-8")
    (bundle / "log.md").write_text("# Journal\n", encoding="utf-8")
    title_line = "title: Marge brute\n" if with_title else ""
    (bundle / "metrics" / "marge.md").write_text(
        "---\ntype: Metric\n" + title_line +
        "description: Marge du perimetre retail.\ntags: [finance, marge]\n---\n\n"
        "# Definition\n\nRevenu moins cout complet.\n", encoding="utf-8")
    return bundle


class TestLoadSources(AidlcTestCase):
    """knowledge-sources.json : declaration des depots distants par le projet."""

    def test_sans_fichier_de_sources_rend_une_liste_vide(self):
        self.assertEqual(load_sources(self.root), [])

    def test_source_declaree_est_normalisee(self):
        write_json(sources_path(self.root),
                   {"sources": [{"name": "acme", "repo": "https://example.test/acme.git",
                                 "path": "/okf/bundles/acme/", "ref": "main"}]})
        out = load_sources(self.root)
        self.assertEqual(out, [{"name": "acme", "repo": "https://example.test/acme.git",
                                "path": "okf/bundles/acme", "ref": "main"}])

    def test_ref_absente_devient_une_chaine_vide(self):
        write_json(sources_path(self.root),
                   {"sources": [{"name": "acme", "repo": "https://example.test/acme.git"}]})
        self.assertEqual(load_sources(self.root)[0]["ref"], "")

    def test_nom_de_source_non_atomique_leve(self):
        write_json(sources_path(self.root),
                   {"sources": [{"name": "../evasion", "repo": "https://example.test"}]})
        with self.assertRaises(ValueError):
            load_sources(self.root)

    def test_chemin_avec_double_point_leve(self):
        write_json(sources_path(self.root),
                   {"sources": [{"name": "acme", "repo": "https://example.test",
                                 "path": "../../etc"}]})
        with self.assertRaises(ValueError):
            load_sources(self.root)

    def test_repo_manquant_leve(self):
        write_json(sources_path(self.root), {"sources": [{"name": "acme"}]})
        with self.assertRaises(ValueError):
            load_sources(self.root)

    def test_fichier_de_sources_malforme_leve_une_erreur_json(self):
        self.write(knowledge.SOURCES_FILE, "{ceci n'est pas du JSON")
        with self.assertRaises(ValueError):
            load_sources(self.root)


class TestSync(AidlcTestCase):
    """Materialisation locale d'une source : reutilisee telle quelle, ou clonee/
    rafraichie dans le cache du projet."""

    def test_repo_local_existant_est_utilise_tel_quel(self):
        local = ensure_dir(self.root / "voisin")
        out = sync(self.root, {"name": "voisin", "repo": str(local), "path": "", "ref": ""})
        self.assertEqual(out, local.resolve())
        # aucun cache n'a ete cree : le depot voisin est utilise en place
        self.assertFalse(cache_root(self.root).exists())

    def test_repo_local_avec_sous_chemin_resout_le_sous_dossier(self):
        local = ensure_dir(self.root / "voisin")
        ensure_dir(local / "okf" / "bundle")
        out = sync(self.root, {"name": "voisin", "repo": str(local),
                               "path": "okf/bundle", "ref": ""})
        self.assertEqual(out, (local / "okf" / "bundle").resolve())

    def test_clone_utilise_la_reference_demandee(self):
        origin = _make_git_repo(self.root / "origin", branch="stable")
        source = {"name": "distante", "repo": f"file://{origin}", "path": "", "ref": "stable"}
        out = sync(self.root, source)
        self.assertTrue((out / "fichier.txt").exists())
        self.assertEqual(out, (cache_root(self.root) / "distante").resolve())

    def test_clone_est_conserve_sans_reclonage_si_refresh_absent(self):
        origin = _make_git_repo(self.root / "origin")
        source = {"name": "distante", "repo": f"file://{origin}", "path": "", "ref": ""}
        first = sync(self.root, source)
        (first / "marqueur-local.txt").write_text("ne doit pas disparaitre", encoding="utf-8")
        _add_commit(origin, "contenu suivant\n")
        second = sync(self.root, source, refresh=False)
        self.assertEqual(second, first)
        self.assertTrue((second / "marqueur-local.txt").exists())

    def test_rafraichissement_sans_nouveaute_reussit(self):
        origin = _make_git_repo(self.root / "origin")
        source = {"name": "distante", "repo": f"file://{origin}", "path": "", "ref": ""}
        sync(self.root, source)
        # un clone deja present et sans --branch a l'appel initial : un `git pull
        # --ff-only` doit reellement etre tente (pas juste un no-op deguise en succes).
        with unittest.mock.patch.object(knowledge, "_git",
                                        wraps=knowledge._git) as spied:
            out = sync(self.root, source, refresh=True)
        self.assertTrue((out / "fichier.txt").exists())
        spied.assert_called_once_with(["pull", "--ff-only", "--depth", "1"],
                                      cwd=cache_root(self.root) / "distante")

    def test_rafraichissement_qui_echoue_leve_runtimeerror(self):
        origin = _make_git_repo(self.root / "origin")
        source = {"name": "distante", "repo": f"file://{origin}", "path": "", "ref": ""}
        sync(self.root, source)
        # le clone est peu profond (--depth 1) : un nouveau commit en amont rend
        # l'historique divergent, la mise a jour --ff-only ne peut plus avancer.
        _add_commit(origin, "contenu qui diverge\n")
        with self.assertRaises(RuntimeError) as cm:
            sync(self.root, source, refresh=True)
        self.assertIn("distante", str(cm.exception))

    def test_clone_impossible_leve_runtimeerror_nommee(self):
        source = {"name": "introuvable", "repo": str(self.root / "nulle-part"), "path": "", "ref": ""}
        with self.assertRaises(RuntimeError) as cm:
            sync(self.root, source)
        self.assertIn("introuvable", str(cm.exception))


class TestFrontValues(AidlcTestCase):
    """Frontmatter YAML restreint d'un concept OKF : scalaires et listes en flux."""

    def test_frontmatter_ferme_donne_les_valeurs(self):
        values = front_values("---\ntype: Metric\ntitle: Marge\n---\ncorps")
        self.assertEqual(values, {"type": "Metric", "title": "Marge"})

    def test_frontmatter_absent_rend_un_dict_vide(self):
        self.assertEqual(front_values("# Pas de frontmatter du tout"), {})

    def test_frontmatter_non_ferme_rend_un_dict_vide(self):
        self.assertEqual(front_values("---\ntype: Metric\npas de fermeture"), {})

    def test_liste_en_flux_est_decoupee(self):
        values = front_values('---\ntags: [finance, marge]\n---\n')
        self.assertEqual(values["tags"], ["finance", "marge"])

    def test_ligne_hors_forme_cle_valeur_est_ignoree(self):
        values = front_values("---\ntitle: Marge\n- ceci n'est pas une cle\ntype: Metric\n---\n")
        self.assertEqual(values, {"title": "Marge", "type": "Metric"})

    def test_valeur_mapping_en_flux_est_ignoree(self):
        values = front_values("---\ntitle: Marge\nmeta: {a: 1}\n---\n")
        self.assertEqual(values, {"title": "Marge"})


class TestConcepts(AidlcTestCase):
    """Concepts d'un bundle : un dict par fichier Markdown, hors fichiers reserves."""

    def test_fichiers_reserves_sont_exclus(self):
        bundle = _make_bundle(self.root)
        refs = [c["ref"] for c in concepts(bundle, "local")]
        self.assertEqual(refs, ["local/metrics/marge"])

    def test_titre_par_defaut_derive_du_nom_de_fichier(self):
        bundle = _make_bundle(self.root, with_title=False)
        entry = concepts(bundle, "local")[0]
        self.assertEqual(entry["title"], "marge")

    def test_frontmatter_present_alimente_type_titre_description_et_tags(self):
        bundle = _make_bundle(self.root)
        entry = concepts(bundle, "local")[0]
        self.assertEqual(entry["type"], "Metric")
        self.assertEqual(entry["title"], "Marge brute")
        self.assertEqual(entry["description"], "Marge du perimetre retail.")
        self.assertEqual(entry["tags"], ["finance", "marge"])

    def test_bundle_absent_rend_une_liste_vide(self):
        self.assertEqual(concepts(self.root / "jamais-cree", "local"), [])


class TestCatalog(AidlcTestCase):
    """Catalogue agrege de toutes les sources declarees."""

    def test_agrege_les_concepts_de_chaque_source(self):
        bundle = _make_bundle(self.root)
        write_json(sources_path(self.root),
                   {"sources": [{"name": "local", "repo": str(bundle)}]})
        view = catalog(self.root)
        self.assertEqual([c["ref"] for c in view["concepts"]], ["local/metrics/marge"])
        self.assertEqual(view["errors"], [])

    def test_filtre_only_restreint_a_la_source_nommee(self):
        bundle_a = _make_bundle(self.root / "a")
        bundle_b = _make_bundle(self.root / "b")
        write_json(sources_path(self.root),
                   {"sources": [{"name": "a", "repo": str(bundle_a)},
                                {"name": "b", "repo": str(bundle_b)}]})
        view = catalog(self.root, only="b")
        self.assertEqual(view["sources"], ["b"])
        # le filtre doit aussi restreindre les concepts agreges, pas seulement l'entete
        self.assertEqual([c["source"] for c in view["concepts"]], ["b"])

    def test_only_inconnu_rend_une_erreur_nommee(self):
        write_json(sources_path(self.root), {"sources": []})
        view = catalog(self.root, only="fantome")
        self.assertEqual(view["sources"], [])
        self.assertEqual(view["errors"], ["source inconnue : fantome"])

    def test_source_injoignable_est_signalee_sans_faire_tomber_les_autres(self):
        bundle = _make_bundle(self.root)
        write_json(sources_path(self.root),
                   {"sources": [{"name": "local", "repo": str(bundle)},
                                {"name": "absente", "repo": str(self.root / "nulle-part")}]})
        view = catalog(self.root)
        self.assertTrue(view["errors"])
        self.assertEqual([c["ref"] for c in view["concepts"]], ["local/metrics/marge"])

    def test_nom_de_source_non_atomique_leve_meme_via_catalog(self):
        # contrairement a une source injoignable (RuntimeError, reportee dans errors),
        # un nom de source non atomique est une erreur de declaration : elle n'est pas
        # avalee, le cache n'est pas creusable.
        write_json(sources_path(self.root),
                   {"sources": [{"name": "../evasion", "repo": str(_make_bundle(self.root))}]})
        with self.assertRaises(ValueError):
            catalog(self.root)


class TestSearch(AidlcTestCase):
    """Recherche par mots-cles : frontmatter d'abord, puis corps."""

    def setUp(self):
        super().setUp()
        bundle = _make_bundle(self.root)
        self.entries = concepts(bundle, "local")

    def test_mot_du_frontmatter_ramene_le_concept(self):
        self.assertEqual(search(self.entries, ["marge"]), self.entries)

    def test_mot_du_corps_ramene_le_concept(self):
        self.assertEqual(search(self.entries, ["complet"]), self.entries)

    def test_tous_les_mots_doivent_etre_presents(self):
        self.assertEqual(search(self.entries, ["marge", "absent"]), [])

    def test_correspondance_de_frontmatter_avant_correspondance_de_corps(self):
        bundle = self.root / "bundle"
        (bundle / "metrics" / "autre.md").write_text(
            "---\ntype: Metric\ntitle: Autre indicateur\n"
            "description: Sans rapport.\n---\n\ncontient aussi le mot cherche ici.\n",
            encoding="utf-8")
        entries = concepts(bundle, "local")
        hits = search(entries, ["cherche"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["ref"], "local/metrics/autre")


class TestRender(AidlcTestCase):
    """Rendu compact : une ligne par concept."""

    def test_rendu_compact_porte_type_titre_et_description(self):
        entry = {"ref": "local/metrics/marge", "type": "Metric", "title": "Marge brute",
                 "description": "Marge du perimetre retail."}
        line = render([entry])
        self.assertEqual(line, "local/metrics/marge [Metric] - Marge brute : "
                                "Marge du perimetre retail.")

    def test_type_et_description_absents_sont_omis(self):
        entry = {"ref": "local/metrics/marge", "type": "", "title": "Marge brute",
                 "description": ""}
        self.assertEqual(render([entry]), "local/metrics/marge - Marge brute")

    def test_rend_une_chaine_vide_sans_concept(self):
        self.assertEqual(render([]), "")


class TestResolve(AidlcTestCase):
    """Un concept se resout par reference exacte, ou par suffixe sans ambiguite."""

    def setUp(self):
        super().setUp()
        bundle = _make_bundle(self.root)
        self.entries = concepts(bundle, "local")
        self.concept = self.entries[0]

    def test_reference_exacte_est_retenue(self):
        self.assertIs(resolve(self.entries, "local/metrics/marge"), self.concept)

    def test_suffixe_sans_ambiguite_se_resout(self):
        self.assertIs(resolve(self.entries, "metrics/marge"), self.concept)

    def test_suffixe_ambigu_rend_none(self):
        bundle2 = _make_bundle(self.root / "second")
        entries = self.entries + concepts(bundle2, "second")
        self.assertIsNone(resolve(entries, "metrics/marge"))

    def test_reference_inconnue_rend_none(self):
        self.assertIsNone(resolve(self.entries, "metrics/absent"))
