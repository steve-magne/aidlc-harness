---
type: Reference
title: Stratégie de tests du harnais AI-DLC
description: Ce que le harnais teste, comment, et pourquoi — suite unittest stdlib découpée par concern, contrat CLI en sous-processus, portes structurelles sur les artefacts de plugin, et ratchet de non-régression de couverture.
tags: [tests, qualité, ci, harness]
generated: { by: human:steve-magne, at: 2026-09-06T00:00:00Z }
---

# Stratégie de tests du harnais AI-DLC

## 1. Ce qu'on défend

Le harnais est un **orchestrateur d'agents**. Ce qu'il produit — des livrables — est jugé par des
agents et par des humains, et cette part-là n'est pas testable au sens classique. Ce qui l'est, et
qui doit l'être sans concession, c'est le **moteur déterministe** : le code qui décide si un
livrable est valide, si une étape est franchie, quel agent vient ensuite, quelle écriture est
refusée. Les prompts changent, les agents dérivent, les modèles évoluent ; le moteur est la partie
qui doit rester vraie quoi qu'il arrive, parce que c'est lui qu'on invoque pour arbitrer.

Un harnais dont la porte de qualité est cassée est pire qu'un harnais absent : il tamponne.

## 2. Le socle : `unittest`, et rien d'autre

La suite repose sur `unittest`, de la bibliothèque standard. Ce n'est pas un compromis, c'est la
contrainte structurante du dépôt qui se prolonge : le harnais est distribué comme plugin Claude
Code et doit tourner chez n'importe quel consommateur avec `python3` seul. Un `pip install pytest`
dans les prérequis d'installation transformerait une garantie en dépendance.

`unittest` apporte gratuitement ce qu'on aurait dû écrire à la main : isolation par test,
`setUp`/`tearDown`, poursuite après échec, nommage des scénarios, filtrage. La règle 3 de
[CLAUDE.md](../CLAUDE.md) autorise explicitement `unittest` et `trace` ; elle continue d'exclure
tout paquet à installer, `pytest` et `coverage` compris.

**La suite n'est pas un second point d'entrée.** Elle n'est atteignable que par `aidlc.py` :

```bash
S=plugins/aidlc-core/scripts/aidlc.py
python3 $S test                  # toute la suite
python3 $S test -k registry -v   # un sous-ensemble, un nom de test par ligne
python3 $S test --failfast       # s'arrête au premier échec
python3 $S coverage              # non-régression de couverture (exit 2 = baisse)
python3 $S coverage --reset      # rebase le plancher (geste humain, visible au diff)
```

`--selftest` reste l'alias historique de `test` — c'est ce que la CI, les hooks et les
consommateurs appellent depuis toujours, et rien ne les oblige à changer.

## 3. Quatre niveaux, quatre risques distincts

La suite n'est pas un tas de tests unitaires : chaque niveau défend contre une façon différente de
casser le harnais.

| Niveau | Fichiers | Ce qu'il attrape |
| --- | --- | --- |
| **Unitaire, par concern** | `test_<module>.py` en face de chaque `_aidlc/<module>.py` | Une règle de validation qui change de sens, un seuil qui glisse, un chemin d'erreur qui cesse d'être géré |
| **Couche commandes** | `test_commands.py` | Une sous-commande qui renvoie le mauvais code, qui écrit sur le mauvais flux, ou qui cesse de gérer une option |
| **Contrat CLI, en sous-processus** | `test_cli.py` | Le contrat public réel : ce que les hooks et les skills invoquent. Codes de sortie (`exit 2` = bloquant), JSON sur **stdout** et humain sur **stderr**, exceptions d'IO/JSON converties en message français |
| **Artefacts de plugin** | `test_plugins.py` | Un renommage qui casse les hooks en silence : chemin cité dans `hooks.json` ou dans un `SKILL.md` qui n'existe plus, sous-commande disparue du parseur, `agent.json` refusé par le registre, marketplace désynchronisé de `plugins/` |

