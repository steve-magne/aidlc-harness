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

## Conventions

Le script unique vit dans le plugin `aidlc-core` (`${CLAUDE_PLUGIN_ROOT}`) ; les journaux, scores
et refus qu'il agrège sont dans le projet consommateur (`$CLAUDE_PROJECT_DIR/.aidlc/`).

Corriger le harness, c'est corriger **sa source** (les plugins du dépôt auteur), jamais la copie
installée par Claude Code : une modification du cache serait écrasée à la prochaine mise à jour.
Si tu tournes depuis une copie installée (le plugin n'est pas dans un dépôt versionné), propose le
diff à l'humain pour application dans le dépôt d'origine, sans éditer le cache.

## 1. Collecter le diagnostic

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" improve --stage <stage>
```

Sans argument d'étape, lance-la sans `--stage` pour couvrir tout le pipeline.

Le script agrège `.aidlc/logs/*.jsonl`, `.aidlc/maturity.json` et `.aidlc/improvement-queue.jsonl`,
et sort un JSON : nombre de tours, outils les plus utilisés, erreurs de validation récurrentes, axes
de score les plus faibles, refus humains et leurs justifications. Depuis que le gate OKF bloque la
sortie de session, la section `okf` du diagnostic isole les refus du gate (`refusals` : session,
bundle, fichiers fautifs, corrélés aux sessions qui ont écrit) et porte une proposition de
correctif de frontmatter vérifiée en mémoire (`proposals`) pour les concepts encore fautifs.

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
| `traceability` bas | `must_reference_inputs` absent, ou le bundle `knowledge/` manque de concepts utiles (ou de `stages` sur ceux qui existent) | `checks.json`, `knowledge/` |
| `autonomy` bas, beaucoup de tours dans les logs | l'agent pose les questions dans le désordre, ou une par une alors qu'elles sont liées | `agents/<stage>-analyst.md`, `skills/<stage>/SKILL.md` |
| même erreur de `validate` à chaque run | le template ne guide pas vers ce que le check exige | `templates/` |
| refus humain répété sur le même motif | le critère du relecteur n'est ni dans les checks ni dans le SKILL.md | selon le motif |

Énonce la cause racine en une phrase, avec sa preuve : « la section *Contraintes* est vide dans les
3 derniers runs (maturity.json), le template ne propose aucun exemple, et `min_items_per_section`
ne la couvre pas ».

Si tu n'as pas de preuve, dis-le : « données insuffisantes, il faut N runs de plus ». Un diagnostic
inventé est pire qu'aucun diagnostic. En dessous de deux runs enregistrés, ne conclus pas.

## 3bis. Quand c'est le gate OKF qui a refusé

Le gate OKF de sortie (hook `Stop`, `check-okf --stop`) refuse l'arrêt d'une session interactive
dont le bundle `knowledge/` n'est pas conforme (en headless `claude -p`, il émet et enregistre le
refus sans bloquer — la porte dure y est la CI). Le refus est journalisé dans la file
(`kind: okf_stop`) ; le diagnostic le corrèle aux sessions fautives : chaque écriture dans un
bundle non conforme est journalisée par le hook `check-okf --touched` (session, fichier,
horodatage, dans `.aidlc/logs/`), donc `implicated` nomme la session qui a **écrit** le fichier,
pas celle qui a tenté de fermer.

1. Si `diag["okf"]["refusals"]` est vide, rien à faire pour ce bloc.
2. Pour chaque refus : lis `session_id` (celle qui a fermé) et `implicated` (fichiers + sessions
   auteures + horodatage), puis ouvre la session fautive dans `.aidlc/logs/` pour comprendre
   *pourquoi* le concept a été écrit sans frontmatter (recette oubliée ? template absent ?).
3. Ouvre le concept fautif. S'il est encore non conforme, `diag["okf"]["proposals"]` porte un
   correctif déterministe (`edits` : ligne d'insertion + texte, `preview` : tête réparée).
   Présente-le avec le gabarit du bloc 4, `Fichier : knowledge/<concept>`. La `note` du script
   rappelle que le `type` par défaut (`Reference`) et le titre dérivé sont à confirmer.
4. Si le concept est déjà corrigé, ne propose rien : dis-le. Le sommaire `index.md`, lui, reçoit
   une proposition `index_entries` quand des concepts sont **orphelins** (présents dans le
   bundle, absents de la liste) : titre et description repris du frontmatter de chaque concept,
   entrées ajoutées en queue de liste — l'ordonnancement par sections reste manuel. `log.md` et
   les erreurs de forme (flux déséquilibrés) n'ont pas de correctif automatique — réparation
   manuelle.

Le correctif porte sur un **concept du bundle**, pas sur un livrable d'étape : la règle « jamais
le livrable » ne s'y applique pas — le bundle EST la source à corriger. L'accord humain explicite
reste exigé avant toute application.

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
  déjà noté — réécrire le livrable masquerait le problème sans le résoudre. Exception assumée : un
  concept `knowledge/` cassé (gate OKF) se corrige dans le bundle, avec accord (bloc 3bis).
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
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" --selftest
   ```
3. Rejoue la validation sur le livrable existant :
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" validate <stage> --json
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
