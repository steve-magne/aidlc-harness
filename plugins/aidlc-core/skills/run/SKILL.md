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
- **Le harnais** (plugin `aidlc-core`) : le script unique et le pipeline y sont installés.
  `${CLAUDE_PLUGIN_ROOT}` résout le dossier du plugin ; le pipeline se lit dans
  `${CLAUDE_PLUGIN_ROOT}/pipeline.json` et les contrats déterministes dans
  `${CLAUDE_PLUGIN_ROOT}/checks/<stage>.json`.

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

- Si l'utilisateur a fourni un argument, c'est l'id d'étape à traiter. Vérifie qu'il existe dans
  `${CLAUDE_PLUGIN_ROOT}/pipeline.json` ; sinon liste les ids valides et arrête-toi.
- Sans argument, prends la première étape du tableau `stages` de ce fichier dont la porte n'est
  pas franchie (voir le champ correspondant dans la sortie de `status --json`).
- Si toutes les étapes sont franchies, dis-le et arrête-toi. Ne relance rien « pour voir ».

## 2. Vérifier que l'étape est implémentée

Lis l'entrée de l'étape dans `${CLAUDE_PLUGIN_ROOT}/pipeline.json`.

- `status` vaut `"planned"` -> le plugin n'existe pas encore. **Arrête-toi** et propose à
  l'utilisateur d'utiliser la skill `aidlc-core:new-stage` pour la concevoir puis la générer.
  Ne tente pas d'improviser le livrable sans plugin.
- `status` vaut `"implemented"` -> continue.

## 3. Vérifier les entrées amont

Pour chaque chemin listé dans `inputs` :

- Le fichier doit exister. S'il manque, l'étape amont n'est pas faite : dis quelle étape produire
  d'abord (`/aidlc-core:run <étape amont>`) et arrête-toi.
- Le fichier doit avoir passé sa propre porte. En cas de doute :
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" gate <étape amont>` (exit 0 = franchie,
  exit 2 = bloquée).
  Une porte amont fermée est bloquante : ne construis pas sur du sable.

## 4. Charger le contexte

Délègue au sous-agent `librarian` la question : « quel contexte pour l'étape `<stage>` ? ».
Il lit `knowledge/index.json`, `knowledge/glossary.md` et les livrables amont, et te rend une
synthèse des sources de vérité à citer. Transmets cette synthèse à la skill de l'étape.

## 5. Produire le livrable

Invoque la skill déclarée dans le champ `skill` de l'entrée de l'étape (par exemple
`aidlc-plan:plan` pour `plan`) via l'outil Skill, en lui passant :

- le chemin du livrable attendu (`deliverable`) ;
- les chemins des `inputs` ;
- la synthèse du librarian.

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
