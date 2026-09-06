---
type: Reference
title: Architecture du harness AI-DLC
description: Référence de conception du dépôt aidlc-harness — intention, composants, cycle de vie d'une étape, grille de maturité, mode autonome et boucle de self-improvement.
tags: [architecture, harness]
generated: { by: human:steve-magne, at: 2026-09-06T00:00:00Z }
---

# Architecture du harness AI-DLC

Ce document est la référence de conception du dépôt `aidlc-harness`. Il décrit ce que fait le
harness, de quoi il est fait, et selon quelles règles une étape du cycle de vie logiciel est
considérée comme franchie.

---

## 1. Intention

Le harness industrialise un cycle de développement logiciel piloté par des agents. C'est un
**orchestrateur d'agents modulaire** : chaque équipe publie son agent dans son propre plugin,
qu'elle maintient seule, et l'orchestrateur le découvre par son **manifeste** sans rien connaître
de son implémentation. Un agent qui produit un livrable est une étape du SDLC ; le livrable est
versionné dans **le projet qui consomme le harnais** (pas dans le dépôt du harnais) et devient
l'entrée de l'agent suivant.

Le dépôt `aidlc-harness` est distribué comme un **marketplace de plugins Claude Code**. Il
distingue deux racines : le **harnais** (`plugins/aidlc-core/` : `pipeline.json`, contrats,
script, hooks — installé dans le cache de Claude Code, désigné par `CLAUDE_PLUGIN_ROOT`) et le
**projet consommateur** (`CLAUDE_PROJECT_DIR` : `deliverables/`, `.aidlc/`, `knowledge/`). Quand
le dépôt sert de projet d'essai, les deux racines se confondent.

Trois principes gouvernent l'ensemble :

1. **Le livrable est le contrat.** Rien ne circule entre deux étapes en dehors d'un fichier
   présent dans `deliverables/` du projet consommateur. Pas de mémoire implicite, pas de contexte
   transmis de vive voix. C'est aussi ce qui **ordonne** les étapes : l'agent qui consomme un
   livrable passe après celui qui le produit, sans qu'aucun fichier n'ait à fixer un rang.
2. **La qualité se mesure deux fois.** D'abord de façon déterministe (un script applique un
   fichier de règles), ensuite de façon qualitative (un agent reviewer note sur une grille de
   maturité). Les deux doivent passer.
3. **L'autonomie se mérite.** Une étape ne se passe de revue humaine qu'après avoir démontré sa
   fiabilité sur plusieurs exécutions consécutives.
4. **Le noyau ne connaît personne.** Aucun composant ne contient une liste d'agents. Ajouter un
   agent, c'est publier un plugin qui porte un `agent.json` — jamais modifier l'orchestrateur.
   C'est la condition pour que chaque direction reste autonome sur son agent.

---

## 2. Le registre d'agents

### 2.1 Le manifeste `agent.json`

Chaque plugin d'agent porte, à sa racine, un manifeste standardisé. C'est le **seul** contrat que
l'orchestrateur lit : tout y est neutre vis-à-vis de la plateforme, **sauf le bloc `invocation`**,
indexé par plateforme — c'est là, et seulement là, que vit l'implémentation propre à Claude Code
ou à Codex.

```json
{
  "manifest_version": 1,
  "id": "security-review",
  "team": "AppSec",
  "version": "0.1.0",
  "description": "Relit une conception et signale les risques exploitables.",
  "capabilities": ["security:review", "security:threat-model"],
  "invocation": {
    "claude-code": "aidlc-security:security-review",
    "codex": "skills/security-review/SKILL.md"
  }
}
```

| Champ | Obligatoire | Rôle |
| --- | --- | --- |
| `manifest_version` | oui | Version du contrat. Le noyau refuse explicitement toute valeur autre que `1`. |
| `id` | oui | Adresse de l'agent, unique dans le registre. Deux équipes qui publient le même id sont signalées, la première source gagne. |
| `team` | oui | L'équipe propriétaire — qui appeler quand l'agent se trompe. |
| `description` | oui | La phrase sur laquelle l'orchestrateur choisit. Sans elle, il devrait ouvrir l'implémentation : c'est précisément ce que le manifeste interdit. |
| `capabilities` | oui | Chaînes libres, convention `domaine:action`. Aucune taxonomie imposée : les collisions entre équipes sont un sujet de gouvernance, rendu visible par `team`. |
| `invocation` | oui | `{plateforme: invocation}`. Une plateforme absente rend l'agent non invocable **ici**, ce qui est signalé, jamais deviné. |
| `version` | non | Informatif, affiché. Jamais résolu en plage sémantique : le harnais n'est pas un gestionnaire de paquets. |
| `produces` | non | Le livrable unique. **Sa présence fait de l'agent une étape gouvernée.** |
| `consumes` | non | Les livrables amont attendus. C'est ce qui place l'agent dans la chaîne. |
| `requires` | non | Dépendance sur un agent qui ne produit rien (rare : la dépendance normale passe par les livrables). |
| `checks` | non | Contrat déterministe, **relatif au manifeste** — donc lu dans le plugin de l'équipe. |
| `review` | non | Rubrique de revue de l'équipe, **relative au manifeste**. Ce que chaque axe de maturité veut dire pour ce métier. Elle précise et durcit la grille universelle, jamais l'inverse. |
| `human_role` | non | Le rôle humain responsable de la revue. |

