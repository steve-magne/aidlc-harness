# Maintenir et publier le harnais AI-DLC (guide auteur)

Ce guide s'adresse à l'**équipe qui maintient le harnais** : celle qui conçoit de nouvelles étapes,
fait évoluer les contrats et publie les changements dans le marketplace `aidlc` que les projets
consommateurs ont enregistré. C'est le pendant du guide
[Consommer le harnais dans votre projet](CONSUMER.md) : là où le consommateur *installe et
exécute*, l'auteur *conçoit, génère et publie*.

Trois idées structurent tout le reste :

1. **Le pipeline est la source de vérité.** Il vit dans `plugins/aidlc-core/pipeline.json`, *dans
   le plugin* — il est donc installé chez chaque consommateur avec le plugin `aidlc-core`. Ajouter
   une étape, c'est d'abord modifier ce fichier, puis tout ce qui en découle.
2. **Une étape = un plugin** (`plugins/aidlc-<stage>/`), référencé par le pipeline et listé dans
   `.claude-plugin/marketplace.json`. Le consommateur n'installe le plugin d'une étape **que s'il
   veut la jouer** ; le noyau, lui, voit toujours toutes les étapes.
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

### 2.2 La voie directe : le pipeline d'abord, puis `scaffold`

Le scaffolder **ne crée pas l'entrée d'étape** : il exige qu'elle existe déjà dans
`plugins/aidlc-core/pipeline.json`. Si l'étape n'est pas encore dans le pipeline (nouvelle étape
hors des six du cycle), ajoutez son entrée à la bonne position, sur le modèle exact des autres :

```json
{
  "id": "design",
  "name": "Design",
  "plugin": "aidlc-design",
  "skill": "aidlc-design:design",
  "deliverable": "deliverables/design/spec.md",
  "inputs": ["deliverables/plan/intent.md"],
  "checks": "checks/design.json",
  "human_role": "Architecte de solution",
  "status": "planned"
}
```

Puis :

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
| `plugins/aidlc-core/pipeline.json` | `status` passe à `implemented`, `checks` à `checks/<stage>.json`. |
| `plugins/aidlc-core/checks/<stage>.json` | **Miroir** du contrat (lien symbolique vers le `checks.json` du plugin d'étape ; copie si votre système de fichiers l'exige). |
| `.claude-plugin/marketplace.json` | Nouvelle entrée `aidlc-<stage>` (`source: ./plugins/aidlc-<stage>`). |

Le miroir est le point clé : le noyau lit **toujours** le contrat d'une étape dans
`plugins/aidlc-core/checks/`, quel que soit l'agencement des plugins dans le cache de Claude Code.
C'est pourquoi **ajouter une étape ne touche ni aux hooks ni à `aidlc.py`** : la validation à
l'écriture et le garde-fou d'intégrité s'appliquent automatiquement au nouveau livrable dès que le
pipeline le déclare.

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
5. **`knowledge/index.json`** — versez les sources de vérité citées pendant l'entretien
   (normes, ADR, référentiels) pour que l'axe `traceability` ait de quoi s'appuyer.

### 2.5 Vérifier avant de publier

```bash
# 1. Tous les JSON parsent (pipeline, marketplaces, manifests, checks, knowledge), le Python compile
python3 -c "import json,glob;[json.load(open(p)) for p in glob.glob('plugins/**/*.json',recursive=True)+glob.glob('.claude-plugin/*.json')+glob.glob('knowledge/*.json')]" && echo "JSON OK"
python3 -m py_compile plugins/aidlc-core/scripts/aidlc.py && echo "py OK"

# 2. L'auto-test du harnais passe (le seul test du projet)
python3 plugins/aidlc-core/scripts/aidlc.py --selftest

# 3. Le plugin de l'étape est valide pour Claude Code
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
| `plugins/aidlc-core/pipeline.json` (nouvelle étape, nouvel input, nouveau seuil…) | `plugins/aidlc-core/.claude-plugin/plugin.json` |
| Les hooks, le script `aidlc.py`, les skills ou agents du noyau | `plugins/aidlc-core/.claude-plugin/plugin.json` |
| Un miroir `plugins/aidlc-core/checks/<stage>.json` (donc le `checks.json` d'une étape) | `aidlc-core` **et** le plugin de l'étape concernée |
| Le contenu d'un plugin d'étape (SKILL, agent, template, checks) | `plugins/aidlc-<stage>/.claude-plugin/plugin.json` |

Exemple : l'ajout de l'étape `design` modifie le pipeline du noyau et crée un nouveau plugin —
vous incrémentez `aidlc-core` (0.1.0 → 0.2.0) et le nouveau plugin naît en 0.1.0. Sans le bump de
`aidlc-core`, le tableau de bord d'un consommateur continuerait d'ignorer `design`.

### 3.2 Checklist de publication

1. Les vérifications de la section 2.5 passent (selftest, `claude plugin validate`, JSON).
2. Les versions sont incrémentées pour **tous** les plugins modifiés, y compris `aidlc-core` dès
   que `pipeline.json` change.
3. `.claude-plugin/marketplace.json` liste chaque plugin d'étape avec un `source` relatif
   (`./plugins/aidlc-<stage>`) — les chemins relatifs sont résolus par rapport à la racine du
   marketplace, donc ils fonctionnent que le consommateur ait ajouté le dépôt par chemin local ou
   par git.
4. La documentation suit : ce guide et `docs/CONSUMER.md` pour les changements de procédure,
   `knowledge/index.json` pour les nouvelles sources de vérité.
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

Deux conséquences à assumer quand vous annoncez une release :

- **Une nouvelle étape exige une action du consommateur** (installer le plugin, pas seulement
  mettre à jour le catalogue). Dès qu'il met à jour `aidlc-core`, son pipeline affiche l'étape
  comme `implemented` — mais tant qu'il n'a pas installé `aidlc-<stage>@aidlc`, `/aidlc-core:run
  <stage>` échoue faute de skill : la mise à jour du catalogue ne suffit pas.
- **Modifier le `checks.json` ou le template d'une étape déjà franchie** chez des consommateurs
  actifs peut rouvrir leur porte au prochain run (la validation rejoue les nouvelles règles sur le
  livrable existant). Annoncez ce type de changement ; l'historique de maturité
  (`.aidlc/maturity.json` des consommateurs) n'est jamais recalculé.

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
python3 plugins/aidlc-core/scripts/aidlc.py scaffold <stage>       # génère le plugin d'une étape planned
python3 plugins/aidlc-core/scripts/aidlc.py scaffold <stage> --force   # écrase et régénère
python3 plugins/aidlc-core/scripts/aidlc.py --selftest             # auto-test (doit passer avant chaque release)
claude plugin validate plugins/aidlc-core                          # validité des plugins pour Claude Code
claude plugin validate plugins/aidlc-<stage>
```

Règles non négociables rappelées par [CLAUDE.md](../CLAUDE.md) : un livrable = un fichier de
`deliverables/` chez le consommateur ; toute logique déterministe vit dans `aidlc.py` (jamais de
second script, jamais de logique dans un hook) ; une nouvelle vérification s'exprime d'abord dans
un `checks.json` ; aucune dépendance externe ; aucun placeholder non résolu hors des `templates/`.
