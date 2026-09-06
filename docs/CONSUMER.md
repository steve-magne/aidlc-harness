---
type: Playbook
title: Consommer le harnais AI-DLC dans votre projet
description: Guide consommateur prêt à publier — installation du marketplace et des plugins, premier run de l'étape Plan, revue humaine, versionnage et mises à jour.
tags: [consumer, guide, harness]
generated: { by: human:steve-magne, at: 2026-09-04T00:00:00Z }
---

# Consommer le harnais AI-DLC dans votre projet

Ce guide s'adresse à une **équipe de projet** qui veut produire ses livrables de cadrage avec le
harnais agentique AI-DLC : un orchestrateur d'agents d'équipe et une chaîne d'étapes
(Plan → Design → Build → Test → Deploy → Maintain)
piloté par des agents Claude Code, validé par des contrôles déterministes, noté par un agent
*reviewer* et gardé par des portes de qualité qui exigent votre signature tant que l'étape n'est
pas autonome.

Aujourd'hui, deux étapes sont implémentées — **Plan** (`deliverables/plan/intent.md`) et
**Design** (`deliverables/design/spec.md`) — plus un agent consultatif AppSec. Les autres étapes
apparaissent au tableau de bord comme « prévues, plugin non installé » ; elles sont conçues et
publiées par l'équipe qui les porte, pas par le projet consommateur.

**Ce que le harnais garantit, et qui n'est pas dans les prompts** : une étape ne démarre pas sans
que le livrable de l'étape précédente existe **et** ait franchi sa propre porte. C'est le code de
sortie de `gate` qui le dit, donc c'est vrai aussi en CI et quel que soit ce que l'agent a
compris.

---

## 1. Ce que vous installez, et où atterrissent les fichiers

Le harnais est distribué comme un **marketplace de plugins Claude Code** nommé `aidlc`, qui
contient aujourd'hui quatre plugins :

| Plugin | Rôle |
| --- | --- |
| `aidlc-core` | Le noyau : registre d'agents, gouvernance, script déterministe `aidlc.py`, orchestrateur, reviewer, librarian, hooks de journalisation et de garde-fous. Il ne contient la liste d'aucun agent : il les découvre. |
| `aidlc-plan` | L'étape Plan : agent de dialogue avec le Product Owner, recette de la skill `plan`, squelette du livrable, contrat `checks.json`. |
| `aidlc-design` | L'étape Design : consomme le livrable de Plan et arrête l'architecture cible. |
| `aidlc-security` | Agent consultatif AppSec : un avis, pas un livrable — l'exemple à copier pour publier l'agent de votre équipe. |

Vous n'installez que ce dont votre initiative a besoin, et vous déclarez le workflow retenu dans
`aidlc.json` (section 3 bis).

Deux racines sont à distinguer :

- **Le harnais (les plugins)** — une fois installés, Claude Code copie les plugins dans son cache
  (`~/.claude/plugins/cache/…`) ; le pipeline, les contrats et le script y vivent. **Vous n'y
  écrivez rien.**
- **Votre projet** — c'est là que sont produits les livrables (`deliverables/`) et l'état runtime
  (`.aidlc/`). **Aucun livrable n'est écrit dans le dépôt du harnais** : tout ce qui compte pour
  vous atterrit dans votre projet.

Quand un agent ou un hook appelle `aidlc.py`, le script résout lui-même les deux racines :
`CLAUDE_PROJECT_DIR` (votre projet, défini par la session Claude Code) et `CLAUDE_PLUGIN_ROOT` (la
copie installée du plugin).

## 2. Prérequis

- **Claude Code** — une version récente, qui gère les marketplaces de plugins et les hooks.
- **Python 3** — le harnais n'utilise que la bibliothèque standard : aucune dépendance à installer,
  aucun `pip install`.
- **L'accès au dépôt `aidlc-harness`** — par un chemin local ou par son URL git (GitHub, GitLab,
  etc.).

## 3. Installer les plugins

Depuis la racine de votre projet (l'enregistrement du marketplace est lié à votre
machine/utilisateur, mais lancer l'installation **dans le projet** permet de choisir la portée
« Ce projet ») :

```bash
# 1. Enregistrer le dépôt aidlc-harness comme marketplace nommé « aidlc ».
#    Par chemin local :
claude plugin marketplace add /chemin/vers/aidlc-harness
#    Ou par dépôt git (selon l'hébergement du harnais) :
claude plugin marketplace add https://github.com/<organisation>/aidlc-harness.git

# 2. Installer les deux plugins (choisir « Ce projet » comme portée au prompt
#    d'installation, si le harnais ne concerne que ce projet) :
claude plugin install aidlc-core@aidlc
claude plugin install aidlc-plan@aidlc
claude plugin install aidlc-design@aidlc

# 3. Vérifier :
claude plugin list
```

