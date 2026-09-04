# aidlc-harness

Harnais agentique pour un SDLC piloté par des agents, distribué **comme un ensemble de plugins
Claude Code**. Un orchestrateur instancie une session agentique par étape du cycle de vie
logiciel ; le livrable d'une étape est l'entrée de la suivante ; un agent *reviewer* note chaque
livrable et une porte (`gate`) décide si l'étape est franchie.

Les six étapes suivent le *AI-native SDLC* : **Plan → Design → Build → Test → Deploy → Maintain**.
Seule l'étape `plan` est implémentée. Les cinq autres se génèrent avec `aidlc.py scaffold <stage>`,
piloté par la skill `/aidlc-core:new-stage` — une opération d'auteur, menée dans ce dépôt.

Contraintes structurantes : Python de la bibliothèque standard uniquement, **aucune dépendance
externe**, **un seul script** pour toute la logique déterministe, validation **déclarative** via des
`checks.json`.

## Deux racines, à ne pas confondre

Ce dépôt est la **source** du harnais : il héberge le marketplace local (`.claude-plugin/`), les
plugins (`plugins/`) et la documentation. Il sert aussi de projet d'essai quand on l'utilise
« en interne ». Mais quand le harnais est **consommé**, les livrables ne sont pas écrits ici : ils
le sont dans le projet qui a installé les plugins.

- **Le harnais** — le pipeline, les contrats `checks/<stage>.json` et le script `aidlc.py` vivent
  dans le plugin `plugins/aidlc-core/` (et, une fois installé, dans la copie que Claude Code met en
  cache ; `${CLAUDE_PLUGIN_ROOT}` pointe cette copie).
- **Le projet consommateur** — `$CLAUDE_PROJECT_DIR` : c'est là que sont produits les livrables
  (`deliverables/<stage>/…`) et l'état runtime (`.aidlc/`, `knowledge/`).

`aidlc.py` résout les deux racines tout seul : `CLAUDE_PROJECT_DIR` pour le projet,
`CLAUDE_PLUGIN_ROOT` (sinon auto-localisation du script) pour le harnais.

## Arborescence

```
.claude-plugin/marketplace.json      marketplace local (installation des plugins)
CLAUDE.md                            conventions lues par tout agent du dépôt
docs/ARCHITECTURE.md                 architecture, grille de maturité, cycle de vie
knowledge/                           base de connaissance du dépôt (projet d'essai)

plugins/aidlc-core/                  le noyau — un plugin
  pipeline.json                        source de vérité : étapes, livrables, checks, statuts
  checks/<stage>.json                  contrats déterministes (miroir des plugins d'étape)
  agents/orchestrator.md               pilote le pipeline, ne rédige jamais un livrable
  agents/reviewer.md                   note le livrable sur 4 axes, émet un verdict
  agents/librarian.md                  indexe et sert knowledge/ (lecture seule)
  skills/{run,status,review,new-stage,improve}/SKILL.md
  scripts/aidlc.py                     TOUTE la logique déterministe
  hooks/hooks.json                     journalisation, validation à l'écriture, garde-fous

plugins/aidlc-plan/                  l'étape Plan (tranche verticale de référence) — un plugin
  agents/plan-analyst.md               dialogue avec le Product Owner
  skills/plan/SKILL.md                 la recette du livrable
  templates/intent.md                  le squelette du livrable
  checks.json                          le contrat de l'étape (source, miroir dans le noyau)

deliverables/<stage>/                livrables — produits dans le PROJET consommateur
.aidlc/logs/<session_id>.jsonl       journal des sessions — dans le PROJET consommateur
.aidlc/maturity.json                 historique des scores — dans le PROJET consommateur
.aidlc/reviews/<stage>-<n>.json      revues humaines signées — dans le PROJET consommateur
```

## Consommer le harnais dans un projet

Le guide pas à pas, prêt à diffuser aux équipes — installation, premier run, revue humaine,
versionnage des livrables — est dans [docs/CONSUMER.md](docs/CONSUMER.md). L'essentiel, depuis la
racine du **projet** qui veut utiliser le harnais :

```bash
# 1. Enregistrer ce dépôt comme marketplace, puis installer les plugins
claude plugin marketplace add <chemin-ou-git-de-aidlc-harness>
claude plugin install aidlc-core@aidlc
claude plugin install aidlc-plan@aidlc

# 2. Lancer une session Claude Code dans le projet
claude

# 3. Dans la session : produire le livrable de l'étape courante (le hook valide à chaque écriture)
/aidlc-core:run plan
```

Les livrables sont écrits dans `deliverables/<stage>/…` **du projet**, l'état de maturité dans
`.aidlc/` **du projet**. Rien n'est écrit dans le dépôt du harnais ni dans le cache des plugins.

Le script est aussi appelable en ligne de commande depuis le projet ; il trouve lui-même les deux
racines :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" gate plan
```

`gate` renvoie `0` si l'étape est franchie et `2` sinon — code de sortie exploitable par un hook
`Stop` ou par une CI.

## Développer le harnais (ce dépôt)

Le guide complet pour ajouter une étape, la publier dans le marketplace et faire évoluer les
contrats — avec la mécanique de version qui propage les mises à jour chez les consommateurs — est
dans [docs/MAINTAINER.md](docs/MAINTAINER.md). Depuis la racine du dépôt, le script se lance
directement (il s'auto-localise) :

```bash
# 1. Vérifier que le harnais est sain (le seul test du projet)
python3 plugins/aidlc-core/scripts/aidlc.py --selftest

# 2. Voir où en est le pipeline (les livrables, eux, vivent dans le projet consommateur)
python3 plugins/aidlc-core/scripts/aidlc.py status

