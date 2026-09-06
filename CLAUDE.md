# Conventions du dépôt aidlc-harness

Ce fichier est lu par **tout agent** qui travaille dans ce dépôt. Il prime sur les habitudes générales.

## Rôle du dépôt

`aidlc-harness` est la **source d'un harnais agentique d'entreprise pour le AI-native SDLC**,
distribué comme un marketplace de plugins Claude Code (`.claude-plugin/marketplace.json`).

C'est un **orchestrateur d'agents modulaire**. Chaque équipe publie son agent dans son propre
plugin, qu'elle maintient seule, et l'y déclare par un **manifeste `agent.json`** : identité,
équipe propriétaire, capacités, version, invocation par plateforme, et — s'il produit un livrable
— ce qu'il produit, ce qu'il consomme et son contrat. L'orchestrateur **découvre** les agents par
ces manifestes : il ne tient aucune liste, et ajouter un agent ne modifie jamais le noyau.

Un agent qui déclare `produces` est une **étape gouvernée** : son livrable est validé, noté par un
agent *reviewer*, et soumis à une porte de qualité ; l'ordre des étapes se dérive de la chaîne
producteur → consommateur, pas d'une position dans un fichier. Un agent sans `produces` est
**consultatif** : invocable pour un avis, jamais noté. Chaque session est journalisée en JSONL ;
sous le seuil de maturité une revue humaine est obligatoire, et les refus alimentent une boucle
d'auto-amélioration.

### Deux racines

Le harnais distingue **le harnais** (les plugins, leur pipeline et leurs contrats) du **projet
consommateur** (le projet qui installe les plugins et dans lequel sont produits les livrables) :

- **Harnais** — `plugins/aidlc-core/` contient `pipeline.json` (gouvernance seule : seuils,
  autonomie, watchdog, et `planned_stages` — feuille de route consultative), le moteur `scripts/` (point d'entrée `aidlc.py`,
  paquet stdlib `_aidlc/`) et les hooks. Une fois les plugins
  installés par Claude Code, cette racine est la copie en cache désignée par `CLAUDE_PLUGIN_ROOT`.
  **Le noyau ne contient aucun registre d'étapes ni miroir de contrat** : chaque contrat vit dans
  le plugin de l'équipe qui le porte.
- **Projet consommateur** — `CLAUDE_PROJECT_DIR` : `deliverables/`, `.aidlc/` et `knowledge/` y
  vivent. Quand ce dépôt est utilisé comme projet d'essai (session Claude Code ouverte ici), les
  deux racines se confondent dans le dépôt.

`aidlc.py` résout les deux racines seul (variables d'environnement `CLAUDE_PROJECT_DIR` et
`CLAUDE_PLUGIN_ROOT`, sinon auto-localisation du pipeline à côté du script).

## Langue

- **Français** (accents corrects) : documentation, `SKILL.md`, prompts d'agents, messages destinés à
  l'utilisateur.
- **Anglais** : identifiants, noms de fichiers, chemins, clés JSON, code Python.

## Arborescence

```
README.md                     présentation et quickstart (consommation + développement)
CLAUDE.md                     ce fichier
.claude-plugin/               marketplace local (marketplace.json)
docs/                         documentation publiée — bundle OKF v0.2 (index.md, log.md)
  ARCHITECTURE.md              architecture, grille de maturité, cycle de vie
  CONSUMER.md                  guide consommateur prêt à publier (installation, premier run, revue humaine)
  MAINTAINER.md                guide auteur prêt à publier (nouvel agent, release, mises à jour)
knowledge/                    base de connaissance du dépôt (projet d'essai) — bundle OKF v0.2
                              (index.md, log.md, glossary.md, conventions.md, sources/)

plugins/aidlc-core/           noyau : orchestrator, reviewer, librarian, aidlc.py, hooks, skills
  pipeline.json                 gouvernance seule (seuils, `watchdog`, `planned_stages`) — aucun registre d'étapes
  scripts/_aidlc/tests/         la suite : harness.py (socle partagé) + un test_<module>.py par concern
plugins/<plugin>/agent.json   manifeste d'un agent : le seul contrat que l'orchestrateur lit
plugins/aidlc-plan/           agent d'étape (produit un livrable, donc gouverné)
plugins/aidlc-design/         agent d'étape aval (consomme le livrable de plan)
plugins/aidlc-security/       agent d'équipe consultatif (exemple de référence, équipe AppSec)
planchers figés               .aidlc/ratchet.json — planchers de sévérité (guard protégé)
                              .aidlc/coverage.json — plancher de couverture (ne descend jamais)

deliverables/<stage>/         livrables — dans le PROJET consommateur (CLAUDE_PROJECT_DIR)
knowledge-sources.json        bundles OKF distants déclarés — projet consommateur
.aidlc/                       état runtime (logs, maturity.json, reviews, tmp/knowledge = cache
                              des bundles distants) — projet consommateur
```

