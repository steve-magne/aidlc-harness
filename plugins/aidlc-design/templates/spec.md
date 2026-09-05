---
stage: design
version: 1
status: draft
author: <à remplir : prénom et nom de l'architecte d'entreprise>
date: <à remplir : AAAA-MM-JJ>
---

# Conception — <à remplir : titre court de l'initiative, repris de l'intention>

<!-- Squelette du livrable de l'étape Design. Chaque marqueur `<à remplir : ... >` doit être remplacé par du contenu réel, puis ce commentaire supprimé : `aidlc.py validate design` refuse tout marqueur restant. -->

## Contexte

<à remplir : ce que demande l'intention produit `deliverables/plan/intent.md` — le chemin doit être cité ici, pas seulement ailleurs — le problème retenu, le bénéfice visé, et au moins un fait mesuré chiffré avec sa source qui justifie de concevoir maintenant>

Personas et volumétrie retenus : <à remplir : les utilisateurs impactés repris de l'intention, avec leur volume>

## Capacités et dépendances SI

- <à remplir : capacité métier impactée — application ou domaine qui la porte — nature de l'impact (création, extension, remplacement)>
- <à remplir : dépendance amont ou aval — système, équipe propriétaire, contrat d'interface, disponibilité attendue>

## Architecture cible

<à remplir : la conception retenue en cinq à quinze phrases — composants, flux de données, points d'intégration, où vit la donnée de référence. Décrire ce qui est décidé, pas ce qui est envisagé>

Décision structurante : <à remplir : le choix qui coûte le plus cher à revenir en arrière, et ce qui le justifie>

## Options écartées

- <à remplir : option envisagée — pourquoi elle a été écartée, avec le critère qui a tranché (coût, délai, dépendance, risque)>

## Exigences non fonctionnelles

- <à remplir : performance — seuil chiffré et unité, par exemple « p95 sous 300 ms sur le parcours de saisie »>
- <à remplir : disponibilité ou résilience — objectif chiffré, fenêtre de mesure>
- <à remplir : sécurité, confidentialité ou conformité — exigence et texte de référence>

## Risques et mitigations

- <à remplir : risque — probabilité et impact — mitigation retenue et qui la porte>
- <à remplir : deuxième risque, y compris organisationnel (compétence, dépendance à une équipe, délai fournisseur)>

## Critères d'acceptation

- <à remplir : critère testable — étant donné <situation>, quand <action>, alors <résultat observable et chiffré>>
- <à remplir : deuxième critère, portant sur une exigence non fonctionnelle chiffrée>
- <à remplir : troisième critère, couvrant un cas d'erreur, une limite ou un mode dégradé>

## Hors périmètre

- <à remplir : ce que cette conception ne traite pas — reprendre les exclusions de l'intention, elles restent exclues>
- <à remplir : ce qui est reporté à une itération ultérieure, et à quelle échéance>

## Sources et références

- `deliverables/plan/intent.md` — <à remplir : version et date de l'intention sur laquelle cette conception est bâtie>
- <à remplir : entretien — nom, rôle, date>
- <à remplir : document de référence du dossier knowledge/, avec son chemin>
