# Conventions du dépôt aidlc-harness

Ce fichier est lu par **tout agent** qui travaille dans ce dépôt. Il prime sur les habitudes
générales. Le guide utilisateur est le [README](README.md) ; l'architecture détaillée vit dans
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Rôle du dépôt

`aidlc-harness` est la source d'un **harnais agentique d'entreprise pour le AI-native SDLC**,
distribué comme un marketplace de plugins Claude Code. C'est un orchestrateur d'agents modulaire :
chaque équipe publie son agent dans son propre plugin et l'y déclare par un manifeste `agent.json`.
L'orchestrateur **découvre** les agents par ces manifestes — il ne tient aucune liste, et ajouter
un agent ne modifie jamais le noyau.

Un agent qui déclare `produces` est une **étape gouvernée** : son livrable est validé, noté, soumis
à une porte. L'ordre des étapes se dérive de la chaîne producteur → consommateur, pas d'une
position dans un fichier. Un agent sans `produces` est **consultatif** : invocable pour un avis,
jamais noté.

### Deux racines

- **Harnais** — `plugins/aidlc/` : `pipeline.json` (gouvernance par défaut), le moteur
  `scripts/_aidlc/`, le lanceur `bin/aidlc`, les hooks, la skill routeur. Une fois installé, c'est
  la copie en cache désignée par `CLAUDE_PLUGIN_ROOT`, **en lecture seule**.
- **Projet consommateur** — `CLAUDE_PROJECT_DIR` : `aidlc.json`, `deliverables/`, `.aidlc/` et
  `knowledge/`. `aidlc.json` recouvre `pipeline.json` clé par clé : c'est la seule gouvernance
  qu'une équipe projet écrit. Quand ce dépôt sert de projet d'essai, les deux se confondent.

## Langue

- **Français** (accents corrects) : documentation, `SKILL.md`, prompts d'agents, messages
  destinés à l'utilisateur, **noms de méthodes de test**.
- **Anglais** : identifiants, noms de fichiers, chemins, clés JSON, code Python.

## Deux points d'entrée, une frontière

```bash
plugins/aidlc/bin/aidlc <commande>   # pilotage : ce que le plugin expose à un consommateur
tools/aidlc-dev <commande>           # portes de CE dépôt : test, coverage, selfscore, ratchet
```

Le lanceur choisit `uv` quand il est présent (version Python garantie par le bloc PEP 723 de
`scripts/aidlc.py`), `python3` sinon ; `AIDLC_PYTHON` force un interpréteur. Sorties machine en
JSON sur **stdout**, messages humains sur **stderr**.

**La frontière est structurante** : `test`, `coverage`, `selfscore` et `ratchet` notent, mesurent
et figent CE dépôt. Elles n'ont aucun sens dans un projet consommateur — elles vivent donc hors du
plugin, et `aidlc --help` ne les montre pas.

```bash
D=tools/aidlc-dev
A=plugins/aidlc/bin/aidlc

$A agents                       # catalogue du registre (équipes, capacités, invocation)
$A init                         # amorce un projet consommateur
$A workflow --add design --initiative reco-panier   # composer le workflow, nommer l'idée
$A status --history             # tableau de bord, journal de passage
$A validate plan                # vérifie le livrable d'une étape
$A score plan --file review.json  # enregistre une revue du reviewer
$A gate plan                    # décide si l'étape est franchie (exit 2 = bloquant)
$A review-request plan          # prépare le formulaire de revue humaine
$A sign plan --approve --by "Nom" --why "..."   # signe (exige un terminal humain)
$A recall plan                  # reproches des tentatives précédentes
$A doctor                       # dérive projet ↔ version installée (exit 2 = bloquant)
$A improve --stage plan         # diagnostic pour la boucle d'amélioration
$A feedback --agent plan        # ce que ce projet a mesuré sur un agent
$A experiment record --stage plan --target precision --file <f> --cause "..."
$A knowledge search marge brute # savoir OKF des bundles déclarés
$A scaffold design              # génère le plugin d'un agent (n'écrit pas dans le noyau)
$A check-okf knowledge          # conformité OKF v0.2 (exit 1 = non conforme)
$A check-python · $A check-json # règle 6 : tout compile, tout parse
$A watchdog                     # détecteurs de stagnation (exit 2 = halte)

$D test                         # suite unittest — doit passer
$D test -k registry -v          # un sous-ensemble
$D coverage                     # non-régression de couverture (exit 2 = baisse)
$D selfscore                    # score de maturité du dépôt (exit 2 = sous le seuil)
$D ratchet                      # planchers de sévérité des checks.json
```

Les modes de hook (`hook log|guard|post-write|stop`) sont déclarés dans `hooks.json` et ne
s'invoquent jamais à la main.

## Arborescence

