---
type: Reference
title: Fonctionnement de la base de connaissance
description: Comment le bundle knowledge/ est organisé au format OKF v0.2, comment le librarian le lit par étape et comment verser ou remplacer un concept.
tags: [knowledge, conventions, okf]
stages: [plan, design, build, test, deploy, maintain]
generated: { by: human:steve-magne, at: 2026-09-06T00:00:00Z }
sources:
- { id: claude-md, resource: ../CLAUDE.md, title: Conventions du dépôt aidlc-harness }
---
# Base de connaissance — fonctionnement

Ce concept remplace l'ancien manuel `knowledge/README.md` et l'index machine
`knowledge/index.json` : la base est désormais un **bundle Open Knowledge Format v0.2**
([spec](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md)),
auto-descriptif, lu directement par le librarian et par tout agent.

## Organisation

```
knowledge/
  index.md        sommaire du bundle (progressive disclosure) — fichier réservé
  log.md          journal des changements (dates ISO, plus récent en premier) — fichier réservé
  glossary.md     concept — type: Glossary (source de vérité du vocabulaire)
  conventions.md  concept — type: Reference (ce document)
  sources/        concepts hébergés dans le dépôt (ADR, normes locales)
```

- Chaque fichier Markdown non réservé de `knowledge/` est un **concept** : un frontmatter YAML
  (`type` obligatoire, non vide) puis un corps Markdown. `index.md` et `log.md` sont réservés et
  ne sont jamais des concepts.
- `type` est descriptif et autonome (`Glossary`, `Architecture Decision`, `Reference`,
  `Playbook`…) : les consommateurs tolèrent les types inconnus, inutile d'inventer une taxonomie.
- Les familles de métadonnées OKF (provenance, confiance, cycle de vie — `generated`, `verified`,
  `status`, `stale_after`, `sources`) sont facultatives ; leur absence est honnête et tolérée.
  La spec v0.2 fait foi (sections 4 et 5).
- `stages` est une **extension maison** : la liste des étapes du cycle de vie auxquelles le
  concept s'applique (`plan`, `design`, `build`, `test`, `deploy`, `maintain` — les étapes
  implémentées se lisent dans les manifestes `agent.json`, les autres dans `planned_stages`).
  C'est le filtre principal du librarian. En cas d'hésitation, ne rattacher le concept qu'aux
  étapes où son absence ferait commettre une erreur : un concept rattaché aux six étapes ne
  filtre plus rien.
- Le `description` d'un concept dit **quand le citer**, pas seulement ce qu'il contient. Un
  résumé qui paraphrase le titre ne sert à rien.
- `index.md` et `log.md` se mettent à jour à chaque versement : le sommaire reste exact, le
  journal enregistre le changement.

## Lire la base — le rôle du librarian

Pour répondre à « quel contexte pour l'étape X » :

1. Lire `knowledge/index.md`, puis les concepts du bundle.
2. Retenir les concepts dont `stages` contient `X`, plus `glossary.md` pour le vocabulaire.
3. Y ajouter les entrées amont déclarées dans le champ `consumes` de l'`agent.json` de l'étape :
   ce sont du contexte **obligatoire**, qu'elles figurent ou non dans le bundle.
4. Ouvrir réellement chaque concept retenu, citer des extraits littéraux, et signaler ce qui est
   annoncé mais introuvable plutôt que de combler le vide.

La valeur du service est la **citabilité** : un agent doit repartir avec des chemins exacts
(`knowledge/glossary.md`, `knowledge/sources/adr-0001-socle-agentique.md`…) — c'est ce qui
alimente l'axe *traceability* de la grille de maturité, où une référence locale et vérifiable
sépare un 4 d'un 3.

## Verser un concept

1. **Rendre la source atteignable.** Soit le document vit dans le dépôt — le poser dans
   `knowledge/sources/` — soit il vit ailleurs et on retient son URL stable dans son `resource`
   ou dans une entrée `sources[]` d'un concept (pas un lien de partage temporaire, pas un lien
   vers une conversation).
2. **Écrire le concept** : frontmatter avec `type` (obligatoire), `title`, `description` qui dit
   quand citer le concept, `tags`, `stages` parcimonieux, et les familles OKF utiles
   (`generated`, `status`, `sources`…).
3. **Mettre à jour `knowledge/index.md`** (une entrée par concept) et **`knowledge/log.md`**
   (une entrée datée).
4. **Vérifier la forme** : le frontmatter s'ouvre par `---`, se ferme par `---`, contient un
   `type` non vide. En session Claude Code, les hooks du plugin `aidlc-core` contrôlent le
   bundle : `check-okf --touched` à chaque écriture (retour immédiat en contexte, et
   journalisation de l'écriture fautive — session, fichier — pour le diagnostic `improve`) et
   `check-okf --stop` à la fermeture — l'arrêt est refusé tant que le bundle est non conforme en
   session interactive (en headless `claude -p`, le refus est émis et enregistré sans bloquer).
   La passe de conformité du harnais (`aidlc.py test`) couvre `docs/` et `knowledge/` du
   dépôt ; pour un bundle arbitraire — ex. le `knowledge/` d'un projet consommateur — la
   sous-commande `aidlc.py check-okf <dossier>` est la porte dure (exit 1 si non conforme) :
   branchez-la en CI pour gater le bundle à chaque changement.
5. Ne jamais verser un secret, un identifiant, un jeton ni une donnée personnelle. Si un document
   en contient, le signaler et n'indexer rien.

## Remplacer ou retirer

- Une source contredite par une plus récente est **remplacée**, pas laissée en concurrence :
  deux normes opposées dans le bundle produisent des livrables incohérents.
- Un concept cité par des livrables ne se supprime pas : on remplace son contenu par la version à
  jour (statut `deprecated` si la version remplacée reste utile à l'historique des liens), en le
  disant dans le `description` et dans `log.md`.
- Une norme externe n'a pas d'existence locale : elle se cite dans les `sources[]` des concepts
  qui s'y réfèrent, elle n'est pas dupliquée dans le bundle.
- `glossary.md` est la source de vérité du vocabulaire. Un terme employé dans un livrable et
  absent du glossaire est soit à définir, soit à remplacer par un terme déjà défini.

## Sources de vérité hors bundle

Le bundle `knowledge/` est autonome et vit dans le **projet consommateur**. Dans ce dépôt, qui
sert aussi de projet d'essai, la base documente le harnais lui-même, dont les sources de vérité
vivent hors du bundle :

- [CLAUDE.md](../CLAUDE.md) — les conventions lues par tout agent du dépôt ;[^claude-md]
- le bundle [docs/](../docs/index.md) — architecture, guide consommateur, guide mainteneur ;
- `plugins/aidlc-core/pipeline.json` — la gouvernance par défaut du harnais : seuils, `watchdog`,
  et `planned_stages` (feuille de route consultative) — installée avec le plugin ;
- l'`agent.json` de chaque plugin d'étape — la définition de l'étape elle-même : son livrable
  (`produces`), ses entrées (`consumes`), son rôle humain, son contrat (`checks`) ;
- les templates et checks des plugins d'étape, ex. `plugins/aidlc-plan/templates/intent.md`.

Un projet consommateur, lui, alimente son propre `knowledge/` avec les normes, ADR et retours
d'expérience de son organisation : il n'a pas besoin du dépôt du harnais.

[^claude-md]: Conventions du dépôt aidlc-harness