Si l'installation affiche « Run /reload-plugins to activate », lancez `/reload-plugins` dans la
session, ou fermez et rouvrez Claude Code.

> **Portée d'installation.** En portée « Ce projet », les hooks du harnais (journalisation,
> validation, garde-fous) ne s'activent que dans les sessions ouvertes dans ce projet — c'est le
> choix recommandé pour un essai. En portée « utilisateur », ils s'activent dans tous vos projets,
> y compris ceux qui ne consomment pas le harnais (la journalisation y créerait un dossier
> `.aidlc/`).

## 3 bis. Amorcer le projet : `aidlc.py init`

Votre projet **existe déjà** : il a son code, son README, ses décisions d'architecture. Le harnais
doit le savoir avant de faire parler ses agents. Une fois les plugins installés, depuis le bash
d'une session Claude Code ouverte à la racine du projet :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" init
```

La commande **ne remplace jamais un fichier existant** ; on peut la relancer sans risque. Elle pose :

| Fichier | Ce qu'il porte |
| --- | --- |
| `aidlc.json` | **La gouvernance de votre initiative** : votre seuil de maturité, votre plancher par axe, et surtout `agents` — la liste des agents qui composent *votre* workflow. |
| `deliverables/` | Le dossier des livrables. |
| `knowledge/` | Le bundle OKF du projet : `index.md`, `log.md`, et un concept `sources/projet-existant.md`. |
| `knowledge-sources.json` | Les bundles OKF distants, vide au départ (section 6). |
| `.gitignore` | Les deux caches jetables (`.aidlc/tmp/`, `.aidlc/logs/`) ajoutés à ce que vous aviez déjà. |

`sources/projet-existant.md` est un **inventaire brut** : les README, manifestes de dépendances et
documents de `docs/` trouvés à l'amorçage, listés en liens relatifs. Rien n'est lu ni résumé —
c'est déterministe, il n'y a pas d'agent derrière. Son intérêt est que le `librarian` a désormais
quelque chose à servir dès le premier run, au lieu d'un entretien à froid sur un projet dont le
harnais ne sait rien. **Complétez-le** : c'est votre base, pas celle du harnais.

### `aidlc.json` : votre exigence et votre workflow

C'est le seul endroit où une équipe projet règle la gouvernance. Le `pipeline.json` du harnais vit
dans la copie installée par Claude Code, que le garde-fou protège de toute écriture : sans ce
fichier, vous subiriez les seuils du harnais et le workflow que la machine a installé.

```json
{
  "maturity_threshold": 4.0,
  "min_axis_score": 3.0,
  "consecutive_runs_to_autonomy": 3,
  "initiative": "reco-panier",
  "agents": ["plan", "design", "security-review"],
  "planned_stages": [
    { "id": "build", "name": "Build", "deliverable": "deliverables/build/plan.md",
      "inputs": ["deliverables/design/spec.md"], "human_role": "Tech Lead", "team": "Ingenierie" }
  ]
}
```

- **`agents`** — la liste blanche des identifiants qui composent votre pipeline. Un plugin installé
  sur la machine pour une autre initiative mais absent de cette liste **n'existe pas** pour ce
  projet. L'avertissement joue dans les deux sens sous le tableau de bord : un identifiant listé
  dont aucun plugin n'est installé vous est signalé (c'est un plugin d'équipe qu'il vous reste à
  installer, pas une faute de frappe silencieuse), et un agent découvert que vous n'avez pas
  branché aussi — sans quoi une équipe publie son plugin et vous ne voyez rien. Omettez la clé et
  tous les agents découverts composent le workflow.
  **N'éditez pas cette liste à la main** : `aidlc.py workflow --add <agent>` / `--remove <agent>`
  valide ce qu'elle écrit, refuse un identifiant qu'aucun manifeste ne porte, et vous prévient
  quand un retrait casse la chaîne producteur → consommateur.
- **`initiative`** — le nom de l'idée en cours. Un projet vit plus longtemps qu'une idée : sans ce
  nom, la deuxième évolution écrase les livrables, les scores et les signatures de la première,
  parce que les chemins sont fixes. Avec lui, chaque idée a son dossier —
  `deliverables/<initiative>/` et `.aidlc/<initiative>/` — et l'histoire de la précédente reste
  lisible (`status --history`). Posez-le par `aidlc.py workflow --initiative "<nom-court>"`, en
  minuscules et sans espace. Changer d'initiative **ne déplace rien** : les fichiers de la
  précédente restent où ils sont. Omettez la clé si votre projet ne mène qu'une idée.
- **`planned_stages`** — *votre* feuille de route : les étapes que vous attendez et dont le plugin
  n'est pas encore publié.
- Les autres clés recouvrent celles du harnais, une par une. Ce que vous ne déclarez pas reste
  celui du harnais.
- Une clé inconnue est **ignorée**, et `status` vous le dit (`Gouvernance du projet : clé inconnue
  '…'`) — plutôt que de vous laisser croire que votre seuil s'applique.

Versionnez ce fichier : c'est une décision de projet, comme une dépendance.

### `aidlc.py workflow` : composer la chaîne

Ne l'éditez pas à la main. La sous-commande valide ce qu'elle écrit, et sans option elle répond à
la question qu'on se pose vraiment — « qu'est-ce qu'on a, qu'est-ce qu'on joue ? » :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow
```

