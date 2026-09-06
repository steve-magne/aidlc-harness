---
name: run
description: Exécuter une étape du pipeline AI-DLC de bout en bout — rédaction du livrable, validation déterministe, revue de maturité, décision de passage. À utiliser quand on demande de lancer le pipeline, de démarrer, de relancer ou de faire avancer une étape (plan, design, build, test, deploy, maintain).
argument-hint: "[stage] — id d'étape ; vide = prochaine étape à traiter"
---

# Lancer une étape du pipeline

## Conventions

Deux racines, à ne pas confondre :

- **Le projet consommateur** (`$CLAUDE_PROJECT_DIR`) : c'est là que vivent les livrables
  (`deliverables/`), l'état runtime (`.aidlc/`) et la connaissance du projet (`knowledge/`).
  Les commandes se lancent depuis cette racine.
- **Le harnais** (plugin `aidlc-core`) : le script unique y est installé. `${CLAUDE_PLUGIN_ROOT}`
  résout le dossier du plugin ; la gouvernance se lit dans `${CLAUDE_PLUGIN_ROOT}/pipeline.json`.
  Les étapes, elles, se lisent dans le **registre d'agents** (`aidlc.py agents`), et le contrat
  déterministe de chaque étape dans le `checks.json` du plugin qui la porte.

Dans la suite, le script est noté :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" <sous-commande>
```

Tu **ne rédiges jamais le livrable toi-même** : tu délègues à la skill de l'étape. Ton rôle ici est
d'enchaîner les étapes dans le bon ordre et de t'arrêter net quand une porte est fermée.

## 1. Déterminer l'étape à traiter

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status --json
```

- Si l'utilisateur a fourni un argument, c'est l'id d'agent à traiter. Vérifie qu'il figure au
  registre (`aidlc.py agents`) ; sinon liste les ids valides et arrête-toi.
- Sans argument, prends la première étape non franchie du tableau `stages` de `status --json` :
  il est déjà trié par dépendances entre livrables.
- Si toutes les étapes sont franchies, dis-le et arrête-toi. Ne relance rien « pour voir ».
- Demande sans livrable attendu (un avis, une revue transverse) : ce n'est pas une étape. Bascule
  sur `/aidlc-core:dispatch`.

## 2. Vérifier que l'étape est jouable

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" agents --json
```

- L'id n'est pas au registre mais figure en `planned` dans `status` -> aucun plugin ne le porte
  encore. **Arrête-toi** et propose `aidlc-core:new-stage`. Ne tente pas d'improviser le livrable.
- `"invocable": false` -> l'agent ne déclare pas d'invocation pour cette plateforme : arrête-toi et
  nomme l'équipe propriétaire (`team`).
- `contract_problems` mentionne cet agent -> son `checks.json` est incohérent (règle jamais
  appliquée, section exigée que le contrat n'impose pas, gabarit qui a dérivé). **Arrête-toi** :
  le livrable ne pourrait pas valider quoi que tu écrives. Relaie le message et nomme l'équipe
  propriétaire — ce contrat se corrige dans son dépôt, pas ici.
- Sinon, continue : retiens `invoke` (l'invocation exacte), `produces` et `consumes`.

## 3. Vérifier les entrées amont

Pour chaque chemin listé dans `consumes` :

- Le fichier doit exister. S'il manque, cherche dans le catalogue l'agent qui le `produces` et
  dis lequel lancer d'abord (`/aidlc-core:run <agent amont>`), puis arrête-toi. Si personne ne le
  produit, c'est un trou du registre (`missing_producers`) : dis-le, le plugin manque.
- Le fichier doit avoir passé sa propre porte. En cas de doute :
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" gate <étape amont>` (exit 0 = franchie,
  exit 2 = bloquée).
  Une porte amont fermée est bloquante : ne construis pas sur du sable.

## 4. Charger le contexte

Délègue au sous-agent `librarian` la question : « quel contexte pour l'étape `<stage>` ? ».
Il lit le bundle OKF `knowledge/` — concepts filtrés par leur `stages`, glossaire, sommaire
`index.md` — et les livrables amont, et te rend une synthèse des sources de vérité à citer.
Transmets cette synthèse à la skill de l'étape.

## 5. Produire le livrable

Si l'étape porte déjà un run, récupère d'abord ce qui lui a été reproché :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" recall <stage>
```

Invoque **exactement** la valeur du champ `invoke` du catalogue (par exemple `aidlc-plan:plan`),
via l'outil Skill, en lui passant :

- le chemin du livrable attendu (`produces`) ;
- les chemins des `consumes` ;
- la synthèse du librarian ;
- les reproches du `recall`, s'il y en a — sans eux l'agent refait l'erreur pour laquelle
  l'étape a été refusée.

La skill de l'étape mène le dialogue métier et écrit le livrable. Laisse-la faire : tu n'écris pas
dans `deliverables/` toi-même.

## 6. Valider (déterministe)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" validate <stage> --json
```

- **exit 0** : continue à l'étape 7.
- **exit 1** : lis le tableau `errors` de la sortie JSON. Renvoie ces erreurs, **telles quelles**, à
  la skill de l'étape pour correction, puis relance la validation.
  Trois tentatives maximum. Si la troisième échoue, arrête-toi, affiche les erreurs restantes et
  demande l'arbitrage humain — ne désactive jamais un check pour faire passer la validation.

## 7. Faire noter le livrable

Invoque la skill `aidlc-core:review` sur l'étape :

```
/aidlc-core:review <stage>
```

Elle délègue au sous-agent `reviewer`, qui note sur les 4 axes, écrit un `review.json` et appelle
`aidlc.py score`. N'écris ni le `review.json` ni `.aidlc/maturity.json` toi-même : un hook
`PreToolUse` refuse ces écritures, et c'est voulu.

## 8. Ouvrir la porte

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" gate <stage>
```

Lis la sortie JSON : `passed`, `blocking`, `next_stage`, `human_review_required`.

- **exit 0 (`passed: true`)** : annonce l'étape franchie et indique `next_stage`. Propose
  `/aidlc-core:run <next_stage>`. Ne l'enchaîne pas automatiquement sans accord de l'utilisateur.
- **exit 2 (`passed: false`)** : traite le tableau `blocking` :
  - verdict `rejected` ou score sous le seuil -> retour à l'étape 5 avec les `findings` du reviewer
    comme consignes de réécriture ;
  - `human_review_required: true` -> passe à l'étape 9 ;
  - validation en échec -> retour à l'étape 6.

## 9. Demander la revue humaine

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" review-request <stage>
```

Le script écrit `.aidlc/reviews/<stage>-<run>.template.json` et affiche les consignes sur stderr.
Relaie-les à l'utilisateur : quel fichier lire, où signer, comment justifier un refus.

**Arrête-toi ici.** C'est l'humain, pas toi, qui remplit et renomme le fichier de revue
(`<stage>-<run>.json`). Quand il te dit que c'est signé, relance l'étape 8.

## Conditions d'arrêt (récapitulatif)

Tu t'arrêtes et tu rends la main dès que : l'étape est `planned`, une entrée amont manque ou sa porte
est fermée, la validation échoue trois fois, une revue humaine est requise, ou la porte est franchie.
Tu ne contournes jamais une porte, tu ne modifies jamais un `checks.json` pour faire passer un
livrable, et tu ne signes jamais une revue humaine à la place de l'humain.