```
README.md                     présentation et quickstart
CLAUDE.md                     ce fichier
.claude-plugin/               marketplace local — `aidlc` d'abord, puis les exemples
.githooks/pre-commit          porte locale : le selfscore avant chaque commit
                              (activation : git config core.hooksPath .githooks)
docs/                         documentation publiée — bundle OKF v0.2
knowledge/                    base de connaissance du dépôt — bundle OKF v0.2

plugins/aidlc/                LE plugin : le harnais complet
  skills/aidlc/SKILL.md         la porte d'entrée — une table de verbes, rien d'autre
  skills/aidlc/reference/*.md   le détail d'un verbe, chargé seulement quand il est choisi
  bin/aidlc                     lanceur cité par les hooks, les skills et la doc
  scripts/aidlc.py              point d'entrée du moteur (bloc PEP 723)
  scripts/_aidlc/               un module par concern + le paquet tests/
  pipeline.json                 gouvernance par défaut — aucun registre d'étapes
  hooks/hooks.json              une entrée par événement, un processus par entrée
plugins/aidlc-plan/           EXEMPLE — étape en tête de chaîne
plugins/aidlc-design/         EXEMPLE — étape aval (consomme le livrable de plan)
plugins/aidlc-security/       EXEMPLE — agent consultatif (aucun `produces`)
tools/aidlc-dev(.py)          les portes de CE dépôt, hors du plugin

aidlc.json                    gouvernance du PROJET (seuils, `agents`, `initiative`)
deliverables/<stage>/         livrables — dans le projet consommateur
.aidlc/                       état runtime (logs, maturity.json, reviews, ratchet, coverage,
                              experiments.jsonl, harness.json) — projet consommateur
```

## Règles non négociables

1. **Un livrable = un fichier dans `deliverables/<stage>/` du projet consommateur**, au chemin
   exact déclaré par le `produces` du manifeste. Jamais ailleurs, jamais éclaté. Les livrables ne
   sont jamais écrits dans ce dépôt quand le harnais est consommé ailleurs.
2. **Toute logique déterministe vit sous `plugins/aidlc/scripts/`** : `aidlc.py` délègue au paquet
   stdlib `_aidlc/`, un module par concern (`util`, `checks`, `maturity`, `registry`, `scaffold`,
   `init`, `improve`, `experiment`, `hookslog`, `okf`, `knowledge`, `syntax`, `ratchet`,
   `watchdog`, `coverage`, `selfscore`, `doctor`, `commands`, `cli`, plus `tests/`). Jamais de
   troisième point d'entrée, jamais de logique dans un `Makefile` ni en shell inline dans un hook.
   Une vérification nouvelle s'exprime d'abord **déclarativement** dans le `checks.json` de
   l'étape ; on ne touche au Python que si aucune règle existante ne convient.
3. **Aucune dépendance externe.** Bibliothèque standard Python uniquement (`json`, `os`, `sys`,
   `re`, `pathlib`, `argparse`, `datetime`, `uuid`, `subprocess`, `statistics`, `unittest`,
   `trace`). Pas de `pip install`, pas de YAML, pas de pytest — ce serait une dépendance, et c'est
   elle qui est interdite, pas le fait de tester sérieusement. `uv` est un **lanceur préféré**,
   jamais un prérequis : `python3` seul doit toujours suffire.
4. **L'état runtime et le référentiel de règles ne sont jamais édités à la main par un agent.**
   `.aidlc/**` et `aidlc.json` ne sont écrits que par les scripts et par l'humain. Un hook
   `PreToolUse` refuse activement ces écritures, ainsi que toute écriture dans la copie installée
   du harnais, dans le plugin d'une autre équipe, et dans le livrable d'un autre agent. Un agent
   n'édite ni les règles qui le jugent, ni sa propre note, ni le contrat sur lequel il sera jugé.
   C'est un garde-fou d'intégrité, pas une gêne à contourner.
5. **Aucun placeholder non résolu** (`TODO`, `TBD`, `<à remplir>`, « lorem ») dans un fichier
   livré. Seule exception : les marqueurs entre chevrons des `templates/`.
6. **Tout JSON doit parser, tout Python doit compiler.** Les chemins écrits dans `hooks.json` et
   dans les `SKILL.md` doivent correspondre exactement à l'arborescence réelle.
7. Les raccourcis assumés portent un commentaire `# ponytail: ...` expliquant le compromis et son
   plafond. Pas d'abstraction spéculative : le moins de fichiers possible.
8. **Toute logique déterministe nouvelle arrive avec son test.** Un module de `_aidlc/` a un
   `_aidlc/tests/test_<module>.py` en face de lui ; une sous-commande nouvelle est testée deux
   fois — sa fonction `cmd_*` appelée directement (`test_commands.py`) et son contrat en
   sous-processus (`test_cli.py`). La couverture ne descend jamais.
