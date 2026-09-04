---
type: Architecture Decision
title: ADR-0001 — Socle déterministe du harness agentique
description: Choix d'un socle vérifiable et déclaratif pour le harness — un seul script déterministe, validation déclarative, score non éditable par un agent.
tags: [architecture, decisions]
id: adr-0001
date: 2026-09-04
deciders: Steve Magne
decision_status: accepted
generated: { by: human:steve-magne, at: 2026-09-04T00:00:00Z }
stages: [design, build]
---

# ADR-0001 — Socle déterministe du harness agentique

## Contexte
Le harness fait produire chaque livrable du SDLC par une session agentique. Un agent est
non déterministe : il peut oublier une section, inventer une source, ou se noter lui-même
avec indulgence. Il faut donc un socle vérifiable qui ne dépende pas du modèle, sans pour
autant transformer le dépôt en projet logiciel à part entière qu'il faudrait maintenir.

## Décision
1. **Toute la logique déterministe tient dans un seul script**, `plugins/aidlc-core/scripts/aidlc.py`,
   bibliothèque standard Python uniquement. Pas de second script, pas de Makefile, pas de
   dépendance installée, pas de logique en shell dans les hooks.
2. **La validation d'un livrable est déclarative**, exprimée dans le `checks.json` de l'étape.
   Ajouter un critère ne demande pas d'écrire du Python : un architecte ou un QA lead édite
   son propre fichier de règles.
3. **Le score de maturité n'est pas éditable par un agent.** Un hook `PreToolUse` refuse toute
   écriture dans `.aidlc/maturity.json` et `.aidlc/reviews/`. Seuls `aidlc.py score` et l'humain
   y écrivent.
4. **Le passage d'une étape à la suivante est un code de sortie**, pas une appréciation :
   `aidlc.py gate <stage>` sort en 2 tant que la validation échoue, que le score est sous le
   seuil, ou que la revue humaine manque.

## Conséquences
- Le harness fonctionne sur un poste vierge disposant de Python 3 : rien à installer.
- Une nouvelle étape SDLC coûte un `checks.json` et un gabarit, pas du code.
- Le prix payé est un script unique qui grossit. Le seuil de découpage assumé est le moment où
  deux sous-commandes ne partagent plus aucune fonction : jusque-là, un fichier reste plus
  simple à lire qu'un paquet.
- Un agent ne peut pas contourner le garde-fou d'intégrité par une écriture directe, mais il
  pourrait le contourner via un `Bash` non couvert par le hook. Le jour où cela se produit,
  la parade est d'étendre le matcher, pas de durcir le script.

## Alternatives écartées
- **Un script par vérification** : multiplie les chemins à maintenir dans `hooks.json` et dans
  les `SKILL.md`, pour aucun gain de lisibilité.
- **Un framework de test** (pytest et consorts) : introduit une dépendance et une étape
  d'installation pour un usage limité à un seul auto-test.
- **Laisser l'agent reviewer écrire directement son score** : supprime la seule garantie
  d'intégrité de la boucle de maturité.
