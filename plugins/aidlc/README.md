# Plugin `aidlc` — le noyau du harness AI-DLC

`aidlc` est le plugin central du harnais agentique **AI-DLC** (AI-native SDLC). Il ne
correspond à **aucune étape métier** du cycle de vie : il fournit l'infrastructure qui fait
tourner toutes les étapes. Les six étapes du pipeline (`plan`, `design`, `build`, `test`,
`deploy`, `maintain`) sont des plugins autonomes qui s'appuient sur lui.

En **développement** (depuis la racine du dépôt `aidlc-harness`), il se charge avec le plugin de
l'étape courante :

```bash
claude --plugin-dir plugins/aidlc --plugin-dir plugins/aidlc-plan
```

En **consommation**, les deux plugins s'installent depuis le marketplace (`claude plugin install
aidlc@aidlc aidlc-plan@aidlc`) et la session s'ouvre dans le **projet** qui veut produire
les livrables.

## Deux racines

- Le **harnais** : ce plugin (`${CLAUDE_PLUGIN_ROOT}` une fois installé) porte le pipeline
  (`pipeline.json` : gouvernance seule ; les contrats sont lus dans les plugins
  d'étape), le script (`scripts/aidlc.py`) et les hooks.
- Le **projet consommateur** (`$CLAUDE_PROJECT_DIR`) : les livrables (`deliverables/`), l'état
  runtime (`.aidlc/`) et la connaissance (`knowledge/`). Les chemins cités plus bas (`.aidlc/…`,
  `deliverables/…`) sont relatifs à ce projet — jamais au dépôt du harnais.

`aidlc.py` résout les deux racines seul (`CLAUDE_PROJECT_DIR`, `CLAUDE_PLUGIN_ROOT`, sinon
auto-localisation) ; les skills et agents de ce plugin appellent le script via
`"${CLAUDE_PLUGIN_ROOT}/bin/aidlc"`.

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
  alimente la boucle de correction du harness lui-même, puis **mesure** l'effet de chaque
  correction appliquée sur les runs suivants (`experiment`) : la boucle sait ce qu'elle a déjà
  tenté et ce que ça a donné.
- **Registre d'agents** — découvre les manifestes `agent.json` des plugins (`agents`), indexe les
  capacités, dérive l'ordre des étapes de la chaîne des livrables.
- **Scaffolding** — génère le plugin complet d'un nouvel agent, sans écrire dans le noyau.

## Arborescence

```
plugins/aidlc/
  .claude-plugin/plugin.json      déclaration du plugin (nom, description, version)
  pipeline.json                   gouvernance par defaut : seuils, watchdog, planned_stages
                                  (aucun registre d'agents ; recouverte par l'aidlc.json du projet)
  agents/
    orchestrator.md               pilote le pipeline ; ne rédige jamais un livrable
    reviewer.md                   note le livrable sur 4 axes, émet un verdict, cite
    librarian.md                  sert knowledge/ : contexte citable pour chaque étape
  skills/
    aidlc/SKILL.md                LA porte d'entrée : une table de verbes, rien d'autre
    aidlc/reference/*.md          le détail d'un verbe, chargé seulement quand il est choisi
  bin/
    aidlc                         lanceur (uv sinon python3) — ce que citent hooks et skills
  scripts/
    aidlc.py                      moteur (bloc PEP 723) — appelé par bin/aidlc
    _aidlc/                       le paquet du moteur (stdlib, un module par concern)
  hooks/
    hooks.json                    une entrée par événement, un processus par entrée
```

## Les agents

Le pipeline s'appuie sur trois rôles d'agent, définis dans `agents/` et invoqués via la
primitive `Task` :

| Agent | Rôle | Droits |
| --- | --- | --- |
| `orchestrator` | décide quelle étape tourne, délègue la rédaction, déclenche le reviewer, applique la porte | **aucun `Write`/`Edit`** : il pilote, il ne rédige pas |
| `/aidlc ask` (skill) | traite une demande transverse : lit le catalogue, mobilise les agents par capacité, synthétise | n'écrit aucun fichier, n'invoque que des `id` du catalogue |
| `reviewer` | note le livrable (0–5 par axe), justifie chaque note par une citation, écrit `review.json` | écrit seulement dans `.aidlc/tmp/` |
| `librarian` | lit le bundle OKF `knowledge/` (concepts filtrés par `stages`) et les livrables amont, répond à « quel contexte pour l'étape X » | **lecture seule hors de `knowledge/`** |

La séparation des droits est le cœur de la conception : l'orchestrateur ne peut pas écrire un
livrable, le reviewer ne peut pas éditer sa propre note. Un hook `PreToolUse` (`guard`) refuse
d'ailleurs tout écriture d'agent dans `.aidlc/maturity.json` et `.aidlc/reviews/*.json`.

## La skill routeur

Le plugin n'expose **qu'une seule skill**, `aidlc`. Son `SKILL.md` tient en une table de routage ;
chaque verbe charge sa référence, et rien d'autre.

| Verbe | Ce qu'il fait | Référence |
| --- | --- | --- |
| `init` | amorce le projet et compose le workflow de l'initiative | `reference/init.md` |
| `next [étape]` | enchaîne : entrées amont → contexte (librarian) → rédaction déléguée → validation → notation → porte. S'arrête net sur une porte fermée. | `reference/next.md` |
| `status` | tableau de bord : où en est le pipeline, ce qui bloque, la prochaine action | `reference/status.md` |
| `review [étape]` | délègue au reviewer, vérifie la forme du `review.json`, enregistre la note, rejoue la porte | `reference/review.md` |
| `sign [étape]` | prépare la revue humaine et relaie la commande à taper — l'agent ne signe jamais | `reference/sign.md` |
| `agents` | qui est publié, qui est branché sur l'initiative, comment brancher | `reference/agents.md` |
| `new-agent [étape]` | l'entretien avec le référent métier, puis le scaffold. La pièce maîtresse : un savoir-faire humain devient une étape automatisable. | `reference/new-agent.md` |
| `ask <demande>` | mobilise les agents consultatifs par capacité et synthétise leurs avis | `reference/ask.md` |
| `improve [étape]` | corrèle faiblesse et cause racine, **propose** un diff, puis l'enregistre comme expérience jugée par les runs suivants | `reference/improve.md` |
| `doctor` | dérive entre le projet et la version installée : agent branché sans plugin, contrat cassé, livrable orphelin | `reference/doctor.md` |
| `knowledge [mots]` | sommaire, recherche, lecture d'un concept des bundles OKF déclarés | `reference/knowledge.md` |

Pourquoi une seule skill : huit descriptions concurrentes obligeaient l'agent à arbitrer entre des
périmètres qui se recouvraient, et chargeaient un fichier entier pour une question de routage. Une
table courte plus des références à la demande, c'est le motif *progressive disclosure* — et un test
tient les deux sens de la relation, pour qu'aucun verbe ne pointe dans le vide et qu'aucune
référence ne devienne inatteignable.

## Le moteur déterministe — `scripts/`

Le point d'entrée `scripts/aidlc.py` (chemin stable des hooks et des skills) délègue au paquet
`_aidlc/` : **toute** la logique non-agentique du harness y vit, bibliothèque standard Python
uniquement, un module par concern (`util`, `checks`, `maturity`, `scaffold`, `improve`,
`experiment`, `hookslog`, `okf`, `knowledge`, `syntax`, `ratchet`, `watchdog`, `coverage`,
`commands`, `cli`,
plus le paquet `tests/` qui porte la suite). Sorties machine : JSON sur
**stdout** ; messages humains sur **stderr**.

| Sous-commande | Rôle |
| --- | --- |
| `log` | journalise un événement de hook dans `.aidlc/logs/<session_id>.jsonl` ; ne casse jamais la session |
| `guard` | refuse l'écriture directe d'un agent dans les artefacts de score (hook `PreToolUse`) |
| `validate <stage>` | applique le `checks.json` de l'étape au livrable (exit 0 = conforme, 1 = non) |
| `validate --touched` | même contrôle en mode hook `PostToolUse`, non bloquant, retour de contexte immédiat |
| `score <stage> --file review.json` | recalcule la note globale (moyenne des 4 axes) et l'enregistre dans `.aidlc/maturity.json` |
| `gate <stage>` | décide si l'étape est franchie ; exit 2 si bloquante. **Vérifie le contrat et l'amont d'abord** : un `checks.json` absent ou incohérent bloque, puis chaque entrée `consumes` doit exister et son producteur avoir franchi sa porte |
| `review-request <stage>` | génère le formulaire de revue humaine `.aidlc/reviews/<stage>-<run>.template.json` |
| `sign <stage> --approve\|--reject --by "Nom" --why "..."` | écrit la revue humaine et rejoue la porte ; **refuse de tourner sans terminal interactif** — un agent ne signe pas |
| `init` | amorce un projet consommateur : `aidlc.json`, `deliverables/`, bundle `knowledge/`, inventaire des sources déjà présentes ; ne remplace jamais un fichier |
| `status [--json]` | tableau de bord des étapes (dont la colonne « en attente de » et les blocages amont), des agents consultatifs et des trous du registre |
| `status --history` | journal de passage de l'initiative : qui a produit, qui a noté, qui a signé, et quand |
| `workflow [--add X] [--remove X] [--initiative N]` | compose le workflow du projet : seule écrivaine de la clé `agents` d'`aidlc.json` et du nom de l'initiative ; sans option, montre ce qui est branché, ce qui est publié sans l'être, et ce qui est déclaré sans plugin |
| `feedback [--agent X] [--json]` | ce que ce projet a mesuré sur chaque agent — équipe, version, série de notes, axes faibles, refus et réserves — à rendre à l'équipe qui le maintient |
| `agents [--capability X] [--platform P] [--json] [--strict]` | catalogue du registre : équipes, capacités, invocation ; contrôle chaque `checks.json` à vide (règle inconnue, regex fautive, section insatisfiable, dérive gabarit, rubrique de revue absente) ; `--strict` = porte CI sur les manifestes et contrats du dépôt |
| `scaffold <stage>` | génère le plugin complet d'un agent (dont son `agent.json`) — n'écrit rien dans le noyau |
| `improve [--stage X]` | agrège logs, scores et refus (humains + gate OKF) en un diagnostic JSON ; propose des correctifs de frontmatter et les concepts orphelins du sommaire `index.md` ; porte les expériences déjà mesurées |
| `experiment record --stage X --target <axe> --file F --cause "..."` | date un correctif appliqué au harnais et fige la moyenne de l'axe visé (mesure d'avant) |
| `experiment effect [--stage X]` | confronte chaque correctif aux runs postérieurs : `improved`, `regressed`, `no_effect`, `pending` (exit 0, informatif) |
| `knowledge index` | sommaire des bundles OKF distants déclarés : une ligne par concept (référence, type, titre, description) |
| `knowledge search <mots>` | concepts portant tous les mots (frontmatter d'abord, puis corps) — rend des références |
| `knowledge get <source>/<id>` | le markdown d'un concept ; `--source`, `--refresh`, `--limit`, `--json` |
| `knowledge links <source>/<id>` | les voisins dans le graphe OKF : `->` cités, `<-` qui citent |
| `check-okf <dir>` | conformance OKF v0.2 d'un bundle (`docs/`, `knowledge/`, ou le `knowledge/` d'un consommateur) ; exit 1 si non conforme |
| `check-okf --touched` | même contrôle en mode hook `PostToolUse` : gate les bundles OKF du projet touchés par l'écriture, non bloquant |
| `check-okf --stop` | mode hook `Stop` : refuse la fermeture de session (deny) si un bundle du projet est non conforme ; enregistre le refus dans la file d'amélioration |
| `check-python` | compile tout Python du dépôt (règle 6, `py_compile`, sans rien écrire — pyc jetables) ; exit 1 si erreur de syntaxe |
| `check-python --touched` | mode hook `PostToolUse` : compile le fichier `.py` écrit — retour en contexte, non bloquant, silencieux hors Python |
| `check-json` | parse tout JSON du dépôt (règle 6) ; exit 1 si fichier invalide |
| `check-json --touched` | mode hook `PostToolUse` : parse le fichier `.json` écrit — retour en contexte, non bloquant, silencieux hors JSON |
| `test` | suite de tests du moteur (`unittest`, stdlib) ; `-k <motif>` filtre, `-v` détaille, `--failfast` s'arrête au premier échec |
| `coverage` | ratchet de couverture : la couverture ne descend jamais sous le plancher figé dans `.aidlc/coverage.json` ; exit 2 = régression |
| `coverage --reset` | rebase le plancher sur l'état courant (geste humain, refusé si la suite est rouge) |
| `selfscore` | note de maturité du dépôt : cinq axes déterministes (`hygiene`, `contracts`, `tests`, `coverage`, `knowledge`) agrégés sur le barème des livrables, seuil et plancher par axe de `pipeline.json` ; exit 2 si le seuil n'est pas tenu ou qu'un axe s'effondre — porte du hook pre-commit (`.githooks/pre-commit`) et de la CI |
| `--selftest` | alias historique de `test` — ce que la CI, les hooks et les consommateurs appellent depuis toujours |

## Les hooks — branchement sur le cycle de vie des sessions

`hooks/hooks.json` connecte le moteur aux événements de la session. **Une entrée par événement, un
processus par entrée** : c'est la règle qui gouverne ce fichier. Les passes d'un même événement
s'enchaînent *dans* le moteur, jamais en multipliant les entrées.

| Événement | Commande | Ce que ça fait |
| --- | --- | --- |
| `SessionStart`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `SessionEnd`, `PostToolUseFailure`, `Notification`, `PermissionDenied`, `PreCompact` | `hook log` | trace la session sans jamais l'interrompre — tours, relances, et ce que le procédé a coûté (un outil qui résiste, une permission demandée, un refus humain, un contexte qui déborde). C'est la matière de l'axe *autonomy*, qui sans elle se noterait à l'impression. |
| `PreToolUse` (`Write\|Edit`) | `hook guard` | refuse qu'un agent écrive dans `.aidlc/`, dans `aidlc.json`, dans la copie installée du harnais, dans le plugin d'une autre équipe, ou dans le livrable d'un voisin. |
| `PostToolUse` (`Write\|Edit`) | `hook post-write` | une passe unique, six diagnostics, un seul bloc de contexte. |
| `Stop` | `hook stop` | journalise, puis tient la porte OKF de clôture. |

### Ce que fait `hook post-write`, dans l'ordre

1. **Journal** — d'abord, toujours. Les détecteurs d'écriture du watchdog comptent
   `payload.tool_name` et `tool_input.file_path` ; sans un événement d'outil journalisé, ils ne
   peuvent jamais se déclencher. Du `tool_input`, seuls les chemins sont retenus : le contenu
   écrit n'entre pas dans `.aidlc/logs/`.
2. **Validation du livrable touché** — l'agent reçoit immédiatement la liste de ce qui manque, et
   corrige au fil de l'eau au lieu d'être sanctionné à la fin.
3. **Conformité OKF** — toute écriture dans un bundle du projet (`knowledge/`, et `docs/` s'il
   existe) est contrôlée : concept sans frontmatter, `index.md` incohérent, `log.md` non daté.
4. **Syntaxe Python**, **5. syntaxe JSON** — le fichier écrit est compilé ou parsé. Portée : ce
   fichier seul, la syntaxe étant sans état cross-fichier ; l'état complet du dépôt reste la
   porte `check-python` / `check-json` en CI (exit 1).
6. **Watchdog** — détecteurs de stagnation, non bloquants, qui alimentent la file d'amélioration.

Aucune passe ne peut casser la session : chacune est isolée, comme l'était son hook. Les six
étaient six entrées distinctes de `hooks.json` — donc six démarrages de l'interpréteur et six
lectures concurrentes du même stdin après **chaque** écriture de fichier. Ici stdin est lu une
fois, la session lue en circule jusqu'aux passes, et les diagnostics partent groupés.

### La porte de clôture

`hook stop` refuse l'arrêt (`deny`) quand un bundle OKF du projet n'est pas conforme, avec la
liste des problèmes. Portée du contrat : en interactif, l'arrêt refusé ramène le contrôle en
session ; en headless `-p`, le refus est émis et enregistré dans la file d'amélioration mais le
processus sort en 0 — la porte dure y est la CI `check-okf`. Bundle conforme ou absent, la session
se ferme normalement.

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
l'exemple de référence). `aidlc` ne connaît aucun agent en dur : il **découvre** les
manifestes `agent.json` des plugins installés (identité, équipe, capacités, invocation, et pour
une étape son livrable, ses entrées et son contrat). Son `pipeline.json` ne porte que la
gouvernance **par défaut** : le projet consommateur la recouvre clé par clé dans son `aidlc.json`,
posé par `aidlc.py init`, dont la clé `agents` déclare le workflow de l'initiative. Les plugins d'agent ne contiennent **aucune logique** : seulement le manifeste,
l'agent, la skill, le template et le `checks.json` — lu là où il est, sans copie dans le noyau.
Les plugins d'agent sont enregistrés dans
`.claude-plugin/marketplace.json` du dépôt auteur et installables via
`claude plugin install aidlc-<stage>@aidlc`.