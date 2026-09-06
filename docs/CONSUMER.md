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

Aujourd'hui, **l'étape Plan est la seule implémentée** : elle produit le livrable de cadrage
`deliverables/plan/intent.md`. Les autres étapes apparaissent au tableau de bord comme
« planifiées » ; elles sont conçues et générées par l'équipe qui maintient le harnais, pas par le
projet consommateur.

---

## 1. Ce que vous installez, et où atterrissent les fichiers

Le harnais est distribué comme un **marketplace de plugins Claude Code** nommé `aidlc`, qui
contient pour l'instant deux plugins :

| Plugin | Rôle |
| --- | --- |
| `aidlc-core` | Le noyau : registre d'agents, gouvernance, script déterministe `aidlc.py`, orchestrateur, reviewer, librarian, hooks de journalisation et de garde-fous. Il ne contient la liste d'aucun agent : il les découvre. |
| `aidlc-plan` | L'étape Plan : agent de dialogue avec le Product Owner, recette de la skill `plan`, squelette du livrable, contrat `checks.json`. |

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
5. **La porte** (`gate`) s'ouvre seulement si la validation passe, le verdict est `accepted` et le
   score est au moins `4.0` (le seuil). Tant que l'étape n'est pas autonome, **la revue humaine est
   exigée** : la porte reste fermée et l'orchestrateur vous laisse la main (section suivante).

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
Seuil de maturite : 4.0 | Etape courante : plan

ETAPE      PLUGIN      LIVRABLE  VALIDE  SCORE  AUTO  PROCHAINE ACTION
plan       implemented non      -       -      non   Produire le livrable : skill aidlc-plan:plan
design     planned     non      -       -      non   Scaffolder l'etape : aidlc.py scaffold design
build      planned     non      -       -      non   Scaffolder l'etape : aidlc.py scaffold build
test       planned     non      -       -      non   Scaffolder l'etape : aidlc.py scaffold test
deploy     planned     non      -       -      non   Scaffolder l'etape : aidlc.py scaffold deploy
maintain   planned     non      -       -      non   Scaffolder l'etape : aidlc.py scaffold maintain
```

Les lignes `design` → `maintain` affichent une action **réservée à l'équipe qui maintient le
harnais** : un projet consommateur ne scaffolde pas d'étape, il attend que le plugin correspondant
soit publié dans le marketplace (voir « Mises à jour »).

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

Copiez le gabarit vers le fichier de revue définitif et renseignez-le :

```bash
cp .aidlc/reviews/plan-1.template.json .aidlc/reviews/plan-1.json
```

```json
{
  "stage": "plan",
  "run": 1,
  "approved": true,
  "reviewer": "Votre Prénom Nom",
  "justification": "Le problème, le périmètre et les critères d'acceptation correspondent au besoin exprimé.",
  "ts": "2026-09-04T10:00:00+00:00"
}
```

Puis dites à Claude, dans la session : **« la revue humaine est signée, rouvre la porte »**.
L'orchestrateur relance `gate` : la porte s'ouvre, l'étape est franchie et il vous propose l'étape
suivante (`design` — planifiée, donc à attendre du mainteneur du harnais).

### 5.4 Vous refusez

Si le livrable n'est pas acceptable, mettez `"approved": false`. La **justification est
obligatoire** : elle est copiée automatiquement dans `.aidlc/improvement-queue.jsonl` et alimente
la boucle d'amélioration du harnais (la skill `aidlc-core:improve` du dépôt d'origine). La porte
reste fermée ; reprenez le livrable (`/aidlc-core:run plan`, qui entre alors en mode « reprise »),
puis une nouvelle revue du reviewer ouvrira un run n° 2 (`plan-2`).

### Qui peut signer ?

**Uniquement un humain.** Le hook `PreToolUse` refuse les écritures d'agents dans
`.aidlc/reviews/` : Claude ne peut ni remplir le fichier à votre place ni le modifier après
signature. La signature se reconnaît par la présence du fichier `<stage>-<run>.json` — le
`.template.json` seul ne vaut pas signature.

### Quand la revue humaine n'est-elle plus exigée ?

Après **3 runs consécutifs** au-dessus du seuil (4.0) **et approuvés** par une revue humaine,
l'étape passe en `autonomous` : le tableau de bord affiche `AUTO = oui` et les runs suivants n'exigent
plus votre signature à chaque passage. Le seuil et le nombre de runs sont configurables dans
`pipeline.json` du harnais.

## 6. Les commandes utiles en ligne de commande

Dans une session Claude Code, le plugin expose le script dans l'environnement (`CLAUDE_PLUGIN_ROOT`
n'existe que dans la session) :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" agents            # catalogue des agents installés
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status            # tableau de bord
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" gate plan         # porte : exit 0 = franchie, exit 2 = bloquée
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" review-request plan   # prépare la revue humaine (gabarit + consignes)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" watchdog           # détecteurs de stagnation sur les journaux (exit 2 = halte)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" ratchet           # fige les planchers de sévérité des contrats (exit 2 = régression)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" knowledge index    # sommaire des bundles OKF distants déclarés
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" knowledge search marge brute   # recherche par mots-clés
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" knowledge get <source>/<concept-id>   # un concept, en entier
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
| L'étape `design` (ou suivante) est « planned » | Le plugin n'est pas encore publié par le mainteneur | Rien à faire côté projet : le mainteneur scaffolde l'étape dans le dépôt du harnais, puis vous l'installez (section 8). |
| Une étape franchie repasse à « à faire » sans avoir été touchée, avec « Entrée amont modifiée » | Le livrable amont a été révisé depuis que cette étape a été notée : la note portait sur une version disparue | Relisez le diff de l'amont, dites quelles décisions il remet en cause, corrigez le livrable, puis relancez le reviewer (`/aidlc-core:run <étape>`). |
| « Livrable modifié depuis la revue » | Le fichier noté a été retouché après sa revue : la note et la signature humaine portent sur une version qui n'est plus sur disque | Relancez le reviewer sur la version courante (`/aidlc-core:review <étape>`), puis refaites signer. Une retouche, même mineure, redemande une note. |