Un agent **sans `produces`** est *consultatif* : invocable pour un avis, jamais noté, aucune porte.
Un agent **avec `produces`** est une *étape* : validation déterministe, notation par le reviewer,
porte de qualité, ratchet. Un seul concept, un champ qui bascule.

### 2.2 La découverte

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" agents --json
```

Trois sources, par ordre de précédence :

1. **`AIDLC_AGENT_PATH`** — répertoires séparés par `:`. Le contrat documenté : explicite,
   portable, utilisable en CI et sous Codex.
2. **Les plugins du dépôt et du projet** — `plugins/*/agent.json`.
3. **Les plugins installés par Claude Code**, au mieux. Cette source repose sur un fichier interne
   non documenté et n'existe pas sous Codex : elle **n'est jamais porteuse**. Toute erreur y est un
   avertissement, jamais une exception ni un échec.

Le scan est de profondeur 1, jamais récursif : la découverte est sur le chemin chaud du hook
`guard`, qui s'exécute à chaque écriture.

### 2.3 Les étapes du SDLC

Le cycle suit les six phases du AI-native SDLC : `plan`, `design`, `build`, `test`, `deploy`,
`maintain`. Chaque étape a un livrable unique, un rôle humain responsable, et un plugin dédié qui
la déclare par son manifeste.

| Étape      | Livrable                                | Rôle humain               | État            |
| ---------- | --------------------------------------- | ------------------------- | --------------- |
| `plan`     | `deliverables/plan/intent.md`            | Product Owner / Business Analyst | implémentée |
| `design`   | `deliverables/design/spec.md`            | Architecte d'entreprise   | implémentée     |
| `build`    | `deliverables/build/plan.md`             | Tech Lead                 | planifiée       |
| `test`     | `deliverables/test/test-plan.md`         | QA Lead                   | planifiée       |
| `deploy`   | `deliverables/deploy/release-notes.md`   | SRE / Release Manager     | planifiée       |
| `maintain` | `deliverables/maintain/ops-report.md`    | Ops / Support             | planifiée       |

Les étapes `plan` et `design` sont livrées en entier : ensemble, elles forment la tranche
verticale de référence, et surtout le premier **handoff** réel entre deux directions — le Product
Owner cadre, l'architecte d'entreprise instruit. Les quatre autres figurent dans `planned_stages`
de `pipeline.json` — une **feuille de route consultative**,
affichée par `status` et utilisée pour pré-remplir le scaffold, qui n'exécute rien et n'oblige à
rien : un agent peut naître sans y figurer. Elles se matérialisent à la demande via
`aidlc.py scaffold <stage>`, piloté par la skill `/aidlc-core:new-stage`.

Le dépôt livre aussi `plugins/aidlc-security/` : un agent **consultatif** de l'équipe AppSec, qui
sert d'exemple de référence à toute équipe voulant publier le sien.

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

Le champ `consumes` du manifeste de chaque agent énumère les fichiers amont obligatoires. Cette
chaîne est tenue à **deux niveaux, qui ne disent pas la même chose** :

| Niveau | Question | Où | Sanction |
| --- | --- | --- | --- |
| Forme du livrable | le livrable **cite**-t-il ses entrées ? | `must_reference_inputs`, `required_input_section` (`checks.json`) | erreur de validation |
| État du pipeline | l'entrée **existe**-t-elle, et son producteur a-t-il franchi sa porte ? | `maturity.upstream_blockers`, appelé par `gate` | bloquant, exit 2 |

La distinction n'est pas cosmétique : `must_reference_inputs` ne compare qu'une **chaîne de
caractères** dans le texte du livrable. Tant que la porte ne regardait pas le disque, un livrable
aval pouvait valider à douze règles vertes, être noté 4/5 et franchir sa porte en mentionnant le
chemin d'une entrée qui n'avait jamais été écrite — la promesse de bout en bout ne tenait alors
que par la bonne volonté de l'orchestrateur, et n'importe quel appel direct ou en CI la
contournait.

`gate` refuse donc, **avant tout autre motif** :

```
[bloquant] Entree amont absente : deliverables/plan/intent.md — produire d'abord le livrable de l'agent 'plan'.
[bloquant] Entree amont absente : deliverables/x/y.md — aucun agent installe ne la produit, son plugin manque.
[bloquant] Porte amont fermee : l'agent 'plan' n'a pas franchi la sienne (Revue humaine requise…).
```

La remontée est **d'un cran à la fois** : la porte de l'aval demande celle de son amont direct,
qui demande la sienne, et un ensemble `seen` coupe une dépendance circulaire (que le registre
signale par ailleurs). Le tableau de bord, lui, n'appelle jamais `gate` : les agents lui arrivent
déjà triés par la chaîne producteur → consommateur, il lui suffit de retenir au fil de l'eau
quelles lignes sont franchies.

Côté validation, une entrée absente ne devient pas une erreur — la forme du livrable, elle, peut
être irréprochable — mais elle produit un **avertissement nommé** : les règles qui lisent l'amont
(`must_reference_inputs`, `required_input_section`, `must_not_violate_scope`, cette dernière
s'échappant silencieusement quand le fichier manque) n'ont alors rien vérifié, et un vert muet
serait un mensonge.

### Où vivent les dépôts

Le handoff entre deux personas est un **chemin de fichier versionné**. La topologie git en découle
directement (ADR-0003) :

| Dépôt | Ce qu'il porte | Qui le possède |
| --- | --- | --- |
| **Un par équipe** | le plugin d'un agent : manifeste, prompt, `checks.json`, squelette, skill | l'équipe qui publie l'agent — elle seule décide de son rythme de release |
| **Un par initiative** | le projet consommateur : `deliverables/`, `.aidlc/`, `knowledge/` | l'initiative — **tous les personas y écrivent** |

Ce n'est pas une convention décorative : la frontière entre équipes est *active*, le hook
`PreToolUse` refusant à un agent d'écrire dans le plugin d'une autre équipe installé hors du
projet. À l'inverse, les livrables partagent un seul dépôt parce que `consumes` est un chemin qui
doit résoudre — et parce que git y apporte sans rien coder l'historique du KPI modifié, la *pull
request* comme lieu de la revue humaine, et le diff quand l'amont est révisé.

Un dépôt par persona, une base ou un bus partagé, ou des livrables écrits dans le dépôt du harnais
ont été écartés : voir `knowledge/sources/adr-0003-topologie-depots.md`.

Tant qu'il y a peu d'équipes, les plugins cohabitent dans `aidlc-harness` — amorçage assumé. Le
signal de sortie est le rythme de release : `AIDLC_AGENT_PATH` et le marketplace font de
l'éclatement un changement de configuration, pas un remaniement.

### Péremption d'une note

Le lien producteur → consommateur ne vaut pas qu'au démarrage de l'étape aval. Quand un run est
noté (`score`), l'empreinte de chaque fichier listé dans `consumes` est **figée avec lui** dans
`.aidlc/maturity.json` (`runs[].inputs`). `gate` et `status` comparent ensuite cette empreinte à
l'état courant du fichier : toute divergence est bloquante et nomme le fichier qui a bougé
(`stale_inputs`).

C'est ce qui empêche le mode de panne le plus silencieux d'un cycle multi-équipes : le Product
Owner révise `intent.md` — un KPI corrigé, un persona retiré — après que l'architecte a livré et
fait noter `spec.md`, et la spec reste verte alors qu'elle instruit une intention disparue. Une
étape peut donc redevenir « à faire » sans avoir été touchée.

**La même fenêtre est fermée sur le livrable lui-même.** Le run fige aussi l'empreinte du fichier
qu'il note (`runs[].deliverable`) : un livrable réécrit après sa revue rouvre la porte
(`stale_deliverable`), au même titre qu'une entrée amont révisée. Sans cela, la note — et la
signature humaine, elle aussi attachée au run — survivaient à la version qu'elles jugeaient :
`validate` ne voit que la forme, et un fichier entièrement réécrit repasse ses `checks` sans
difficulté. Une note porte sur un contenu, pas sur un nom de fichier.

Deux limites assumées : la comparaison porte sur l'octet et non sur le sens (une typo corrigée en
amont périme l'aval — compromis marqué dans `util.digest`), et un run noté avant l'existence des
empreintes ne périme rien, par compatibilité ascendante.

---

## 3. Composants

### 3.1 `pipeline.json` — la gouvernance, et rien d'autre

Fichier unique installé avec le plugin noyau : `plugins/aidlc-core/pipeline.json` (dans la copie
installée, il est résolu via `CLAUDE_PLUGIN_ROOT` ou par auto-localisation du script).

**Il ne contient plus aucun registre d'étapes.** « Quels agents existent » se lit dans les
manifestes (§2) ; l'ordre se dérive des livrables. Ce fichier ne porte que les réglages qui
appartiennent à l'entreprise et non à une équipe : les seuils, ceux du watchdog, et
`planned_stages` — la feuille de route consultative. Les deux paramètres de gouvernance :

- `maturity_threshold` (4.0) : note globale minimale pour qu'un livrable soit accepté.
- `consecutive_runs_to_autonomy` (3) : nombre d'exécutions consécutives au-dessus du seuil avant
  qu'une étape puisse passer en mode autonome.

#### `aidlc.json` — la gouvernance du projet, qui recouvre celle du harnais

`pipeline.json` porte les **défauts de l'entreprise**. Une initiative a la sienne, et elle ne peut
pas l'écrire là : le fichier vit dans la copie que Claude Code installe, que le garde-fou
`PreToolUse` protège de toute écriture. Sans autre mécanisme, un projet subissait donc à la fois
le seuil du harnais et le workflow que la machine avait installé — deux projets ouverts sur le
même poste héritaient forcément du même pipeline.

`aidlc.json`, à la racine du **projet**, recouvre `pipeline.json` clé par clé
(`util.load_pipeline`). Cinq clés reconnues, toute autre est ignorée et signalée par `status` :

| Clé | Ce qu'elle décide |
| --- | --- |
| `maturity_threshold`, `min_axis_score`, `consecutive_runs_to_autonomy` | l'exigence de l'initiative |
| `watchdog` | ses seuils de stagnation |
| `planned_stages` | **sa** feuille de route : ce qu'il lui reste à installer |
| `agents` | **son workflow** : la liste blanche des identifiants qui composent le pipeline |

`agents` est la clé structurante. La découverte reste ouverte — on installe ce qu'on veut sur sa
machine — mais le filtre s'applique dans `registry.discover`, donc partout : catalogue, ordre,
tableau de bord, portes. Un identifiant déclaré qu'aucun manifeste ne porte remonte en
**avertissement** plutôt que de rétrécir le pipeline en silence : c'est le plugin d'une équipe qui
n'est pas encore installé. Omettre la clé revient à prendre tous les agents découverts.

`aidlc.py init` pose ce fichier, ainsi que `deliverables/`, le bundle `knowledge/` et un concept
`sources/projet-existant.md` — l'inventaire déterministe des README, manifestes de dépendances et
documents de `docs/` déjà présents dans le dépôt d'accueil. Le harnais suppose un projet qui
existe ; sans cet amorçage, la première étape s'ouvrait sur un entretien à froid et le `librarian`
n'avait aucun bundle à servir. La passe ne lit ni ne résume aucun contenu : elle rend des chemins,
le sens reste à l'humain et aux agents. Elle ne remplace jamais un fichier existant.

Aucun composant ne doit contenir une liste d'agents en dur — ni ce fichier, ni le moteur, ni un
prompt. Tout ce qui a besoin de savoir quels agents existent interroge le registre
(`aidlc.py agents`, module `_aidlc/registry.py`).

### 3.2 `checks.json` — validation déclarative

Chaque plugin d'agent embarque son `checks.json`, désigné par le champ `checks` de son manifeste
et résolu **relativement à ce manifeste** : le contrat vit donc dans le plugin de l'équipe qui le
porte, et le noyau n'en garde aucune copie. C'était la dernière centralisation qui obligeait à
toucher le harnais pour publier un agent. Le fichier décrit, sans code, ce qu'un livrable
acceptable doit contenir. Les règles disponibles :

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
`checks_do_not_self_reference` (`plugins/aidlc-plan/checks.json`, désigné par le champ `checks` du
manifeste de l'agent) : un `intent.md` doit citer un fait mesuré dans son
Contexte, chiffrer ses critères, et ne jamais citer les lignes de son propre `checks.json`. Les
règles `required_input_section` et `must_not_violate_scope` s'activeront avec les étapes qui ont
des entrées amont (design et suivantes).

Ajouter une exigence à une étape, c'est éditer un fichier JSON, pas écrire du Python. C'est le
levier principal du self-improvement : une faiblesse récurrente détectée par le reviewer se
traduit par une règle supplémentaire dans le `checks.json` de l'étape.

#### Le contrat est contrôlé à vide

Le registre est ouvert : le noyau lit le `checks.json` d'une équipe qu'il ne connaît pas. Ce
fichier n'était jusqu'ici ouvert qu'au moment de valider un livrable — une règle mal nommée, une
regex fautive ou une section mal orthographiée y restaient donc invisibles jusqu'à rendre le
contrat **insatisfiable en pleine session** : l'agent corrige, revalide, et n'y arrive jamais.

`aidlc.py agents` contrôle désormais chaque contrat **avant tout livrable**, et remonte sous
`contract_problems` (préfixe `[contrat]` en sortie humaine, également dans `status`) :

- une clé de règle inconnue — elle ne sera jamais appliquée ;
- une regex de `forbidden_patterns` / `required_patterns` qui ne compile pas ;
- une section visée par `min_items_per_section`, `proof_of_run`, `required_input_section` ou
  `must_not_violate_scope` mais absente de `required_sections` — le contrat est insatisfiable ;
- une clé de `required_input_section` qui n'est pas une entrée `consumes` de l'agent, ou
  `must_reference_inputs` actif sur un agent sans entrée : la règle ne vérifie rien ;
- `min_words` supérieur à `max_words` ;
- une étape gouvernée sans champ `checks` : son livrable ne serait validé par aucune règle ;
- la **dérive gabarit / contrat** — les skills d'étape partent de `templates/<nom du livrable>` du
  plugin ; si ce squelette ne porte pas les sections exigées, l'agent démarre sur un livrable qui
  ne peut pas valider. Seules les sections sont confrontées : un gabarit est court et plein de
  marqueurs, il ne peut satisfaire ni `min_words` ni `forbidden_patterns`.

La sévérité est la même que pour les manifestes : `agents --strict` (porte CI) ne rougit que pour
les contrats **de ce dépôt** — la CI d'un consommateur n'échoue pas sur le contrat cassé d'une
direction voisine, elle l'affiche.

### 3.3 `plugins/aidlc-core/scripts/` — la seule logique déterministe

Bibliothèque standard Python uniquement, sans dépendance externe. Le point d'entrée `aidlc.py`
(chemin stable utilisé par les hooks et les skills) délègue au paquet `_aidlc/` du même
répertoire, un module par concern — `util` (racines et IO), `checks` (validation des livrables),
`maturity` (scores, porte amont, porte, revue, signature), `scaffold`, `init` (amorçage d'un
projet consommateur), `improve`, `hookslog`, `okf` (conformance et
correctifs des bundles), `knowledge` (bundles OKF distants : cache, sommaire, recherche),
`syntax` (hygiène du dépôt : tout Python compile, tout JSON parse),
`ratchet` (planchers de sévérité figés), `watchdog` (détecteurs de stagnation),
`coverage` (ratchet de couverture), `commands` (gestionnaires de sous-commandes) et `cli`
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
| `init` | amorce un projet consommateur : `aidlc.json`, `deliverables/`, bundle `knowledge/`, inventaire des sources existantes ; ne remplace jamais un fichier |
| `review-request <stage>` | prépare le formulaire de revue humaine et affiche la consigne |
| `sign <stage> --approve\|--reject --by … --why …` | écrit la revue humaine et rejoue la porte ; **refuse de tourner sans terminal interactif** |
| `status` | tableau de bord de l'avancement du pipeline |
| `scaffold <stage>` | génère le plugin complet d'une étape déclarée mais non implémentée |
| `improve` | agrège journaux, scores, refus et haltes du watchdog en un diagnostic JSON |
| `ratchet` | fige les planchers de sévérité des `checks.json` (min_words, min_items_per_section, required_sections) dans `.aidlc/ratchet.json` (protégé) et refuse toute régression ; `--reset <stage>` repart du contrat courant après décision humaine (geste auteur) ; exit 2 si violation |
| `watchdog` | détecteurs de stagnation sur les journaux (acharnement sur livrable en échec, boucle d'écriture, rafale de relances) ; halte enregistrée dans la file d'amélioration (`kind: watchdog`) ; exit 2 si halte |
| `watchdog-touched` | mode hook `PostToolUse` : diagnostic non bloquant après chaque écriture, muet sans détection |
| `knowledge index` | sommaire des bundles OKF distants déclarés dans `knowledge-sources.json` : une ligne par concept (référence, type, titre, description) |
| `knowledge search <mots>` | concepts portant **tous** les mots (frontmatter d'abord, puis corps) ; rend des références, pas du contenu |
| `knowledge get <source>/<id>` | le markdown d'un seul concept ; `--refresh` met le cache à jour, `--source` restreint, `--json` rend la forme machine |
| `knowledge links <source>/<id>` | les voisins du concept dans le graphe : `->` ce qu'il cite, `<-` ce qui le cite. La traversée est **déterministe** — elle suit les liens croisés relatifs de la spec, là où la recherche par mots-clés ne rend que des correspondances isolées |
| `check-okf <dir>` | vérifie la conformance OKF v0.2 d'un bundle (`docs/`, `knowledge/`, ou le `knowledge/` d'un consommateur) ; exit 1 si non conforme |
| `check-okf --touched` | même contrôle en mode hook `PostToolUse` : gate les bundles OKF du projet (`knowledge/`, et `docs/` s'il existe), non bloquant, retour en contexte |
| `check-okf --stop` | mode hook `Stop` : porte de sortie — refuse la fermeture de session (deny) si un bundle du projet est non conforme, et enregistre le refus dans la file d'amélioration |
| `check-python` | compile tout Python du dépôt (règle 6, `py_compile`, sans rien écrire) ; exit 1 si erreur de syntaxe |
| `check-python --touched` | mode hook `PostToolUse` : compile le fichier `.py` écrit — retour en contexte, non bloquant, silencieux hors Python |
| `check-json` | parse tout JSON du dépôt (règle 6) ; exit 1 si fichier invalide |
| `check-json --touched` | mode hook `PostToolUse` : parse le fichier `.json` écrit — retour en contexte, non bloquant, silencieux hors JSON |
| `agents [--capability] [--json] [--strict]` | catalogue du registre (équipes, capacités, invocation) ; contrôle chaque `checks.json` à vide sous `contract_problems` ; `--strict` fait de la porte une porte CI sur les manifestes et contrats **de ce dépôt** |
| `recall <stage>` | reproches des derniers runs (findings du reviewer, axes sous le plancher, justification d'un refus humain) pour qui reprend une étape |
| `test` | suite `unittest` du moteur (paquet `_aidlc/tests/`, un module par concern) ; `-k`, `-v`, `--failfast` |
| `coverage` | ratchet de couverture mesuré par `trace` ; plancher figé dans `.aidlc/coverage.json`, exit 2 si régression |
| `experiment record --stage --target --file --cause` | date un correctif appliqué au harnais et fige la moyenne de l'axe visé (mesure d'avant) |
| `experiment effect [--stage]` | confronte chaque correctif aux runs postérieurs : `improved`, `regressed`, `no_effect`, `pending`, `no_baseline` (exit 0, informatif) |
| `selfscore` | note de maturité du dépôt : cinq axes déterministes (`hygiene`, `contracts`, `tests`, `coverage`, `knowledge`) agrégés sur le barème des livrables ; exit 2 si le seuil n'est pas tenu ou qu'un axe passe sous le plancher — porte de tête du hook pre-commit et de la CI (détail : [docs/TESTING.md](TESTING.md) §7) |
| `--selftest` | alias historique de `test` |

Règle non négociable du dépôt : toute nouvelle logique déterministe devient une sous-commande
exposée par ce point d'entrée, dans le module du paquet `_aidlc/` qui possède déjà le concern
(ou un nouveau module si c'est un concern nouveau). On n'ajoute pas de second point d'entrée ni
de fichier hors de `scripts/`.

### 3.4 Les hooks

Les hooks du plugin `aidlc-core` branchent le script sur le cycle de vie des sessions Claude Code.

- `SessionStart`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop` et `SessionEnd` appellent
  `log`. C'est la matière première de l'axe *autonomy* et du diagnostic `improve` : on sait
  combien de tours, quelles relances ont été nécessaires pour produire un livrable.
- `PostToolUseFailure`, `Notification` (matcher `permission_prompt|idle_prompt|agent_needs_input`),
  `PermissionDenied` et `PreCompact` appellent `log` : un outil qui résiste, une permission
  demandée, un refus humain sur une action, un contexte qui déborde. L'axe *autonomy* mesure le
  coût déjà payé du procédé — ces événements sont ce coût ; non journalisés, l'axe se noterait à
  l'impression. Le `Notification` est filtré sur les motifs qui disent quelque chose du procédé :
  une reprise de quota ou une authentification n'en disent rien.
- `PostToolUse` sur `Write|Edit` appelle `log` **en premier**, avant toute vérification. C'est ce
  qui fait exister la matière « quels outils, quels fichiers » : les détecteurs d'écriture du
  watchdog (`validation_failures`, `write_loop`) comptent `payload.tool_name` et
  `tool_input.file_path` dans le journal, et sans un événement d'outil journalisé ils ne peuvent
  jamais se déclencher. Le journal est écrit avant les validations pour exister même quand
  l'une d'elles échoue. Du `tool_input`, seuls les **chemins** sont retenus : le contenu écrit
  n'entre pas dans `.aidlc/logs/` — il consommerait la fenêtre de relecture en quelques
  événements et recopierait le travail en clair.
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
  les scripts. Il refuse également l'écriture de **`aidlc.json`**, la gouvernance du projet :
  ce fichier porte le seuil de maturité, le plancher par axe et la liste des agents qui composent
  le pipeline — un agent qui pourrait l'éditer abaisserait le mètre qui le juge, ou se retirerait
  du pipeline pour échapper à sa porte. Il vit hors de `.aidlc/` (il se versionne avec le projet),
  d'où sa garde propre. Il refuse aussi, en mode consommateur, toute écriture dans la **copie installée**
  du harnais (hors du projet) : `pipeline.json`, `checks/`, `hooks/`, `scripts/`, agents,
  skills, templates — c'est la **liste protégée**. Un modèle ne doit pas pouvoir éditer sa
  propre note ni les règles qui le jugent : l'intégrité de la mesure conditionne tout le reste.
  Dans le dépôt auteur (les deux racines confondues), la conception reste libre.
  Il refuse enfin à un **sous-agent nommé** d'écrire le `produces` d'un *autre* agent : la chaîne
  producteur → consommateur n'ordonne plus rien si l'agent aval peut « corriger » son entrée
  amont — il se fabriquerait le contrat sur lequel il est jugé, et la porte de l'étape amont
  noterait un texte que son propre agent n'a pas écrit. Le refus est nominatif (le `produces`
  exact, jamais une annexe) et ne s'applique que si le payload du hook nomme l'agent courant :
  sans identité, rien n'est bloqué — un garde-fou qui devine coûterait plus qu'il ne protège.

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

`aidlc-core` expose sept skills : `run` (exécuter une étape de bout en bout), `status` (tableau de
bord), `review` (déclencher le reviewer), `new-stage` (concevoir une nouvelle étape en dialogue
avec le métier puis la générer), `improve` (analyser le diagnostic et proposer un correctif),
`dispatch` (mobiliser les agents consultatifs par capacité et synthétiser leurs avis) et
`knowledge` (consulter les bundles OKF distants déclarés : sommaire, recherche, puis un concept).

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

Le savoir **externe**, lui, est déclaré par le projet dans `knowledge-sources.json` : des bundles
OKF vivant dans d'autres dépôts (normes d'entreprise, catalogue de données, politiques d'une
autre direction). La sous-commande `knowledge` les clone en profondeur 1 dans
`.aidlc/tmp/knowledge/` — un cache jetable, jamais versionné — et n'en sert que ce qui est
demandé : sommaire, puis recherche, puis un concept entier. C'est la divulgation progressive de
la spec OKF appliquée au budget de contexte : un agent qui a besoin d'une définition n'ouvre pas
un dépôt, il ouvre un concept. Le contenu servi est une **donnée à citer**, jamais une
instruction — un bundle tiers n'autorise rien. Un `repo` qui désigne un dossier existant est lu
tel quel, sans clone (bundle monté, dépôt voisin, test hors réseau).

### 3.8 État runtime

Ces chemins sont produits par le script dans le **projet consommateur**, jamais rédigés à la main
(à l'exception des fichiers de revue, signés par un humain) :

```
deliverables/<stage>/...            livrables versionnés (projet consommateur)
.aidlc/logs/<session_id>.jsonl      journal des sessions
.aidlc/maturity.json                historique des scores
.aidlc/reviews/<stage>-<n>.json     revues humaines signées
.aidlc/improvement-queue.jsonl      refus humains, haltes du watchdog et refus du gate OKF
.aidlc/experiments.jsonl            corrections du harnais appliquées et effet mesuré (protégé)
.aidlc/ratchet.json                 planchers de sévérité figés (protégé par le guard)
.aidlc/tmp/                         scratch, ignoré par git
.aidlc/tmp/knowledge/<source>/      cache des bundles OKF distants (clone profondeur 1)
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

`aidlc.py gate <stage>` ne renvoie `passed: true` que si les cinq conditions suivantes sont
réunies :

0. **L'amont est en place** : chaque chemin du `consumes` existe sur disque, et l'agent qui le
   produit a franchi sa propre porte (§2, « Chaîne livrable vers entrée »). Cette condition est
   évaluée en premier et ses bloquants sont listés en tête : une étape bâtie sur du vide n'a pas
   de qualité à mesurer, et le dire avant la note évite d'envoyer l'utilisateur relancer un
   reviewer pour rien.
1. `validate <stage>` passe : le livrable respecte toutes les règles de son `checks.json`.
2. Le dernier run enregistré porte le verdict `accepted` **et** une note globale supérieure ou
   égale à `maturity_threshold`.
3. La revue humaine est présente et approuvée — sauf si l'étape est passée en mode autonome.
4. Ni les entrées amont ni le livrable lui-même n'ont été modifiés depuis que le dernier run a
   été noté (voir « Péremption d'une note », §2) : `stale_inputs` doit être vide et
   `stale_deliverable` faux.

Sinon, la sortie liste les éléments bloquants et le code de retour vaut 2, ce qui permet à un hook
`Stop` de retenir la session tant que l'étape n'est pas franchie.

### La signature humaine, et ses deux verrous

`review-request <stage>` pose un gabarit `.aidlc/reviews/<stage>-<run>.template.json` et affiche
la consigne de relecture. Signer consistait alors à copier ce gabarit, éditer un JSON à la main —
horodatage ISO 8601 compris — puis demander à l'agent de relancer la porte : trois gestes manuels
et un format de date, demandés à un Product Owner ou à un référent métier.

`aidlc.py sign <stage> --approve|--reject --by "Nom" --why "…"` fait le même travail en une
commande, et **rejoue la porte dans la foulée** (exit 0 si elle s'ouvre, 2 avec les bloquants
sinon). Elle tient trois exigences que le fichier ne savait pas tenir : un relecteur nommé, une
justification non vide **dans les deux sens** (une approbation sans motif est un tampon, pas une
revue), et le refus d'écraser une signature déjà apposée — `--force` est un geste explicite.

Deux verrous, et non un seul, garantissent que la signature est humaine :

1. le hook `PreToolUse` refuse les écritures d'agents dans `.aidlc/reviews/` — mais il ne couvre
   que les outils `Write` et `Edit` ;
2. `sign` **exige un stdin interactif**. Un agent qui lancerait la commande par un outil `Bash`
   n'en a pas : il reçoit un refus motivé, pas une signature. C'est ce test qui distingue
   « l'humain a signé » de « l'agent a écrit qu'il avait signé », et la suite le vérifie en
   sous-processus — exactement le contexte d'un agent.

La voie manuelle reste ouverte pour les contextes sans terminal (CI, session headless) : le
gabarit de `review-request` s'y remplit à la main, comme avant.

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

Ces six niveaux sont les seules notes possibles : `aidlc.py score` **refuse une note
fractionnaire**. L'échelle est ordinale — chaque cran a un sens écrit — et une demi-note n'en
désigne aucun ; elle sert surtout à négocier le franchissement du plancher par le haut (2,9 contre
3,0). La règle vivait dans la skill de revue, donc dans un prompt : elle est dans le moteur.

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

#### Le plancher par axe est tenu par le moteur

`min_axis_score` (`pipeline.json`, **3** par défaut) : si un des **axes du livrable** passe sous ce
plancher, `aidlc.py score` force le verdict enregistré à `rejected`, quelle que soit la moyenne et
quel que soit le verdict rendu par le reviewer. Le run porte alors `weak_axes`, et `gate` bloque en
nommant l'axe fautif.

La règle existait déjà — dans le **prompt** du reviewer, et nulle part ailleurs. Un livrable noté
`{completeness: 5, precision: 5, traceability: 1, autonomy: 5}` obtient une moyenne de 4,0 : avec
un verdict `accepted`, il franchissait la porte. Une consigne de prompt n'est pas un garde-fou —
elle dépend du modèle qui la lit, et c'est exactement ce que le harnais refuse ailleurs (liste
protégée, ratchet, holdout). Elle est désormais dans le moteur.

Une moyenne flatteuse ne rachète pas un axe effondré : un livrable complet, précis et produit sans
relance mais **sans aucune traçabilité** reste un livrable qu'on ne peut pas auditer — et il
servira d'entrée à toute l'aval.

#### Le plancher juge le livrable, pas son coût de production

Les axes plafonnés sont `completeness`, `precision` et `traceability` — les trois qui décrivent le
fichier noté. **`autonomy` n'a pas de plancher**, et c'est délibéré : elle mesure ce que la
production a déjà coûté. Un run ne peut pas défaire les tours qu'il a consommés ; rejeter un
livrable irréprochable pour ce motif fermerait une porte **sans action de sortie**, et le seul
« remède » offert à l'agent serait de moins se corriger — l'inverse du comportement recherché.
Elle continue de peser un quart de la moyenne : trois axes parfaits et une autonomie à 1 donnent
4,0 et passent, mais la moindre imperfection ailleurs fait tomber la moyenne sous le seuil. Et
c'est la **série** de runs (§6), pas un run isolé, qui tire les conséquences d'une autonomie
médiocre : l'étape n'accède pas au mode autonome.

Limite assumée de l'axe : `improve --stage` agrège **tous** les journaux de l'étape, sans fenêtre
par run — plus l'étape a d'historique, plus le diagnostic est chargé. `autonomy` est donc l'axe le
plus bruité de la grille, ce qui est une raison de plus de ne pas en faire un couperet.

### 5.6 La rubrique de l'équipe

La grille des §5.1 à §5.4 est **universelle** : elle vaut pour tout livrable. Elle ne sait pas ce
que « précis » veut dire pour une intention produit par opposition à une conception cible. Le
champ `review` du manifeste comble cet écart : chaque équipe maintient, **dans son plugin**, une
rubrique que le reviewer charge avant de noter (`plugins/aidlc-plan/review.md`,
`plugins/aidlc-design/review.md`).

Une rubrique dit trois choses, et rien d'autre :

1. ce que chaque axe veut dire pour ce métier (« un persona sans volume ni fréquence plafonne
   `completeness` à 2 ») ;
2. les fautes **rédhibitoires** du métier, qui imposent `rejected` quelle que soit la moyenne ;
3. les nuances d'`autonomy` propres à l'étape (en Design, signaler une lacune de l'intention amont
   plutôt que de produire une conception bancale vaut 5).

**Ce qu'une rubrique ne peut pas faire** — et c'est la frontière qui rend le dispositif sûr : elle
ne change ni le barème 0-5, ni les quatre axes, ni le seuil, ni le plancher par axe, ni le calcul
de la note. Elle **précise et durcit**, jamais l'inverse. Une équipe affine la lecture de son
métier ; elle n'assouplit pas le mètre qui la juge.

Une rubrique déclarée mais absente du plugin est signalée par `agents` (`[contrat]`) : sans ce
contrôle, le reviewer retomberait silencieusement sur la grille universelle et l'équipe croirait
sa rubrique appliquée. `scaffold` en génère une avec l'agent, pour qu'aucune étape ne naisse sans.

---

## 6. Passage en mode autonome

Par défaut, **toute étape exige une revue humaine** avant d'être franchie. C'est la position de
départ : le harness n'a rien prouvé.

Une étape bascule en mode autonome (`autonomous: true` dans `.aidlc/maturity.json`) quand les deux
conditions suivantes sont réunies :

1. Les `consecutive_runs_to_autonomy` derniers runs — trois par défaut — affichent tous une note
   globale supérieure ou égale au seuil de maturité.
2. Une revue humaine approuvée existe pour ceux de ces runs qui ont été produits **sous
   surveillance** : l'humain a validé non seulement le livrable, mais la constance du procédé. Un
   run produit alors que l'étape était déjà autonome porte `supervised: false` et n'attend pas de
   signature — sans cette exemption, la fenêtre glissante trouvait un run non signé dès le premier
   run bénéficiant du mode autonome, et l'étape y repassait sous surveillance après exactement un
   run. Un run antérieur à ce champ est lu comme supervisé.

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
 accord humain explicite  ->  application
        |
        v
 aidlc.py experiment record       (ce qui a été changé, l'axe visé, la mesure d'avant)
        |
        |  runs suivants notés par le reviewer
        v
 aidlc.py experiment effect  ->  improved | no_effect | regressed | pending
        |
        +--> réinjecté dans le diagnostic `improve` (section `experiments`)
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
décide pas. Ce qui est appliqué, en revanche, est **mesuré** : voir §7.0.

### 7.1 Mécanismes anti-dérive

Quatre mécanismes, hérités des principes du « dark factory » (ai-software-factory), rendent la
confiance indépendante des prompts :

1. **La liste protégée** — un agent ne peut pas écrire dans l'état runtime (score, revues,
   ratchet, file, registre des expériences, journaux), ni dans `aidlc.json` (le seuil et le
   workflow du projet), ni dans la copie installée du harnais (pipeline, contrats, hooks,
   script, agents, skills, templates), ni dans le livrable d'un autre agent. Le hook `PreToolUse`/`guard` refuse ces écritures ; la
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

### 7.2 La boucle se referme : l'expérience mesurée

Un correctif proposé, appliqué, puis oublié n'est pas une boucle — c'est un diagnostic répété. Le
registre `.aidlc/experiments.jsonl` est la **mémoire** de la boucle : chaque correction appliquée
au harnais y est datée avec l'axe qu'elle vise, le fichier touché, la cause racine énoncée, et la
**moyenne de cet axe à cet instant** (`baseline`, sur `baseline_runs` runs).

`aidlc.py experiment effect` confronte ensuite chaque correction aux runs **postérieurs** à elle
— c'est `baseline_runs` qui sépare l'avant de l'après, donc un run faible d'avant ne peut plus
peser sur le verdict :

| Verdict | Lecture |
|---|---|
| `pending` | moins de deux runs notés depuis la correction : on ne conclut pas |
| `improved` | l'axe visé a gagné au moins un demi-point |
| `regressed` | il en a perdu autant : la correction a nui, elle est à défaire |
| `no_effect` | il n'a pas bougé : la cause racine était mauvaise, pas le correctif |
| `no_baseline` | l'étape n'avait aucun run avant la correction : mesure sans comparaison |

Le résultat remonte dans la section `experiments` du diagnostic `improve`. C'est ce qui interdit à
la boucle de tourner à vide : un agent qui prépare une proposition **voit ce qui a déjà été tenté
sur la même cible et ce que les runs en ont dit**, et ne repropose pas un correctif que la mesure
a déjà jugé sans effet. Le registre n'est pas dédoublonné — réessayer après un échec est
légitime, à condition que ce soit une nouvelle hypothèse et non la même.

Comme le reste de l'état runtime, ce fichier n'est écrit que par le script : le hook `guard`
refuse son édition directe. Antidater une expérience reviendrait à se noter soi-même, exactement
ce que la liste protégée empêche pour `maturity.json`. Et `experiment effect` **ne bloque
rien** (exit 0) : un correctif sans effet est une information rendue à l'humain, pas un défaut du
dépôt — la décision d'insister ou de revenir en arrière reste la sienne.

---

## 8. Conventions de conception

- Un livrable = un fichier dans `deliverables/` du **projet consommateur**, au chemin exact déclaré
  par le champ `produces` de l'`agent.json` de son agent (§2.1) — jamais par `pipeline.json`, qui
  ne porte que la gouvernance.
- Le harnais (pipeline, contrats, script) vit dans les plugins ; le projet (livrables, `.aidlc/`,
  `knowledge/`) vit chez le consommateur. Deux racines, résolues par le script.
- Toute logique déterministe vit dans `aidlc.py`, jamais dans un nouveau script.
- Bibliothèque standard Python uniquement, aucune dépendance externe, aucun format autre que JSON
  et Markdown.
- `.aidlc/maturity.json` et `.aidlc/reviews/*.json` ne sont jamais édités à la main par un agent :
  seuls `aidlc.py score` et l'humain y écrivent, et le hook `guard` fait respecter la règle.
- Les raccourcis assumés sont marqués dans le code par un commentaire `# ponytail: ...`.
