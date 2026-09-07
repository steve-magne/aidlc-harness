# aidlc-harness

**Un harnais agentique d'entreprise pour le AI-native SDLC**, distribué comme un marketplace de
plugins Claude Code. Des agents produisent les livrables du cycle de vie logiciel — cadrage,
conception, build, test, déploiement — et le harnais **garantit que ce qu'ils produisent est
vérifiable** : validation déterministe, notation par un agent *reviewer*, porte de qualité,
signature humaine, journal de session.

Une seule porte d'entrée : **`/aidlc`**.

---

## Installer

**Un seul plugin à installer.** Depuis la racine de **votre** projet :

```bash
claude plugin marketplace add <chemin-local-ou-url-git-de-aidlc-harness>
claude plugin install aidlc@aidlc
```

C'est tout. Les trois autres entrées du marketplace — `aidlc-plan`, `aidlc-design`,
`aidlc-security` — sont des **exemples d'agents d'équipe** : installez-les pour essayer le harnais
sur un cycle complet, ou copiez-les pour écrire le vôtre. Aucun n'est requis.

```bash
# facultatif : de quoi jouer une chaîne plan → design de bout en bout
claude plugin install aidlc-plan@aidlc
claude plugin install aidlc-design@aidlc
```

Prérequis : **Claude Code** récent (marketplaces + hooks) et **Python 3** — ou **uv**, que le
lanceur préfère quand il est présent. Aucune dépendance à installer : le moteur n'utilise que la
bibliothèque standard.

## Premier run

Dans une session ouverte à la racine de votre projet :

```
/aidlc init
```

Il amorce le projet — `aidlc.json` (votre seuil, votre workflow), `deliverables/`, le bundle
`knowledge/` — et **compose votre chaîne** en dialoguant : quelles équipes interviennent, sous quel
nom d'initiative. L'amorçage part d'un inventaire de ce que votre dépôt dit déjà de lui-même
(README, manifestes, ADR), et ne remplace jamais un fichier existant.

Ensuite, tout passe par le même verbe :

```
/aidlc              # sans argument : lit l'état et propose la prochaine action
/aidlc status       # où en est le pipeline, qui est attendu, ce qui bloque
/aidlc next plan    # produire le livrable de cadrage, de bout en bout
/aidlc doctor       # quelque chose cloche ? le diagnostic en une commande
```

L'agent dialogue avec vous, écrit `deliverables/plan/intent.md` **dans votre projet**, le hook le
valide à chaque écriture, le reviewer le note, la porte s'arrête et vous demande de signer. **Rien
n'est jamais écrit dans le dépôt du harnais** : la copie installée est en lecture seule, et un hook
le fait respecter.

| Verbe | Ce qu'il fait |
| --- | --- |
| `init` | Amorce le projet et compose le workflow de l'initiative |
| `next [étape]` | Exécute une étape : livrable, validation, revue, porte |
| `status` | Tableau de bord du pipeline |
| `review` / `sign` | Faire noter un livrable · préparer la revue humaine |
| `agents` | Qui est publié, qui est branché, comment en ajouter |
| `new-agent` | Concevoir une étape avec son référent métier, générer son plugin |
| `ask` | Un avis transverse, sans livrable (sécurité, archi…) |
| `improve` / `doctor` | Diagnostiquer une étape qui stagne · la dérive d'installation |
| `knowledge` | Consulter le savoir OKF déclaré par le projet |

→ Le guide pas à pas, y compris la signature : **[docs/CONSUMER.md](docs/CONSUMER.md)**.

## À quel besoin ça répond

Faire écrire un document de cadrage par une IA est facile. Le faire **de façon fiable, traçable et
reproductible dans une entreprise où chaque direction a ses règles** ne l'est pas.

| Le problème | La réponse |
| --- | --- |
| La qualité dépend de la chance du prompt | Un contrat déclaratif (`checks.json`) par livrable, appliqué **à chaque écriture** par un hook |
| « C'est bon ? » n'a pas de réponse objective | Une note 0–5 sur 4 axes, un seuil, une porte qui rend un code de sortie exploitable en CI |
| Une étape démarre sur un livrable amont absent ou pas validé | La porte exige que chaque entrée `consumes` existe et que son producteur ait franchi la sienne |
| L'IA avance seule là où l'humain devait décider | Revue humaine obligatoire tant que l'étape n'est pas autonome ; `sign` exige un terminal, un agent ne peut pas signer à votre place |
| Un projet mène plusieurs idées, la seconde écrase la première | La clé `initiative` isole livrables, scores et signatures : `deliverables/<idée>/`, `.aidlc/<idée>/` |
| Chaque équipe veut son agent, personne ne veut d'un noyau à modifier | Chaque équipe publie son plugin avec un manifeste `agent.json` ; l'orchestrateur **découvre** les agents, il n'en tient aucune liste |

