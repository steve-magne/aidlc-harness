---
type: Architecture Decision
title: ADR-0006 — Ce que la note de maturité mesure, et sur quoi elle porte
description: La note est attachée au contenu qu'elle a jugé et non à un nom de fichier ; le plancher par axe ne juge que le livrable, l'échelle est ordinale, et l'autonomie acquise n'exige plus de signature sur les runs qu'elle dispense.
tags: [architecture, decisions, revue, maturite, gouvernance, autonomie]
id: adr-0006
date: 2026-09-06
deciders: Steve Magne
decision_status: accepted
stages: [plan, design, build, test, deploy, maintain]
generated: { by: human:steve-magne, at: 2026-09-06T00:00:00Z }
---

# ADR-0006 — Ce que la note mesure, et sur quoi elle porte

## Contexte

L'ADR-0005 a fixé **qui** note (le noyau), **qui** lit la note (l'orchestrateur) et **ce que**
l'équipe décentralise (la rubrique). Restait ce que la note mesure exactement. Une relecture de la
définition a montré quatre écarts entre ce que la documentation affirme et ce que le moteur tient.

1. **La note ne portait sur rien de vérifiable.** L'ADR-0003 fige l'empreinte des entrées amont
   avec le run, mais pas celle du livrable noté. Un fichier réécrit après sa revue franchissait la
   porte sur la note — et sur la signature humaine — d'une version disparue. `validate` ne voit
   que la forme : un livrable entièrement récrit repasse ses `checks` sans difficulté.
2. **Le mode autonome s'annulait de lui-même.** L'autonomie exigeait une revue humaine approuvée
   sur chacun des trois derniers runs. Un run produit en mode autonome n'en a pas — c'est sa
   définition. Dès le premier run qui en bénéficiait, la fenêtre glissante contenait un run non
   signé et l'étape repassait sous surveillance. L'autonomie durait exactement un run.
3. **Le plancher par axe fermait une porte sans issue.** `autonomy` mesure le coût de production
   déjà payé. Un livrable irréprochable produit avec des reprises était rejeté, et la seule
   correction offerte à l'agent — moins se corriger — est l'inverse du comportement recherché.
4. **L'échelle n'avait pas les graduations qu'elle documente.** La grille définit six niveaux
   ancrés ; le moteur acceptait n'importe quel réel de 0 à 5. La règle « des entiers » vivait dans
   la skill de revue, c'est-à-dire dans un prompt.

## Décision

**Une note porte sur un contenu, pas sur un nom de fichier.** Le run fige l'empreinte du livrable
noté (`runs[].deliverable`) ; `gate` et `status` rouvrent la porte quand elle diverge
(`stale_deliverable`), symétriquement au `stale_inputs` de l'ADR-0003.

**Un run produit en mode autonome n'attend pas de signature.** Il porte `supervised: false` ;
`compute_autonomy` n'exige de revue approuvée que sur les runs produits sous surveillance.

**Le plancher par axe ne juge que le livrable** — `completeness`, `precision`, `traceability`.
`autonomy` reste notée et pèse un quart de la moyenne, mais ne déclenche plus de rejet couperet.

**Une note est un entier.** `score` refuse une note fractionnaire.

## Justification

**Pourquoi l'empreinte du livrable.** C'est le même mode de panne que l'ADR-0003, du côté qui
était resté ouvert. Une porte de qualité qui laisse passer un fichier sur la note d'un autre
fichier ne mesure rien ; et le trou est plus grave en mode autonome, où plus aucun humain ne
regarde. Le coût est nul : l'empreinte, la comparaison et l'affichage existaient déjà.

**Pourquoi exempter les runs autonomes de signature.** Le mode autonome supprime l'attente de la
signature humaine ; en faire ensuite une condition de son maintien est contradictoire. La
constance reste vérifiée sur ce qui est vérifiable sans humain : le verdict et la note de chaque
run de la fenêtre. Un run autonome sous le seuil casse toujours la série.

**Pourquoi `autonomy` échappe au plancher.** Un plancher n'a de sens que si l'agent dispose d'une
action de sortie. Les trois axes du livrable en ont une : réécrire le fichier. Le coût de
production, lui, est déjà payé au moment de la note ; aucune reprise ne le rattrape, et une reprise
supplémentaire l'aggrave. S'ajoute la qualité de la mesure : `improve --stage` agrège tous les
journaux de l'étape sans fenêtre par run, ce qui fait de `autonomy` l'axe le plus bruité de la
grille — le dernier sur lequel poser un couperet. Le levier d'autonomie du harnais est ailleurs, et
il est plus juste : la série de runs consécutifs (`consecutive_runs_to_autonomy`).

**Pourquoi les entiers.** L'échelle est ordinale : chaque cran porte un sens écrit, aucun n'est
défini entre deux crans. Une demi-note ne sert qu'à négocier le franchissement du plancher par le
haut. Et l'argument de l'ADR-0005 s'applique tel quel : une règle qui doit tenir indépendamment du
modèle qui la lit n'a pas sa place dans un prompt.

## Alternatives écartées

* **Pondérer les axes** (donner plus de poids à la traçabilité, qui protège l'aval). Écarté : le
  plancher par axe traite déjà le cas qui motivait la pondération, et des poids rendraient les
  notes historiques incomparables pour un gain de discrimination nul.
* **Sortir `autonomy` de la moyenne** et n'en faire qu'un indicateur. Écarté : le coût de
  production est un objectif du harnais, et le retirer de la moyenne recalibrerait le seuil pour
  toutes les étapes, donc invaliderait la comparaison entre runs passés et futurs.
* **Fenêtrer `improve` par run** pour dé-bruiter `autonomy`. Écarté pour l'instant : la corrélation
  journaux ↔ run par horodatage est faisable mais coûte plus que le problème qu'elle résout, dès
  lors que l'axe n'est plus un couperet. La limite est documentée (ARCHITECTURE §5.5).
* **Périmer la note à la moindre relecture** (empreinte des `checks.json` et de la rubrique).
  Écarté : durcir un contrat périmerait tous les runs de l'étape en une fois, et le ratchet couvre
  déjà le risque que ce contrat s'assouplisse.

## Conséquences

* Une retouche du livrable après sa revue, même mineure, redemande une note : `gate` bloque avec
  « Livrable modifié depuis la revue » et `status` remet l'étape à faire.
* Une étape qui a gagné son autonomie la conserve tant que ses runs restent acceptés au-dessus du
  seuil ; elle la perd sur la note, plus sur une signature qu'on ne lui demande pas.
* Un livrable irréprochable produit à grand renfort de reprises passe la porte, et son coût reste
  lisible dans `improve` (`axis_means`, `weakest_axes`) et dans la série d'autonomie.
* Un reviewer qui rend `2.5` reçoit une erreur explicite plutôt qu'un enregistrement silencieux.
* Compatibilité ascendante : un run antérieur sans `deliverable` ne périme rien, un run sans
  `supervised` est lu comme supervisé — même geste que l'ADR-0003 pour `inputs`.
