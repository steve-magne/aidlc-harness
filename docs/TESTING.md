---
type: Reference
title: Stratégie de tests du harnais AI-DLC
description: Ce que le harnais teste, comment, et pourquoi — suite unittest stdlib découpée par concern, contrat CLI en sous-processus, portes structurelles sur les artefacts de plugin, ratchet de non-régression de couverture et score de maturité du harnais (selfscore).
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
| **Contrat CLI, en sous-processus** | `test_cli.py` | Le contrat public réel : ce que les hooks et les skills invoquent. Codes de sortie (`exit 2` = bloquant), JSON sur **stdout** et humain sur **stderr**, exceptions d'IO/JSON converties en message français. C'est aussi le seul niveau où le **refus de `sign` hors terminal** se vérifie pour de bon : un sous-processus est exactement le contexte d'un agent qui lancerait la commande par un outil Bash |
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

## 7. Le score de maturité du harnais

Les portes précédentes répondent chacune par oui ou non. Une évolution du harnais mérite une
réponse plus fine : **est-ce que le dépôt est plus mûr ou moins mûr qu'avant ce diff ?**
`aidlc.py selfscore` répond par une note, sur le barème qui sert déjà à juger un livrable — 0 à 5,
seuil `maturity_threshold`, plancher par axe `min_axis_score`, tous trois lus dans `pipeline.json`.
Le harnais est noté par la grille qu'il impose aux autres.

Cinq axes, cinq risques distincts, tous **déterministes** : aucun juge, aucun prompt, aucun réseau.
Deux invocations sur le même arbre de fichiers rendent la même note.

| Axe | Ce qu'il mesure | Barème |
| --- | --- | --- |
| `hygiene` | Règle 6 : tout Python compile, tout JSON parse | 5, ou **0** si un seul fichier est fautif |
| `contracts` | Manifestes `agent.json` et contrats `checks.json` **de ce dépôt** ; cycle producteur → consommateur | 5, ou **0** au premier défaut |
| `tests` | La suite passe, et chaque module de `_aidlc/` a son `tests/test_<module>.py` en face (règle 8) | **0** si la suite est rouge ; sinon 5 − 1 par module orphelin |
| `coverage` | Le taux mesuré par `trace`, confronté au plancher figé dans `.aidlc/coverage.json` | **0** si régression ; sinon ≥ 95 % → 5, ≥ 90 → 4, ≥ 80 → 3, ≥ 70 → 2, ≥ 50 → 1 |
| `knowledge` | Conformance OKF v0.2 des bundles du projet (`knowledge/`, `docs/`) | 5 × bundles conformes / bundles |

Trois décisions valent d'être explicitées :

- **Les axes binaires le sont exprès.** Un dépôt dont un JSON ne parse pas n'a pas une qualité
  partielle : il ne se charge pas, et les axes suivants deviennent incalculables. La graduation a du
  sens là où la dégradation est graduelle — un module orphelin de test, un bundle sur deux, un taux
  de couverture — pas ailleurs.
- **Un axe effondré ne se compense pas.** La moyenne doit atteindre le seuil *et* aucun axe ne doit
  passer sous le plancher. Sans cette seconde règle, quatre axes à 5 et un à 0 donneraient 4,0 et
  franchiraient la porte — le défaut exact que `min_axis_score` corrige déjà pour les livrables.
- **Un axe peut être non applicable (`n/a`), jamais nul par défaut.** Un projet consommateur qui ne
  porte aucun bundle OKF n'est pas puni pour ce qu'il n'a pas : l'axe est affiché, il ne pèse pas
  dans la moyenne.

La passe est en **lecture seule**, et la suite n'y tourne qu'une fois : `tests` et `coverage` sont
deux lectures de la même mesure. Le plancher de couverture reste écrit par `aidlc.py coverage`
seul — sinon un `git commit` laisserait derrière lui un `.aidlc/coverage.json` modifié *hors* du
commit qu'il vient de valider.

Deux endroits l'exécutent, avec le même verdict :

```bash
git config core.hooksPath .githooks   # une fois par clone : la porte devient pre-commit
python3 plugins/aidlc-core/scripts/aidlc.py selfscore
```

Le hook `.githooks/pre-commit` refuse le commit sur `exit 2` (comptez une quinzaine de secondes,
la mesure sous `trace` domine) ; `git commit --no-verify` reste le contournement assumé, et la CI
rattrape ce qui passe par là.

## 8. Les portes de la CI

