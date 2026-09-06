---
okf_version: "0.2"
---
# Base de connaissance

Mémoire longue du projet : normes internes, décisions d'architecture, vocabulaire et retours
d'expérience, organisée en bundle Open Knowledge Format v0.2. Quand le dépôt sert de projet
d'essai, la base documente le harnais lui-même. L'exploitation du bundle (lecture par le
librarian, versement de concepts) est décrite dans [conventions.md](conventions.md).

# Concepts
* [Glossaire du harness AI-DLC](glossary.md) - Vocabulaire du dépôt : un terme employé dans un livrable doit correspondre à une entrée de ce glossaire.
* [Fonctionnement de la base de connaissance](conventions.md) - Comment le bundle knowledge/ est organisé, comment le librarian le lit par étape et comment verser ou remplacer un concept.

# Décisions et sources
* [ADR-0001 — Socle déterministe du harness agentique](sources/adr-0001-socle-agentique.md) - Choix d'un socle vérifiable et déclaratif : toute la logique déterministe tient dans un seul script, la validation est déclarative, le score n'est pas éditable par un agent.
* [ADR-0002 — Registre ouvert d'agents par manifeste](sources/adr-0002-registre-agents.md) - Remplacement du registre central d'étapes par une découverte des manifestes agent.json : chaque équipe publie son agent sans modifier le noyau, l'ordre se dérive des livrables, l'invocation est séparée par plateforme.
* [ADR-0003 — Topologie des dépôts et péremption des entrées amont](sources/adr-0003-topologie-depots.md) - Un dépôt par équipe pour les agents, un dépôt par initiative pour les livrables ; le handoff reste un fichier versionné, et une entrée amont modifiée après la revue rouvre la porte de l'aval.
* [ADR-0004 — Savoir OKF externe par sources déclarées](sources/adr-0004-savoir-okf-externe.md) - Le savoir qui vit hors du projet est consulté par un CLI sur des bundles OKF déclarés — sommaire, recherche, puis un concept — plutôt que copié dans knowledge/ ou lu en vrac par un agent.
* [ADR-0005 — Le score de maturité revient à l'orchestrateur, la rubrique appartient à l'équipe](sources/adr-0005-revue-de-maturite.md) - La note d'un livrable est enregistrée par le noyau et lue par l'orchestrateur, jamais rendue à l'agent noté ; ce que l'équipe décentralise, c'est la grille de lecture de son métier, pas le mètre ni la porte.
* [ADR-0006 — Ce que la note de maturité mesure, et sur quoi elle porte](sources/adr-0006-mesure-de-maturite.md) - La note est attachée au contenu qu'elle a jugé et non à un nom de fichier ; le plancher par axe ne juge que le livrable, l'échelle est ordinale, et l'autonomie acquise n'exige plus de signature sur les runs qu'elle dispense.
* [ADR-0007 — Le harnais est noté par la grille qu'il impose](sources/adr-0007-score-de-maturite-du-harnais.md) - La qualité du dépôt cesse d'être une collection de booléens verts : cinq axes déterministes agrégés en une note sur 5, avec le seuil et le plancher par axe des livrables, tenue en pre-commit et en CI.
* [ADR-0008 — Le bout en bout est une porte, et le projet déclare son workflow](sources/adr-0008-chainage-et-gouvernance-projet.md) - La chaîne producteur → consommateur cesse d'être une consigne d'orchestrateur pour devenir un code de sortie ; le projet consommateur porte sa propre gouvernance dans aidlc.json, s'amorce par init et signe par sign.
