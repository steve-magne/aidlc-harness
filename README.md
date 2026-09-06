# aidlc-harness

**Un harnais agentique d'entreprise pour le AI-native SDLC**, distribué comme un marketplace de
plugins Claude Code. Des agents produisent les livrables du cycle de vie logiciel — cadrage,
conception, build, test, déploiement, exploitation — et le harnais **garantit que ce qu'ils
produisent est vérifiable** : validation déterministe, notation par un agent *reviewer*, porte de
qualité, signature humaine, journal de session.

---

## À quel besoin ça répond

Faire écrire un document de cadrage par une IA est facile. Le faire **de façon fiable, traçable et
reproductible dans une entreprise où chaque direction a ses règles** ne l'est pas. Quatre problèmes
concrets, et la réponse du harnais :

| Le problème | La réponse |
| --- | --- |
| La qualité dépend de la chance du prompt | Un contrat déclaratif (`checks.json`) par livrable, appliqué **à chaque écriture** par un hook |
| « C'est bon ? » n'a pas de réponse objective | Une note 0–5 sur 4 axes, un seuil, une porte qui renvoie un code de sortie exploitable en CI |
| Une étape démarre sur un livrable amont absent, ou pas encore validé | La porte exige que chaque entrée `consumes` **existe** et que son producteur ait franchi la sienne — dans le moteur, donc en CI aussi |
| L'IA avance seule là où l'humain devait décider | Revue humaine **obligatoire** tant que l'étape n'est pas autonome ; `sign` exige un terminal, un agent ne peut pas signer à votre place |
| Chaque projet a son exigence et son périmètre d'agents | `aidlc.json` à la racine du projet : seuils, feuille de route, et la liste blanche des agents qui composent **son** workflow |
| Un projet mène plusieurs idées, la seconde écrase la première | La clé `initiative` isole livrables, scores et signatures par idée : `deliverables/<idée>/`, `.aidlc/<idée>/` |
| Ce que les relecteurs constatent reste enfermé dans un projet | `feedback` rend à chaque équipe ce que les projets ont mesuré sur son agent : notes, axes faibles, refus **et** approbations motivées |
| Chaque équipe veut son agent, personne ne veut d'un noyau à modifier | Chaque équipe publie son plugin avec un manifeste `agent.json` ; l'orchestrateur **découvre** les agents, il n'en tient aucune liste |

À qui ça s'adresse : une **équipe projet** qui veut produire ses livrables avec des agents sous
contrôle (parcours A ci-dessous), et une **équipe plateforme/métier** qui veut publier son propre
agent dans la chaîne (parcours B).

---

## Démarrer en 5 minutes

Prérequis dans les deux cas : **Claude Code** récent (marketplaces de plugins + hooks) et
**Python 3**. Aucune dépendance à installer — le moteur n'utilise que la bibliothèque standard.

### Parcours A — j'utilise le harnais dans mon projet

Depuis la racine de **votre** projet (pas celle du harnais) :

```bash
claude plugin marketplace add <chemin-local-ou-url-git-de-aidlc-harness>
claude plugin install aidlc-core@aidlc
claude plugin install aidlc-plan@aidlc
claude plugin install aidlc-design@aidlc
claude
```

Puis, dans la session — l'amorçage d'abord, une fois pour toutes :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" init
```

Il pose `aidlc.json` (votre seuil, votre workflow), `deliverables/`, le bundle `knowledge/` et un
**inventaire des sources déjà présentes** dans votre dépôt — README, manifestes, ADR : le harnais
part de ce que le projet dit de lui-même, pas d'un entretien à froid. Il ne remplace jamais un
fichier existant.

Puis composez **votre** chaîne — quels agents d'équipe la traversent, et sous quel nom :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow    # ce qui est branché, et ce qui ne l'est pas
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow --initiative reco-panier --add design
```

