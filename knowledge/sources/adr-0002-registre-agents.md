---
type: Architecture Decision
title: ADR-0002 — Registre ouvert d'agents par manifeste
description: Remplacement du registre central d'étapes par un registre ouvert alimenté par les manifestes agent.json des plugins, pour qu'une équipe publie son agent sans modifier le noyau.
tags: [architecture, decisions, orchestration]
id: adr-0002
date: 2026-09-05
deciders: Steve Magne
decision_status: accepted
generated: { by: human:steve-magne, at: 2026-09-05T00:00:00Z }
stages: [design, build]
---

# ADR-0002 — Registre ouvert d'agents par manifeste

## Contexte
Le harnais orchestrait un cycle de vie **fermé** : `plugins/aidlc-core/pipeline.json` listait les
six étapes, dans un ordre positionnel (l'index dans le tableau), et le noyau gardait un miroir du
contrat de chacune (`plugins/aidlc-core/checks/<stage>.json`). Ajouter une étape imposait donc
d'écrire dans le noyau — `scaffold` modifiait `pipeline.json`, créait le miroir et inscrivait le
plugin au marketplace.

Le besoin d'entreprise est l'inverse : chaque direction possède son agent spécialisé
(architecture, sécurité, frontend, backend, QA), le développe et le maintient de façon autonome, et
l'orchestrateur doit l'utiliser **sans connaître son implémentation**. Un registre central fait de
l'orchestrateur un goulot d'étranglement organisationnel : aucune équipe ne peut publier sans une
modification du noyau, donc sans une release du harnais.

Il manquait par ailleurs toute notion d'équipe propriétaire, de capacité, de version et de
prérequis, et l'invocation était câblée au format Claude Code — rendant le modèle inutilisable
sous une autre plateforme.

## Décision
Le registre central est supprimé au profit d'un **registre ouvert par découverte**.

1. Chaque plugin d'agent porte un manifeste `agent.json` à sa racine. Champs obligatoires :
   `manifest_version`, `id`, `team`, `description`, `capabilities`, `invocation`. Optionnels :
   `version`, `produces`, `consumes`, `requires`, `checks`, `human_role`.
2. **Tout est neutre sauf `invocation`**, dict indexé par plateforme (`claude-code`, `codex`) :
   c'est là, et seulement là, que vit l'implémentation propre à une plateforme. Le contrat
   d'intégration en est ainsi séparé.
3. La présence de `produces` fait d'un agent une **étape gouvernée** (validation, notation, porte,
   ratchet) ; son absence en fait un agent **consultatif** (invocable, jamais noté). Un seul
   concept, un champ qui bascule.
4. L'ordre d'exécution se **dérive** de la chaîne producteur → consommateur (`produces` /
   `consumes`), par tri topologique. Aucun rang n'est déclaré nulle part.
5. Le contrat `checks.json` est résolu **relativement au manifeste**, donc lu dans le plugin de
   l'équipe. Le miroir du noyau disparaît.
6. `pipeline.json` ne porte plus que la gouvernance (seuils, watchdog) et `planned_stages`, une
   feuille de route consultative qui n'exécute rien.
7. La découverte suit trois sources par précédence : `AIDLC_AGENT_PATH` (le contrat documenté,
   portable et testable), les plugins du dépôt et du projet, puis les plugins installés par
   Claude Code — cette dernière source, fondée sur un fichier interne non documenté et absente
   sous Codex, n'est **jamais porteuse** : toute erreur y est un avertissement.

## Conséquences
Publier un agent ne modifie plus le noyau : `scaffold` n'écrit que dans le plugin généré et dans le
marketplace du dépôt. Une équipe peut développer son agent hors du dépôt et le déclarer par
`AIDLC_AGENT_PATH`. L'orchestrateur gagne une seconde boucle, `/aidlc-core:dispatch`, qui traite une
demande transverse en mobilisant les agents par capacité, et rend une synthèse attribuée nommément.

Un registre ouvert crée deux risques, tous deux traités :

- **Le mètre pourrait s'effacer.** Désinstaller un plugin ferait disparaître le plancher de qualité
  figé de son agent. Le ratchet traite désormais un plancher figé dont l'agent a quitté le registre
  comme une **violation** (exit 2), et non comme un silence. Le seul assouplissement légal reste
  `aidlc.py ratchet --reset <agent>`.
- **Le tableau de bord pourrait rétrécir en silence.** `status` affiche les trous : une entrée que
  plus aucun agent installé ne produit (`missing_producers`), et les étapes prévues dont le plugin
  n'est pas installé.

Le garde-fou d'écriture est étendu : le plugin d'un agent appartenant à une autre équipe, installé
hors du projet, est protégé au même titre que le noyau. Son manifeste est lu, jamais réécrit.

L'attribution d'un événement de journal à une étape cesse par ailleurs de reposer sur la prose.
`hookslog.guess_stage` reconnaissait l'identifiant d'une étape comme mot du prompt : « revois le
plan de charge » était étiqueté `stage=plan`, faussant `improve --stage` et le détecteur de
relances du watchdog. Un registre ouvert aggravait le défaut, les identifiants d'agents étant des
mots courants choisis par chaque équipe. Trois signaux réels le remplacent, par fiabilité
décroissante :

1. **le chemin de fichier que porte l'événement** — livrable exact d'un agent, sinon le répertoire
   de ce livrable (annexe, ou livrable pas encore créé) ;
2. **la dernière étape attribuée dans la même session** — continuité constatée, qui donne leur
   étape aux événements sans chemin (prompt, démarrage, arrêt) ; elle ne franchit pas les
   frontières de session ;
3. **l'étape courante du pipeline** — l'état réel, jamais le texte.

Aucune correspondance n'est plus cherchée dans du texte libre.
