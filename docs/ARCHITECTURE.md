---
type: Reference
title: Architecture du harness AI-DLC
description: Référence de conception du dépôt aidlc-harness — intention, composants, cycle de vie d'une étape, grille de maturité, mode autonome et boucle de self-improvement.
tags: [architecture, harness]
generated: { by: human:steve-magne, at: 2026-09-04T00:00:00Z }
---

# Architecture du harness AI-DLC

Ce document est la référence de conception du dépôt `aidlc-harness`. Il décrit ce que fait le
harness, de quoi il est fait, et selon quelles règles une étape du cycle de vie logiciel est
considérée comme franchie.

---

## 1. Intention

Le harness industrialise un cycle de développement logiciel piloté par des agents. Un
orchestrateur instancie une session agentique par étape du SDLC. Chaque étape produit un
livrable écrit, versionné dans **le projet qui consomme le harnais** (pas dans le dépôt du
harnais), qui devient l'entrée de l'étape suivante.

Le dépôt `aidlc-harness` est distribué comme un **marketplace de plugins Claude Code**. Il
distingue deux racines : le **harnais** (`plugins/aidlc-core/` : `pipeline.json`, contrats,
script, hooks — installé dans le cache de Claude Code, désigné par `CLAUDE_PLUGIN_ROOT`) et le
**projet consommateur** (`CLAUDE_PROJECT_DIR` : `deliverables/`, `.aidlc/`, `knowledge/`). Quand
le dépôt sert de projet d'essai, les deux racines se confondent.

Trois principes gouvernent l'ensemble :

1. **Le livrable est le contrat.** Rien ne circule entre deux étapes en dehors d'un fichier
   présent dans `deliverables/` du projet consommateur. Pas de mémoire implicite, pas de contexte transmis de vive voix.
2. **La qualité se mesure deux fois.** D'abord de façon déterministe (un script applique un
   fichier de règles), ensuite de façon qualitative (un agent reviewer note sur une grille de
   maturité). Les deux doivent passer.
3. **L'autonomie se mérite.** Une étape ne se passe de revue humaine qu'après avoir démontré sa
   fiabilité sur plusieurs exécutions consécutives.

---

## 2. Les six étapes

Le pipeline suit les six phases du AI-native SDLC : `plan`, `design`, `build`, `test`, `deploy`,
`maintain`. Chaque étape a un livrable unique, un rôle humain responsable, et un plugin dédié.

| Étape      | Livrable                                | Rôle humain               | État            |
| ---------- | --------------------------------------- | ------------------------- | --------------- |
| `plan`     | `deliverables/plan/intent.md`            | Product Owner / Business Analyst | implémentée |
| `design`   | `deliverables/design/spec.md`            | Architecte de solution    | planifiée       |
| `build`    | `deliverables/build/plan.md`             | Tech Lead                 | planifiée       |
| `test`     | `deliverables/test/test-plan.md`         | QA Lead                   | planifiée       |
| `deploy`   | `deliverables/deploy/release-notes.md`   | SRE / Release Manager     | planifiée       |
| `maintain` | `deliverables/maintain/ops-report.md`    | Ops / Support             | planifiée       |

Seule l'étape `plan` est livrée en entier : elle sert de tranche verticale de référence. Les
cinq autres sont déclarées dans `pipeline.json` et se matérialisent à la demande via
`aidlc.py scaffold <stage>`, piloté par la skill `/aidlc-core:new-stage`.

### Chaîne livrable vers entrée

```
[besoin métier]
      |
      v
  plan  --> intent.md ------> design --> spec.md ------> build --> plan.md
                                                                     |
                                                                     v
 maintain <-- release-notes.md <-- deploy <-- test-plan.md <--     test
      |
      v
 ops-report.md --> (nouveau tour de plan)
```

Le champ `inputs` de chaque étape dans `pipeline.json` énumère les fichiers amont obligatoires.
La règle `must_reference_inputs` des `checks.json` vérifie que le livrable cite réellement ces
fichiers : un livrable qui ne s'appuie sur rien est rejeté par le contrôle déterministe, avant
même d'atteindre le reviewer.

---

## 3. Composants

### 3.1 `pipeline.json` — source de vérité des étapes

