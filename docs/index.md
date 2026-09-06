---
okf_version: "0.2"
---
# Documentation du harnais AI-DLC

Ce dossier est un bundle Open Knowledge Format v0.2 : les guides publiés du harnais, en concepts
à frontmatter YAML. Le contenu rédactionnel des guides fait foi ; les métadonnées (type, titre,
description, provenance) facilitent la lecture par les agents.

# Guides
* [Le harnais AI-DLC en schémas](DIAGRAMS.md) - Vue d'ensemble du fonctionnement en diagrammes ASCII : les deux racines, le cycle d'une étape, les conditions de la porte, la découverte des agents, les hooks, les garde-fous, la boucle d'amélioration et le moteur.
* [Architecture du harness AI-DLC](ARCHITECTURE.md) - Référence de conception du dépôt : intention, composants, cycle de vie d'une étape, grille de maturité, mode autonome, boucle de self-improvement.
* [Consommer le harnais AI-DLC dans votre projet](CONSUMER.md) - Guide consommateur prêt à publier : installation du marketplace et des plugins, premier run de l'étape Plan, revue humaine, versionnage et mises à jour.
* [Maintenir et publier le harnais AI-DLC (guide auteur)](MAINTAINER.md) - Guide auteur prêt à publier : concevoir une nouvelle étape, remplir les squelettes générés, vérifier avant release et publier dans le marketplace.
* [Stratégie de tests du harnais AI-DLC](TESTING.md) - Ce que le harnais teste, comment, et pourquoi : suite unittest stdlib découpée par concern, contrat CLI en sous-processus, portes structurelles sur les artefacts de plugin, ratchet de non-régression de couverture et score de maturité du harnais (selfscore).