```
Workflow de l'initiative « reco-panier »

  plan                 Produit        deliverables/reco-panier/plan/intent.md
  security-review      AppSec         consultatif (pas de livrable)
  design               Architecture   deliverables/reco-panier/design/spec.md

Découverts, hors de ce workflow : build
Les brancher : aidlc.py workflow --add build
```

Trois lignes, trois réponses différentes : un agent **branché** compose la chaîne ; un agent
**découvert hors du workflow** a été publié par une équipe que personne n'a branchée — demandez-lui
si elle intervient sur cette initiative ; un agent **introuvable** est déclaré mais son plugin
n'est pas installé.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow --add design --remove build
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow --initiative "refonte-sso"
```

La skill `/aidlc-core:setup` mène ce dialogue pour vous, amorçage compris.

## 4. Premier run : produire le livrable Plan

Ouvrez une session Claude Code **à la racine de votre projet**, puis lancez l'étape :

```
/aidlc-core:run plan
```

(Sans argument, `/aidlc-core:run` prend automatiquement la prochaine étape à traiter — ici `plan`.)

Ce qui se passe, dans l'ordre :

1. **L'orchestrateur** lit le pipeline (dans le plugin installé), vérifie que l'étape est
   implémentée et que ses entrées amont existent (l'étape Plan n'en a aucune), puis délègue à la
   skill `aidlc-plan:plan`.
2. **L'agent plan-analyst** mène l'entretien de cadrage avec le Product Owner : huit sections,
   questions **par salves de trois à cinq**, une quinzaine de minutes. Il ne devine jamais (une
   information manquante se demande, sinon elle est marquée « hypothèse à confirmer »), relance sur
   les chiffres et refuse la solution technique — le « comment » appartient à l'étape Design.
3. **L'écriture du livrable** `deliverables/plan/intent.md` déclenche à chaque modification un hook
   `PostToolUse` du plugin `aidlc-core` : la validation déterministe tourne contre le contrat
   `checks.json` de l'étape (sections présentes au caractère près, mots interdits, frontmatter,
   nombre de puces, 250 à 2000 mots) et renvoie immédiatement les `errors`/`warnings`. L'agent
   corrige jusqu'au vert — aucun livrable ne se rend avec des erreurs de validation.
4. **L'orchestrateur rejoue la validation**, puis délègue la revue : l'agent *reviewer* note le
   livrable de 0 à 5 sur quatre axes — `completeness`, `precision`, `traceability`, `autonomy` —
   chaque note justifiée par une citation, verdict `accepted` ou `rejected`, et enregistre le score
   dans `.aidlc/maturity.json`.
5. **La porte** (`gate`) s'ouvre seulement si **l'amont est en place**, la validation passe, le
   verdict est `accepted` et le score atteint votre seuil. Tant que l'étape n'est pas autonome,
   **la revue humaine est exigée** : la porte reste fermée et l'orchestrateur vous laisse la main
   (section suivante).

   L'amont d'abord, et c'est le cœur du bout-en-bout : une étape ne se franchit pas sur du vide.
   Pour chaque entrée déclarée dans le `consumes` de son manifeste, la porte exige que le
   **fichier existe** et que **l'agent qui le produit ait franchi sa propre porte**. Sinon, deux
   bloquants nommés :

   ```
   [bloquant] Entree amont absente : deliverables/plan/intent.md — produire d'abord le livrable de l'agent 'plan'.
   [bloquant] Porte amont fermee : l'agent 'plan' n'a pas franchi la sienne (Revue humaine requise…).
   ```

   Ce contrôle est **dans le moteur**, pas dans un prompt : il vaut pour un appel direct, pour un
   hook et pour votre CI, quel que soit ce que l'agent a compris. À l'écriture, la validation vous
   avertit déjà (`Entree amont absente : … la porte de l'etape restera fermee`) — un livrable aval
   peut être formellement valide tout en n'ayant aucun amont, et le vert ne doit pas le laisser
   croire.