## Lancer les commandes

Toute la logique déterministe passe par le point d'entrée `aidlc.py`, qui délègue au paquet
stdlib `_aidlc/`. Depuis la racine du dépôt (mode auteur, le moteur s'auto-localise) :

```bash
S=plugins/aidlc-core/scripts/aidlc.py

python3 $S agents                       # catalogue du registre (équipes, capacités, invocation)
python3 $S agents --capability security:review --json
python3 $S status                       # tableau de bord des étapes
python3 $S validate plan                # vérifie le livrable de l'étape plan
python3 $S score plan --file review.json  # enregistre une revue du reviewer
python3 $S gate plan                    # décide si l'étape est franchie (exit 2 = bloquant)
python3 $S review-request plan          # prépare le formulaire de revue humaine
python3 $S improve --stage plan         # diagnostic pour la boucle d'amélioration
python3 $S knowledge index              # sommaire des bundles OKF distants déclarés
python3 $S knowledge search marge brute # recherche par mots-clés (frontmatter puis corps)
python3 $S knowledge get <source>/<id>  # markdown d'un seul concept
python3 $S scaffold design              # génère le plugin d'un agent (n'écrit pas dans le noyau)
python3 $S ratchet                      # fige les planchers de sévérité des checks.json (exit 2 = régression)
python3 $S watchdog                     # détecteurs de stagnation sur les journaux (exit 2 = halte)
python3 $S check-okf knowledge          # conformité OKF v0.2 du bundle knowledge/ (exit 1 = non conforme)
python3 $S check-python                 # tout Python compile (règle 6 ; exit 1 = erreur de syntaxe)
python3 $S check-json                   # tout JSON parse (règle 6 ; exit 1 = JSON invalide)
python3 $S test                         # suite de tests du moteur (unittest stdlib) — doit passer
python3 $S test -k registry             # ne garde que les tests dont l'identifiant contient « registry »
python3 $S coverage                     # non-régression de couverture (exit 2 = la couverture a baissé)
python3 $S coverage --reset             # rebase le plancher de couverture (geste humain, visible au diff)
python3 $S --selftest                   # alias historique de `test` (hooks, CI, consommateurs)
```

Dans un **projet consommateur**, le script se lance depuis le plugin installé — les hooks et les
skills utilisent `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py"` ; le projet est résolu via
`CLAUDE_PROJECT_DIR`. Les sorties machine sont du JSON sur **stdout**, les messages humains sur
**stderr**. Dans les hooks, le script est appelé via
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py"`.

## Règles non négociables

1. **Un livrable = un fichier dans `deliverables/<stage>/` du projet consommateur**, au chemin exact
   déclaré par le champ `produces` du manifeste de l'agent. Pas de livrable ailleurs, pas de
   livrable éclaté en plusieurs fichiers. Les livrables ne sont jamais écrits dans ce dépôt quand
   le harnais est consommé ailleurs.
2. **Toute logique déterministe vit sous `plugins/aidlc-core/scripts/`** : le point d'entrée
   `aidlc.py` délègue au paquet stdlib `_aidlc/`, un module par concern (`util`, `checks`,
   `maturity`, `registry`, `scaffold`, `improve`, `hookslog`, `okf`, `knowledge`, `syntax`,
   `ratchet`, `watchdog`, `coverage`, `commands`, `cli`, plus le paquet `tests/`). Jamais de
   second point d'entrée, jamais de logique dans un `Makefile` ni en shell inline dans un hook. Si
   une nouvelle vérification est nécessaire, elle s'exprime d'abord de façon **déclarative** dans
   le `checks.json` de l'étape ; on ne touche au Python que si aucune règle existante ne convient.
3. **Aucune dépendance externe.** Bibliothèque standard Python uniquement (`json`, `os`, `sys`, `re`,
   `pathlib`, `argparse`, `datetime`, `uuid`, `subprocess`, `statistics`, `unittest`, `trace`). Pas
   de `pip install`, pas de YAML. Le framework de test est `unittest` — il est dans la stdlib, donc
   la suite tourne chez n'importe quel consommateur avec `python3` seul. Pas de pytest : ce serait
   une dépendance externe, et c'est elle qui est interdite, pas le fait de tester sérieusement.
4. **L'état runtime et le référentiel de règles ne sont jamais édités à la main par un agent.**
   `.aidlc/maturity.json`, `.aidlc/reviews/*.json`, `.aidlc/ratchet.json`,
   `.aidlc/improvement-queue.jsonl` et `.aidlc/logs/` ne sont écrits que par les scripts
   (`score`, `ratchet`, hooks) et l'humain (revues). Un hook `PreToolUse` refuse activement ces
   écritures, ainsi que toute écriture dans la **copie installée du harnais** hors du projet
   (pipeline.json, hooks/, script, agents, skills, templates — la liste protégée) **et dans le
   plugin d'un agent appartenant à une autre équipe, installé hors du projet** : un agent n'édite
   ni les règles qui le jugent, ni sa propre note, ni l'implémentation d'une direction voisine —
   son manifeste est lu, pas réécrit. C'est un garde-fou d'intégrité, pas une gêne à contourner ;
   chaque agent évolue dans le dépôt de son équipe.
5. **Aucun placeholder non résolu** (`TODO`, `TBD`, `<à remplir>`, « lorem ») dans un fichier livré.
   Seule exception : les marqueurs entre chevrons des `templates/`, qui sont documentés comme tels.
6. **Tout JSON doit parser, tout Python doit compiler** (`python3 -m py_compile`). Les chemins écrits
   dans `hooks.json` et dans les `SKILL.md` doivent correspondre exactement à l'arborescence réelle.
7. Les raccourcis assumés sont marqués par un commentaire `# ponytail: ...` expliquant le compromis.
   Pas d'abstraction spéculative : le moins de fichiers possible.
8. **Toute logique déterministe nouvelle arrive avec son test.** Un module de `_aidlc/` a un
   `_aidlc/tests/test_<module>.py` en face de lui ; une sous-commande nouvelle est testée deux
   fois — sa fonction `cmd_*` appelée directement (`test_commands.py`) et son contrat en
   sous-processus (`test_cli.py`, codes de sortie, stdout machine / stderr humain). La couverture
   ne descend jamais : `aidlc.py coverage` rougit la CI si elle baisse.

## Tester

La suite vit dans `plugins/aidlc-core/scripts/_aidlc/tests/` — un module par concern, en face du
module qu'il teste. Elle repose sur `unittest` (bibliothèque standard : rien à installer, ni ici
ni chez un consommateur) et n'est atteignable que par le point d'entrée : `aidlc.py test`, dont
`--selftest` reste l'alias historique.