## Comment ça marche

> Neuf schémas, un par question : **[docs/DIAGRAMS.md](docs/DIAGRAMS.md)**.

```
   porte amont          l'entrée `consumes` existe ? son producteur a franchi sa porte ?
        │               non → bloqué, avec le nom de l'agent à relancer
        ▼
   l'agent écrit        deliverables/<étape>/<fichier>, dans VOTRE projet
        │
        ▼
   hook PostToolUse     une passe unique : validation, OKF, syntaxe, watchdog
        │
        ▼
   reviewer             note 0–5 sur completeness · precision · traceability · autonomy
        │
        ▼
   porte de sortie      seuil tenu ? revue humaine faite ? → étape suivante
```

L'ordre des étapes se **dérive** de la chaîne producteur → consommateur déclarée dans les
manifestes — jamais d'une position dans un fichier de configuration.

## Publier l'agent de son équipe

Le noyau n'est **jamais** modifié pour ajouter un agent : c'est la condition de la modularité.
Depuis ce dépôt :

```
/aidlc new-agent design
```

La skill mène l'entretien avec le référent métier, puis génère le plugin complet — manifeste
`agent.json`, agent, skill, gabarit, contrat déterministe — et l'inscrit au marketplace. Un agent
**consultatif** (un avis, pas de livrable) omet simplement `produces` : voir `plugins/aidlc-security/`.

→ Le guide auteur : **[docs/MAINTAINER.md](docs/MAINTAINER.md)**.

## Deux racines, à ne pas confondre

| | Où | Quoi |
| --- | --- | --- |
| **Le harnais** | `CLAUDE_PLUGIN_ROOT` | La copie installée du plugin. **Lecture seule** : gouvernance par défaut, moteur, hooks. |
| **Votre projet** | `CLAUDE_PROJECT_DIR` | `aidlc.json`, `deliverables/`, `.aidlc/`, `knowledge/`. Tout ce que le harnais produit atterrit ici. |

Quand ce dépôt sert de projet d'essai, les deux se confondent — c'est le seul cas.

## Développer le harnais lui-même

Depuis la racine de ce dépôt :

```bash
tools/aidlc-dev test          # la suite unittest — doit passer
tools/aidlc-dev selfscore     # le score de maturité du dépôt (porte du pre-commit et de la CI)
plugins/aidlc/bin/aidlc agents  # qui est dans le registre
claude --plugin-dir plugins/aidlc --plugin-dir plugins/aidlc-plan
```

Les portes du dépôt (`test`, `coverage`, `selfscore`, `ratchet`) vivent dans `tools/`, **hors du
plugin** : elles notent ce dépôt, pas le projet d'un consommateur. Activez la porte locale une fois
par clone :

```bash
git config core.hooksPath .githooks
```

→ Les tests : **[docs/TESTING.md](docs/TESTING.md)** · l'architecture :
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** · les conventions du dépôt :
**[CLAUDE.md](CLAUDE.md)**.

## Arborescence

```
plugins/aidlc/                le harnais — c'est le seul plugin à installer
  skills/aidlc/SKILL.md         la porte d'entrée : une table de verbes
  skills/aidlc/reference/       le détail de chaque verbe, chargé à la demande
  bin/aidlc                     lanceur (uv sinon python3) — cité par les hooks et les skills
  scripts/_aidlc/               le moteur déterministe (stdlib seule)
  pipeline.json                 gouvernance par défaut : seuils, watchdog, feuille de route
plugins/aidlc-plan/           EXEMPLE — agent d'étape en tête de chaîne
plugins/aidlc-design/         EXEMPLE — agent d'étape aval (consomme le livrable de plan)
plugins/aidlc-security/       EXEMPLE — agent consultatif (aucun `produces`)
tools/aidlc-dev               les portes de CE dépôt, hors du plugin
docs/                         documentation publiée (bundle OKF v0.2)
knowledge/                    base de connaissance de ce dépôt (bundle OKF v0.2)
```

## Les contraintes structurantes

- **Aucune dépendance externe.** Bibliothèque standard Python uniquement, `unittest` pour les
  tests. Le harnais tourne chez n'importe quel consommateur avec `python3` seul.
- **Un livrable = un fichier**, au chemin exact déclaré par le `produces` du manifeste.
- **L'état runtime et les règles ne s'éditent jamais à la main par un agent** : un hook
  `PreToolUse` refuse ces écritures. Un agent n'édite ni les règles qui le jugent, ni sa propre
  note, ni le livrable d'un voisin.
- **Le dépôt se note lui-même, et la note est bloquante** : `tools/aidlc-dev selfscore` agrège
  cinq axes déterministes et rougit la CI sous le seuil.