Pendant tout le run, les hooks journalisent la session dans `.aidlc/logs/<session>.jsonl` et un
garde-fou `PreToolUse` refuse que quiconque — agent compris — écrive dans `.aidlc/maturity.json`
ou `.aidlc/reviews/`.

### Le tableau de bord

À tout moment, demandez l'état du pipeline dans la session :

```
/aidlc-core:status
```

Exemple de sortie en début de vie d'un projet consommateur :

```
AI-DLC — tableau de bord (/chemin/de/votre/projet)
Seuil de maturite : 4.0 | Plateforme : claude-code | Gouvernance : aidlc.json | Etape courante : plan

AGENT   EQUIPE        LIVRABLE  VALIDE  SCORE  AUTO  EN ATTENTE DE               PROCHAINE ACTION
plan    Produit       non       -       -      non   Product Owner / Busines...  Produire le livrable : aidlc-plan:plan
design  Architecture  non       -       -      non   -                           En attente de l'amont : plan

Bloque : design attend deliverables/plan/intent.md — livrable pas encore produit.
Prevu, plugin non installe : build (Build) — a publier par l'equipe Ingenierie
```

Trois choses à lire :

- **`EN ATTENTE DE`** répond à « c'est à qui ? ». Une seule ligne porte un nom à la fois : celle
  qui est jouable. Une étape franchie n'attend personne, et une étape bloquée par son amont non
  plus — l'action est sur la ligne du dessus.
- **`En attente de l'amont : plan`** : l'étape `design` n'est pas jouable. Ne lancez pas son agent,
  lancez celui de l'amont.
- **`a publier par l'equipe <équipe>`** : le plugin de cette étape n'est pas encore publié. Un
  projet consommateur ne scaffolde pas d'étape — il attend que l'équipe propriétaire la publie au
  marketplace (voir « Mises à jour »). Dans le dépôt qui *maintient* le harnais, la même ligne
  propose `aidlc.py scaffold <étape>`.

## 5. La revue humaine : lire, signer, ou refuser

C'est le moment où **vous** entrez dans le circuit. Le rôle humain de l'étape Plan est le
**Product Owner / Business Analyst** : c'est lui qui détient le besoin, c'est lui qui signe.

### 5.1 L'orchestrateur s'arrête et prépare la revue

Quand la porte demande une revue humaine, l'orchestrateur (ou vous, par
`/aidlc-core:run plan`) appelle la demande de revue, qui écrit un gabarit et affiche les consignes :

```
.aidlc/reviews/plan-1.template.json
```

Le fichier `plan-1` signifie : étape `plan`, run n° 1. Le numéro s'incrémente à chaque nouvelle
revue du reviewer.

### 5.2 Vous relisez le livrable

1. Ouvrez `deliverables/plan/intent.md` et vérifiez les quatre points que le script vous rappelle :
   1. le livrable répond au **besoin réel**, pas seulement au gabarit ;
   2. les **critères d'acceptation** sont testables et chiffrés ;
   3. les **entrées amont** (ici : le contexte métier que vous avez donné) sont citées et
      correctement interprétées ;
   4. il n'y a aucun **engagement implicite** non assumé (délai, coût, périmètre).

### 5.3 Vous signez

**Depuis votre terminal** — pas depuis la session Claude — une seule commande :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" sign plan --approve --by "Votre Prénom Nom" --why "Le problème, le périmètre et les critères d'acceptation correspondent au besoin exprimé."
```

Elle écrit `.aidlc/reviews/plan-1.json` avec le bon horodatage, puis **rejoue la porte dans la
foulée** : sortie 0, l'étape est franchie et l'étape suivante est annoncée ; sortie 2, elle vous
liste ce qui bloque encore. Vous n'avez plus ni gabarit à copier, ni JSON à remplir, ni à demander
à Claude de rouvrir quoi que ce soit.

Trois exigences que la commande tient et que le fichier ne savait pas tenir :

- **un relecteur nommé** — une revue anonyme n'engage personne ;
- **une justification, y compris pour approuver** — sans motif écrit, la signature ne dit pas ce
  qui a été vérifié. Et ce motif **sert** : une approbation motivée ne bloque rien, mais elle est
  conservée dans `.aidlc/improvement-queue.jsonl` comme *réserve* et alimente la boucle
  d'amélioration au même titre qu'un refus. Écrivez ce qui vous a gêné même quand vous laissez
  passer — trois réserves sur le même motif valent un refus, et personne ne l'aurait vu venir ;
- **pas de réécriture silencieuse** — un run déjà signé est refusé, avec le nom et la date de la
  signature en place. Pour revenir sur votre décision : `--force`, ou supprimez le fichier.

### 5.4 Vous refusez

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" sign plan --reject --by "Votre Prénom Nom" --why "Les critères d'acceptation ne sont pas chiffrés."
```