```bash
S=plugins/aidlc-core/scripts/aidlc.py
python3 $S test                  # toute la suite
python3 $S test -k registry -v   # un sous-ensemble, un nom de test par ligne
python3 $S test --failfast       # s'arrête au premier échec
python3 $S coverage              # non-régression de couverture (exit 2 = baisse)
```

Ce qui vaut pour un test de ce dépôt :

- **`harness.AidlcTestCase` ou rien.** Chaque test reçoit un projet temporaire neuf qui joue les
  deux racines, un environnement sauvé puis restauré, et un cache de registre vidé. Un test qui
  dépend de l'ordre des autres, laisse une variable d'environnement ou écrit hors de `self.root`
  est un défaut, pas une commodité. Le dépôt réel ne s'ouvre qu'en lecture, via `repo_root()`.
- **Le nom de la méthode est la spécification.** Il est en français et se lit comme une phrase :
  c'est lui qui s'affiche quand le test tombe. C'est l'exception assumée à la règle « identifiants
  en anglais » — un nom de test ne nomme pas une API, il énonce un comportement attendu.
- **Une méthode = un comportement.** On ne fusionne pas deux assertions distinctes pour raccourcir.
- **Pas de test tautologique.** Une assertion qui ne tombe jamais quand le comportement change ne
  teste rien. Les chemins d'erreur et les entrées malformées valent mieux que le chemin nominal.
- **Jamais de test qui relance la suite.** `test`, `--selftest` et `coverage` lancent la suite
  entière ; un test qui les invoque récurse. Un garde-fou de réentrance neutralise l'imbrication,
  mais on teste ce routage par substitution (`unittest.mock`), pas en relançant.
- **Aucune dépendance externe, y compris pour mesurer.** La couverture se mesure avec `trace`
  (stdlib), jamais avec le paquet pip `coverage`.

## Ajouter un agent

Ne créez pas un plugin d'agent à la main, et ne le faites pas depuis un projet consommateur (la
copie installée du harnais n'est pas le lieu de conception). Utilisez la skill `/aidlc-core:new-stage`
dans ce dépôt : elle dialogue avec le référent métier puis appelle `aidlc.py scaffold <stage>`,
qui génère le plugin complet sous `plugins/` — dont son manifeste `agent.json` — et ajoute
l'entrée dans `.claude-plugin/marketplace.json`.

**Le noyau n'est jamais modifié.** C'est la condition de la modularité : une équipe publie son
agent, l'orchestrateur le découvre par son manifeste. Un agent consultatif (un avis, pas de
livrable) omet simplement `produces` : voir `plugins/aidlc-security/agent.json`. Un agent
développé hors de ce dépôt se déclare par `AIDLC_AGENT_PATH` (répertoires séparés par `:`), qui a
la précédence sur toutes les autres sources de découverte.
