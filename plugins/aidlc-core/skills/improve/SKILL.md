---
name: improve
description: Analyser les logs de sessions, l'historique de maturité et les refus humains pour diagnostiquer pourquoi une étape produit des livrables faibles, puis proposer un diff précis sur son SKILL.md, son template ou son checks.json. À utiliser quand une étape est refusée plusieurs fois, quand les scores stagnent, ou quand on demande d'améliorer le harness lui-même.
argument-hint: "[stage] — id d'étape à diagnostiquer ; vide = tout le pipeline"
---

# Boucle de self-improvement

Le harness apprend de ses échecs. Cette skill ferme la boucle : elle relie un **score faible** à ce
qui s'est réellement passé dans les **logs**, et aux **justifications de refus** écrites par les
humains — puis propose une correction sur les fichiers du plugin, jamais sur le livrable.

Règle absolue : **tu ne modifies rien sans accord explicite de l'utilisateur.** Cette skill produit
un diagnostic et une proposition de diff. L'application est un acte séparé, demandé à l'humain.

## 1. Collecter le diagnostic

Depuis la racine du projet :

```bash
python3 plugins/aidlc-core/scripts/aidlc.py improve --stage <stage>
```

Sans argument d'étape, lance-la sans `--stage` pour couvrir tout le pipeline.

Le script agrège `.aidlc/logs/*.jsonl`, `.aidlc/maturity.json` et `.aidlc/improvement-queue.jsonl`,
et sort un JSON : nombre de tours, outils les plus utilisés, erreurs de validation récurrentes, axes
de score les plus faibles, refus humains et leurs justifications.

**Le script ne fait que compter. L'analyse, c'est toi.** N'ajoute pas de traitement dans `aidlc.py`
pour ce que tu peux lire dans le JSON.

## 2. Lire les sources de première main

Le JSON agrégé oriente ; il ne remplace pas la lecture. Ouvre :

- `.aidlc/maturity.json` — la série des runs de l'étape : quel axe stagne, lequel se dégrade.
- `.aidlc/improvement-queue.jsonl` — les justifications de refus humain, mot pour mot. C'est la
  source la plus riche du dépôt : un humain a pris le temps d'écrire pourquoi il refusait.
- `.aidlc/logs/<session_id>.jsonl` — le déroulé des sessions faibles : combien de tours,
  combien d'allers-retours avec l'humain, quels outils, où ça a patiné.
- Le livrable refusé lui-même, et le `review.json` correspondant s'il est encore dans `.aidlc/tmp/`.

## 3. Corréler — du score faible à la cause racine

Pour chaque axe faible, remonte à la cause dans les logs et les refus. Grille de corrélation :

| Symptôme | Cause probable | Fichier à corriger |
|---|---|---|
| `completeness` bas, même section vide à chaque run | la section n'est pas dans les checks, ou le template ne dit pas quoi y mettre | `checks.json` (`required_sections`, `min_items_per_section`), `templates/` |
| `precision` bas, findings du type « vague », « non testable » | le SKILL.md ne demande pas de chiffres ni de critères observables | `skills/<stage>/SKILL.md`, `required_patterns` |
| `traceability` bas | `must_reference_inputs` absent, ou `knowledge/index.json` incomplet | `checks.json`, `knowledge/index.json` |
| `autonomy` bas, beaucoup de tours dans les logs | l'agent pose les questions dans le désordre, ou une par une alors qu'elles sont liées | `agents/<stage>-analyst.md`, `skills/<stage>/SKILL.md` |
| même erreur de `validate` à chaque run | le template ne guide pas vers ce que le check exige | `templates/` |
| refus humain répété sur le même motif | le critère du relecteur n'est ni dans les checks ni dans le SKILL.md | selon le motif |

Énonce la cause racine en une phrase, avec sa preuve : « la section *Contraintes* est vide dans les
3 derniers runs (maturity.json), le template ne propose aucun exemple, et `min_items_per_section`
ne la couvre pas ».

Si tu n'as pas de preuve, dis-le : « données insuffisantes, il faut N runs de plus ». Un diagnostic
inventé est pire qu'aucun diagnostic. En dessous de deux runs enregistrés, ne conclus pas.

## 4. Proposer un diff — précis, minimal, unique

Pour chaque cause racine, une seule proposition. Présente-la ainsi :

```
Cause    : <une phrase, avec la preuve chiffrée>
Fichier  : plugins/aidlc-<stage>/checks.json
Avant    : "min_items_per_section": {"## Critères d'acceptation": 3}
Après    : "min_items_per_section": {"## Critères d'acceptation": 3, "## Contraintes": 2}
Effet    : le livrable est rejeté tant que les contraintes ne sont pas énumérées
Risque   : les 2 livrables existants ne passeront plus la validation et devront être complétés
```

Règles de proposition :

- **Trois propositions maximum**, classées par impact. Un correctif appliqué et mesuré vaut mieux
  que dix suggestions.
- On corrige le **harness** (`skills/`, `templates/`, `checks.json`, `agents/`), jamais le livrable
  déjà noté — réécrire le livrable masquerait le problème sans le résoudre.
- On ne **relâche jamais** un check pour faire monter un score. Si un check est jugé trop strict par
  l'humain, c'est lui qui le dit, et sa justification est citée.
- On ne touche ni à `maturity_threshold` ni à `consecutive_runs_to_autonomy` : baisser la barre n'est
  pas une amélioration.
- Aucun nouveau script. Toute logique déterministe reste dans `aidlc.py`.

## 5. Demander l'accord — et s'arrêter

Pose la question explicitement : « Est-ce que j'applique la proposition 1, 2, 3, ou aucune ? »

**Tant que la réponse n'est pas un accord clair, tu n'édites aucun fichier.** Pas de « je prépare
juste le changement ». Attendre est le comportement correct.

## 6. Appliquer, si et seulement si l'accord est donné

1. Applique le diff, exactement tel qu'il a été présenté — rien de plus.
2. Vérifie la forme :
   ```bash
   python3 -c "import json;json.load(open('plugins/aidlc-<stage>/checks.json'))" && echo "JSON OK"
   python3 plugins/aidlc-core/scripts/aidlc.py --selftest
   ```
3. Rejoue la validation sur le livrable existant :
   ```bash
   python3 plugins/aidlc-core/scripts/aidlc.py validate <stage> --json
   ```
   Un échec ici est **attendu et sain** si tu viens de durcir un check : il montre que la règle mord.
   Explique-le plutôt que de revenir en arrière.
4. Consigne ce qui a été changé et pourquoi, dans ta réponse à l'utilisateur.

## 7. Mesurer au prochain tour

Rappelle à l'utilisateur que l'effet se lit au run suivant : `/aidlc-core:run <stage>` puis
`/aidlc-core:status`. Si l'axe visé ne remonte pas après deux runs, la cause racine était mauvaise :
reviens au bloc 3 avec les nouvelles données, n'empile pas un second correctif sur le premier.

## Conditions d'arrêt

Tu t'arrêtes si : moins de deux runs sont enregistrés pour l'étape, aucune corrélation n'est étayée
par une preuve, ou l'utilisateur ne donne pas son accord. Tu ne modifies jamais `.aidlc/maturity.json`
ni `.aidlc/reviews/` — un hook `PreToolUse` les protège, et réécrire l'historique des scores viderait
de son sens toute cette boucle.
