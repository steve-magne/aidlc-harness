---
name: review
description: Faire noter un livrable par l'agent reviewer sur la grille de maturité (completeness, precision, traceability, autonomy) et enregistrer le score. À utiliser quand un livrable vient d'être écrit ou modifié et qu'on veut savoir s'il est acceptable, ou quand on demande d'évaluer, noter ou auditer une étape.
argument-hint: "[stage] — id d'étape ; vide = étape du dernier livrable modifié"
---

# Revue de maturité d'un livrable

## Conventions

Le script unique vit dans le plugin `aidlc-core` (`${CLAUDE_PLUGIN_ROOT}`) ; les livrables, les
logs et `.aidlc/` sont dans le projet consommateur (`$CLAUDE_PROJECT_DIR`). Le pipeline se lit dans
`${CLAUDE_PLUGIN_ROOT}/pipeline.json`, les contrats dans `${CLAUDE_PLUGIN_ROOT}/checks/<stage>.json`.

Le fichier de revue de travail va dans `.aidlc/tmp/` (scratch, gitignoré). **Jamais** dans
`.aidlc/reviews/` ni dans `.aidlc/maturity.json` : ces chemins sont réservés à l'humain et au script,
et un hook `PreToolUse` refuse l'écriture d'un agent.

## 1. Résoudre l'étape et le livrable

- Argument fourni -> c'est l'id d'étape.
- Sans argument -> `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status --json` et prends
  l'étape dont
  le livrable existe et n'a pas encore de score pour ce run.
- Lis l'entrée de l'étape dans `${CLAUDE_PLUGIN_ROOT}/pipeline.json` : `deliverable`, `inputs`,
  `checks`, `human_role`.
- Si le livrable n'existe pas : dis-le et arrête-toi. On ne note pas un fichier absent (ce serait un
  score de 0 sans valeur diagnostique). Propose `/aidlc-core:run <stage>`.

## 2. Passer la validation déterministe d'abord

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" validate <stage> --json
```

- **exit 1** : ne mobilise pas le reviewer. Affiche les `errors` et renvoie l'utilisateur vers
  `/aidlc-core:run <stage>` pour corriger. Faire noter un livrable qui ne passe même pas la forme
  gaspille un tour et pollue l'historique de maturité.
- **exit 0** : continue, et **transmets les `warnings`** au reviewer : ce sont des pistes de
  reproche légitimes.

## 3. Déléguer au reviewer

Invoque le sous-agent `reviewer` (agent `aidlc-core:reviewer`) avec, dans son prompt :

- le chemin du livrable et son contenu intégral ;
- les chemins et le contenu des `inputs` de l'étape (indispensable pour noter la traçabilité) ;
- le contrat de l'étape (`${CLAUDE_PLUGIN_ROOT}/checks/<stage>.json`) et les `warnings` de la
  validation ;
- le contexte de `knowledge/index.json` (via le sous-agent `librarian` si l'étape en dépend) ;
- le nombre de tours et d'allers-retours humains de la session, extraits des logs :
  `.aidlc/logs/<session_id>.jsonl` — c'est la matière de l'axe `autonomy` ;
- la consigne explicite : **chaque note doit être justifiée par une citation du livrable**.

Grille imposée, 0 à 5 par axe :
`0` absent · `1` brouillon · `2` incomplet · `3` acceptable avec réserves · `4` conforme · `5` exemplaire.

Axes : `completeness` (sections utiles présentes et remplies), `precision` (testable, non ambigu,
chiffré), `traceability` (cite ses entrées et les sources de vérité de `knowledge/`),
`autonomy` (peu d'allers-retours humains dans les logs).

## 4. Vérifier le fichier de revue

Le reviewer écrit `.aidlc/tmp/review-<stage>.json`. Avant d'aller plus loin, contrôle qu'il contient :

```json
{"stage":"<id>","scores":{"completeness":0,"precision":0,"traceability":0,"autonomy":0},
 "overall":0.0,"verdict":"accepted","findings":[],"recommendations":[]}
```

- Les quatre axes sont présents et entiers entre 0 et 5.
- `verdict` vaut exactement `accepted` ou `rejected`.
- Chaque entrée de `findings` cite un extrait du livrable. Une note basse sans citation est une
  note non justifiée : renvoie le reviewer la compléter.
- Ne corrige pas les notes toi-même. Tu vérifies la forme, pas le jugement.

## 5. Enregistrer le score

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" score <stage> --file .aidlc/tmp/review-<stage>.json
```

Le script **recalcule** `overall` comme la moyenne des quatre axes (arrondie à 0,1) et ignore la
valeur fournie par le reviewer : c'est normal, ne t'en étonne pas et ne cherche pas à la corriger en
amont. Il ajoute le run à `.aidlc/maturity.json`.

## 6. Restituer et conclure

Affiche à l'utilisateur : les quatre notes, le `overall` recalculé, le verdict, les `findings` et les
`recommendations`.

Puis :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" gate <stage>
```

- **exit 0** : étape franchie, annonce `next_stage`.
- **exit 2** : énumère le tableau `blocking`. Si `human_review_required` est `true`, lance
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" review-request <stage>` et relaie les
  consignes à
  l'humain désigné par `human_role`. Si le verdict est `rejected`, propose `/aidlc-core:run <stage>`
  avec les `findings` en consignes de réécriture.

## Conditions d'arrêt

Une revue = un score enregistré. Tu ne relances pas le reviewer pour obtenir une meilleure note, tu
ne modifies pas le livrable pendant la revue (ce serait juge et partie), et tu n'écris jamais dans
`.aidlc/maturity.json` ni dans `.aidlc/reviews/`.
