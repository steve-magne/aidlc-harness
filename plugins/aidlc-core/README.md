# Plugin `aidlc-core` — le noyau du harness AI-DLC

`aidlc-core` est le plugin central du harnais agentique **AI-DLC** (AI-native SDLC). Il ne
correspond à **aucune étape métier** du cycle de vie : il fournit l'infrastructure qui fait
tourner toutes les étapes. Les six étapes du pipeline (`plan`, `design`, `build`, `test`,
`deploy`, `maintain`) sont des plugins autonomes qui s'appuient sur lui.

En **développement** (depuis la racine du dépôt `aidlc-harness`), il se charge avec le plugin de
l'étape courante :

```bash
claude --plugin-dir plugins/aidlc-core --plugin-dir plugins/aidlc-plan
```

En **consommation**, les deux plugins s'installent depuis le marketplace (`claude plugin install
aidlc-core@aidlc aidlc-plan@aidlc`) et la session s'ouvre dans le **projet** qui veut produire
les livrables.

## Deux racines

- Le **harnais** : ce plugin (`${CLAUDE_PLUGIN_ROOT}` une fois installé) porte le pipeline
  (`pipeline.json`), les contrats (`checks/<stage>.json`, miroirs des `checks.json` des plugins
  d'étape), le script (`scripts/aidlc.py`) et les hooks.
- Le **projet consommateur** (`$CLAUDE_PROJECT_DIR`) : les livrables (`deliverables/`), l'état
  runtime (`.aidlc/`) et la connaissance (`knowledge/`). Les chemins cités plus bas (`.aidlc/…`,
  `deliverables/…`) sont relatifs à ce projet — jamais au dépôt du harnais.

`aidlc.py` résout les deux racines seul (`CLAUDE_PROJECT_DIR`, `CLAUDE_PLUGIN_ROOT`, sinon
auto-localisation) ; les skills et agents de ce plugin appellent le script via
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py"`.

## Ce que fait ce plugin

- **Orchestration** — détermine l'étape courante, délègue la rédaction du livrable à la skill de
  l'étape, fait noter le résultat et applique la porte de qualité (`gate`).
- **Validation déterministe** — applique les règles déclaratives d'un `checks.json` de l'étape au
  livrable, sans code métier dans les plugins d'étape.
- **Notation de maturité** — un agent *reviewer* note chaque livrable de 0 à 5 sur quatre axes et
  enregistre le score dans `.aidlc/maturity.json`.
- **Revue humaine & autonomie** — prépare les formulaires de revue humaine et calcule l'autonomie
  d'une étape (revue humaine dispensée après N runs consécutifs au-dessus du seuil).
- **Journalisation** — trace chaque session dans `.aidlc/logs/<session_id>.jsonl`, la matière
  première de l'axe *autonomie* et du diagnostic d'amélioration.
- **Auto-improvement** — agrège logs, historique de maturité et refus humains en un diagnostic qui
  alimente la boucle de correction du harness lui-même.
- **Scaffolding** — génère le plugin complet d'une nouvelle étape à partir de `pipeline.json`.

## Arborescence

```
plugins/aidlc-core/
  .claude-plugin/plugin.json      déclaration du plugin (nom, description, version)
  pipeline.json                   source de vérité : étapes, livrables, entrées, checks, statuts
  checks/<stage>.json             contrats déterministes (miroirs des plugins d'étape)
  agents/
    orchestrator.md               pilote le pipeline ; ne rédige jamais un livrable
    reviewer.md                   note le livrable sur 4 axes, émet un verdict, cite
    librarian.md                  sert knowledge/ : contexte citable pour chaque étape
  skills/
    run/SKILL.md                  exécuter une étape de bout en bout (le chef d'orchestre)
    status/SKILL.md               afficher le tableau de bord du pipeline
    review/SKILL.md               déclencher la revue de maturité d'un livrable
    new-stage/SKILL.md            concevoir une nouvelle étape avec le métier puis la générer
    improve/SKILL.md              diagnostiquer une étape faible et proposer un correctif
  scripts/
    aidlc.py                      point d'entrée — chemin stable des hooks et skills
    _aidlc/                       le paquet du moteur (stdlib, un module par concern)
  hooks/
    hooks.json                    branche le script sur le cycle de vie des sessions
```

## Les agents

Le pipeline s'appuie sur trois rôles d'agent, définis dans `agents/` et invoqués via la
primitive `Task` :