Le dernier niveau est le moins habituel et le plus rentable. Dans un harnais, la plupart des
régressions réelles ne sont pas des bugs de calcul : ce sont des **chemins qui ne pointent plus
nulle part** après un déplacement de fichier. Rien ne plante — le hook échoue silencieusement, et
la gouvernance s'arrête sans que personne le voie.

## 4. Le socle partagé : `harness.AidlcTestCase`

Toute classe de test en hérite. Chaque méthode `test_*` reçoit :

- un **répertoire temporaire neuf** qui joue les deux racines à la fois (le harnais qui porte
  `pipeline.json` et les plugins ; le projet consommateur qui porte `deliverables/` et `.aidlc/`) ;
- un **environnement sauvé puis restauré** (`CLAUDE_PROJECT_DIR`, `AIDLC_HARNESS_ROOT`,
  `AIDLC_AGENT_PATH`, `CLAUDE_CONFIG_DIR`, `CLAUDE_PLUGIN_ROOT`, `AIDLC_PLATFORM`), y compris une
  configuration Claude Code factice qui isole la découverte des plugins réellement installés sur
  la machine ;
- un **cache de registre vidé** avant et après ;
- des fixtures prêtes : `manifest()`, `document()`, `plan_intent()`, `write_agent()`,
  `agent_path()`, `run_cli()`, `muted()`, `assertJson()`.

Conséquence : la suite rend le même résultat d'où qu'on la lance, quel que soit l'ordre des tests,
et quels que soient les plugins installés sur la machine du développeur.

Le dépôt réel n'est accessible qu'**en lecture**, via `repo_root()`. Un test qui écrirait dans le
dépôt serait un test qui pollue le dépôt suivant.

## 5. Ce qui vaut pour un test de ce dépôt

- **Le nom de la méthode est la spécification.** Il est en français et se lit comme une phrase :
  c'est lui qui s'affiche quand le test tombe. C'est l'exception assumée à la règle « identifiants
  en anglais » — un nom de test ne nomme pas une API, il énonce un comportement attendu.
- **Une méthode = un comportement.** On ne fusionne pas deux assertions distinctes pour raccourcir.
- **Pas de test tautologique.** Une assertion qui ne tombe jamais quand le comportement change ne
  teste rien. Les chemins d'erreur et les entrées malformées valent mieux que le chemin nominal :
  c'est là que sont les lignes que personne n'exécute.
- **Un test ne corrige jamais le moteur.** S'il révèle un bug, il fige le comportement **réel**
  observé et le bug est signalé séparément. Un test qui suit le code n'a plus de valeur de preuve.
- **Jamais de test qui relance la suite.** `test`, `--selftest` et `coverage` lancent la suite
  entière ; un test qui les invoque récurse à l'infini. Un garde-fou de réentrance
  (`_aidlc.tests._REENTRANCY`, une variable d'environnement — la récursion passe par des
  sous-processus, qui en héritent) neutralise l'imbrication. On teste ce routage par substitution
  (`unittest.mock`), jamais en relançant.
- **Un test neuf est relu de façon adversariale.** La question posée au relecteur n'est pas
  « est-ce que ça passe » mais « est-ce que ça tombe si je casse le comportement ? », et il doit
  le vérifier concrètement en substituant la fonction du moteur en mémoire. La passe qui a produit
  cette suite a ainsi éliminé un `assertIn("OK", message)` qui passait même en cas d'échec —
  parce que le message d'échec contenait « OKF ».
- **Aucune dépendance externe, y compris pour mesurer.** La couverture se mesure avec `trace`
  (stdlib), jamais avec le paquet pip `coverage`.

## 6. La couverture : mesurée, figée, défendue

`aidlc.py coverage` mesure la couverture ligne avec `trace` (stdlib) et la compare au plancher figé
dans `.aidlc/coverage.json`. Même geste que le `ratchet` sur les planchers de sévérité : **un
plancher ne descend jamais**. Monter est libre et re-fige automatiquement ; descendre exige
`aidlc.py coverage --reset`, un geste humain explicite qui se voit dans le diff.

Deux plafonds sont assumés et documentés dans le code :

- une tolérance de 0,5 point avant de crier à la régression — un refactor qui supprime des lignes
  déplace mécaniquement le taux sans rien tester de moins ;
