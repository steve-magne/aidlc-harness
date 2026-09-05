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
plugins/<plugin>/agent.json   manifeste d'un agent : le seul contrat que l'orchestrateur lit
plugins/aidlc-plan/           agent d'étape (produit un livrable, donc gouverné)
plugins/aidlc-design/         agent d'étape aval (consomme le livrable de plan)
plugins/aidlc-security/       agent d'équipe consultatif (exemple de référence, équipe AppSec)
planchers figés               .aidlc/ratchet.json — planchers de sévérité (guard protégé)

deliverables/<stage>/         livrables — dans le PROJET consommateur (CLAUDE_PROJECT_DIR)
.aidlc/                       état runtime (logs, maturity.json, reviews, tmp) — projet consommateur
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
python3 $S scaffold design              # génère le plugin d'un agent (n'écrit pas dans le noyau)
python3 $S ratchet                      # fige les planchers de sévérité des checks.json (exit 2 = régression)
python3 $S watchdog                     # détecteurs de stagnation sur les journaux (exit 2 = halte)
python3 $S check-okf knowledge          # conformité OKF v0.2 du bundle knowledge/ (exit 1 = non conforme)
python3 $S check-python                 # tout Python compile (règle 6 ; exit 1 = erreur de syntaxe)
python3 $S check-json                   # tout JSON parse (règle 6 ; exit 1 = JSON invalide)
python3 $S --selftest                   # auto-test : le seul test du projet, il doit passer
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
   `maturity`, `registry`, `scaffold`, `improve`, `hookslog`, `okf`, `syntax`, `selftest`,
   `commands`, `cli`). Jamais de
   second point d'entrée, jamais de logique dans un `Makefile` ni en shell inline dans un hook. Si
   une nouvelle vérification est nécessaire, elle s'exprime d'abord de façon **déclarative** dans
   le `checks.json` de l'étape ; on ne touche au Python que si aucune règle existante ne convient.
3. **Aucune dépendance externe.** Bibliothèque standard Python uniquement (`json`, `os`, `sys`, `re`,
   `pathlib`, `argparse`, `datetime`, `uuid`, `subprocess`, `statistics`). Pas de `pip install`, pas
   de YAML, pas de framework de test.
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