| Agent | Rôle | Droits |
| --- | --- | --- |
| `orchestrator` | décide quelle étape tourne, délègue la rédaction, déclenche le reviewer, applique la porte | **aucun `Write`/`Edit`** : il pilote, il ne rédige pas |
| `reviewer` | note le livrable (0–5 par axe), justifie chaque note par une citation, écrit `review.json` | écrit seulement dans `.aidlc/tmp/` |
| `librarian` | lit le bundle OKF `knowledge/` (concepts filtrés par `stages`) et les livrables amont, répond à « quel contexte pour l'étape X » | **lecture seule hors de `knowledge/`** |

La séparation des droits est le cœur de la conception : l'orchestrateur ne peut pas écrire un
livrable, le reviewer ne peut pas éditer sa propre note. Un hook `PreToolUse` (`guard`) refuse
d'ailleurs tout écriture d'agent dans `.aidlc/maturity.json` et `.aidlc/reviews/*.json`.

## Les skills

Chaque skill est un scénario d'agent complet (frontmatter + instructions) :

- **`run <stage>`** — enchaîne : déterminer l'étape → vérifier les entrées amont → charger le
  contexte (librarian) → déléguer la rédaction à la skill de l'étape → valider → faire noter →
  ouvrir la porte. Il s'arrête net si une porte est fermée.
- **`status [stage]`** — lance `aidlc.py status` et commente : où en est le pipeline, ce qui
  bloque, la prochaine action. Lecture seule.
- **`review <stage>`** — délègue au reviewer, vérifie la forme du `review.json`, appelle
  `aidlc.py score`, restitue les notes puis applique `aidlc.py gate`.
- **`new-stage <stage>`** — mène l'entretien avec le référent métier (livrable, sections, règles
  déterministes, rôle humain) puis appelle `aidlc.py scaffold`. C'est la pièce maîtresse :
  c'est là qu'un savoir-faire humain devient une étape automatisable.
- **`improve <stage>`** — lit le diagnostic `aidlc.py improve`, corrèle faiblesse et cause racine,
  puis **propose** un diff sur un `SKILL.md`, un template ou un `checks.json` — et, quand c'est le
  gate OKF qui a bloqué, sur le frontmatter d'un concept `knowledge/` (correctif déjà structuré
  par le script) — appliqué seulement après accord explicite de l'humain.

## Le moteur déterministe — `scripts/`

Le point d'entrée `scripts/aidlc.py` (chemin stable des hooks et des skills) délègue au paquet
`_aidlc/` : **toute** la logique non-agentique du harness y vit, bibliothèque standard Python
uniquement, un module par concern (`util`, `checks`, `maturity`, `scaffold`, `improve`,
`hookslog`, `okf`, `commands`, `cli`, plus `selftest`). Sorties machine : JSON sur **stdout** ;
messages humains sur **stderr**.

| Sous-commande | Rôle |
| --- | --- |
| `log` | journalise un événement de hook dans `.aidlc/logs/<session_id>.jsonl` ; ne casse jamais la session |
| `guard` | refuse l'écriture directe d'un agent dans les artefacts de score (hook `PreToolUse`) |
| `validate <stage>` | applique le `checks.json` de l'étape au livrable (exit 0 = conforme, 1 = non) |
| `validate --touched` | même contrôle en mode hook `PostToolUse`, non bloquant, retour de contexte immédiat |
| `score <stage> --file review.json` | recalcule la note globale (moyenne des 4 axes) et l'enregistre dans `.aidlc/maturity.json` |
| `gate <stage>` | décide si l'étape est franchie ; exit 2 si bloquante |
| `review-request <stage>` | génère le formulaire de revue humaine `.aidlc/reviews/<stage>-<run>.template.json` |
| `status [--json]` | tableau de bord de l'avancement du pipeline |
| `scaffold <stage>` | génère le plugin complet d'une étape déclarée mais non implémentée |
| `improve [--stage X]` | agrège logs, scores et refus (humains + gate OKF) en un diagnostic JSON ; propose des correctifs de frontmatter et les concepts orphelins du sommaire `index.md` |
| `check-okf <dir>` | conformance OKF v0.2 d'un bundle (`docs/`, `knowledge/`, ou le `knowledge/` d'un consommateur) ; exit 1 si non conforme |
| `check-okf --touched` | même contrôle en mode hook `PostToolUse` : gate les bundles OKF du projet touchés par l'écriture, non bloquant |
| `check-okf --stop` | mode hook `Stop` : refuse la fermeture de session (deny) si un bundle du projet est non conforme ; enregistre le refus dans la file d'amélioration |
| `--selftest` | auto-test du projet (le seul test, il doit passer) |

