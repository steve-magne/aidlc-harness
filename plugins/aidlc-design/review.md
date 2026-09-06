# Rubrique de revue — étape Design

Ce fichier appartient à l'équipe **Architecture**. Il ne remplace pas la grille universelle du
reviewer (`aidlc-core`) : il dit ce que chaque axe veut dire **pour une conception cible**, et
quelles fautes de ce métier sont rédhibitoires. Le barème (0-5), le calcul de la note globale, le
plancher par axe et l'enregistrement restent au noyau — cette équipe ne note pas sa propre copie.

## `completeness` — ce que « complet » veut dire ici

- `## Options écartées` contient au moins une alternative **réellement envisageable**, avec le
  critère qui l'a fait perdre. Une option écartée fantoche (« ne rien faire ») vaut 0 sur cette
  section : elle simule l'arbitrage au lieu de le documenter.
- `## Capacités et dépendances SI` nomme les systèmes existants impactés, pas seulement les
  composants à construire. Une conception qui ignore l'existant est une conception de champ vierge.
- `## Risques et mitigations` porte, pour chaque risque, sa **mitigation** et le signal qui
  déclenchera cette mitigation. Un risque sans mitigation est une clause de style.

## `precision` — ce que « testable » veut dire ici

- Les exigences non fonctionnelles sont chiffrées **avec leur charge de référence** : un p95
  sans le débit auquel il est tenu ne veut rien dire.
- L'architecture cible désigne des composants nommés et leurs échanges, pas des boîtes génériques.
- Toute affirmation de capacité (« supporte la montée en charge ») sans budget chiffré plafonne
  l'axe à 2.

## `traceability` — ce que « tracé » veut dire ici

L'étape Design **consomme** `deliverables/plan/intent.md`. La traçabilité s'y juge durement :

- l'intention est citée **dans `## Contexte`** — le contrat l'impose (`required_input_section`),
  mais la citation doit être exploitée, pas décorative ;
- chaque décision d'architecture structurante se rattache à un critère d'acceptation ou à une
  contrainte de l'intention. Une décision qui ne sert aucun besoin exprimé est une préférence
  d'architecte : la signaler en `findings` ;
- **le périmètre du plan est une frontière**, pas une suggestion. Un élément que le plan a mis
  hors périmètre et que la conception réintroduit sans l'assumer explicitement est une faute de
  traçabilité, pas un oubli : plafonner à 1.

## `autonomy`

Grille universelle. Nuance propre à l'étape : signaler une lacune de l'intention amont plutôt que
de produire une conception bancale sur un besoin flou vaut **5** — c'est le comportement attendu
d'un architecte, pas un échec de production.

## Fautes rédhibitoires (verdict `rejected`, quelle que soit la moyenne)

- Une exigence non fonctionnelle reprise du plan sans être instruite (recopiée telle quelle).
- Un choix d'architecture présenté sans alternative, alors que le domaine en offre de connues.
- Une dépendance à un système tiers sans que son propriétaire ni son contrat d'interface soient
  nommés.