- `trace` ne suit pas les sous-processus, donc les tests de contrat CLI (qui relancent `aidlc.py`)
  ne comptent pas dans la mesure. Le taux rendu est donc un **plancher**, jamais une surestimation.

## 7. Les portes de la CI

Dans l'ordre, chacune rougissant le build :

| Porte | Ce qu'elle défend |
| --- | --- |
| `test`, **sur une matrice de versions de Python** | La suite passe — et la promesse « `python3` seul, aucun `pip install` » tient réellement d'une version à l'autre |
| `check-python`, `check-json` | Règle 6 : tout Python compile, tout JSON parse |
| `agents --strict` | Les manifestes `agent.json` de ce dépôt sont valides |
| `coverage` | La couverture n'a pas baissé (`exit 2`) |
| `check-okf docs`, `check-okf knowledge` | Conformance OKF v0.2 des deux bundles |
| `claude plugin validate` | Chaque plugin reste valide pour Claude Code |

La suite tourne dans un job à matrice ; le reste des portes dans un job unique. La couverture
n'est mesurée que sur **une** version : le taux varie d'une version de Python à l'autre selon les
branches conditionnelles, et comparer un plancher unique à plusieurs mesures fabriquerait de
fausses régressions.

Aucune porte n'installe quoi que ce soit côté Python : la seule dépendance du workflow est le CLI
`@anthropic-ai/claude-code`, outil de build du runner, pas du moteur.

## 8. Où en est la suite

| | Avant | Après |
| --- | --- | --- |
| Forme | une fonction `selftest()` de 1254 lignes | 16 modules, 7 851 lignes |
| Cas | 173 assertions dans un bloc unique | **812 tests** nommés, en 183 classes |
| Isolation | un `TemporaryDirectory` partagé par tout | un projet temporaire neuf par test |
| Échec | le premier échec masque les 32 scénarios suivants | chaque test tombe seul et se nomme |
| Sélection | tout ou rien | `-k <motif>` |
| Couverture | **81,3 %** (471 lignes jamais exécutées) | **99,6 %** (10 lignes) |
| Non-régression | aucune | plancher figé, `exit 2` si baisse |

Répartition par module :

| Module | Tests | Couverture |
| --- | ---: | ---: |
| `commands` | 106 | 100 % |
| `cli` | 90 | 93,6 % |
| `registry` | 82 | 100 % |
| `checks` | 73 | 100 % |
| `maturity` | 72 | 100 % |
| `okf` | 70 | 100 % |
| `hookslog` | 54 | 100 % |
| `watchdog` | 52 | 100 % |
| `knowledge` | 40 | 100 % |
| `ratchet` | 35 | 100 % |
| `coverage` | 32 | 100 % |
| `scaffold` | 27 | 100 % |
| `improve` | 27 | 100 % |
| `util` | 20 | 100 % |
| `syntax` | 19 | 100 % |
| `plugins` (artefacts) | 13 | — |

Les **10 seules lignes non couvertes** du moteur sont dans `cli.py`, et ce sont exactement celles
que `test_cli.py` exerce en sous-processus : l'aide sans sous-commande, `log` et `guard` qui lisent
stdin, et les deux `except` qui convertissent `FileNotFoundError` et `json.JSONDecodeError` en
message français. Elles sont testées ; c'est `trace` qui ne les voit pas, faute de suivre les
sous-processus. Le taux affiché est donc un plancher, pas un état réel.

## 9. Ce qui reste hors périmètre

- **Les prompts des agents** (`agents/*.md`, `skills/*/SKILL.md`) ne sont pas testés pour leur
  contenu — seulement pour la validité des chemins qu'ils citent. Ce qu'un agent produit est jugé
  par le `reviewer` et par la revue humaine, pas par une assertion.
- **Le comportement de Claude Code lui-même** (déclenchement effectif des hooks, chargement des
  plugins) est couvert par `claude plugin validate` en CI, pas par la suite.
- **Aucun test de performance.** Le moteur est en dizaines de millisecondes sur des fichiers de
  quelques kilo-octets ; mesurer coûterait plus que le risque.
