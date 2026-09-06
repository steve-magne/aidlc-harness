---
type: Glossary
title: Glossaire du harness AI-DLC
description: Vocabulaire du dépôt aidlc-harness — un terme employé dans un livrable doit correspondre à une entrée de ce glossaire.
tags: [glossary, vocabulary]
stages: [plan, design, build, test, deploy, maintain]
generated: { by: human:steve-magne, at: 2026-09-06T00:00:00Z }
---

# Glossaire

Vocabulaire du dépôt `aidlc-harness`. Un terme employé dans un livrable doit correspondre à une
entrée de ce glossaire ; sinon, il faut soit l'y ajouter, soit employer le terme déjà défini.
Les identifiants techniques restent en anglais, la prose reste en français.

---

**ADR** (*Architecture Decision Record*) — Document court qui acte une décision d'architecture :
le contexte, la décision, les alternatives écartées, les conséquences. Concept de type OKF
`Architecture Decision` dans `knowledge/sources/` (exemple :
[ADR-0001](sources/adr-0001-socle-agentique.md)). Une décision de livrable qui cite un ADR est
traçable ; une décision qui n'en cite aucun ne l'est pas.

**Agent** — Session Claude Code spécialisée, décrite par un fichier Markdown dans `agents/` d'un
plugin. Le harness en définit trois transverses (`orchestrator`, `reviewer`, `librarian`) et un
par étape (`<stage>-analyst`).

**AI-DLC** — *AI-native Development Life Cycle*. Cycle de développement logiciel dont chaque phase
est exécutée par une session agentique plutôt que par une équipe seule. Les six phases retenues
ici : `plan`, `design`, `build`, `test`, `deploy`, `maintain`.