Fichier unique installé avec le plugin noyau : `plugins/aidlc-core/pipeline.json` (dans la copie
installée, il est résolu via `CLAUDE_PLUGIN_ROOT` ou par auto-localisation du script). Il déclare
la liste ordonnée des étapes, pour chacune : son identifiant, son plugin, sa skill, son livrable
(chemin relatif au **projet consommateur**), ses entrées, son fichier de contrôles — `checks/<stage>.json`,
relatif au plugin noyau — le rôle humain responsable et son statut (`implemented` ou `planned`).
Il porte aussi les deux paramètres de gouvernance :

- `maturity_threshold` (4.0) : note globale minimale pour qu'un livrable soit accepté.
- `consecutive_runs_to_autonomy` (3) : nombre d'exécutions consécutives au-dessus du seuil avant
  qu'une étape puisse passer en mode autonome.

Aucun composant ne doit contenir une liste d'étapes en dur. Tout ce qui a besoin de connaître le
pipeline lit ce fichier.

### 3.2 `checks.json` — validation déclarative

Chaque plugin d'étape embarque un `checks.json` (la source, dans `plugins/aidlc-<stage>/`) dont le
plugin noyau garde un miroir (`plugins/aidlc-core/checks/<stage>.json`) : c'est ce miroir que
`aidlc.py` lit, ce qui le rend indépendant de l'emplacement des plugins après installation. Le
fichier décrit, sans code, ce qu'un livrable acceptable doit contenir. Les règles disponibles :

| Règle | Effet |
| ----- | ----- |
| `required_frontmatter` | clés obligatoires du bloc YAML en tête de fichier |
| `required_sections` | titres markdown exacts obligatoires |
| `min_words` / `max_words` | volume minimal et maximal |
| `forbidden_patterns` | expressions régulières interdites (marqueurs de brouillon : `TODO`, `TBD`, `XXX`, « à compléter », « lorem ») |
| `required_patterns` | expressions régulières obligatoires |
| `must_reference_inputs` | chaque entrée déclarée de l'étape doit être citée dans le texte |
| `min_items_per_section` | nombre minimal de puces sous une section donnée |
| `proof_of_run` | **preuve d'exécution** : les sections déclarées doivent citer une valeur observée concrète (chiffre + unité, date, chemin, p95/p99, id) — reformuler l'attendu sans la valeur constatée n'est pas une preuve |
| `required_input_section` | chaque entrée doit être citée **dans une section précise** (`{"deliverables/plan/intent.md": "## Contexte"}`) — plus fort que `must_reference_inputs` |
| `must_not_violate_scope` | le livrable doit reprendre les items « hors périmètre » du plan amont dans sa propre section de périmètre sans les contredire (configurable : `{ "section": "## Hors périmètre" }`) |
| `checks_do_not_self_reference` | **holdout stdlib** : un livrable qui cite une ligne de son propre `checks.json` est rejeté — on optimise contre le livrable, pas contre le mètre |

Quatre de ces règles (`proof_of_run`, `required_input_section`, `must_not_violate_scope`,
`checks_do_not_self_reference`) sont héritées des mécanismes anti-dérive du « dark factory »
(ai-software-factory) : *evidence not claims*, *scope like a protected boundary*, *holdout* —
transposées en règles déclaratives, sans dépendance externe.

L'étape `plan` (tranche verticale de référence) active dès maintenant la preuve d'exécution sur
`## Contexte` et `## Critères d'acceptation` ainsi que le holdout
`checks_do_not_self_reference` (source `plugins/aidlc-plan/checks.json`, miroir
`plugins/aidlc-core/checks/plan.json`) : un `intent.md` doit citer un fait mesuré dans son
Contexte, chiffrer ses critères, et ne jamais citer les lignes de son propre `checks.json`. Les
règles `required_input_section` et `must_not_violate_scope` s'activeront avec les étapes qui ont
des entrées amont (design et suivantes).

Ajouter une exigence à une étape, c'est éditer un fichier JSON, pas écrire du Python. C'est le
levier principal du self-improvement : une faiblesse récurrente détectée par le reviewer se
traduit par une règle supplémentaire dans le `checks.json` de l'étape.

### 3.3 `plugins/aidlc-core/scripts/` — la seule logique déterministe

