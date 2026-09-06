---
type: Architecture Decision
title: ADR-0009 — L'initiative est une unité de travail, le workflow se compose, le feedback remonte
description: Un projet mène plusieurs idées dans le temps sans que la seconde écrase la première ; composer la chaîne devient une commande outillée plutôt qu'une édition JSON ; le contrat absent ferme la porte et l'approbation motivée alimente la boucle d'amélioration.
tags: [architecture, decisions, initiative, workflow, feedback, gouvernance]
id: adr-0009
date: 2026-09-06
deciders: Steve Magne
decision_status: accepted
stages: [plan, design, build, test, deploy, maintain]
generated: { by: human:steve-magne, at: 2026-09-06T00:00:00Z }
---

# ADR-0009 — L'initiative est une unité de travail, le workflow se compose, le feedback remonte

## Contexte

Le harnais tenait sa promesse pour **une** idée traversant **une** chaîne déjà branchée. Un
parcours rejoué de bout en bout sur un projet consommateur — amorçage, livrable, validation,
note, signature, étape aval, puis branchement d'un agent maison par `AIDLC_AGENT_PATH` — a fait
apparaître six écarts entre ce que le harnais promet et ce qu'il tenait.

**Une seule idée par projet.** `produces` est un chemin fixe (`deliverables/plan/intent.md`) et
`.aidlc/` est global. La deuxième évolution d'un même produit écrasait les livrables, les scores
et les signatures de la première. Aucune notion d'initiative n'existait dans le moteur.

**Composer la chaîne n'était pas outillé.** « Indiquer les agents disponibles pour son workflow »
est le geste d'entrée du harnais, et il se faisait en éditant `aidlc.json` à la main. Le hook
`PreToolUse` interdit (à raison) à un agent d'écrire ce fichier, mais rien n'obligeait à le
laisser sans commande — c'est exactement le raisonnement qui avait produit `sign`.

**Un agent découvert mais non déclaré disparaissait en silence.** Le filtre de la liste blanche
avertissait dans un seul sens : un id déclaré qu'aucun manifeste ne porte ressortait, un agent
publié que personne n'avait branché ne ressortait pas. Pire, le tableau de bord l'annonçait
« prévu, plugin non installé — à publier par l'équipe X », alors que l'équipe X venait de le
publier.

**Une étape gouvernée sans contrat franchissait sa porte.** `validate` rendait `ok: true` avec
`checks_run: 0` sur un livrable de trois mots ; `contract_problems` savait le dire — `status`
l'affichait, `agents --strict` sortait 1 — mais `gate_stage` ne le consultait jamais. C'est le
cas type d'un agent d'équipe branché sans `checks.json`, et il contredisait la règle « un vert
muet est un mensonge ».

**Le feedback n'était capté que quand il refusait.** `sign` exige une justification dans les deux
sens, et celle de l'approbation était écrite puis jetée : seul `approved: false` alimentait
`improvement-queue.jsonl`. En régime établi, le signal majoritaire est « d'accord, mais… ».

**Le feedback ne remontait jamais à l'équipe qui maintient l'agent.** Scores, refus et motifs
restaient dans le projet consommateur. `selfscore` note le dépôt du harnais sur ses axes internes,
rien ne disait à l'équipe *Produit* que son agent `plan` plafonne en traçabilité chez trois
projets. Et `improve` ne savait corriger qu'un plugin — jamais conclure « il manque un maillon »
ou « cette étape ne sert à rien ».

## Décision

**L'initiative est une clé de `aidlc.json`.** `initiative: "reco-panier"` situe les livrables sous
`deliverables/reco-panier/` et l'état runtime sous `.aidlc/reco-panier/`. Le segment est inséré
par `util.scoped()` **au seul endroit où un chemin de manifeste entre dans le moteur** —
`registry._normalize` — si bien que la porte, le garde-fou, la validation et le tableau de bord
suivent sans le savoir. Un contrat déclare ses chemins nus comme le manifeste : `checks.scoped_checks`
les situe au chargement, sans quoi nommer une initiative rendrait incohérent le `checks.json` de
toute équipe qui cite une entrée amont. Le garde-fou porte sur **tout** `.aidlc/`, pas sur le seul
dossier courant : sinon, déclarer une initiative déverrouillerait les scores et les signatures de
la précédente — précisément la fraude qu'il existe pour empêcher. Sans la clé, rien ne change :
un projet qui ne mène qu'une idée reste à plat, et ne rien lui imposer est le comportement correct.

**`aidlc.py workflow` compose la chaîne.** Sans option, elle montre ce qui est branché, ce qui est
découvert et hors du workflow, et ce qui est déclaré mais introuvable. `--add`/`--remove` écrivent
la clé `agents`, `--initiative` nomme l'idée. Elle refuse un identifiant qu'aucun manifeste ne
porte, préserve les clés étrangères du fichier, avertit quand un retrait casse la chaîne
producteur → consommateur, et interdit un nom d'initiative qui collisionne avec une entrée
protégée de `.aidlc/`. La skill `/aidlc-core:setup` porte le dialogue autour de cette commande.

**Le filtre parle dans les deux sens.** `discover()` rend `undeclared` et avertit, en nommant la
commande qui branche l'agent ; le tableau de bord cesse d'annoncer « à publier » un plugin déjà
publié.

**Un contrat incohérent ferme la porte.** `gate_stage` consulte `contract_problems` avant tout le
reste et nomme l'équipe propriétaire : un livrable que rien ne validerait n'a pas de qualité à
mesurer.

**L'approbation motivée entre dans la boucle**, marquée `kind: reserve` : elle ne bloque rien, ne
se lit pas comme un refus, et donne au diagnostic le gisement régulier qui lui manquait.

**Le feedback se rend à qui maintient l'agent.** `aidlc.py feedback` agrège par agent — équipe,
manifeste, version, série de notes, axes faibles, refus et réserves. Et le diagnostic `improve`
porte une section `workflow` : maillons manquants, agents branchés jamais joués, agents publiés
non branchés, coût par étape en tentatives. Le harnais peut enfin proposer de faire évoluer le
workflow, pas seulement le plugin.

## Conséquences

Pour une équipe projet : une nouvelle idée se déclare (`workflow --initiative`) au lieu d'écraser
la précédente, et l'historique de l'ancienne reste lisible (`status --history`). Composer la chaîne
est une commande, pas une édition à la main. Un agent qu'une équipe vient de publier ne disparaît
plus en silence.

Pour une équipe qui publie un agent : publier sans `checks.json` ne passe plus la porte — le
contrat est le prix d'entrée dans une chaîne gouvernée. En retour, `feedback` lui rend ce que les
projets ont mesuré sur son agent.

Pour qui relit : la justification d'une approbation n'est plus perdue, et `review-request` donne la
commande `sign` au lieu d'envoyer copier un gabarit JSON.

Ce qui n'a pas changé : le noyau ne tient toujours aucune liste d'agents, l'état runtime n'est
écrit que par les scripts, et la signature humaine exige toujours un terminal.

Coût assumé : `scoped()` insère le segment après le premier segment `deliverables` et préfixe en
tête un chemin déclaré ailleurs — une règle positionnelle, documentée par un commentaire
`ponytail:`, à remplacer par un champ `deliverables_root` de manifeste si un jour elle gêne.
Changer d'initiative en cours de route ne déplace rien : les fichiers de la précédente restent où
ils sont, et la commande le dit.