```
/aidlc-core:setup      # amorcer et composer le workflow, en dialogue
/aidlc-core:status     # où en est le pipeline, qui est attendu, qu'est-ce qui bloque
/aidlc-core:run plan   # produire le livrable de cadrage, de bout en bout
```

L'agent dialogue avec vous, écrit `deliverables/plan/intent.md` **dans votre projet**, le hook le
valide à chaque écriture, le reviewer le note, la porte s'arrête et vous demande de signer. Rien
n'est écrit dans le dépôt du harnais.

→ Le guide pas à pas, y compris la signature de la revue : **[docs/CONSUMER.md](docs/CONSUMER.md)**.

### Parcours B — je développe ou j'étends le harnais

Depuis la racine de **ce dépôt** (le script s'auto-localise) :

```bash
python3 plugins/aidlc-core/scripts/aidlc.py test       # la suite unittest — doit passer
python3 plugins/aidlc-core/scripts/aidlc.py agents     # qui est dans le registre
python3 plugins/aidlc-core/scripts/aidlc.py status     # l'état du pipeline
claude --plugin-dir plugins/aidlc-core --plugin-dir plugins/aidlc-plan
```

Puis, dans la session, pour concevoir un nouvel agent avec son référent métier :

```
/aidlc-core:new-stage design
```

→ Le guide auteur : **[docs/MAINTAINER.md](docs/MAINTAINER.md)** · les tests :
**[docs/TESTING.md](docs/TESTING.md)**.

---

## Comment ça marche

> Une vue complète en diagrammes ASCII — neuf schémas, un par question — est dans
> **[docs/DIAGRAMS.md](docs/DIAGRAMS.md)**.

```
        ┌──────────────────────┐
        │   porte amont (gate) │  l'entrée `consumes` existe ?
        │   exit 2 si absente  │  son producteur a franchi sa porte ?
        └──────────┬───────────┘
                   │ ok
  contexte métier (humain)  +  savoir OKF (librarian)
                    │
                    ▼
        ┌──────────────────────┐  écriture   ┌──────────────────────┐
        │    agent d'étape     │ ──────────► │       validate       │  hook, à chaque écriture
        │      (dialogue)      │ ◄────────── │     (checks.json)    │  sections, mots interdits,
        └──────────────────────┘ corrections └──────────────────────┘  preuves d'exécution
                    │
                    ▼
        ┌──────────────────────┐             ┌──────────────────────┐
        │   reviewer  (0–5)    │ ──score──►  │         gate         │ ── exit 0 ─► étape suivante
        │   4 axes + verdict   │             │  seuil + signature   │ ── exit 2 ─► bloqué
        └──────────────────────┘             └──────────────────────┘
                                                        │ refus
                                                        ▼
                                        improvement-queue → /aidlc-core:improve
```

**Les cinq temps, en clair :**

1. **Étape.** L'orchestrateur lit le registre, détermine l'étape courante (`status`) et délègue à
   la skill de l'étape. L'agent dialogue avec le référent métier, interroge le *librarian*, remplit
   le template de son plugin et écrit le livrable au chemin déclaré par son manifeste.
2. **Validation déterministe.** À chaque écriture, un hook lance `validate --touched` : sections
   manquantes, mots interdits (`TODO`, `TBD`…), nombre de mots, puces minimales, citation des
   livrables amont. **Les règles sont déclarées, pas codées** — elles vivent dans le `checks.json`
   du plugin de l'équipe. Le même hook contrôle la syntaxe (Python, JSON) et la conformité OKF des
   bundles de connaissance.
3. **Review.** L'agent *reviewer* note de 0 à 5 sur `completeness`, `precision`, `traceability`,
   `autonomy`, justifie chaque note **par une citation**, rend un verdict et appelle `score`.
4. **Gate.** `gate <stage>` ouvre l'étape si — et seulement si — **chaque entrée amont existe et
   son producteur a franchi sa propre porte**, la validation passe, le verdict est `accepted`, la
   moyenne atteint **4.0**, **aucun axe ne tombe sous 3.0** (une bonne moyenne ne rachète pas un
   axe effondré), les entrées amont n'ont pas changé depuis la revue, et la revue humaine est
   signée (`aidlc.py sign <stage> --approve --by … --why …`, depuis un terminal). Sinon : exit 2,
   avec la liste des blocages, l'amont en tête.
5. **Autonomie & amélioration.** Après **3 runs consécutifs** au-dessus du seuil avec revue humaine
   approuvée, l'étape passe `autonomous` : la signature n'est plus exigée à chaque passage. Tout
   refus (humain, porte OKF, halte du watchdog) alimente `.aidlc/improvement-queue.jsonl`, que
   `/aidlc-core:improve` transforme en proposition de correctif **sur le harnais**, jamais sur le
   livrable — et jamais sans votre accord. Un correctif appliqué est **daté et mesuré**
   (`experiment`) : la boucle sait ce qu'elle a déjà tenté et ce que les runs suivants en ont dit,
   au lieu de reproposer indéfiniment ce qui n'a rien changé.

---

## Ce qui existe aujourd'hui

| Plugin | Type | Ce qu'il fait | Livrable |
| --- | --- | --- | --- |
| `aidlc-core` | noyau | orchestrateur, reviewer, librarian, moteur `aidlc.py`, hooks, skills | — |
| `aidlc-plan` | étape | cadre le besoin avec le Product Owner | `deliverables/plan/intent.md` |
| `aidlc-design` | étape | instruit l'intention, arrête l'architecture cible | `deliverables/design/spec.md` |
| `aidlc-security` | consultatif | avis AppSec sur une conception ou un changement | aucun (un avis, pas un livrable) |

`build`, `test`, `deploy` et `maintain` sont déclarés en **feuille de route** dans `pipeline.json` :
`status` les affiche en « prévu, plugin non installé », et `/aidlc-core:new-stage` les fabrique.

**Les skills à connaître :**

| Skill | Quand |
| --- | --- |
| `/aidlc-core:setup [initiative]` | amorcer le projet et composer le workflow avec les agents des équipes |
| `/aidlc-core:run [stage]` | faire tourner une étape de bout en bout |
| `/aidlc-core:status [stage]` | où on en est, **qui est attendu**, ce qui bloque |
| `/aidlc-core:review [stage]` | faire noter un livrable qu'on vient d'écrire |
| `/aidlc-core:dispatch <demande>` | demande transverse : mobilise les agents d'équipe par capacité et synthétise, en attribuant nommément |
| `/aidlc-core:knowledge [mots]` | chercher une définition, une norme, une décision antérieure |
| `/aidlc-core:new-stage <stage>` | concevoir un nouvel agent avec son référent métier (dépôt auteur) |
| `/aidlc-core:improve [stage]` | diagnostiquer une étape faible et proposer un correctif |

---

## Les commandes du moteur

Toute la logique déterministe passe par **un seul point d'entrée**. Depuis ce dépôt :
`S=plugins/aidlc-core/scripts/aidlc.py` ; depuis un projet consommateur :
`S="${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py"`.

```bash
python3 $S init                        # amorce un projet consommateur (idempotent)
python3 $S workflow                    # ce qui compose la chaîne, et ce qui est publié sans être branché
python3 $S workflow --add design --initiative reco-panier   # composer, et nommer l'idée en cours
python3 $S status                      # tableau de bord des étapes, et qui est attendu
python3 $S status --history            # journal de passage : qui a produit, noté et signé quoi
python3 $S agents --capability security:review --json
python3 $S validate plan               # le livrable respecte-t-il son contrat
python3 $S score plan --file review.json
python3 $S gate plan                   # porte de qualité          — exit 2 = bloquant
python3 $S review-request plan         # gabarit + consignes de revue humaine
python3 $S sign plan --approve --by "Nom" --why "..."   # signe et rejoue la porte (terminal humain)
python3 $S recall plan                 # ce qui a été reproché aux runs précédents
python3 $S improve --stage plan        # diagnostic d'auto-amélioration (JSON)
python3 $S feedback --agent plan       # ce que ce projet a mesuré sur un agent, à rendre à son équipe
python3 $S experiment effect           # ce qu'ont donné les correctifs déjà appliqués
python3 $S knowledge search marge brute
python3 $S scaffold design             # génère le plugin d'un agent (n'écrit pas dans le noyau)
```

Les portes exploitables en CI (le code de sortie *est* le verdict) :

| Commande | Ce qu'elle refuse | Exit |
| --- | --- | --- |
| `selfscore` | une évolution du **harnais** qui fait baisser sa note de maturité | 2 |
| `gate <stage>` | une étape non mûre, bâtie sur un amont absent ou non franchi, **ou dont le contrat est incohérent ou absent** | 2 |
| `ratchet` | une régression de sévérité d'un `checks.json` | 2 |
| `watchdog` | une boucle de stagnation détectée dans les journaux | 2 |
| `coverage` | une baisse de la couverture de tests | 2 |
| `check-okf <dir>` | un bundle de connaissance non conforme OKF v0.2 | 1 |
| `check-python` / `check-json` | un fichier qui ne compile pas / ne parse pas | 1 |
| `agents --strict` | un manifeste invalide **de ce dépôt** | 1 |
| `test` | un test en échec | ≠0 |

Sorties machine sur **stdout** (JSON), messages humains sur **stderr**. Dans un terminal, les
commandes qui portent déjà un résumé lisible (`init`, `workflow`, `gate`, `score`, `sign`) ne le
doublent pas d'un dump JSON ; hors terminal — hook, skill, CI, pipe — le JSON sort comme toujours,
et `--json` le force partout.

`selfscore` est la porte de tête : elle agrège en une note sur 5 les cinq axes déterministes du
dépôt — hygiène (`check-python`, `check-json`), contrats d'agents (`agents --strict`), suite de
tests et règle « un module, un test en face », couverture confrontée à son plancher figé, et
conformance OKF des bundles. La moyenne est comparée au `maturity_threshold` de `pipeline.json`,
et **un axe effondré ne se compense pas** (`min_axis_score`). C'est le même barème que la note
d'un livrable, appliqué au harnais qui les juge. En local, une fois par clone :

```bash
git config core.hooksPath .githooks   # le score devient une porte pre-commit
```

---

## Les garde-fous anti-dérive

La confiance ne repose pas sur les prompts. Quatre mécanismes structurels :

- **Preuve d'exécution** — des règles déclaratives exigent qu'une section **cite des valeurs
  observées** plutôt que de reformuler l'attendu (`proof_of_run`), que chaque entrée amont soit
  citée dans la section prévue (`required_input_section`), que le livrable respecte le hors
  périmètre décidé en amont (`must_not_violate_scope`), et qu'il **ne cite pas son propre
  `checks.json`** (holdout : `checks_do_not_self_reference`).
- **Porte amont** — `gate` refuse une étape dont une entrée `consumes` n'existe pas, ou dont
  l'agent producteur n'a pas franchi sa propre porte. La chaîne producteur → consommateur cesse
  d'être une consigne adressée à l'orchestrateur : c'est un code de sortie, opposable en CI.
- **Liste protégée** — un hook `PreToolUse` refuse l'écriture d'un agent dans `.aidlc/` (scores,
  revues, ratchet, expériences, journaux), dans `aidlc.json` (le seuil et le workflow du projet :
  un agent n'abaisse pas le mètre qui le juge, ni ne se retire du pipeline), dans la copie
  installée du harnais, et dans le plugin d'une **autre équipe** : un agent n'édite ni les règles qui le jugent, ni sa propre note, ni le code d'une
  direction voisine. `sign` complète le dispositif là où le hook ne va pas : elle **exige un
  terminal**, donc un agent qui la lancerait par un outil Bash reçoit un refus, pas une signature.
- **Contrat obligatoire** — une étape gouvernée dont le `checks.json` est absent ou incohérent ne
  franchit pas sa porte, et le bloquant nomme l'équipe qui doit le corriger. Sans cette règle,
  `validate` rendait « ok » avec zéro règle appliquée : le contrat est le prix d'entrée dans une
  chaîne gouvernée.
- **Ratchet** — `ratchet` fige les planchers de sévérité des contrats et refuse toute régression ;
  desserrer un contrat est un **geste humain explicite** (`ratchet --reset <stage>`), visible au diff.
- **Watchdog** — détecte dans les journaux l'acharnement sur un livrable en échec, les boucles
  d'écriture et les rafales de relances ; chaque halte alimente `improve`. Seuils dans le bloc
  `watchdog` de `pipeline.json`.

---

## Le registre d'agents — publier le sien

Le noyau ne contient la liste d'aucun agent : il les **découvre**. Chaque plugin porte un
`agent.json` à sa racine — identité, équipe propriétaire, capacités, version, invocation par
plateforme (`claude-code`, `codex`), et, s'il produit un livrable, ce qu'il produit, ce qu'il
consomme et son contrat.

- **Avec `produces`** → étape **gouvernée** : validée, notée, soumise à la porte. L'ordre des étapes
  se dérive de la chaîne producteur → consommateur, jamais d'une position dans un fichier.
- **Sans `produces`** → agent **consultatif** : invocable pour un avis, jamais noté. Modèle à
  copier : [`plugins/aidlc-security/agent.json`](plugins/aidlc-security/agent.json).

**Le projet, lui, choisit lesquels il retient.** La découverte est ouverte — on installe ce qu'on
veut sur sa machine —, mais la clé `agents` de l'`aidlc.json` du projet est une **liste blanche** :
un plugin installé pour une autre initiative et absent de cette liste n'existe pas pour ce projet.
L'avertissement joue **dans les deux sens** : un identifiant listé dont aucun plugin n'est installé
remonte sous le tableau de bord, et un agent découvert que personne n'a branché aussi — sans quoi
une équipe publie son plugin et ne voit rien. `aidlc.py workflow` est la seule commande qui écrit
cette liste : elle refuse un identifiant qu'aucun manifeste ne porte, et prévient quand un retrait
casse la chaîne producteur → consommateur.

**Publier un agent ne modifie jamais le noyau.** Un agent développé hors de ce dépôt se déclare par
`AIDLC_AGENT_PATH` (répertoires séparés par `:`), qui prime sur toute autre source de découverte :

```bash
AIDLC_AGENT_PATH=/chemin/vers/mes-agents python3 $S agents
```

Ne créez pas un plugin à la main : `/aidlc-core:new-stage` mène l'entretien métier puis appelle
`scaffold`, qui génère le plugin complet (`plugin.json`, `agent.json`, agent, `SKILL.md`, template,
`checks.json`, `review.md`) et l'inscrit au marketplace.

### Ajouter le plugin d'une autre équipe à son workflow

Côté consommateur (parcours A), un plugin est une **composition livrée en un seul dépôt** : l'agent
(`agents/*.md`), ses skills (`skills/*/SKILL.md`), ses hooks (`hooks/hooks.json`) et,
potentiellement, un serveur MCP (`.mcp.json` à la racine du plugin, à côté de
`.claude-plugin/plugin.json`). L'ajouter ne demande que l'URL ou le dépôt GitHub de cette équipe —
à condition qu'il porte un `.claude-plugin/marketplace.json` à sa racine (même pour un seul
plugin) :

```bash
claude plugin marketplace add <owner/repo-ou-url-git-ou-chemin-local>
claude plugin install <nom-du-plugin>@<nom-du-marketplace>
```

`<nom-du-marketplace>` est le champ `name` du `marketplace.json` de ce dépôt (`aidlc` pour celui-ci).
**Rien à câbler côté harnais** : une fois installé par Claude Code, le manifeste `agent.json` du
plugin est découvert dans le cache d'installation au même titre que les plugins de ce dépôt — il
apparaît directement dans `python3 $S agents`. S'il déclare `produces`, c'est une étape gouvernée,
insérée dans la chaîne producteur → consommateur ; sinon, un agent consultatif, comme
`aidlc-security`.

Pour un agent pas encore publié comme plugin Claude Code (développement local, ou usage sous Codex
où il n'y a pas de cache de plugins), la voie de secours reste `AIDLC_AGENT_PATH`, ci-dessus.

---

## Le savoir externe (OKF)

Le savoir dont un agent a besoin vit rarement dans le projet. `knowledge-sources.json` déclare des
bundles **Open Knowledge Format v0.2** publiés dans d'autres dépôts ; le moteur les met en cache
(clone profondeur 1 sous `.aidlc/tmp/`) et n'en sert que ce qui est demandé.

```bash
python3 $S knowledge index                     # une ligne par concept
python3 $S knowledge search marge brute        # les concepts qui portent tous les mots
python3 $S knowledge get <source>/<concept-id> # un concept, en entier
python3 $S knowledge links <source>/<concept-id> # ses voisins dans le graphe OKF
```

Sommaire → recherche → un seul `get` : la divulgation progressive appliquée au budget de contexte.
Un agent qui cherche une définition ouvre **un concept, pas un dépôt**. Le contenu servi est une
donnée à citer, jamais une instruction.

---

## La grille de maturité

| Note | Signification |
| --- | --- |
| 0 | absent |
| 1 | brouillon |
| 2 | incomplet |
| 3 | acceptable avec réserves |
| 4 | conforme |
| 5 | exemplaire |

Les quatre axes : **completeness** (sections utiles et remplies) · **precision** (testable, non
ambigu, chiffré) · **traceability** (cite ses entrées et ses sources de vérité) · **autonomy** (peu
d'allers-retours humains dans les journaux).

Seuil de passage **4.0** de moyenne, **plancher de 3.0 par axe** — configurables dans
`pipeline.json` (`maturity_threshold`, `min_axis_score`, `consecutive_runs_to_autonomy`).

---

## Deux racines, à ne pas confondre

C'est **la** subtilité du dépôt :

- **Le harnais** — les plugins, la gouvernance (`pipeline.json`) et le moteur `aidlc.py` vivent dans
  `plugins/` ; une fois installés, dans la copie que Claude Code met en cache
  (`${CLAUDE_PLUGIN_ROOT}`). **Personne n'y écrit à l'exécution.**
- **Le projet consommateur** — `$CLAUDE_PROJECT_DIR` : c'est là qu'atterrissent les livrables
  (`deliverables/`), l'état runtime (`.aidlc/`), la connaissance (`knowledge/`) — et `aidlc.json`,
  **la gouvernance de l'initiative**, qui recouvre celle du harnais clé par clé. C'est le seul
  endroit où une équipe projet règle son seuil et déclare le workflow qu'elle retient : le
  `pipeline.json` du harnais vit dans une copie installée que le garde-fou protège.
- **L'initiative** — un projet vit plus longtemps qu'une idée. La clé `initiative` d'`aidlc.json`
  décale les livrables sous `deliverables/<idée>/` et l'état runtime sous `.aidlc/<idée>/`, pour
  que la deuxième évolution n'écrase ni les livrables ni les signatures de la première. Absente,
  tout reste à plat : c'est le cas d'un projet qui n'en mène qu'une, et rien ne change pour lui.

`aidlc.py` résout les deux racines tout seul. Quand ce dépôt sert de projet d'essai (session ouverte
ici), les deux racines se confondent — d'où la présence de `deliverables/` et `.aidlc/` à la racine.

---

## Arborescence

```
README.md                          ce fichier
CLAUDE.md                          les conventions que suit tout agent travaillant ici
aidlc.json                         la gouvernance du PROJET consommateur : seuils, workflow
                                   (`agents`), feuille de route — posé par `aidlc.py init`
.claude-plugin/marketplace.json    le marketplace local (installation des plugins)
docs/                              bundle OKF : ARCHITECTURE, CONSUMER, MAINTAINER, TESTING
knowledge/                         bundle OKF du dépôt : glossaire, conventions, ADR
knowledge-sources.json             bundles OKF distants déclarés  (projet consommateur)

plugins/aidlc-core/                le noyau
  pipeline.json                      gouvernance seule : seuils, watchdog, feuille de route
  agents/{orchestrator,reviewer,librarian}.md
  skills/{run,dispatch,status,review,new-stage,improve,knowledge}/SKILL.md
  scripts/aidlc.py                   le point d'entrée unique
  scripts/_aidlc/                    le moteur, un module stdlib par concern
  scripts/_aidlc/tests/              la suite, un test_<module>.py par concern
  hooks/hooks.json                   journalisation, validation, portes, garde-fous

plugins/aidlc-plan/                l'étape Plan — la tranche verticale de référence
  agent.json                         le manifeste : la seule chose que l'orchestrateur lit
  agents/plan-analyst.md             l'agent qui dialogue avec le Product Owner
  skills/plan/SKILL.md               la recette du livrable
  templates/intent.md                le squelette
  checks.json                        le contrat déterministe (lu ici, sans miroir dans le noyau)
  review.md                          la grille de lecture du reviewer pour cette étape
plugins/aidlc-design/              l'étape Design — même structure, consomme le livrable de Plan
plugins/aidlc-security/            un agent consultatif d'équipe (AppSec) — l'exemple à copier

.githooks/pre-commit               la porte locale : `selfscore` avant chaque commit

deliverables/<stage>/…             les livrables            (projet consommateur)
deliverables/<initiative>/<stage>/ … quand le projet nomme son initiative dans aidlc.json
.aidlc/logs/<session>.jsonl        le journal des sessions  (projet consommateur)
.aidlc/maturity.json               l'historique des scores  (projet consommateur, protégé)
.aidlc/reviews/<stage>-<n>.json    les revues humaines signées (protégé)
.aidlc/{ratchet,coverage}.json     les planchers figés — ne descendent jamais (protégés)
.aidlc/experiments.jsonl           les correctifs appliqués et leur effet mesuré (protégé)
```

---

## Les contraintes structurantes

Trois règles expliquent la plupart des choix de conception. Le détail est dans
[CLAUDE.md](CLAUDE.md) :

1. **Aucune dépendance externe.** Bibliothèque standard Python uniquement — y compris pour tester
   (`unittest`) et pour mesurer la couverture (`trace`). La suite tourne chez n'importe quel
   consommateur avec `python3` seul.
2. **Toute la logique déterministe sous `plugins/aidlc-core/scripts/`**, derrière un point d'entrée
   unique. Pas de `Makefile`, pas de shell inline dans un hook, pas de second point d'entrée.
3. **Une nouvelle vérification s'écrit d'abord dans un `checks.json`**, pas en Python — et toute
   logique nouvelle arrive avec son test : la couverture ne redescend jamais, et `selfscore`
   refuse le commit qui ferait baisser la note du dépôt.

## Pour aller plus loin

| Document | Pour qui |
| --- | --- |
| [docs/DIAGRAMS.md](docs/DIAGRAMS.md) | comprendre le fonctionnement en schémas, sans lire de code |
| [docs/CONSUMER.md](docs/CONSUMER.md) | l'équipe projet : installation, premier run, revue humaine, mises à jour |
| [docs/MAINTAINER.md](docs/MAINTAINER.md) | l'auteur d'un agent : concevoir, remplir, vérifier, publier |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | la référence de conception : composants, cycle de vie, décisions |
| [docs/TESTING.md](docs/TESTING.md) | ce qui est testé, comment, et pourquoi |
| [knowledge/](knowledge/) | le glossaire, les conventions et les ADR du dépôt |
