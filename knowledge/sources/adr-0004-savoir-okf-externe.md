---
type: Architecture Decision
title: ADR-0004 — Savoir OKF externe par sources déclarées
description: Le savoir qui vit hors du projet est consulté par un CLI sur des bundles OKF déclarés — sommaire, recherche, puis un concept — plutôt que copié dans knowledge/ ou lu en vrac par un agent.
tags: [architecture, decisions, knowledge, okf, contexte]
id: adr-0004
date: 2026-09-05
deciders: Steve Magne
decision_status: accepted
stages: [plan, design, build]
generated: { by: human:steve-magne, at: 2026-09-05T00:00:00Z }
---

# ADR-0004 — Savoir OKF externe par sources déclarées

## Contexte

Le bundle `knowledge/` sert la mémoire **du projet**. Or l'essentiel du savoir dont un agent a
besoin appartient à l'entreprise et vit ailleurs : glossaire métier, politiques finance, catalogue
des tables, normes d'une autre direction. Trois façons de le lui donner, deux mauvaises :

- **Le copier dans `knowledge/`** — la copie périme le jour de son écriture, et l'équipe
  propriétaire du savoir n'a aucun moyen de corriger la copie faite chez le voisin. C'est le même
  défaut que le registre central d'étapes qu'[ADR-0002](adr-0002-registre-agents.md) a supprimé :
  une liste tenue par qui ne la possède pas.
- **Laisser l'agent aller le lire** — un clone, un `grep`, quelques `Read` : le dépôt entier
  traverse le contexte pour trois phrases utiles, et rien ne distingue le contenu tiers d'une
  consigne légitime.
- **Le déclarer et le servir par morceaux** — la voie retenue.

Le format Open Knowledge Format v0.2 rend la troisième voie praticable : un bundle est un dossier
de concepts Markdown à frontmatter, où `title`, `description`, `type` et `tags` suffisent à
décider *quoi ouvrir* sans ouvrir. C'est de la divulgation progressive, et c'est exactement ce
qu'un budget de contexte demande.

## Décision

1. Le projet consommateur déclare ses bundles externes dans **`knowledge-sources.json`**, à sa
   racine : `name` (identifiant atomique qui préfixe les références), `repo` (URL clonable ou
   dossier existant), `path` (le bundle dans le dépôt), `ref` (branche). Le fichier est versionné :
   déclarer une source est une décision de projet, comme une dépendance.
2. Le moteur expose la sous-commande **`knowledge`** en trois pas — `index` (une ligne par
   concept), `search <mots>` (les concepts qui portent tous les mots, frontmatter d'abord),
   `get <source>/<concept-id>` (un concept, en entier). Aucune commande ne rend un dépôt.
3. Les dépôts sont clonés en **profondeur 1 sous `.aidlc/tmp/knowledge/`** : un cache jetable, non
   versionné, reconstruit au premier appel, rafraîchi sur demande (`--refresh`). Un `repo` qui
   désigne un dossier existant est lu tel quel, sans clone — bundle monté, dépôt voisin, ou test
   hors réseau.
4. Le contenu servi est une **donnée à citer, jamais une instruction**. La skill
   `/aidlc-core:knowledge` et le prompt du librarian le posent explicitement, et le CLI le rappelle
   à chaque `get`. Un bundle tiers n'autorise rien.
5. Le cache n'est jamais lu directement (`Read`, `Glob`, `Grep`) : l'ouvrir annule l'économie que
   la commande existe pour produire.

## Conséquences

- **Pour qui rédige un livrable** — une norme externe se cite par sa référence exacte
  (`<source>/<concept-id>`), comme un chemin du bundle local. Le reviewer peut refaire le `get` :
  l'axe `traceability` reste vérifiable.
- **Pour qui installe le harnais** — versionner `knowledge-sources.json`, ignorer `.aidlc/tmp/`.
  Le clone utilise les droits git de la machine : un dépôt privé exigeant des identifiants
  interactifs n'est pas utilisable tel quel.
- **Pour qui possède un savoir** — le publier en bundle OKF dans son dépôt suffit à le rendre
  consultable par tous les agents, sans que personne copie quoi que ce soit. La topologie reste
  celle d'[ADR-0003](adr-0003-topologie-depots.md) : un dépôt par équipe, propriétaire de ce
  qu'elle publie.
- **Coût assumé** — une source injoignable est signalée sans faire tomber les autres, et le
  catalogue est reconstruit à chaque appel (lecture des frontmatters du cache). C'est linéaire, et
  c'est le prix d'une absence d'index à maintenir.

## Alternatives écartées

- **Un index vectoriel ou un serveur de recherche** — dépendance externe et service à exploiter,
  contre la règle 3 du dépôt (bibliothèque standard uniquement). La recherche par mots sur des
  frontmatters courts suffit tant que les bundles se comptent en centaines de concepts.
- **Un serveur MCP dédié** — même objection, plus une configuration par plateforme, alors que le
  besoin se ramène à trois lectures de fichiers.
- **Un miroir périodique dans `knowledge/`** — recrée la copie qui périme, et brouille la frontière
  entre ce que le projet décide et ce qu'il subit.