## Les hooks — branchement sur le cycle de vie des sessions

`hooks/hooks.json` connecte le moteur aux événements de la session :

- `SessionStart`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop` → `aidlc.py log` : la
  session est tracée (tours, outils, relances) sans jamais l'interrompre.
- `Stop` → `aidlc.py log` puis `aidlc.py check-okf --stop` : la fermeture de session est la
  **condition de sortie** du bundle de connaissance — `knowledge/` non conforme ⇒ refus d'arrêt
  (`deny`) avec la liste des problèmes à corriger. Portée du contrat : interactive, l'arrêt
  refusé ramène le contrôle en session ; headless `-p`, le refus est émis et enregistré dans la
  file d'amélioration mais le processus sort en 0 (la porte dure y est la CI `check-okf`). Bundle
  conforme ou absent, elle se ferme normalement. Chaque refus alimente la file d'amélioration
  (diagnostic `improve`).
- `PreToolUse` (matcher `Write|Edit`) → `aidlc.py guard` : refuse qu'un agent écrive dans
  `.aidlc/maturity.json` ou `.aidlc/reviews/*.json`.
- `PostToolUse` (matcher `Write|Edit`) → `aidlc.py validate --touched` : l'agent reçoit
  immédiatement, en contexte additionnel, la liste de ce qui manque à son livrable — il corrige au
  fil de l'eau au lieu d'être sanctionné à la fin.
- `PostToolUse` (matcher `Write|Edit`) → `aidlc.py check-okf --touched` : toute écriture dans un
  bundle OKF du projet (`knowledge/`, et `docs/` s'il existe) est contrôlée — un concept sans
  frontmatter, un `index.md` incohérent ou un `log.md` non daté remontent immédiatement en
  contexte. La condition de sortie en session interactive est le hook `Stop`
  (`check-okf --stop`) ; en CI, `check-okf` (exit 1) est la porte dure.

## Le cycle de vie d'une étape

```
                      pipeline.json                    knowledge/ (OKF)
                            |                                  |
                            v                                  v
                      orchestrator <----------------------> librarian
                            |
                            |  lance la skill de l'étape
                            v
                     agent <stage>-analyst --------écrit----> deliverables/<stage>/<fichier>
                            ^                                  |
                            |  hook PostToolUse (retour     v
                            +----- aidlc.py validate <-- checks.json de l'étape
                                                                  |
                                                                  v
                                                   reviewer ------> aidlc.py score --> .aidlc/maturity.json
                                                                         |
                                                                         v
                                                              aidlc.py gate
                                                            /              \
                                                     bloquée            franchie
                                                       |                    |
                                        revue humaine requise → arrêt      étape suivante
```

Conditions de passage d'une étape (`gate` en exit 0) : validation déterministe au vert, dernier
verdict `accepted` avec un score ≥ `maturity_threshold` (4.0 par défaut), et revue humaine
approuvée — sauf si l'étape est autonome (3 runs consécutifs au-dessus du seuil, chacun approuvé
par un humain).

## Garde-fous d'intégrité

- `.aidlc/maturity.json` et `.aidlc/reviews/*.json` ne sont **jamais** édités par un agent ;
  seuls `aidlc.py score` (scores) et l'humain (revues signées) y écrivent.
- Aucun agent ne note son propre livrable ; le reviewer est sévère et doit citer le texte.
- Aucune logique déterministe hors de `scripts/` (`aidlc.py` + paquet `_aidlc/`) : pas de second
  point d'entrée.

## Relations avec les plugins d'étape

Chaque étape du pipeline possède son plugin `aidlc-<stage>` (cf. `plugins/aidlc-plan/` pour
l'exemple de référence). `aidlc-core` ne connaît pas les étapes en dur : il lit son
`pipeline.json` (installé avec lui), la source de vérité — étapes, livrables (relatifs au projet
consommateur), entrées, contrats `checks/<stage>.json`, rôle humain, statut. Les plugins d'étape
ne contiennent **aucune logique** : seulement l'agent, la skill, le template et le `checks.json`
de l'étape (dont le noyau garde un miroir). Les plugins d'étape sont enregistrés dans
`.claude-plugin/marketplace.json` du dépôt auteur et installables via
`claude plugin install aidlc-<stage>@aidlc`.