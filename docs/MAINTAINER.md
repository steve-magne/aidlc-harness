---
type: Playbook
title: Maintenir et publier le harnais AI-DLC (guide auteur)
description: Guide auteur prêt à publier — publier l'agent de son équipe par son manifeste, concevoir une nouvelle étape, remplir les squelettes générés, vérifier avant release et publier dans le marketplace.
tags: [maintainer, guide, harness]
generated: { by: human:steve-magne, at: 2026-09-04T00:00:00Z }
---

# Maintenir et publier le harnais AI-DLC (guide auteur)

Ce guide s'adresse à l'**équipe qui maintient le harnais** : celle qui conçoit de nouvelles étapes,
fait évoluer les contrats et publie les changements dans le marketplace `aidlc` que les projets
consommateurs ont enregistré. C'est le pendant du guide
[Consommer le harnais dans votre projet](CONSUMER.md) : là où le consommateur *installe et
exécute*, l'auteur *conçoit, génère et publie*.

Trois idées structurent tout le reste :

1. **Le manifeste est la source de vérité.** Chaque plugin d'agent porte un `agent.json` à sa
   racine : identité, équipe propriétaire, capacités, version, invocation par plateforme, et — s'il
   produit un livrable — ce qu'il produit, ce qu'il consomme et son contrat. L'orchestrateur ne
   connaît que ça. **Publier un agent ne modifie jamais le noyau** : c'est ce qui permet à chaque
   équipe de rester maîtresse du sien.
2. **Un agent = un plugin** (`plugins/<nom>/`), listé dans `.claude-plugin/marketplace.json`. Le
   consommateur installe les agents qu'il veut ; ceux qu'il n'installe pas n'existent tout
   simplement pas dans son registre — et une entrée que plus personne ne produit lui est signalée
   par `status`, jamais escamotée.
3. **Publier = pousser sur le dépôt git que les consommateurs ont enregistré comme marketplace,**
   après avoir **incrémenté les versions** des plugins modifiés — la version (`version` dans le
   `plugin.json` de chaque plugin) est la clé de cache qui décide si le client d'un consommateur
   se met à jour.

---

## 1. Le contexte de travail : ce dépôt, jamais une copie installée

Toute la conception d'étape se mène dans **ce dépôt**, qui contient `plugins/` et
`.claude-plugin/marketplace.json`. Un projet consommateur ne scaffolde pas d'étape : sa copie
installée du harnais n'a ni `plugins/` ni `marketplace.json` à mettre à jour, et le scaffolder le
refuse.

Deux façons de travailler ici :

```bash
# En session Claude Code, plugins chargés depuis le dépôt (mode développement)
claude --plugin-dir plugins/aidlc-core --plugin-dir plugins/aidlc-plan

# En ligne de commande pure (le script s'auto-localise depuis la racine du dépôt)
python3 plugins/aidlc-core/scripts/aidlc.py status
```

Dans une session de développement, le plugin `aidlc-core` est chargé depuis
`plugins/aidlc-core` : `${CLAUDE_PLUGIN_ROOT}` pointe ce dossier et le pipeline modifié est bien
celui du dépôt. Garde-fou : la skill `new-stage` vérifie qu'elle travaille dans le dépôt auteur et
s'arrête si on l'appelle depuis une copie installée.

## 2. Ajouter une nouvelle étape

### 2.1 La voie recommandée : la skill `/aidlc-core:new-stage`

```
/aidlc-core:new-stage design
```