Dans l'ordre, chacune rougissant le build :

| Porte | Ce qu'elle défend |
| --- | --- |
| `test`, **sur une matrice de versions de Python** | La suite passe — et la promesse « `python3` seul, aucun `pip install` » tient réellement d'une version à l'autre |
| `check-python`, `check-json` | Règle 6 : tout Python compile, tout JSON parse |
| `agents --strict` | Les manifestes `agent.json` de ce dépôt sont valides |
| `check-okf docs`, `check-okf knowledge` | Conformance OKF v0.2 des deux bundles |
| `selfscore` | La note de maturité du dépôt tient le seuil, aucun axe sous le plancher (`exit 2`) |
| `claude plugin validate` | Chaque plugin reste valide pour Claude Code |

`selfscore` remplace la porte `coverage` en CI : elle fait la même mesure, en lecture seule, et
refuse en plus ce qu'une couverture verte laissait passer — un module neuf sans test en face, un
bundle OKF cassé, un manifeste invalide. Les portes unitaires restent en amont dans le workflow :
elles coûtent une seconde et nomment la panne avant que la porte agrégée ne la chiffre.

La suite tourne dans un job à matrice ; le reste des portes dans un job unique. La couverture
n'est mesurée que sur **une** version : le taux varie d'une version de Python à l'autre selon les
branches conditionnelles, et comparer un plancher unique à plusieurs mesures fabriquerait de
fausses régressions.

Aucune porte n'installe quoi que ce soit côté Python : la seule dépendance du workflow est le CLI
`@anthropic-ai/claude-code`, outil de build du runner, pas du moteur.

## 9. Où en est la suite

| | Avant | Après |
| --- | --- | --- |
| Forme | une fonction `selftest()` de 1254 lignes | 20 modules, 10 306 lignes |
| Cas | 173 assertions dans un bloc unique | **1 136 tests** nommés, en 233 classes |
| Isolation | un `TemporaryDirectory` partagé par tout | un projet temporaire neuf par test |
| Échec | le premier échec masque les 32 scénarios suivants | chaque test tombe seul et se nomme |
| Sélection | tout ou rien | `-k <motif>` |
| Couverture | **81,3 %** (471 lignes jamais exécutées) | **99,7 %** (10 lignes) |
| Non-régression | aucune | plancher figé, `exit 2` si baisse |
| Verdict | « ça passe » | une note sur 5, seuil et plancher par axe (`selfscore`) |

Répartition par module :

| Module | Tests | Couverture |
| --- | ---: | ---: |
| `commands` | 145 | 100 % |
| `maturity` | 141 | 100 % |
| `cli` | 128 | 95,1 % |
| `registry` | 92 | 100 % |
| `checks` | 79 | 100 % |
| `hookslog` | 75 | 100 % |
| `okf` | 70 | 100 % |
| `watchdog` | 52 | 100 % |
| `knowledge` | 50 | 100 % |
| `selfscore` | 45 | 100 % |
| `init` | 44 | 100 % |
| `ratchet` | 35 | 100 % |
| `coverage` | 32 | 100 % |
| `util` | 30 | 100 % |
| `scaffold` | 27 | 100 % |
| `improve` | 27 | 100 % |
| `plugins` (artefacts) | 23 | — |
| `experiment` | 22 | 100 % |
| `syntax` | 19 | 100 % |

Les **seules lignes non couvertes** du moteur sont dans `cli.py`, et ce sont exactement celles
que `test_cli.py` exerce en sous-processus : l'aide sans sous-commande, `log` et `guard` qui lisent
stdin, et les deux `except` qui convertissent `FileNotFoundError` et `json.JSONDecodeError` en
message français. Elles sont testées ; c'est `trace` qui ne les voit pas, faute de suivre les
sous-processus. Le taux affiché est donc un plancher, pas un état réel.

## 10. Ce qui reste hors périmètre

- **Les prompts des agents** (`agents/*.md`, `skills/*/SKILL.md`) ne sont pas testés pour leur
  contenu — seulement pour la validité des chemins qu'ils citent. Ce qu'un agent produit est jugé
  par le `reviewer` et par la revue humaine, pas par une assertion.
- **Le comportement de Claude Code lui-même** (déclenchement effectif des hooks, chargement des
  plugins) est couvert par `claude plugin validate` en CI, pas par la suite.
- **Aucun test de performance.** Le moteur est en dizaines de millisecondes sur des fichiers de
  quelques kilo-octets ; mesurer coûterait plus que le risque.
