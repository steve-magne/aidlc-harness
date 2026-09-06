---
type: Architecture Decision
title: ADR-0005 — Le score de maturité revient à l'orchestrateur, la rubrique appartient à l'équipe
description: La note d'un livrable est enregistrée par le noyau et lue par l'orchestrateur, jamais rendue à l'agent noté ; ce que l'équipe décentralise, c'est la grille de lecture de son métier, pas le mètre ni la porte.
tags: [architecture, decisions, revue, maturite, gouvernance]
id: adr-0005
date: 2026-09-05
deciders: Steve Magne
decision_status: accepted
stages: [plan, design, build, test, deploy, maintain]
generated: { by: human:steve-magne, at: 2026-09-05T00:00:00Z }
---

# ADR-0005 — Le score revient à l'orchestrateur, la rubrique appartient à l'équipe

## Contexte

Le harnais dispose d'un reviewer (`aidlc-core`) qui note chaque livrable sur quatre axes, rend un
verdict et enregistre le run via `aidlc.py score`. Deux questions restaient ouvertes :

1. **À qui le score revient-il ?** À l'orchestrateur, qui décide de la suite, ou au plugin de
   l'agent noté, qui saurait alors se corriger lui-même ?
2. **La revue peut-elle être générique ?** Un `intent.md` produit et une `spec.md` d'architecture
   étaient jusqu'ici notés avec la même grille, alors que le contrat déterministe (`checks.json`)
   est décentralisé par équipe depuis l'ADR-0002. Le déterministe était décentralisé, le
   qualitatif non.

Un troisième constat a précipité la décision : la règle « aucun axe en dessous de 3 » n'existait
que dans le **prompt** du reviewer. Un livrable noté `{5, 5, 5, 1}` obtenait 4,0 de moyenne et
franchissait la porte avec un verdict `accepted`.

## Décision

**Le score revient à l'orchestrateur. Il n'est jamais rendu à l'agent noté.**

Ce qui se décentralise vers l'équipe est la **rubrique de revue** (champ `review` du manifeste) :
ce que chaque axe veut dire pour son métier, et quelles fautes y sont rédhibitoires. Le barème,
les quatre axes, le calcul de la note, le seuil, le plancher par axe, l'enregistrement et la porte
restent au noyau.

Le plancher par axe (`min_axis_score`, 3 par défaut) devient une règle du moteur : `score` force
`rejected` dès qu'un axe passe dessous, quel que soit le verdict rendu.

## Justification

**Pourquoi pas au plugin noté.** Trois raisons, dans l'ordre de gravité :

1. **Juge et partie.** Un agent qui reçoit sa propre note et décide s'il repasse la porte peut
   toujours décider qu'il l'a franchie. Tout le dispositif anti-dérive du harnais existe pour
   l'empêcher — le hook `guard` refuse déjà qu'un agent écrive `.aidlc/maturity.json`, le holdout
   interdit qu'un livrable cite son propre contrat, le ratchet interdit d'abaisser une exigence.
   Rendre le score au plugin défait ces trois mécanismes d'un coup.
2. **La porte est une décision de gouvernance, pas une décision d'équipe.** `gate` combine quatre
   conditions dont trois sont hors du champ de l'agent : la revue humaine, la fraîcheur des
   entrées amont, le seuil de l'entreprise. Une équipe ne peut pas se déclarer franchie.
3. **Seul l'orchestrateur voit la chaîne.** Un score de traçabilité qui s'effondre en Design
   désigne souvent une **intention amont floue**, pas un architecte négligent. Le plugin Design ne
   voit pas ce lien ; l'orchestrateur, qui lit `status` et `improve`, le voit.

**Pourquoi la rubrique, elle, doit être décentralisée.** L'équipe AppSec sait ce qu'est une revue
de sécurité sérieuse ; le noyau ne le saura jamais et ne doit pas essayer de l'apprendre — c'est
exactement l'argument de l'ADR-0002 pour le contrat déterministe. Une rubrique **précise et
durcit** la grille universelle ; elle ne peut ni changer le barème, ni relever un plafond, ni
contourner le plancher. Une équipe affine la lecture de son métier, elle n'assouplit pas le mètre
qui la juge.

**Pourquoi le plancher passe dans le moteur.** Une consigne de prompt dépend du modèle qui la lit.
Le harnais applique déjà ce principe partout ailleurs : ce qui doit tenir indépendamment des
prompts est du code ou une règle déclarative. Le plancher par axe ne faisait pas exception, il
était simplement resté au mauvais endroit.

## Alternatives écartées

* **Rendre le score au plugin producteur, pour qu'il s'auto-corrige.** Écarté : juge et partie
  (ci-dessus). La boucle de correction existe déjà et passe par l'orchestrateur, qui renvoie les
  `findings` du reviewer à la skill de l'étape — l'agent reçoit donc bien le **retour**, sans
  jamais tenir le **verdict**.
* **Un reviewer par équipe, publié dans son plugin.** Écarté pour la même raison, sous une autre
  forme : une équipe qui écrit à la fois son livrable et l'agent qui le note choisit sa propre
  note. La spécificité métier passe par la rubrique — une donnée que le reviewer du noyau lit —
  et non par un juge que l'équipe contrôle.
* **Un axe supplémentaire par étape (grille extensible).** Écarté : les scores ne seraient plus
  comparables entre étapes, `improve` ne pourrait plus désigner l'axe faible d'une chaîne, et
  l'autonomie (moyenne glissante sur quatre axes fixes) perdrait son sens.
* **Laisser le plancher dans le prompt et faire confiance au reviewer.** Écarté : c'est
  précisément le mode de défaillance que le harnais documente comme inacceptable ailleurs.

## Conséquences

* Le reviewer charge la rubrique de l'équipe avant de noter, et nomme dans ses `findings` le
  critère de rubrique qu'il applique : l'auteur peut remonter à la règle qu'on lui oppose.
* Une rubrique déclarée mais absente est signalée par `agents` (`[contrat]`) — sans quoi le
  reviewer retomberait silencieusement sur la grille universelle.
* `scaffold` génère une rubrique avec l'agent : aucune étape ne naît sans.
* Un run enregistré porte `weak_axes` ; `gate` bloque en nommant l'axe effondré plutôt qu'en
  affichant un verdict sans cause.
* Des runs antérieurs notés avant cette décision restent lisibles : `weak_axes` absent ne périme
  rien, comme l'empreinte des entrées de l'ADR-0003.