La skill mène un **entretien de conception** avec le professionnel métier responsable de l'étape
(l'architecte pour `design`, le QA lead pour `test`, etc.), bloc par bloc : identité et position de
l'étape, **le livrable unique** (un fichier dans `deliverables/<stage>/`), les entrées amont, la
structure exacte du document, les critères **vérifiables par machine** (traduits en règles de
`checks.json`, jamais en code), le rôle humain qui signe, et les questions que cet humain pose
systématiquement. Elle ne génère rien avant un « oui » explicite sur une fiche de synthèse, puis
appelle le scaffolder. Ses points d'arrêt : étape déjà `implemented`, synthèse non validée, refus
d'écrasement du scaffolder.

### 2.2 La voie directe : `scaffold`

Le scaffolder n'a besoin d'aucune déclaration préalable. Si l'étape figure dans `planned_stages` de
`plugins/aidlc-core/pipeline.json`, il en reprend le livrable, les entrées, le rôle humain et
l'équipe pour pré-remplir le manifeste ; sinon il part de zéro et vous complétez `agent.json`.

```bash
python3 plugins/aidlc-core/scripts/aidlc.py scaffold design
# --force écrase un plugin existant : à n'utiliser que pour tout réécrire, jamais par réflexe
```

### 2.3 Ce que produit le scaffolder

| Artefact | Rôle |
| --- | --- |
| `plugins/aidlc-<stage>/.claude-plugin/plugin.json` | Manifeste du plugin d'étape (version `0.1.0`). |
| `plugins/aidlc-<stage>/agents/<stage>-analyst.md` | L'agent qui dialogue avec le `human_role`. |
| `plugins/aidlc-<stage>/skills/<stage>/SKILL.md` | La recette du livrable, appelée par l'orchestrateur. |
| `plugins/aidlc-<stage>/templates/<livrable>` | Le squelette du document, marqueurs `<…>` compris. |
| `plugins/aidlc-<stage>/checks.json` | Le contrat déterministe (squelette générique à affiner). |
| `plugins/aidlc-<stage>/agent.json` | **Le manifeste** : identité, équipe, capacité `sdlc:<stage>`, invocation, `produces`, `consumes`, `checks`. |
| `.claude-plugin/marketplace.json` | Nouvelle entrée `aidlc-<stage>` (`source: ./plugins/aidlc-<stage>`). |

**Rien n'est écrit dans le noyau.** Le manifeste est le point clé : il suffit à faire entrer
l'agent au registre, et le contrat `checks.json` est résolu relativement à lui — donc lu dans votre
plugin, où qu'il soit installé. C'est pourquoi **publier un agent ne touche ni au pipeline, ni aux
hooks, ni à `aidlc.py`** : la validation à l'écriture et le garde-fou d'intégrité s'appliquent au
nouveau livrable dès que le manifeste le déclare.

### 2.3bis Publier un agent consultatif (le cas d'une équipe métier)

Un agent qui rend un **avis** et non un livrable omet simplement `produces` : ni contrat, ni
notation, ni porte. C'est la forme que prendront la plupart des agents d'équipe — sécurité,
architecture, QA. Le dépôt en livre un exemple complet et copiable :
`plugins/aidlc-security/` (équipe AppSec, capacités `security:review` et `security:threat-model`).

Un agent développé **hors de ce dépôt** n'a rien à y ajouter : le consommateur pointe
`AIDLC_AGENT_PATH` sur le répertoire qui le contient, et il entre au registre.

### 2.4 Remplir les squelettes — dans cet ordre

Le scaffolder génère des **squelettes génériques** (frontmatter `stage/version/status/author/date`,
sections types, volume minimal 250 mots, motifs interdits `TODO`/`TBD`/…, citation des entrées si
l'étape en a). C'est l'entretien de la skill qui les rend utiles :

1. **`plugins/aidlc-<stage>/checks.json`** — d'abord, car il fixe le contrat. N'utilisez que les
   règles reconnues par le moteur (voir la liste dans le `SKILL.md` de `new-stage`) : la forme se
   vérifie ici, le **fond se juge au reviewer**, pas avec une expression régulière.
2. **`templates/<livrable>`** — le frontmatter avec les clés de `required_frontmatter`, puis les
   sections obligatoires dans l'ordre. Les marqueurs `<…>` y sont le **seul** remplissage autorisé
   du dépôt.
3. **`skills/<stage>/SKILL.md`** — la recette : questions à poser au métier, structure attendue,
   obligation de citer les entrées, et remise de la validation à l'orchestrateur (le plugin
   d'étape n'appelle pas `aidlc.py` lui-même).
4. **`agents/<stage>-analyst.md`** — le profil de l'interlocuteur (ne devine pas, interroge le
   `librarian`, refuse la solution technique si le rôle l'exige).
5. **`knowledge/` (bundle OKF)** — versez les sources de vérité citées pendant l'entretien
   (normes, ADR, référentiels) comme concepts du bundle : frontmatter `type` et `stages`,
   mise à jour du sommaire `knowledge/index.md` et du journal `knowledge/log.md`. C'est ce qui
   donne à l'axe `traceability` de quoi s'appuyer.

### 2.5 Vérifier avant de publier

```bash
# 1. Hygiène du dépôt — tout Python compile, tout JSON parse (règles non négociables,
#    portes du moteur, exit 1 si fichier fautif ; rien n'est écrit)
python3 plugins/aidlc-core/scripts/aidlc.py check-python
python3 plugins/aidlc-core/scripts/aidlc.py check-json

# 2. L'auto-test du harnais passe — le seul test du projet ; il vérifie aussi la conformité
#    OKF v0.2 des bundles docs/ et knowledge/ (frontmatter, fichiers réservés, dates du journal)
python3 plugins/aidlc-core/scripts/aidlc.py --selftest

# 2bis. Conformance OKF des bundles de connaissance (exit 1 si non conforme)
python3 plugins/aidlc-core/scripts/aidlc.py check-okf docs
python3 plugins/aidlc-core/scripts/aidlc.py check-okf knowledge

# 3. Le plugin de l'étape est valide pour Claude Code (la CI .github/workflows/ci.yml
#    rejoue la validation sur chaque plugin du dépôt à chaque PR)
claude plugin validate plugins/aidlc-core
claude plugin validate plugins/aidlc-<stage>

# 4. Le tableau de bord montre l'étape implémentée
python3 plugins/aidlc-core/scripts/aidlc.py status
```

Test des contrats **à blanc** : copiez le template vers `deliverables/<stage>/<fichier>` (le dépôt
sert de projet d'essai), lancez `validate <stage>` et vérifiez qu'il **échoue** — un template non
rempli doit être rejeté. S'il passe, les checks sont trop lâches. Complétez ensuite un exemplaire
de bout en bout (`/aidlc-core:run <stage>` avec le métier) et **supprimez le fichier d'essai**
avant de committer : un livrable d'essai ne se rend pas dans le dépôt.

## 3. Publier dans le marketplace

### 3.1 La mécanique de version

Claude Code copie les plugins installés dans un cache local
(`~/.claude/plugins/cache/`). Pour décider si un plugin installé doit être mis à jour, il compare
la **version** : si `version` est présent dans le `.claude-plugin/plugin.json` du plugin (il
l'emporte sur la version éventuelle de l'entrée marketplace), **le consommateur ne reçoit la mise à
jour que lorsque vous l'incrémentez**. Incrémenter la version **est** l'acte de publication ; sans
lui, un push ne change rien chez les consommateurs.

| Vous modifiez… | Vous incrémentez la version de… |
| --- | --- |
| `plugins/aidlc-core/pipeline.json` (seuil, feuille de route, watchdog) | `plugins/aidlc-core/.claude-plugin/plugin.json` |
| Les hooks, le script `aidlc.py`, les skills ou agents du noyau | `plugins/aidlc-core/.claude-plugin/plugin.json` |
| Le contenu d'un plugin d'agent (manifeste, SKILL, agent, template, checks) | `plugins/<nom>/.claude-plugin/plugin.json` |

Exemple : l'ajout de l'étape `design` **ne touche pas au noyau** — vous publiez un nouveau plugin
en 0.1.0, et c'est tout. Le consommateur qui l'installe le voit apparaître à son tableau de bord ;
celui qui ne l'installe pas voit une entrée `missing_producers` s'il en dépend. Incrémentez
`aidlc-core` seulement si vous avez modifié le noyau lui-même.

### 3.2 Checklist de publication

1. Les vérifications de la section 2.5 passent (check-python, check-json, selftest, `claude plugin validate`).
2. Les versions sont incrémentées pour **tous** les plugins modifiés (`aidlc-core` seulement si
   le noyau a changé). Le manifeste `agent.json` de chaque agent touché est valide :
   `python3 plugins/aidlc-core/scripts/aidlc.py agents --strict` (porte CI).
3. `.claude-plugin/marketplace.json` liste chaque plugin d'étape avec un `source` relatif
   (`./plugins/aidlc-<stage>`) — les chemins relatifs sont résolus par rapport à la racine du
   marketplace, donc ils fonctionnent que le consommateur ait ajouté le dépôt par chemin local ou
   par git.
4. La documentation suit : ce guide et `docs/CONSUMER.md` pour les changements de procédure,
   `knowledge/` pour les nouvelles sources de vérité (concepts OKF, sommaire `index.md`,
   journal `log.md`).
5. Aucun artefact d'essai ne traîne (`deliverables/<stage>/`, `.aidlc/tmp/`).

Puis **committez et poussez** sur la branche que les consommateurs ont enregistrée. C'est tout :
pas de build, pas de registre — le dépôt git *est* le marketplace. Pour marquer une version
importante, posez un tag (`git tag v0.2.0`) : un consommateur exigeant peut épingler le marketplace
sur ce tag (`claude plugin marketplace add <url>@v0.2.0`) au lieu de suivre la branche par défaut.

### 3.3 Ce que les consommateurs doivent faire de leur côté

Après votre push, chaque projet consommateur doit recharger le catalogue puis installer ou mettre à
jour les plugins (détails dans [CONSUMER.md](CONSUMER.md#8-mises-à-jour-et-désinstallation)) :

```bash
claude plugin marketplace update aidlc        # recharge le catalogue depuis le dépôt
claude plugin install aidlc-design@aidlc      # une NOUVELLE étape = un nouveau plugin à installer
claude plugin update aidlc-core               # une étape existante = mettre à jour les plugins concernés
# puis, dans la session : /reload-plugins (les hooks reprennent la nouvelle copie du plugin)
```

Trois conséquences à assumer quand vous annoncez une release :

- **Une nouvelle étape exige une action du consommateur** (installer le plugin, pas seulement
  mettre à jour le catalogue). Dès qu'il met à jour `aidlc-core`, son pipeline affiche l'étape
  comme `implemented` — mais tant qu'il n'a pas installé `aidlc-<stage>@aidlc`, `/aidlc-core:run
  <stage>` échoue faute de skill : la mise à jour du catalogue ne suffit pas.
- **Modifier le `checks.json` ou le template d'une étape déjà franchie** chez des consommateurs
  actifs peut rouvrir leur porte au prochain run (la validation rejoue les nouvelles règles sur le
  livrable existant). Annoncez ce type de changement ; l'historique de maturité
  (`.aidlc/maturity.json` des consommateurs) n'est jamais recalculé.
- **Une évolution des hooks voyage dans `aidlc-core`** et s'active chez le consommateur au
  prochain reload de plugin — sans action de sa part. Exemples : le hook `PostToolUse`
  `check-okf --touched` (chaque écriture dans `knowledge/`) et le hook `Stop` `check-okf --stop`
  (la fermeture de session est refusée tant que le bundle est non conforme — portée
  interactive : l'arrêt refusé ramène le contrôle en session ; en headless `-p`, le refus est
  enregistré sans bloquer, la porte dure y est la CI. Prévenez les consommateurs que cette
  condition de sortie peut les retenir en session interactive le temps de corriger). Si
  la nouvelle version du noyau contrôle un dossier que le consommateur ne possède pas (pas de
  `knowledge/`), les hooks restent muets : le dispositif est sans effet de bord.

## 4. Faire évoluer une étape existante

Une étape `implemented` ne se reconçoit pas via `new-stage` (la skill s'arrête) : elle **s'améliore**.

```
/aidlc-core:improve <stage>
```

La boucle d'auto-amélioration agrège les signaux — journaux de sessions, historique de maturité,
file des refus humains (`.aidlc/improvement-queue.jsonl`, alimentée à chaque revue humaine
refusée) — et produit un diagnostic. La skill `/aidlc-core:improve` le lit et **propose** un diff
sur le `SKILL.md`, le template ou le `checks.json` de l'étape faible ; elle ne l'applique jamais
sans accord humain explicite, et elle corrige la **source** (ce dépôt), jamais une copie installée.

Une évolution acceptée suit ensuite exactement le circuit de publication de la section 3 :
incrémenter la version du plugin modifié, vérifier (selftest, `claude plugin validate`), committer,
pousser, annoncer aux consommateurs (`claude plugin update`).

## 5. Commandes utiles (récapitulatif)

Depuis la racine du dépôt :

```bash
python3 plugins/aidlc-core/scripts/aidlc.py status                 # tableau de bord
python3 plugins/aidlc-core/scripts/aidlc.py check-okf <dir>        # conformité OKF v0.2 d'un bundle (exit 1 si non conforme)
python3 plugins/aidlc-core/scripts/aidlc.py check-python           # tout Python compile (règle 6, exit 1 si erreur de syntaxe)
python3 plugins/aidlc-core/scripts/aidlc.py check-json             # tout JSON parse (règle 6, exit 1 si JSON invalide)
python3 plugins/aidlc-core/scripts/aidlc.py scaffold <stage>       # génère le plugin d'une étape planned
python3 plugins/aidlc-core/scripts/aidlc.py scaffold <stage> --force   # écrase et régénère
python3 plugins/aidlc-core/scripts/aidlc.py ratchet                # fige les planchers de sévérité des checks.json (exit 2 = régression)
python3 plugins/aidlc-core/scripts/aidlc.py ratchet --reset <stage>  # repart du contrat courant après décision humaine
python3 plugins/aidlc-core/scripts/aidlc.py watchdog                # détecteurs de stagnation sur les journaux (exit 2 = halte)
python3 plugins/aidlc-core/scripts/aidlc.py --selftest             # auto-test (doit passer avant chaque release)
claude plugin validate plugins/aidlc-core                          # validité des plugins pour Claude Code
claude plugin validate plugins/aidlc-<stage>
```

Règles non négociables rappelées par [CLAUDE.md](../CLAUDE.md) : un livrable = un fichier de
`deliverables/` chez le consommateur ; toute logique déterministe vit sous
`plugins/aidlc-core/scripts/` (`aidlc.py` + paquet `_aidlc/`, jamais de second point d'entrée,
jamais de logique dans un hook) ; une nouvelle vérification s'exprime d'abord dans
un `checks.json` ; aucune dépendance externe ; aucun placeholder non résolu hors des `templates/`.
