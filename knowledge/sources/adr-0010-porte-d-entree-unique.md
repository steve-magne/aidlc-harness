---
type: Architecture Decision
title: ADR-0010 — Une porte d'entrée, un plugin à installer, un processus par événement
description: Le harnais cesse d'exposer son CLI comme interface : une skill routeur et onze verbes remplacent huit skills concurrentes, le marketplace distingue le plugin à installer des exemples à copier, les six passes d'un même hook fusionnent en un processus, et les portes du dépôt sortent du plugin.
tags: [architecture, decisions, ux, skills, hooks, plugins]
id: adr-0010
date: 2026-09-07
deciders: Steve Magne
decision_status: accepted
stages: [plan, design, build, test, deploy, maintain]
generated: { by: human:steve-magne, at: 2026-09-07T00:00:00Z }
cites: [adr-0001, adr-0002, adr-0007]
---
# ADR-0010 — Une porte d'entrée, un plugin à installer, un processus par événement

## Contexte

Le moteur tenait ses promesses de gouvernance ; ce que voyait un utilisateur, non. Confrontation
faite avec deux plugins Claude Code largement adoptés — `pbakaus/impeccable` (une skill,
vingt-trois verbes, un binaire appelé par la skill, tout ce qui est produit atterrit dans le
projet) et `obra/superpowers` (un plugin, des skills composables, aucun registre) — quatre écarts
apparaissent.

**Le marketplace ne disait pas quoi installer.** Quatre plugins listés à égalité : le harnais, et
trois agents d'exemple. Un nouveau venu recopiait les trois `claude plugin install`, sans qu'aucun
texte ne dise que deux d'entre eux ne servent qu'à essayer et à copier.

**Le CLI était présenté comme l'interface.** Vingt-six sous-commandes documentées en toutes
lettres, et des invocations de la forme `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" init`
dans la documentation destinée aux humains. Ni impeccable ni superpowers ne demandent à un
utilisateur de nommer un interpréteur et un fichier `.py` : la commande est de la plomberie, pas
un geste.

**Huit skills se disputaient le même domaine.** `setup`, `run`, `status`, `review`, `dispatch`,
`improve`, `knowledge`, `new-stage` : huit descriptions concurrentes à arbitrer, et un fichier
entier chargé pour une question de routage.

**Un événement de hook lançait jusqu'à six processus.** `PostToolUse Write|Edit` déclarait six
entrées — journal, validation, OKF, syntaxe Python, syntaxe JSON, watchdog. Six démarrages de
l'interpréteur après **chaque** écriture de fichier, six lectures concurrentes du même stdin, et
six blocs de contexte séparés là où l'agent n'en lit qu'un.

**Un consommateur héritait des portes du dépôt.** `test`, `coverage`, `selfscore` et `ratchet`
notent, mesurent et figent CE dépôt. Exposées par le plugin, elles donnaient à n'importe quel
projet de quoi re-figer un plancher qui n'était pas le sien.

## Décision

**Une skill, des verbes, des références chargées à la demande.** Le plugin n'expose plus qu'une
skill, `aidlc`. Son `SKILL.md` est une table de routage de onze verbes — `init`, `next`, `status`,
`review`, `sign`, `agents`, `new-agent`, `ask`, `improve`, `doctor`, `knowledge` — et le détail de
chacun vit dans `skills/aidlc/reference/<verbe>.md`, chargé seulement quand ce verbe est choisi.
C'est le motif *progressive disclosure* d'impeccable. Un test tient les deux sens de la relation :
un verbe qui cite une référence absente est une impasse silencieuse, une référence que rien ne
cite est du travail que personne n'atteindra.

**Le CLI redevient de la plomberie.** Un lanceur `bin/aidlc` est le seul chemin cité par les
hooks, les skills et la documentation. Il choisit `uv` quand il est présent — la version de Python
est alors garantie par un bloc PEP 723, au lieu d'être subie — et `python3` sinon. `uv` reste un
**lanceur préféré**, jamais un prérequis : la règle « aucune dépendance externe » vaut aussi pour
l'outillage.

**Le marketplace nomme le plugin à installer.** `aidlc` d'abord, décrit comme le seul requis ; les
trois autres explicitement libellés « EXEMPLE », chacun illustrant une forme différente — étape en
tête de chaîne, étape aval qui consomme, agent consultatif sans `produces`. Ils sont conservés :
un auteur d'agent copie un exemple qui marche plutôt qu'il n'interprète une spécification.

**Une entrée de hook, un processus.** `hooks.json` déclare une commande par événement, et
`hook post-write` enchaîne ses six passes en mémoire. stdin est lu une fois et la session lue
circule jusqu'aux passes — sans quoi chacune relirait un flux déjà vide et perdrait la session qui
corrèle les diagnostics d'`improve`.

**Les portes du dépôt sortent du plugin.** `test`, `coverage`, `selfscore` et `ratchet` vivent
derrière `tools/aidlc-dev`. Le moteur reste unique : ce point d'entrée appelle le même
`_aidlc.cli.main`, en lui demandant d'exposer ces sous-commandes.

**Un diagnostic d'installation.** `doctor`, repris d'impeccable, nomme en une commande ce qui, dans
un projet, ne répond plus à ce que la version installée attend : agent branché dont le plugin a
disparu, contrat devenu incohérent, livrable qu'aucun manifeste ne réclame, bundle OKF cassé,
version du harnais qui a changé. Il rapporte, il ne répare pas : chaque constat porte le geste qui
le corrige, et ce geste appartient à l'humain ou à l'équipe propriétaire.

## Ce qui a été écarté

**Fusionner les plugins en un seul.** Le doute sur « quatre plugins » était fondé, la fusion
aurait été une erreur : la modularité par équipe est la thèse du harnais (ADR-0002). Ce qu'il
fallait séparer, c'est *ce qu'on installe* de *ce qu'on étend*.

**Déplacer `aidlc.json` sous `.aidlc/config.json`**, par mimétisme avec `.impeccable/config.json`.
Cent quatre-vingt-dix occurrences pour un gain cosmétique — et surtout, cacher dans un dossier
point la seule gouvernance qu'un humain édite la rendrait moins découvrable. `.aidlc/` reste
l'état machine, protégé par le garde-fou ; `aidlc.json` reste la décision d'équipe, visible.

**Sortir la suite de tests du plugin.** Onze mille lignes, jamais chargées en contexte, et le
principe « un module, un test en face de lui » (ADR-0007) est structurant ici. La frontière qui
comptait était celle des *commandes*, pas celle des fichiers.

## Conséquences

Pour une équipe projet : une commande d'installation, un verbe à retenir (`/aidlc`), et un
diagnostic quand quelque chose cloche. Les six processus après chaque écriture deviennent un.

Pour une équipe qui publie un agent : rien ne change dans le contrat — le manifeste `agent.json`
et le `checks.json` sont inchangés. Les exemples restent au marketplace pour être copiés.

Pour qui maintient le harnais : les portes du dépôt s'appellent par `tools/aidlc-dev`, et une
sous-commande de maintenance appelée par le plugin fait rougir la suite. Un verbe nouveau s'ajoute
à deux endroits — la table de routage et sa référence — ou le test le refuse.

À surveiller : `uv run` coûte une trentaine de millisecondes de plus que `python3` au démarrage.
Négligeable au regard des cinq processus économisés par écriture, mais c'est le poste à mesurer si
la latence des hooks redevenait un sujet.