La **justification est obligatoire** dans les deux sens : elle est copiée automatiquement dans
`.aidlc/improvement-queue.jsonl` et alimente la boucle d'amélioration du harnais (la skill
`aidlc-core:improve` du dépôt d'origine). La porte reste fermée ; reprenez le livrable
(`/aidlc-core:run plan`, qui entre alors en mode « reprise » et vous relit vos reproches), puis une
nouvelle revue du reviewer ouvrira un run n° 2 (`plan-2`).

### Qui peut signer ?

**Uniquement un humain, depuis un terminal.** Deux verrous, pas un :

- le hook `PreToolUse` refuse les écritures d'agents dans `.aidlc/reviews/` : Claude ne peut ni
  remplir le fichier à votre place ni le modifier après signature ;
- `sign` **refuse de tourner sans terminal interactif**. Un agent qui lancerait la commande par un
  outil Bash n'a pas de stdin interactif : il reçoit un refus, pas une signature. C'est ce qui
  distingue « l'humain a signé » de « l'agent a écrit qu'il avait signé ».

La signature se reconnaît par la présence du fichier `<stage>-<run>.json` — le `.template.json`
seul ne vaut pas signature.

### Sans terminal (CI, session headless)

La voie manuelle reste ouverte : `review-request` pose le gabarit
`.aidlc/reviews/plan-1.template.json`, copiez-le en `plan-1.json` et renseignez `approved`,
`reviewer`, `justification` et `ts` à la main.

### Se passer la main entre équipes

Le harnais gouverne des **livrables**, et le relais entre personas passe par votre dépôt : chaque
étape franchie se transmet en poussant `deliverables/`, `.aidlc/maturity.json` et
`.aidlc/reviews/`. Le Product Owner cadre et signe, pousse ; l'architecte tire, lance
`/aidlc-core:run design`, signe à son tour. À chaque `git pull`, `/aidlc-core:status` répond à
« où en est-on, et **qui attend-on** » — c'est la colonne `EN ATTENTE DE`.

Deux garde-fous rendent ce relais sûr :

- une étape aval **ne peut pas démarrer** tant que son entrée amont n'existe pas ou que l'amont n'a
  pas franchi sa porte (section 4, étape 5) ;
- si l'amont est révisé **après** que l'aval a été noté, la porte de l'aval se rouvre
  automatiquement — la note portait sur une version disparue.