9. **Le dépôt se note lui-même, et la note est bloquante.** `tools/aidlc-dev selfscore` agrège cinq
   axes déterministes (hygiène, contrats d'agents, tests, couverture, bundles OKF) en une note sur
   5. Un module orphelin de test, une couverture en baisse ou un bundle cassé font sortir 2. C'est
   la porte du `.githooks/pre-commit` et de la CI.
10. **Le chaînage est déterministe, jamais une consigne.** Une étape ne franchit pas sa porte si
   une entrée de son `consumes` manque, ou si son producteur n'a pas franchi la sienne — `gate`
   sort 2 avec les bloquants amont **en tête**. Cette règle vit dans `maturity.upstream_blockers`,
   pas dans un prompt. `validate` **avertit** quand une entrée amont manque : un vert muet est un
   mensonge.
11. **Une étape gouvernée sans contrat ne franchit rien.** `gate` consulte `contract_problems`
   avant tout le reste. Le bloquant nomme l'équipe propriétaire : le contrat se corrige dans son
   dépôt, pas ici.
12. **Un projet mène plusieurs idées ; les chemins le savent.** La clé `initiative` décale les
   livrables sous `deliverables/<idée>/` et l'état runtime sous `.aidlc/<idée>/`. Le segment
   s'insère à **un seul endroit** — `registry._normalize`, par `util.scoped`. Le garde-fou, lui,
   porte sur **tout** `.aidlc/` : sinon, déclarer une initiative déverrouillerait les scores de la
   précédente.
13. **La liste blanche du workflow ne s'édite qu'avec `aidlc workflow`.** La sous-commande valide
   ce qu'elle écrit, refuse un identifiant qu'aucun manifeste ne porte, préserve les clés du
   fichier et prévient quand un retrait casse la chaîne.
14. **La signature humaine est un geste de terminal.** `aidlc sign` refuse de tourner sans stdin
   interactif : le hook `PreToolUse` ne couvre que l'outil Write, et rien n'empêcherait sinon un
   agent d'appeler la commande par Bash. C'est ce test qui distingue « l'humain a signé » de
   « l'agent a écrit qu'il avait signé ». Ne l'affaiblissez pas pour la commodité d'un test.
15. **Une porte d'événement, un processus.** `hooks.json` déclare une seule commande par
   événement ; `hook post-write` enchaîne ses passes en mémoire. Six entrées sur le même événement,
   c'étaient six démarrages de l'interpréteur et six lectures concurrentes du même stdin après
   chaque écriture.
16. **La skill `aidlc` est la seule porte d'entrée.** Un verbe nouveau s'ajoute à sa table de
   routage **et** dans `reference/<verbe>.md` : une table qui cite une référence absente est une
   impasse silencieuse, une référence que rien ne cite est du travail que personne n'atteindra.
   Le routeur reste court — le détail vit dans les références, chargées à la demande.

## Tester

La suite vit dans `plugins/aidlc/scripts/_aidlc/tests/` — un module par concern, en face du module
qu'il teste. Elle repose sur `unittest` et n'est atteignable que par `tools/aidlc-dev test`.

Ce qui vaut pour un test de ce dépôt :

- **`harness.AidlcTestCase` ou rien.** Chaque test reçoit un projet temporaire neuf qui joue les
  deux racines, un environnement sauvé puis restauré, et un cache de registre vidé. Un test qui
  dépend de l'ordre des autres, laisse une variable d'environnement ou écrit hors de `self.root`
  est un défaut. Le dépôt réel ne s'ouvre qu'en lecture, via `repo_root()`.
- **Le nom de la méthode est la spécification.** En français, il se lit comme une phrase : c'est
  lui qui s'affiche quand le test tombe.
- **Une méthode = un comportement.** On ne fusionne pas deux assertions pour raccourcir.
- **Pas de test tautologique.** Les chemins d'erreur et les entrées malformées valent mieux que le
  chemin nominal.
- **Jamais de test qui relance la suite.** `test`, `--selftest` et `coverage` lancent la suite
  entière ; un test qui les invoque récurse. On teste ce routage par substitution
  (`unittest.mock`), pas en relançant.
- **Aucune dépendance externe, y compris pour mesurer.** La couverture se mesure avec `trace`.

## Amorcer un projet, ajouter un agent

Le premier contact passe par `/aidlc init` (la référence `skills/aidlc/reference/init.md`) : c'est
le seul endroit d'où les clés `agents` et `initiative` d'`aidlc.json` sont écrites.

Ne créez pas un plugin d'agent à la main, et pas depuis un projet consommateur. Utilisez
`/aidlc new-agent` **dans ce dépôt** : la skill dialogue avec le référent métier puis appelle
`aidlc scaffold <stage>`, qui génère le plugin complet — dont son `agent.json` — et l'inscrit au
marketplace. **Le noyau n'est jamais modifié.** Un agent développé hors de ce dépôt se déclare par
`AIDLC_AGENT_PATH` (répertoires séparés par `:`), qui a la précédence sur toute autre découverte.
