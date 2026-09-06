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