# 3. Lancer une session Claude Code avec les plugins chargés
claude --plugin-dir plugins/aidlc-core --plugin-dir plugins/aidlc-plan
```

## Le cycle : étape → review → gate → amélioration

1. **Étape.** L'orchestrateur lit le pipeline (dans le plugin `aidlc-core`), détermine l'étape
   courante avec `aidlc.py status` et délègue à la skill de l'étape (`aidlc-plan:plan` pour
   `plan`). L'agent d'étape dialogue avec le référent métier, interroge le *librarian*, remplit le
   template du plugin et écrit le livrable au chemin déclaré, par exemple `deliverables/plan/intent.md`
   dans le projet.

2. **Validation déterministe.** À chaque écriture, un hook `PostToolUse` du plugin `aidlc-core`
   appelle `aidlc.py validate --touched` : sections manquantes, mots interdits (`TODO`, `TBD`, …),
   nombre de mots, puces minimales par section, citation obligatoire des livrables amont. Les
   règles sont déclarées dans le `checks.json` de l'étape — pas dans du code. La skill de l'étape
   corrige jusqu'à ce que le hook ne signale plus rien ; l'orchestrateur rejoue la validation avant
   la revue.

3. **Review.** L'agent *reviewer* note le livrable de 0 à 5 sur quatre axes — `completeness`,
   `precision`, `traceability`, `autonomy` — justifie chaque note par une citation, rend un verdict
   `accepted` / `rejected` et appelle `aidlc.py score`, qui recalcule la moyenne et l'écrit dans
   `.aidlc/maturity.json` du projet. Aucun agent n'écrit dans ce fichier : un hook `PreToolUse` le
   refuse.

4. **Gate.** `aidlc.py gate <stage>` franchit l'étape si, et seulement si : la validation passe, le
   dernier verdict est `accepted` avec un score ≥ `maturity_threshold` (4.0), et la revue humaine est
   satisfaite. La revue humaine est **obligatoire** tant que l'étape n'est pas autonome.

5. **Autonomie.** Après `consecutive_runs_to_autonomy` (3) exécutions consécutives au-dessus du seuil
   avec une revue humaine approuvée, l'étape passe `autonomous: true` : la revue humaine n'est plus
   exigée à chaque passage.

6. **Auto-amélioration.** Un refus humain copie sa justification dans
   `.aidlc/improvement-queue.jsonl`. `aidlc.py improve` agrège les logs de sessions, l'historique de
   maturité et cette file, et produit un diagnostic JSON. La skill `/aidlc-core:improve` lit ce
   diagnostic et **propose** un diff sur le `SKILL.md`, le template ou le `checks.json` de l'étape
   faible. Elle ne l'applique jamais sans accord explicite, et elle corrige la **source** du harnais,
   jamais la copie installée.

### Grille de maturité

| Note | Signification |
|------|---------------|
| 0 | absent |
| 1 | brouillon |
| 2 | incomplet |
| 3 | acceptable avec réserves |
| 4 | conforme |
| 5 | exemplaire |

Axes : **completeness** (toutes les sections utiles et remplies), **precision** (testable, non ambigu,
chiffré), **traceability** (cite ses entrées et les sources de vérité de `knowledge/`), **autonomy**
(peu d'allers-retours humains dans les logs de la session).

## Ajouter une étape (auteur)

Ne créez pas un plugin d'étape à la main — et ne le faites pas depuis un projet consommateur : une
étape se conçoit dans **ce dépôt**, qui contient `plugins/` et `.claude-plugin/`.

```
/aidlc-core:new-stage
```

La skill dialogue avec le référent métier — quel livrable, quelles sections, quels critères
déterministes, quel rôle humain — puis appelle le scaffolder, qui génère
`plugins/aidlc-<stage>/` complet (`plugin.json`, agent, `SKILL.md`, template, `checks.json`),
bascule le `status` de l'étape à `implemented` dans `plugins/aidlc-core/pipeline.json`, crée le
miroir `plugins/aidlc-core/checks/<stage>.json` et ajoute l'entrée dans
`.claude-plugin/marketplace.json`.

Le scaffolder s'appelle aussi directement, si vous savez ce que vous faites :

```bash
python3 plugins/aidlc-core/scripts/aidlc.py scaffold design
python3 plugins/aidlc-core/scripts/aidlc.py scaffold design --force   # écrase un dossier existant
```

## Charger les plugins

### En développement (session éphémère, rien d'installé)

```bash
claude --plugin-dir plugins/aidlc-core --plugin-dir plugins/aidlc-plan
```

Les plugins ne sont chargés que pour cette session : c'est le mode à utiliser pendant qu'on modifie
les `SKILL.md`, les agents ou les hooks. Avant de lancer la session, un contrôle rapide :

```bash
claude plugin validate plugins/aidlc-core
claude plugin validate plugins/aidlc-plan
```

### Via le marketplace local (installation persistante)

```bash
claude plugin marketplace add .
claude plugin install aidlc-core@aidlc
claude plugin install aidlc-plan@aidlc
claude plugin list
```

`claude plugin marketplace update aidlc` recharge le marketplace après l'ajout d'une nouvelle étape.
Pour revenir en arrière : `claude plugin uninstall aidlc-plan` puis
`claude plugin marketplace remove aidlc`.

## Conventions

Les règles que suit tout agent travaillant ici sont dans [CLAUDE.md](CLAUDE.md). Les trois qui
surprennent le plus :

- toute la logique déterministe vit dans `plugins/aidlc-core/scripts/aidlc.py` — on n'ajoute pas de
  second script ;
- une nouvelle vérification s'écrit d'abord dans un `checks.json`, pas en Python ;
- `.aidlc/maturity.json` et `.aidlc/reviews/*.json` ne sont jamais édités par un agent ; le hook
  `PreToolUse` refuse l'écriture.
