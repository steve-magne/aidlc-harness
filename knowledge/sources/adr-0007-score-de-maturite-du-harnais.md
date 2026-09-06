---
type: Architecture Decision
title: ADR-0007 — Le harnais est noté par la grille qu'il impose
description: La qualité du dépôt cesse d'être une collection de booléens verts : cinq axes déterministes agrégés en une note sur 5, avec le seuil et le plancher par axe des livrables, tenue en pre-commit et en CI.
tags: [architecture, decisions, qualite, tests, ci, gouvernance]
id: adr-0007
date: 2026-09-06
deciders: Steve Magne
decision_status: accepted
stages: [plan, design, build, test, deploy, maintain]
generated: { by: human:steve-magne, at: 2026-09-06T00:00:00Z }
---

# ADR-0007 — Le harnais est noté par la grille qu'il impose

## Contexte

Le harnais sait juger un livrable : validation déclarative, note sur cinq axes, seuil, plancher par
axe, porte qui rend un code de sortie. Sa propre évolution, elle, n'était défendue que par une
collection de portes indépendantes — `test`, `check-python`, `check-json`, `agents --strict`,
`check-okf`, `coverage` — qui répondent chacune par oui ou non. Trois manques en découlaient.

1. **« Ça passe » n'est pas une mesure.** Six booléens verts ne disent pas si le dépôt est plus mûr
   ou moins mûr qu'avant le diff. Rien ne compare deux états du dépôt, et rien ne dit ce qui s'est
   dégradé quand tout est vert sauf un.
2. **La règle 8 n'était tenue par aucun mécanisme.** « Un module de `_aidlc/` a son
   `tests/test_<module>.py` en face » vivait dans `CLAUDE.md`, c'est-à-dire dans un texte. Et le
   ratchet de couverture ne la rattrapait pas : il compare **module par module**, or un module neuf
   n'a pas de plancher — un module entier livré sans un seul test ne faisait rougir aucune porte.
3. **La première alerte arrivait après le push.** Aucune porte locale : le cycle de correction
   était le plus long possible, alors que toutes les portes sont du Python stdlib exécutable en
   quelques secondes sur le poste de l'auteur.

## Décision

Une sous-commande `aidlc.py selfscore` note le dépôt sur **cinq axes déterministes**, agrégés par
la moyenne : `hygiene` (règle 6), `contracts` (manifestes et contrats d'agents de ce dépôt),
`tests` (la suite passe, et chaque module a son test en face), `coverage` (le taux mesuré confronté
au plancher figé) et `knowledge` (conformance OKF des bundles).

Le barème est **celui des livrables** : 0 à 5, `maturity_threshold` et `min_axis_score` lus dans
`pipeline.json`, `exit 2` quand la moyenne n'atteint pas le seuil **ou** qu'un axe passe sous le
plancher. Un axe non applicable au projet courant vaut `n/a` et ne pèse pas dans la moyenne.

La passe est en **lecture seule** et ne mesure la suite qu'une fois. Elle est branchée à deux
endroits : le hook `.githooks/pre-commit` (activation explicite, une fois par clone) et la CI, où
elle remplace la porte `coverage`.

## Justification

**Pourquoi une note plutôt qu'une porte de plus.** Une note ordonne : elle est comparable d'un diff
au suivant, elle nomme l'axe qui a bougé, et elle rend lisible une dégradation partielle qu'un
booléen écrase. Surtout, le harnais impose cette grille aux équipes : lui appliquer un régime plus
faible que celui qu'il exige de ses agents serait la première contradiction que remarquerait un
auteur d'agent.

**Pourquoi intégralement déterministe.** Une porte qui s'exécute à chaque commit doit être
reproductible, gratuite et hors ligne : aucun juge, aucun prompt, aucun réseau. Deux invocations
sur le même arbre de fichiers rendent la même note. C'est aussi ce qui la rend opposable — on peut
discuter d'un jugement, pas d'un fichier qui ne compile pas.

**Pourquoi réutiliser le seuil et le plancher des livrables.** Un second jeu de seuils serait un
second endroit à maintenir, et le premier à diverger. Le plancher par axe apporte ici exactement ce
qu'il apporte aux livrables : quatre axes à 5 et un à 0 donnent une moyenne de 4,0, qui
franchirait un seuil de 4,0 alors qu'une famille de garanties est tombée à zéro.

**Pourquoi des axes binaires assumés.** Un dépôt dont un JSON ne parse pas n'a pas de qualité
partielle : il ne se charge pas, et les axes suivants deviennent incalculables. La graduation est
réservée à ce qui se dégrade graduellement — modules orphelins, bundles, taux de couverture.

**Pourquoi la lecture seule.** Si la note figeait le plancher de couverture, un `git commit`
laisserait derrière lui un `.aidlc/coverage.json` modifié *hors* du commit qu'il vient de valider.
Le rebase d'un plancher reste un geste humain explicite, visible au diff (`coverage --reset`).

## Alternatives écartées

* **Un ratchet sur la note elle-même** (« la note ne descend jamais »). Écarté : la note est déjà
  défendue par deux règles — le seuil et le plancher par axe — et un troisième fichier d'état figé
  ajouterait un geste de rebase sans refuser un seul cas que les deux premières laissent passer.
* **Un axe « placeholders » sur tout le dépôt** (règle 5). Écarté : les marqueurs cherchés sont
  cités par les règles mêmes qui les interdisent — `CLAUDE.md`, les `checks.json`, les gabarits —
  et le scan produirait plus de faux positifs que de constats. La règle est déjà tenue là où elle
  compte, sur les livrables, par `forbidden_patterns`.
* **Pondérer les axes.** Écarté pour la raison de l'ADR-0006 : des poids rendraient les notes
  incomparables d'une version du harnais à l'autre, pour un gain de discrimination nul.
* **Un framework de pre-commit** (le paquet `pre-commit`). Écarté : dépendance externe, règle 3. Un
  hook shell de dix lignes qui appelle le point d'entrée fait le même travail, et se lit.
* **Remplacer toutes les portes unitaires de la CI par la note.** Écarté : `check-python`,
  `agents --strict` et `check-okf` coûtent une seconde et **nomment** la panne dans le titre de
  l'étape de CI, avant que la porte agrégée ne la chiffre. Seule `coverage` est remplacée : la note
  fait la même mesure, en lecture seule.

## Conséquences

* Un module neuf sans test en face coûte un point immédiatement, avant même d'exister dans le
  plancher de couverture ; trois modules orphelins bloquent la porte.
* Le hook local est **opt-in** (`git config core.hooksPath .githooks`) et contournable
  (`git commit --no-verify`) : c'est un raccourci offert à l'auteur, pas une seconde autorité. La
  CI rattrape ce qui passe par là.
* Un projet consommateur peut lancer `selfscore` : les axes qui ne s'appliquent pas à lui — aucun
  bundle OKF, aucun agent local — sont affichés `n/a` plutôt que notés zéro.
* La note ne juge pas une décision de conception, seulement le fait que le dépôt tienne ses propres
  règles. Elle ne remplace ni la revue de code, ni la revue humaine d'un livrable.