Bibliothèque standard Python uniquement, sans dépendance externe. Le point d'entrée `aidlc.py`
(chemin stable utilisé par les hooks et les skills) délègue au paquet `_aidlc/` du même
répertoire, un module par concern — `util` (racines et IO), `checks` (validation des livrables),
`maturity` (scores, porte, revue), `scaffold`, `improve`, `hookslog`, `okf` (conformance et
correctifs des bundles), `syntax` (hygiène du dépôt : tout Python compile, tout JSON parse),
`ratchet` (planchers de sévérité figés), `watchdog` (détecteurs de stagnation),
`selftest`, `commands` (gestionnaires de sous-commandes) et `cli`
(parseur et dispatch). L'ensemble résout deux racines : le **projet consommateur**
(`CLAUDE_PROJECT_DIR`, sinon le répertoire courant) pour les livrables et `.aidlc/`, et le
**harnais** (`CLAUDE_PLUGIN_ROOT`, sinon auto-localisation de `pipeline.json` à côté du moteur)
pour le pipeline et les contrats. Toutes les sorties machine sont en JSON sur la sortie standard,
les messages destinés à l'humain sur la sortie d'erreur. Ses sous-commandes :

| Commande | Rôle |
| -------- | ---- |
| `log` | journalise un événement de hook dans `.aidlc/logs/<session_id>.jsonl` ; n'échoue jamais |
| `guard` | refuse l'écriture directe d'un agent dans les fichiers de score et de revue |
| `validate <stage>` | applique le `checks.json` de l'étape au livrable |
| `validate --touched --file P` | même contrôle, déclenché par un hook après une écriture, non bloquant |
| `score <stage> --file review.json` | recalcule la note globale et l'enregistre dans `.aidlc/maturity.json` |
| `gate <stage>` | décide si l'étape est franchie ; sort en code 2 si elle ne l'est pas |
| `review-request <stage>` | prépare le formulaire de revue humaine et affiche la consigne |
| `status` | tableau de bord de l'avancement du pipeline |
| `scaffold <stage>` | génère le plugin complet d'une étape déclarée mais non implémentée |
| `improve` | agrège journaux, scores, refus et haltes du watchdog en un diagnostic JSON |
| `ratchet` | fige les planchers de sévérité des `checks.json` (min_words, min_items_per_section, required_sections) dans `.aidlc/ratchet.json` (protégé) et refuse toute régression ; `--reset <stage>` repart du contrat courant après décision humaine (geste auteur) ; exit 2 si violation |
| `watchdog` | détecteurs de stagnation sur les journaux (acharnement sur livrable en échec, boucle d'écriture, rafale de relances) ; halte enregistrée dans la file d'amélioration (`kind: watchdog`) ; exit 2 si halte |
| `watchdog-touched` | mode hook `PostToolUse` : diagnostic non bloquant après chaque écriture, muet sans détection |
| `check-okf <dir>` | vérifie la conformance OKF v0.2 d'un bundle (`docs/`, `knowledge/`, ou le `knowledge/` d'un consommateur) ; exit 1 si non conforme |
| `check-okf --touched` | même contrôle en mode hook `PostToolUse` : gate les bundles OKF du projet (`knowledge/`, et `docs/` s'il existe), non bloquant, retour en contexte |
| `check-okf --stop` | mode hook `Stop` : porte de sortie — refuse la fermeture de session (deny) si un bundle du projet est non conforme, et enregistre le refus dans la file d'amélioration |
| `check-python` | compile tout Python du dépôt (règle 6, `py_compile`, sans rien écrire) ; exit 1 si erreur de syntaxe |
| `check-python --touched` | mode hook `PostToolUse` : compile le fichier `.py` écrit — retour en contexte, non bloquant, silencieux hors Python |
| `check-json` | parse tout JSON du dépôt (règle 6) ; exit 1 si fichier invalide |
| `check-json --touched` | mode hook `PostToolUse` : parse le fichier `.json` écrit — retour en contexte, non bloquant, silencieux hors JSON |
| `--selftest` | auto-test par assertions sur un répertoire temporaire |

Règle non négociable du dépôt : toute nouvelle logique déterministe devient une sous-commande
exposée par ce point d'entrée, dans le module du paquet `_aidlc/` qui possède déjà le concern
(ou un nouveau module si c'est un concern nouveau). On n'ajoute pas de second point d'entrée ni
de fichier hors de `scripts/`.

### 3.4 Les hooks

Les hooks du plugin `aidlc-core` branchent le script sur le cycle de vie des sessions Claude Code.

- `SessionStart`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop` appellent `log`.
  C'est la matière première de l'axe *autonomy* et du diagnostic `improve` : on sait combien de
  tours, quels outils, quelles relances ont été nécessaires pour produire un livrable.
- `Stop` appelle `log` puis `check-okf --stop`. La fermeture de session est la **condition de
  sortie** du bundle de connaissance : si `knowledge/` (ou `docs/`, quand il existe) n'est pas
  conforme OKF v0.2, le hook refuse l'arrêt (`permissionDecision: deny`) et affiche la liste des
  problèmes à corriger ; corrigez puis redemandez l'arrêt. Portée observée du contrat : en
  session **interactive**, l'arrêt refusé ramène le contrôle à la session ; en mode **headless**
  (`claude -p`), le refus est émis et enregistré mais le processus se termine quand même
  (code 0) — la porte dure des pipelines sans session est l'étape CI `check-okf` (exit 1).
  Bundle conforme ou absent, la session se ferme normalement. Chaque refus est enregistré dans
  `.aidlc/improvement-queue.jsonl` (`kind: okf_stop`, session concernée) : c'est une entrée du
  diagnostic `improve` (§7).
- `PostToolUse` sur `Write|Edit` appelle `validate --touched`. L'agent reçoit immédiatement, en
  contexte additionnel, la liste de ce qui manque à son livrable. Le contrôle est informatif :
  il corrige au fil de l'eau au lieu de sanctionner à la fin.
- `PostToolUse` sur `Write|Edit` appelle aussi `check-okf --touched` : toute écriture dans un
  bundle OKF du projet — `knowledge/`, et `docs/` quand il existe (dépôt du harnais) — est
  contrôlée au fil de l'eau. Un concept sans frontmatter, un `index.md` incohérent ou un
  `log.md` mal daté remontent immédiatement en contexte additionnel, comme la validation des
  livrables. Informative en session, la passe est une porte dure en ligne de commande ou en CI
  (`check-okf`, exit 1).
- `PostToolUse` sur `Write|Edit` appelle aussi `check-python --touched` et `check-json --touched` :
  un fichier `.py`/`.json` écrit est compilé / parsé au fil de l'eau — une erreur de syntaxe ou
  un JSON invalide remonte en contexte additionnel, sans casser la session. Portée : le fichier
  écrit, car la syntaxe est sans état cross-fichier (un concept OKF sans frontmatter, lui,
  invalide tout son bundle) ; l'état complet du dépôt reste la porte dure `check-python` /
  `check-json` (exit 1) en ligne de commande et en CI.
- `PostToolUse` sur `Write|Edit` appelle aussi `watchdog-touched` : un diagnostic de stagnation
  non bloquant, muet sans détection. Le watchdog n'interrompt jamais une session qui travaille ;
  il enregistre la halte dans la file d'amelioration, et la commande `aidlc.py watchdog` (ou la
  CI) la rend visible avec exit 2.
- `PreToolUse` sur `Write|Edit` appelle `guard`. Il refuse catégoriquement qu'un agent écrive
  dans `.aidlc/maturity.json`, dans `.aidlc/reviews/*.json`, dans `.aidlc/ratchet.json`, dans
  `.aidlc/improvement-queue.jsonl` ou dans `.aidlc/logs/` — l'état runtime n'est écrit que par
  les scripts. Il refuse aussi, en mode consommateur, toute écriture dans la **copie installée**
  du harnais (hors du projet) : `pipeline.json`, `checks/`, `hooks/`, `scripts/`, agents,
  skills, templates — c'est la **liste protégée**. Un modèle ne doit pas pouvoir éditer sa
  propre note ni les règles qui le jugent : l'intégrité de la mesure conditionne tout le reste.
  Dans le dépôt auteur (les deux racines confondues), la conception reste libre.

Le journal est écrit sans jamais interrompre la session. Un hook qui casse une session coûte plus
cher que l'absence de trace.

### 3.5 Les agents de `aidlc-core`

- **`orchestrator`** — pilote le pipeline. Il lit `pipeline.json`, détermine l'étape courante via
  `aidlc.py status`, lance la skill de l'étape, déclenche le reviewer, puis `aidlc.py gate`. Il
  ne rédige jamais un livrable lui-même : il délègue systématiquement à l'agent d'étape.
- **`reviewer`** — note le livrable sur les quatre axes de la grille de maturité, émet un verdict,
  écrit un `review.json` et appelle `aidlc.py score`. Il doit justifier chaque note par une
  citation du livrable. Il n'a pas le droit d'écrire dans `.aidlc/`.
- **`librarian`** — sert la base de connaissance, un bundle OKF v0.2. Il répond à la question
  « quel contexte pour l'étape X » en lisant les concepts de `knowledge/` (filtrés par leur champ
  `stages`), le glossaire et les livrables amont. Lecture seule en dehors de `knowledge/`.

### 3.6 Les skills

`aidlc-core` expose cinq skills : `run` (exécuter une étape de bout en bout), `status` (tableau de
bord), `review` (déclencher le reviewer), `new-stage` (concevoir une nouvelle étape en dialogue
avec le métier puis la générer), `improve` (analyser le diagnostic et proposer un correctif).

Chaque plugin d'étape expose une skill du même nom que l'étape : elle contient la recette de
rédaction du livrable, les questions à poser à l'humain, et l'obligation de lancer
`aidlc.py validate <stage>` avant de rendre.

### 3.7 `knowledge/` — la base de connaissance

`knowledge/` vit dans le **projet consommateur** (c'est la mémoire du projet : normes internes,
ADR, retours d'expérience). C'est un **bundle OKF v0.2** : chaque fichier Markdown non réservé est
un concept à frontmatter YAML (`type` obligatoire, extension `stages` pour le routage par étape),
`index.md` en est le sommaire, `log.md` le journal des changements. Le librarian sert un briefing
ciblé par étape en filtrant les concepts sur `stages` et en y ajoutant les entrées déclarées dans
`pipeline.json`. Dans ce dépôt, `knowledge/` documente le harnais lui-même et sert de projet
d'essai. Chaque écriture dans le bundle est contrôlée par le hook `PostToolUse` (§3.4) ; en
session, le hook `Stop` refuse l'arrêt tant que le bundle est non conforme (portée interactive :
l'arrêt est refusé et le contrôle revient en session ; en headless `-p`, le refus est enregistré
sans bloquer — §3.4) ; la porte dure universelle est l'étape CI `check-okf` (exit 1). Voir
`knowledge/conventions.md` pour l'organisation du bundle et la procédure de versement d'un
concept.

### 3.8 État runtime

Ces chemins sont produits par le script dans le **projet consommateur**, jamais rédigés à la main
(à l'exception des fichiers de revue, signés par un humain) :

```
deliverables/<stage>/...            livrables versionnés (projet consommateur)
.aidlc/logs/<session_id>.jsonl      journal des sessions
.aidlc/maturity.json                historique des scores
.aidlc/reviews/<stage>-<n>.json     revues humaines signées
.aidlc/improvement-queue.jsonl      refus humains, haltes du watchdog et refus du gate OKF
.aidlc/ratchet.json                 planchers de sévérité figés (protégé par le guard)
.aidlc/tmp/                         scratch, ignoré par git
```

---

## 4. Cycle de vie d'une étape

```
  pipeline.json                              knowledge/ (OKF)
        |                                             |
        v                                             v
 +--------------+       « quel contexte ? »     +-----------+
 | orchestrator | <--------------------------> | librarian |
 +--------------+                               +-----------+
        |
        | (1) lance la skill de l'étape
        v
 +----------------------+   écrit    +--------------------------------+
 | agent <stage>-analyst| ---------> | deliverables/<stage>/<fichier> |
 +----------------------+            +--------------------------------+
        ^                                       |
        |                (2) hook PostToolUse   |
        |     retour immédiat des manques       v
        +---------------------------- aidlc.py validate  <-- checks.json
                                                |
                                        ok ? ---+--- non --> l'agent corrige
                                                |
                                               oui
                                                |
        (3) revue qualitative                   v
                                        +----------------+
                                        |    reviewer    |
                                        +----------------+
                                                |  review.json
                                                v
                                     +---------------------+
                                     |   aidlc.py score    | --> .aidlc/maturity.json
                                     +---------------------+
                                                |
        (4) décision                            v
                                     +---------------------+
                                     |   aidlc.py gate     |
                                     +---------------------+
                                        /                \
                              passed = false          passed = true
                                     |                       |
                       revue humaine requise          étape suivante
                                     |
                        approuvée ---+--- refusée
                            |                |
                     étape suivante   .aidlc/improvement-queue.jsonl
                                             |
                                             v
                                    /aidlc-core:improve
                                    (correctif proposé sur
                                     SKILL.md / template / checks.json)
```

### Les conditions du passage

`aidlc.py gate <stage>` ne renvoie `passed: true` que si les trois conditions suivantes sont
réunies :

1. `validate <stage>` passe : le livrable respecte toutes les règles de son `checks.json`.
2. Le dernier run enregistré porte le verdict `accepted` **et** une note globale supérieure ou
   égale à `maturity_threshold`.
3. La revue humaine est présente et approuvée — sauf si l'étape est passée en mode autonome.

Sinon, la sortie liste les éléments bloquants et le code de retour vaut 2, ce qui permet à un hook
`Stop` de retenir la session tant que l'étape n'est pas franchie.

---

## 5. Grille de maturité

Le reviewer note quatre axes sur une échelle commune :

| Note | Signification |
| ---- | ------------- |
| 0 | absent |
| 1 | brouillon |
| 2 | incomplet |
| 3 | acceptable avec réserves |
| 4 | conforme |
| 5 | exemplaire |

La note globale est la moyenne arithmétique des quatre axes, arrondie au dixième. Le script la
recalcule toujours : la valeur `overall` proposée par le reviewer est ignorée, ce qui évite
qu'une erreur d'arithmétique ou une complaisance passe la barre.

La frontière qui compte est celle entre **3 et 4** : c'est elle qui décide du passage. Chaque axe
ci-dessous donne son critère de discrimination explicite.

### 5.1 `completeness` — toutes les sections utiles sont remplies

- **0** livrable absent, vide, ou réduit au template non rempli.
- **1** une ou deux sections rédigées, le reste laissé en marqueur de remplissage.
- **2** toutes les sections existent mais plusieurs se limitent à une phrase générique.
- **3** toutes les sections obligatoires sont présentes et rédigées, mais au moins une reste
  superficielle : un seul élément là où le métier en attend plusieurs, ou une section qui
  reformule le titre sans rien ajouter.
- **4** chaque section apporte une information exploitable telle quelle ; le lecteur peut agir
  sans poser de question de relance.
- **5** en plus, les cas limites, les alternatives écartées et le hors périmètre sont traités
  explicitement.

> **3 ou 4 ?** Poser la question : *le destinataire du livrable doit-il revenir vers l'auteur pour
> pouvoir commencer son travail ?* Si oui, c'est 3.

### 5.2 `precision` — testable, non ambigu, chiffré

- **0** aucune affirmation vérifiable.
- **1** des intentions, pas des exigences.
- **2** quelques éléments concrets noyés dans du déclaratif.
- **3** la majorité des affirmations sont concrètes, mais au moins un critère d'acceptation reste
  non testable, ou un seuil annoncé n'est pas chiffré.
- **4** chaque critère d'acceptation est formulé de façon testable — un sujet, une action, un
  seuil mesurable — et aucun qualificatif d'appréciation non chiffré ne subsiste (« rapide »,
  « simple », « robuste », « performant »).
- **5** en plus, chaque seuil est sourcé : mesure existante, engagement de service, comparaison
  documentée.

> **3 ou 4 ?** Poser la question : *peut-on écrire, pour chaque critère, un test qui passe ou
> échoue sans interprétation ?* Si un seul critère échappe à la règle, c'est 3.

### 5.3 `traceability` — cite ses entrées et ses sources de vérité

- **0** aucune référence.
- **1** le contexte est évoqué sans être référencé.
- **2** une partie des entrées déclarées est citée, les autres sont ignorées.
- **3** toutes les entrées de l'étape sont citées, mais on ne sait pas quelle partie du livrable
  amont justifie quelle décision : la référence est globale, pas locale.
- **4** chaque décision structurante renvoie explicitement à son origine — chemin du livrable
  amont, section citée, ou chemin d'un concept du bundle `knowledge/` (glossaire, conventions,
  ADR).
- **5** en plus, les écarts assumés par rapport à l'amont sont listés et justifiés un par un.

> **3 ou 4 ?** Poser la question : *peut-on remonter d'une décision vers sa source sans deviner ?*
> Si la remontée demande une reconstitution, c'est 3.

### 5.4 `autonomy` — coût humain de production

Cet axe se lit dans le journal de session (`.aidlc/logs/<session_id>.jsonl`), pas dans le
livrable. Il mesure ce qu'il a fallu d'intervention humaine pour obtenir le résultat.

- **0** l'humain a rédigé à la place de l'agent.
- **1** plus de dix allers-retours correctifs.
- **2** plusieurs relances pour cause de format, de section manquante ou de procédure oubliée.
- **3** des relances ont eu lieu, mais uniquement sur le fond métier : ce sont des questions
  légitimes posées au responsable de l'étape.
- **4** aucune relance de forme ; les seuls échanges sont les questions métier prévues par la
  skill, et `validate` passe dès la première écriture complète du livrable.
- **5** en plus, l'agent a détecté et signalé de lui-même une lacune de ses propres entrées au
  lieu de produire un livrable bancal.

> **3 ou 4 ?** Poser la question : *a-t-on dû rappeler à l'agent sa propre procédure ?* Si oui,
> c'est 3, quelle que soit la qualité du résultat final.

### 5.5 Verdict

Le reviewer émet `accepted` ou `rejected`. Un verdict `accepted` avec une note globale inférieure
au seuil ne franchit pas la porte : le seuil prime sur l'avis. Chaque note doit être justifiée par
une citation du livrable ; une note sans citation est traitée comme non justifiée lors de la revue
humaine.

---

## 6. Passage en mode autonome

Par défaut, **toute étape exige une revue humaine** avant d'être franchie. C'est la position de
départ : le harness n'a rien prouvé.

Une étape bascule en mode autonome (`autonomous: true` dans `.aidlc/maturity.json`) quand les deux
conditions suivantes sont réunies :

1. Les `consecutive_runs_to_autonomy` derniers runs — trois par défaut — affichent tous une note
   globale supérieure ou égale au seuil de maturité.
2. Une revue humaine approuvée existe pour ces runs : l'humain a validé non seulement le livrable,
   mais la constance du procédé.

| Mode | Revue humaine | Ce qui reste actif |
| ---- | ------------- | ------------------ |
| Sous surveillance (défaut) | obligatoire à chaque run | validate, score, gate |
| Autonome | non requise | validate, score, gate |

Le mode autonome ne supprime ni la validation déterministe, ni la notation : il supprime
uniquement l'attente de la signature humaine. Un run autonome qui repasse sous le seuil bloque de
nouveau la porte, et l'étape redevient de fait sous surveillance jusqu'à ce que la série soit
reconstituée. La confiance est une moyenne glissante, pas un acquis.

---

## 7. Boucle de self-improvement

Le harness ne s'améliore pas en changeant de modèle : il s'améliore en changeant ses propres
instructions, à partir de ce que ses journaux montrent.

```
 refus humain (approved: false)
        |  justification
        v
 .aidlc/improvement-queue.jsonl
        |                                      halte du watchdog (kind: watchdog)
        |                                              (acharnement, boucle d'ecriture,
        |                                               rafale de relances)
        |   + .aidlc/logs/*.jsonl     (nombre de tours, outils, relances)
        |   + .aidlc/maturity.json    (axes les plus faibles, tendances)
        v
 aidlc.py improve  ->  diagnostic JSON
        |
        v
 /aidlc-core:improve
        |
        |  l'agent analyse le diagnostic et propose un diff concret
        v
 SKILL.md de l'étape   (la procédure était ambiguë)
 templates/<livrable>  (la structure induisait l'oubli)
 checks.json           (le défaut est détectable de façon déterministe)
        |
        v
 accord humain explicite  ->  application  ->  run suivant
```

Le **gate OKF de sortie** (section 3.4) emprunte le même chemin : quand le hook `Stop` refuse la
fermeture d'une session parce qu'un bundle est non conforme, `check-okf --stop` copie les erreurs
et l'identifiant de la session dans `.aidlc/improvement-queue.jsonl` (entrées `kind: okf_stop`).
Le diagnostic `improve` les isole des refus humains, corrèle chaque refus avec les sessions qui
ont écrit dans le bundle : le hook `check-okf --touched` journalise chaque écriture dans un
bundle non conforme (session, fichier, horodatage, dans `.aidlc/logs/`), ce qui permet de
retrouver la session **auteure** même quand l'arrêt refusé est celui d'une autre session. Le
diagnostic propose — pour les concepts dont seul le frontmatter est
en cause — un **correctif déterministe vérifié en mémoire** (ajout d'un frontmatter, fermeture,
clé `type`) ; le type par défaut et le titre dérivé restent soumis à confirmation humaine. Pour
le sommaire `index.md` (fichier réservé), il propose de même les concepts **orphelins** —
préparés dans le bundle mais absents de la liste — avec titre et description repris du
frontmatter de chaque concept.

Règle de répartition du correctif :

- Un défaut **détectable mécaniquement** (section manquante, volume insuffisant, entrée non
  citée, marqueur de brouillon) doit devenir une règle de `checks.json`. Il ne doit plus jamais
  atteindre le reviewer.
- Un défaut de **procédure** (l'agent n'a pas posé la bonne question, il a rendu trop tôt) se
  corrige dans le `SKILL.md`.
- Un défaut de **structure** (le plan du livrable ne guide pas vers la bonne information) se
  corrige dans le template.
- Un défaut de **forme du bundle de connaissance** (concept sans frontmatter, frontmatter
  ouvert, clé `type` absente) se corrige dans le concept `knowledge/` lui-même : le script
  propose un diff prêt à appliquer, jamais un relâchement de la passe.

Le script produit le diagnostic ; l'analyse fine et la proposition de correctif sont le travail de
l'agent. Aucun correctif n'est appliqué sans accord humain explicite : la boucle propose, elle ne
décide pas.

### 7.1 Mécanismes anti-dérive

Quatre mécanismes, hérités des principes du « dark factory » (ai-software-factory), rendent la
confiance indépendante des prompts :

1. **La liste protégée** — un agent ne peut pas écrire dans l'état runtime (score, revues,
   ratchet, file, journaux) ni dans la copie installée du harnais (pipeline, contrats, hooks,
   script, agents, skills, templates). Le hook `PreToolUse`/`guard` refuse ces écritures ; la
   conception du harnais vit dans le dépôt auteur, où les deux racines se confondent.
2. **Le ratchet** — `aidlc.py ratchet` fige les planchers de sévérité de chaque `checks.json`
   (`min_words`, `min_items_per_section`, `required_sections`) dans `.aidlc/ratchet.json`
   (protégé par le guard). Un plancher peut monter librement (durcir) ; le descendre est refusé
   (exit 2) sauf `ratchet --reset <stage>`, geste explicite de l'auteur après décision humaine.
   « Supprimer le contrôle » n'est pas une voie d'amélioration du score.
3. **Le watchdog** — un tick n'a pas de mémoire. Trois détecteurs sur les journaux de session
   (`_aidlc/watchdog.py`) arrêtent sur les formes de stagnation : acharnement sur un livrable qui
   échoue encore à la validation (le moteur revalide, il ne devine pas), boucle d'écriture d'une
   même session sur un même fichier, rafale de relances sur une même étape. Chaque halte est
   enregistrée dans la file d'amélioration (`kind: watchdog`, dédoublonnée) et remonte dans le
   diagnostic `improve` ; la reprise est un acte humain. En hook il est non bloquant ; en CI
   (`aidlc.py watchdog`) il sort en 2.
4. **Le holdout stdlib** — la règle déclarative `checks_do_not_self_reference` rejette un
   livrable qui cite son propre `checks.json` : on optimise contre le livrable, jamais contre le
   mètre. Combinée à `proof_of_run` (preuve d'exécution) et `must_not_violate_scope` (périmètre
   du plan amont respecté), elle impose que la validation mesure le travail, pas la conformité
   aux règles.

---

## 8. Conventions de conception

- Un livrable = un fichier dans `deliverables/` du **projet consommateur**, au chemin exact déclaré
  par le `pipeline.json` du harnais.
- Le harnais (pipeline, contrats, script) vit dans les plugins ; le projet (livrables, `.aidlc/`,
  `knowledge/`) vit chez le consommateur. Deux racines, résolues par le script.
- Toute logique déterministe vit dans `aidlc.py`, jamais dans un nouveau script.
- Bibliothèque standard Python uniquement, aucune dépendance externe, aucun format autre que JSON
  et Markdown.
- `.aidlc/maturity.json` et `.aidlc/reviews/*.json` ne sont jamais édités à la main par un agent :
  seuls `aidlc.py score` et l'humain y écrivent, et le hook `guard` fait respecter la règle.
- Les raccourcis assumés sont marqués dans le code par un commentaire `# ponytail: ...`.
