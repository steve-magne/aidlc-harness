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