**Axes de maturité** — Les quatre dimensions notées de 0 à 5 par le reviewer :
*completeness* (toutes les sections utiles sont remplies), *precision* (testable, non ambigu,
chiffré), *traceability* (cite ses entrées et ses sources de vérité), *autonomy* (peu
d'intervention humaine dans le journal de session). Détail axe par axe dans
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

**Base de connaissance** — Le dossier `knowledge/`, un bundle OKF v0.2 (concepts à frontmatter,
sommaire `index.md`, journal `log.md`). Mémoire longue de l'organisation, par opposition aux
livrables qui ne valent que pour un cycle.

**Check déterministe** — Règle de validation appliquée par `aidlc.py validate` sans aucun
jugement de modèle : présence d'une section, volume de texte, expression interdite, citation d'une
entrée. S'oppose à la notation qualitative du reviewer.

**checks.json** — Fichier déclaratif, un par plugin d'étape, qui énumère les checks déterministes
du livrable. Ajouter une exigence, c'est éditer ce JSON, pas écrire du code.

**Entrée** (*input*) — Livrable amont déclaré obligatoire pour une étape dans le champ `consumes`
de l'`agent.json` de son agent. La règle `must_reference_inputs` vérifie que le livrable produit
cite réellement ses entrées.

**Étape** (*stage*) — Une des six phases du pipeline. Identifiée par un `id` en anglais, elle
possède un plugin, une skill, un livrable unique, des entrées, un fichier de checks et un rôle
humain responsable.

**File d'amélioration** — `.aidlc/improvement-queue.jsonl`. Reçoit la justification de chaque
refus humain. C'est le point d'entrée de la boucle de self-improvement.

**Frontmatter** — Bloc YAML délimité par `---` en tête d'un document Markdown. Porte les
métadonnées obligatoires (`stage`, `version`, `status`, `author`, `date`) vérifiées par
`required_frontmatter`. Les concepts de la base de connaissance portent un frontmatter OKF
(`type` obligatoire, familles de confiance et de provenance facultatives) — voir
[conventions.md](conventions.md).

**Garde-fou** (*guard*) — Sous-commande `aidlc.py guard`, branchée sur le hook `PreToolUse`. Elle
refuse qu'un agent écrive dans `.aidlc/maturity.json` ou `.aidlc/reviews/*.json` : un modèle ne
doit pas pouvoir modifier sa propre note.

**Grille de maturité** — L'échelle commune aux quatre axes : 0 absent, 1 brouillon, 2 incomplet,
3 acceptable avec réserves, 4 conforme, 5 exemplaire. La frontière opérationnelle est celle entre
3 et 4.

**Harness** — Ce dépôt. L'ensemble orchestrateur, plugins, checks, journaux et base de
connaissance qui fait tourner le cycle de vie et mesure sa qualité.

**Hook** — Point d'accroche du cycle de vie d'une session Claude Code, déclaré dans
`hooks/hooks.json`. Le harness en utilise pour journaliser les événements, valider un livrable dès
son écriture, et refuser les écritures interdites.

**JSONL** — Fichier texte où chaque ligne est un objet JSON autonome. Format des journaux de
session et de la file d'amélioration : on y ajoute une ligne sans jamais relire ni réécrire le
fichier.

**Librarian** — Agent qui sert la base de connaissance. Il compose un briefing ciblé par étape à
partir des concepts du bundle `knowledge/` (filtrés par leur extension `stages`), du glossaire et
des livrables amont. Lecture seule en dehors de `knowledge/`.

**Livrable** (*deliverable*) — Le fichier produit par une étape, rangé dans
`deliverables/<stage>/`. Seul objet qui circule entre deux étapes : rien ne se transmet en dehors
de lui.

**Marketplace** — `.claude-plugin/marketplace.json`, catalogue des plugins du dépôt. Chaque
nouvelle étape générée par `scaffold` y ajoute son entrée.

**Mode autonome** — État d'une étape qui n'exige plus de revue humaine pour franchir sa porte.
Obtenu après `consecutive_runs_to_autonomy` runs consécutifs au-dessus du seuil, avec une revue
humaine approuvée. Il ne suspend ni la validation ni la notation.

**Note globale** (*overall*) — Moyenne arithmétique des quatre axes, arrondie au dixième.
Toujours recalculée par `aidlc.py score` : la valeur proposée par le reviewer est ignorée.

**OKF** (*Open Knowledge Format*) — Format ouvert et versionné de représentation de la
connaissance : des concepts Markdown à frontmatter YAML (`type` obligatoire), organisés en bundle
avec un sommaire `index.md` et un journal `log.md`. Ce dépôt contient deux bundles OKF v0.2 :
`docs/` et `knowledge/`. Les familles de métadonnées (provenance, confiance, cycle de vie) sont
définies dans la spec : https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md

**Orchestrator** — Agent qui pilote le pipeline : il détermine l'étape courante, lance la skill de
l'étape, déclenche le reviewer, puis la porte. Il ne rédige jamais un livrable lui-même.

**Pipeline** — La suite des étapes du cycle de vie. L'ordre se dérive de la chaîne
producteur → consommateur des manifestes `agent.json` (`produces`/`consumes`), jamais d'une
position dans un fichier. `pipeline.json` ne porte que la gouvernance par défaut (seuils,
`watchdog`) et `planned_stages`, une feuille de route consultative. Aucun composant ne doit
contenir de liste d'étapes en dur.

**Plugin** — Unité d'extension Claude Code (`plugins/aidlc-*`), composée d'agents, de skills, de
templates, de checks et parfois de hooks. `aidlc-core` porte l'infrastructure, `aidlc-<stage>`
porte une étape.

**ponytail** — Marqueur de commentaire `# ponytail: ...` signalant un raccourci assumé dans le
code : le choix le plus simple qui fonctionne, documenté comme tel plutôt que dissimulé.

**Porte** (*gate*) — Décision de franchissement d'une étape, calculée par `aidlc.py gate`. Elle
exige la validation déterministe, un verdict accepté au-dessus du seuil, et la revue humaine tant
que l'étape n'est pas autonome.

**Reviewer** — Agent qui note un livrable sur les quatre axes, émet un verdict et justifie chaque
note par une citation du livrable. Il écrit un `review.json` et appelle `aidlc.py score` ; il n'a
pas le droit d'écrire dans `.aidlc/`.

**Revue humaine** — Signature d'un responsable dans `.aidlc/reviews/<stage>-<run>.json`, avec un
booléen d'approbation et une justification. Un refus alimente la file d'amélioration.

**Rôle humain** — Fonction responsable d'une étape, déclarée dans le champ `human_role` de
l'`agent.json` de l'agent (pré-rempli depuis `planned_stages` tant que l'étape n'est pas publiée) :
Product Owner / Business Analyst pour `plan`, Architecte d'entreprise pour `design`, Tech Lead
pour `build`, QA Lead pour `test`, SRE / Release Manager pour `deploy`, Ops / Support pour
`maintain`.

**Run** — Une exécution d'une étape, du lancement de la skill jusqu'à l'enregistrement du score.
Numéroté et historisé par étape dans `.aidlc/maturity.json`.

**Scaffold** — Sous-commande `aidlc.py scaffold <stage>` qui génère le plugin complet d'une étape
déclarée mais non implémentée, à partir de son entrée dans `pipeline.json`.

**Self-improvement** — Boucle qui transforme les journaux, les scores faibles et les refus humains
en correctifs concrets sur les `SKILL.md`, les templates et les `checks.json`. Le script produit
le diagnostic, l'agent propose le correctif, l'humain l'accepte.

**Session agentique** — Une exécution de Claude Code identifiée par un `session_id`. Ses
événements sont journalisés dans `.aidlc/logs/<session_id>.jsonl` et servent à évaluer l'axe
*autonomy*.

**Seuil de maturité** — `maturity_threshold` dans `pipeline.json`, fixé à 4.0. Note globale
minimale pour qu'un livrable soit accepté. Le seuil prime sur le verdict du reviewer.

**Skill** — Procédure exécutable décrite dans `skills/<nom>/SKILL.md`. Une skill par étape décrit
la recette du livrable ; `aidlc-core` en expose sept transverses (`run`, `status`, `review`,
`new-stage`, `improve`, `dispatch`, `knowledge`).

**Source de vérité** — Fichier qui fait autorité sur un sujet et que l'on ne duplique jamais :
`agent.json` pour la définition d'une étape (livrable, entrées, contrat), `checks.json` pour les
exigences d'un livrable, les concepts du bundle `knowledge/` pour les références du projet, ce
glossaire pour le vocabulaire.

**Statut d'étape** — Dérivé par le registre, jamais déclaré : une étape est *implémentée* dès
qu'un plugin installé porte un `agent.json` avec ce `produces` ; elle reste *prévue* — affichée
« plugin non installé » par `status` — tant que seule une entrée `planned_stages` (gouvernance
`pipeline.json` ou `aidlc.json`) l'annonce sans agent producteur.

**Template** — Squelette d'un livrable, dans `templates/` du plugin d'étape. Seul endroit du dépôt
où des marqueurs de remplissage entre chevrons sont autorisés, parce qu'ils sont destinés à être
remplacés.

**Tranche verticale** — L'étape `plan`, implémentée de bout en bout (agent, skill, template,
checks) pour servir de modèle à la génération des cinq autres.

**Verdict** — Avis du reviewer, `accepted` ou `rejected`, consigné dans le `review.json`. Un
verdict accepté sous le seuil ne franchit pas la porte.