Et pour répondre à « qui a validé quoi, et quand », que le tableau de bord ne dit pas (il ne montre
que l'état courant) :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status --history
```

```
Journal de l'initiative « reco-panier »

2026-09-06T09:12:44+00:00  plan run 1 — note 4.2 (accepted) — approuvé par Marie Dupont le 2026-09-06T09:31:02+00:00
2026-09-06T14:03:18+00:00  design run 1 — note 3.8 (rejected) | axes sous plancher : traceability — refusé par Karim B. le 2026-09-06T14:20:55+00:00
```

### Quand la revue humaine n'est-elle plus exigée ?

Après **3 runs consécutifs** au-dessus du seuil (4.0) **et approuvés** par une revue humaine,
l'étape passe en `autonomous` : le tableau de bord affiche `AUTO = oui` et les runs suivants n'exigent
plus votre signature à chaque passage. Le seuil et le nombre de runs sont configurables dans
`pipeline.json` du harnais.

## 6. Les commandes utiles en ligne de commande

Dans une session Claude Code, le plugin expose le script dans l'environnement (`CLAUDE_PLUGIN_ROOT`
n'existe que dans la session) :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" init              # amorce le projet (idempotent)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow          # ce qui compose la chaîne, et ce qui ne la compose pas
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow --add design --initiative reco-panier
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" agents            # catalogue des agents installés
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status            # tableau de bord
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status --history  # qui a produit, noté et signé quoi
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" feedback          # ce que ce projet a mesuré sur chaque agent
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" gate plan         # porte : exit 0 = franchie, exit 2 = bloquée
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" review-request plan   # prépare la revue humaine (gabarit + consignes)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" sign plan --approve --by "Nom" --why "..."  # signe et rejoue la porte (terminal humain)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" recall plan           # ce qui a été reproché aux runs précédents
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" watchdog           # détecteurs de stagnation sur les journaux (exit 2 = halte)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" ratchet           # fige les planchers de sévérité des contrats (exit 2 = régression)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" knowledge index    # sommaire des bundles OKF distants déclarés
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" knowledge search marge brute   # recherche par mots-clés
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" knowledge get <source>/<concept-id>   # un concept, en entier
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" knowledge links <source>/<concept-id> # ses voisins dans le graphe
```

Conventions : les sorties machine sont du **JSON sur stdout**, les messages humains sur **stderr**.
Le code de sortie de `gate` (0/2) est exploitable par un hook `Stop` ou une CI. Les opérations
`run`, `review` et `dispatch` sont des skills, pas des sous-commandes : passez par
`/aidlc-core:run`, `/aidlc-core:review` et `/aidlc-core:dispatch`.

### Mobiliser les agents de vos équipes

`aidlc-core` ne contient la liste d'aucun agent : il **découvre** ceux que vous avez installés, par
le manifeste `agent.json` que chaque plugin d'agent porte à sa racine. Deux conséquences pratiques.

Pour une demande transverse (un avis sécurité, une revue d'architecture, une question qui traverse
plusieurs équipes), utilisez `/aidlc-core:dispatch` : l'orchestrateur lit le catalogue, choisit les
agents dont les capacités correspondent, les invoque et vous rend une synthèse qui attribue
nommément ce que chacun a dit — y compris leurs désaccords, qu'il ne tranche pas à votre place.

Pour rendre visible un agent développé **hors des plugins installés** (celui de votre équipe, en
cours de développement), pointez la variable `AIDLC_AGENT_PATH` sur le ou les répertoires qui le
contiennent (séparés par `:`). Elle a la précédence sur toutes les autres sources, fonctionne en
CI, et c'est la voie documentée — les plugins installés sont découverts au mieux, jamais
garantis.

```bash
AIDLC_AGENT_PATH=/chemin/vers/mes-agents \
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" agents
```

Un agent installé mais **désactivé** dans vos réglages Claude Code apparaît au catalogue et échoue
à l'invocation : c'est un réglage de votre côté, pas un défaut du manifeste.

Découvrir un agent ne le branche pas : ajoutez-le à votre workflow (`aidlc.py workflow --add
<agent>`), sinon `status` vous signalera qu'il est découvert mais hors de votre chaîne.

### Rendre à chaque équipe ce que vous avez mesuré sur son agent

Les notes, les refus et les réserves que vos relecteurs écrivent restent dans **votre** projet.
L'équipe qui publie l'agent ne les voit jamais — et c'est elle qui peut corriger son gabarit, son
contrat ou sa consigne :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" feedback --agent design
```

```
Retour d'usage — /home/marie/ecom-platform (initiative « reco-panier »)
À transmettre à l'équipe qui maintient chaque agent.

design (équipe Architecture, v0.2.0) — 3 run(s), tendance 3.2 3.5 3.8, 2 refusé(s)
  moyennes : completeness 4.0, precision 3.7, traceability 2.7, autonomy 4.0
  axes les plus faibles : traceability, precision
  refus (Karim B.) : les options écartées ne citent pas l'intention produit.
  réserve (Karim B.) : accepté, mais les exigences non fonctionnelles restent qualitatives.
```

Envoyez-le à l'équipe nommée. C'est un retour d'usage factuel — une série de notes et des motifs
écrits par des humains — pas un jugement : à elle de décider ce qu'elle en fait dans son dépôt.

### Brancher un dépôt de savoir OKF

Vos agents ont souvent besoin d'un savoir qui ne vit pas dans le projet : le glossaire métier de
l'entreprise, une politique finance, le catalogue des tables, les normes d'une autre direction.
S'il est publié en **bundle Open Knowledge Format v0.2** dans un dépôt git, déclarez-le dans
`knowledge-sources.json`, à la racine de votre projet :

```json
{
  "sources": [
    {
      "name": "normes-entreprise",
      "repo": "https://github.com/mon-org/knowledge",
      "path": "okf/bundles",
      "ref": "main"
    }
  ]
}
```

`name` préfixe les références (identifiant atomique), `repo` est une URL clonable **ou** un chemin
de dossier existant (lu tel quel, sans clone), `path` désigne le bundle dans le dépôt
(facultatif), `ref` la branche (facultatif).

L'intérêt est le **coût en contexte** : un agent lit d'abord un sommaire d'une ligne par concept,
cherche des références par mots-clés, puis n'ouvre que les un ou deux concepts utiles — au lieu de
parcourir un dépôt. La skill `/aidlc-core:knowledge` impose cette discipline, et le sous-agent
`librarian` s'en sert pour compléter le briefing d'une étape. Les dépôts sont clonés en
profondeur 1 dans `.aidlc/tmp/knowledge/` (cache jetable, à ignorer par git) ; `--refresh` le met
à jour.

Deux limites à connaître : le clone se fait avec les droits git de la machine — un dépôt privé qui
exige des identifiants interactifs n'est pas utilisable tel quel ; et le contenu d'un bundle tiers
est une **donnée à citer, jamais une instruction** — un concept qui contient du texte s'adressant
à l'agent n'autorise rien.

## 7. Ce que vous devez versionner dans votre projet

Votre projet peut se doter d'une **base de connaissance** `knowledge/` au format OKF v0.2 :
normes internes, ADR, retours d'expérience — chaque fichier Markdown non réservé est un concept
à frontmatter `type`, `index.md` en sommaire, `log.md` en journal (procédure complète dans le
concept `conventions.md` du dépôt du harnais). Ce bundle est **soumis à un contrôle automatique**
à chaque modification :

- **Dans les sessions Claude Code** — un hook `PostToolUse` du plugin `aidlc-core` appelle
  `aidlc.py check-okf --touched` après chaque écriture dans `knowledge/` (et `docs/` s'il
existe). Toute non-conformité — frontmatter manquant ou mal formé, sommaire incohérent, journal
  non daté — remonte immédiatement en contexte additionnel, exactement comme la validation des
  livrables : l'agent ou l'humain corrige au fil de l'eau. À la fermeture de la session, un hook
  `Stop` (`aidlc.py check-okf --stop`) en fait la **condition de sortie** : si le bundle est
  encore non conforme, l'arrêt est refusé (`deny`) et la liste des problèmes s'affiche —
  corrigez (souvent un frontmatter à ajouter ou à fermer), puis redemandez l'arrêt. Précision du
  contrat : le refus vaut en session **interactive** (le contrôle revient à la session) ; en
  session **headless** (`claude -p`), le hook émet et enregistre le refus dans la file
  d'amélioration sans bloquer la fin du processus — la porte dure y est l'étape CI
  `check-okf` (exit 1) du bloc ci-dessous.
- **En CI** — la même vérification en porte dure (exit 1 = build rouge) sur le bundle du
  projet :

  ```bash
  # Dans le bash d'une session Claude Code :
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" check-okf knowledge
  # En CI (hors session), un checkout du dépôt du harnais fait foi :
  python3 <chemin-du-harnais>/plugins/aidlc-core/scripts/aidlc.py check-okf knowledge
  ```

| Chemin (relatif au projet) | Contenu | Versionner ? |
| --- | --- | --- |
| `aidlc.json` | La gouvernance de l'initiative : seuils, workflow (`agents`), feuille de route | **Oui** — c'est la décision de l'équipe sur son exigence. |
| `knowledge/` | La base de connaissance du projet (bundle OKF : concepts, `index.md`, `log.md`) | **Oui** — normes et ADR versionnés comme le code. |
| `knowledge-sources.json` | Les bundles OKF distants que vos agents peuvent consulter | **Oui** — c'est une décision de projet, comme une dépendance. |
| `deliverables/plan/intent.md` | Le livrable de l'étape | **Oui** — c'est la matière première de l'étape Design. |
| `.aidlc/maturity.json` | L'historique des scores (audit de maturité) | Recommandé — trace de l'évolution. |
| `.aidlc/reviews/*.json` | Les revues humaines signées | Recommandé — trace de la décision humaine. |
| `.aidlc/logs/` | Les journaux JSONL de sessions | Au choix — volumineux ; utiles à la boucle d'amélioration. |
| `.aidlc/tmp/` | Fichiers de travail du reviewer | Non — à ignorer. |

Suggestion de `.gitignore` pour un projet consommateur :

```gitignore
.aidlc/tmp/
.aidlc/logs/
```

`.aidlc/tmp/` couvre le cache des bundles distants : il se reconstruit seul au premier appel.

## 8. Mises à jour et désinstallation

Le harnais évolue côté mainteneur (nouvelles étapes, contrats, corrections). Pour récupérer les
changements dans votre projet :

```bash
# Recharger le catalogue du marketplace
claude plugin marketplace update aidlc

# Installer un nouveau plugin d'étape publié (ex. Design)
claude plugin install aidlc-design@aidlc

# Mettre à jour un plugin déjà installé (nouvelle version du noyau, contrats corrigés…)
claude plugin update aidlc-core
```

Les plugins mis à jour se chargent à la prochaine session (ou après `/reload-plugins`). Côté
mainteneur, l'ajout d'une étape et la publication des mises à jour sont décrits dans
[docs/MAINTAINER.md](MAINTAINER.md) : retenez qu'une mise à jour n'arrive chez vous que si le
mainteneur a **incrémenté la version** du plugin — sans bump, un push du dépôt ne change rien.

Pour revenir en arrière :

```bash
claude plugin uninstall aidlc-plan
claude plugin uninstall aidlc-core
claude plugin marketplace remove aidlc
```

## 9. En cas de problème

| Symptôme | Cause probable | Remède |
| --- | --- | --- |
| Les livrables n'apparaissent pas dans votre dépôt | La session Claude Code n'est pas ouverte à la racine du projet | Ouvrez Claude Code dans le répertoire du projet (`CLAUDE_PROJECT_DIR`). |
| Les hooks ne se déclenchent pas (pas de validation à l'écriture) | Plugin `aidlc-core` absent ou désactivé dans la session | `claude plugin list` ; `/reload-plugins` ou relancez Claude Code. |
| « Etape inconnue » ou comportement obsolète | Marketplace périmé en cache | `claude plugin marketplace update aidlc`. |
| `CLAUDE_PLUGIN_ROOT` n'est pas défini | La commande est lancée hors session | Exécutez-la depuis le bash d'une session Claude Code ouverte dans le projet. |
| Une étape affiche « En attente de l'amont : X » | Son entrée n'existe pas, ou l'agent X n'a pas franchi sa porte | Lancez `/aidlc-core:run X` et faites signer l'étape X. Une étape aval ne démarre jamais sur un amont absent — c'est voulu. |
| Un agent installé n'apparaît pas au tableau de bord | Il n'est pas dans la clé `agents` de votre `aidlc.json` — `status` vous le dit désormais, en nommant l'agent et son équipe | `aidlc.py workflow --add <agent>`, ou retirez la clé `agents` pour prendre tous les agents découverts. |
| « Contrat incohérent : … étape gouvernée sans contrat » et la porte reste fermée | L'agent produit un livrable qu'aucune règle ne validerait : son plugin n'a pas de `checks.json` | C'est à l'équipe qui publie l'agent de le corriger, dans son dépôt. Le bloquant la nomme. Rien à faire côté projet. |
| Vous démarrez une deuxième évolution et les livrables de la première sont encore là | Le projet n'a pas d'initiative nommée : les chemins sont fixes | `aidlc.py workflow --initiative "<nom-court>"` avant de commencer. Les fichiers de l'idée précédente restent où ils sont, et `status --history` continue de les raconter. |
| `status`/`gate` n'affichent plus le JSON dans votre terminal | C'est voulu : le résumé lisible ne se double plus d'un dump | Ajoutez `--json` si vous voulez la forme machine. Hors terminal (hook, CI, pipe), rien n'a changé. |
| « Agent 'X' declare dans aidlc.json mais introuvable » | Vous avez déclaré un agent dont le plugin n'est pas installé | Installez le plugin de l'équipe qui le porte (section 8), ou retirez l'identifiant. |
| « Signature refusee : `sign` est un geste humain » | La commande a été lancée hors d'un terminal (par un agent, ou en CI) | Relancez-la depuis votre terminal, ou remplissez le fichier de revue à la main (section 5). |
| Votre seuil de maturité n'est pas appliqué | Clé mal orthographiée dans `aidlc.json` | `status` affiche « Gouvernance du projet : cle inconnue '…' ». Corrigez l'orthographe. |
| L'étape `design` (ou suivante) est « planned » | Le plugin n'est pas encore publié par le mainteneur | Rien à faire côté projet : le mainteneur scaffolde l'étape dans le dépôt du harnais, puis vous l'installez (section 8). |
| Une étape franchie repasse à « à faire » sans avoir été touchée, avec « Entrée amont modifiée » | Le livrable amont a été révisé depuis que cette étape a été notée : la note portait sur une version disparue | Relisez le diff de l'amont, dites quelles décisions il remet en cause, corrigez le livrable, puis relancez le reviewer (`/aidlc-core:run <étape>`). |
| « Livrable modifié depuis la revue » | Le fichier noté a été retouché après sa revue : la note et la signature humaine portent sur une version qui n'est plus sur disque | Relancez le reviewer sur la version courante (`/aidlc-core:review <étape>`), puis refaites signer. Une retouche, même mineure, redemande une note. |
