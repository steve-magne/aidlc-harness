---
type: Architecture Decision
title: ADR-0008 — Le bout en bout est une porte, et le projet déclare son workflow
description: La chaîne producteur → consommateur cesse d'être une consigne d'orchestrateur pour devenir un code de sortie ; le projet consommateur porte sa propre gouvernance dans aidlc.json, s'amorce par init et signe par sign.
tags: [architecture, decisions, gouvernance, chainage, consommateur, revue]
id: adr-0008
date: 2026-09-06
deciders: Steve Magne
decision_status: accepted
stages: [plan, design, build, test, deploy, maintain]
generated: { by: human:steve-magne, at: 2026-09-06T00:00:00Z }
---

# ADR-0008 — Le bout en bout est une porte, et le projet déclare son workflow

## Contexte

Le harnais promet qu'une idée traverse les étapes d'un cycle de vie en passant de persona en
persona, chaque livrable étant l'entrée de l'étape suivante. Quatre manques séparaient cette
promesse de ce que le moteur tenait réellement.

1. **Le chaînage n'était garanti par rien de déterministe.** `gate <stage>` ne consultait jamais
   l'état de l'amont : son seul lien était `stale_inputs`, qui compare des empreintes
   **enregistrées au moment de la revue** — donc inopérant quand l'amont n'a jamais existé. Un
   livrable aval n'avait qu'à *mentionner la chaîne de caractères* du chemin de son entrée pour
   satisfaire `must_reference_inputs`, et `must_not_violate_scope` s'échappait silencieusement
   (`if not source.exists(): continue`) quand le fichier manquait. Résultat mesuré : `validate
   design` rendait `ok: true` sur douze règles, et `gate design` rendait `passed: true`, exit 0,
   alors que `deliverables/plan/intent.md` n'existait pas. Le tableau de bord affichait
   sereinement « design : étape franchie » au-dessus de « plan : livrable non produit ». La seule
   vérification de l'amont vivait en prose dans `skills/run/SKILL.md` — donc soumise à ce que
   l'agent avait compris, et contournée par tout appel direct, tout hook et toute CI.
2. **Un projet ne pouvait pas déclarer son workflow ni son exigence.** `pipeline.json` vit dans la
   copie que Claude Code installe, que le garde-fou `PreToolUse` protège de toute écriture. Le
   pipeline d'une initiative était donc l'union de ce que la machine avait installé, et son seuil
   celui du harnais. Deux projets ouverts sur le même poste héritaient forcément du même pipeline,
   et `status` proposait au consommateur `aidlc.py scaffold build` — une commande que le guide lui
   interdit par ailleurs.
3. **Rien n'amorçait le projet d'accueil.** Le harnais suppose un projet qui **existe déjà**, avec
   son code, son README et ses décisions. La première étape s'ouvrait pourtant sur un entretien à
   froid : rien ne lisait le dépôt, et le `librarian` n'avait aucun bundle à servir puisque
   `knowledge/` n'existait pas encore.
4. **La signature humaine était une manipulation de JSON.** Copier un gabarit, éditer un fichier
   caché, y écrire un horodatage ISO 8601 à la main, puis demander à l'agent de rouvrir la porte.
   Trois gestes manuels demandés au détenteur du besoin — et rien ne vérifiait le contenu avant
   `gate`.

## Décision

**Le chaînage devient une porte.** `maturity.upstream_blockers` exige, pour chaque chemin du
`consumes` d'un agent, que le fichier **existe** et que l'agent qui le produit ait franchi **sa**
porte. Les bloquants sont listés en tête de `blocking` — une étape bâtie sur du vide n'a pas de
qualité à mesurer, et le dire avant la note évite d'envoyer l'utilisateur relancer un reviewer pour
rien. La remontée se fait d'un cran à la fois, un ensemble `seen` coupant une dépendance
circulaire. Le tableau de bord tient la même chaîne sans jamais appeler `gate` : les agents lui
arrivent triés par la chaîne producteur → consommateur, il retient au fil de l'eau quelles lignes
sont franchies, et affiche « En attente de l'amont : \<agent\> ».

`validate` reste au niveau de la **forme** du livrable — une entrée absente n'y est pas une erreur
— mais elle **avertit** en nommant l'agent producteur et les règles devenues muettes. Un vert qui
ne dit pas ce qu'il n'a pas vérifié est un mensonge.

**Le projet porte sa gouvernance.** `aidlc.json`, à la racine du projet consommateur, recouvre
`pipeline.json` clé par clé (`util.load_pipeline`) : seuils, `watchdog`, `planned_stages`, et
surtout `agents` — la liste blanche des identifiants qui composent **son** workflow, appliquée dans
`registry.discover` donc partout. Un identifiant déclaré qu'aucun manifeste ne porte remonte en
avertissement plutôt que de rétrécir le pipeline en silence. Une clé inconnue est ignorée et
`status` le dit.

**Le projet s'amorce.** `aidlc.py init` pose `aidlc.json`, `deliverables/`, `knowledge-sources.json`
et un bundle `knowledge/` conforme OKF v0.2 dont un concept `sources/projet-existant.md` :
l'inventaire **déterministe** des README, manifestes de dépendances et documents de `docs/` déjà
présents. La passe ne lit ni ne résume aucun contenu — elle rend des chemins ; le sens reste à
l'humain et aux agents. Elle ne remplace jamais un fichier existant, donc se relance sans risque.

**La signature est une commande, et elle exige un terminal.** `aidlc.py sign <stage>
--approve|--reject --by … --why …` écrit la revue avec le bon horodatage puis rejoue la porte. Elle
tient trois exigences que le fichier ne savait pas tenir : un relecteur nommé, une justification
non vide dans les deux sens, et le refus d'écraser une signature déjà apposée. Elle **refuse de
tourner sans stdin interactif** : le hook `PreToolUse` ne couvre que `Write` et `Edit`, et rien
n'empêcherait sinon un agent d'appeler la commande par un outil `Bash`.

## Conséquences

- Une étape aval ne démarre plus sur un amont absent ou non franchi, y compris en CI et quel que
  soit ce que l'agent a compris. Le prix est une remontée de portes à chaque `gate` d'une étape
  consommatrice — quelques validations de plus, sur des pipelines de cinq à six étapes.
- Un livrable amont révisé rouvre la porte de son propre agent, ce qui rebloque l'aval par la
  chaîne, en plus de la péremption d'empreinte déjà en place (ADR-0006). Les deux mécanismes se
  recouvrent volontairement : l'un porte sur l'existence, l'autre sur le contenu jugé.
- `aidlc.json` devient un fichier **versionné du projet**, au même titre qu'une dépendance : c'est
  là que se discute l'exigence d'une initiative, et non plus dans un cache d'installation.
- La colonne `EN ATTENTE DE` du tableau de bord remplace la ligne « Rôles humains » : le rôle passe
  d'une énumération en bas de page à la réponse à « c'est à qui ? », sur la ligne concernée. Une
  seule ligne porte un nom à la fois — une étape franchie n'attend personne, une étape bloquée par
  son amont non plus, car l'action est sur la ligne du dessus.
- La voie manuelle de signature reste ouverte pour les contextes sans terminal, ce qui évite de
  faire de `sign` un passage obligé en CI.

## Alternatives écartées

- **Faire du chaînage une erreur de `validate`.** Rejeté : la validation répond « ce fichier
  respecte-t-il son contrat de forme ? », le chaînage est une propriété du pipeline. Les mélanger
  aurait fait échouer la validation d'un livrable irréprochable, et rendu le message illisible pour
  l'agent qui corrige.
- **Renforcer la consigne dans `skills/run/SKILL.md`.** Rejeté : c'est ce qui existait, et la
  faille mesurée montre qu'un texte ne tient pas une garantie. Un contrôle qu'on peut contourner en
  appelant la commande directement n'est pas un contrôle.
- **Recalculer récursivement toute la chaîne dans `status`.** Rejeté : le tableau de bord serait
  devenu coûteux (une validation par étape et par ancêtre) pour une information que l'ordre
  topologique donne gratuitement.
- **Laisser `sign` tourner partout et se reposer sur le hook `PreToolUse`.** Rejeté : le hook ne
  voit que les outils d'écriture. Sans le test du terminal, la commande aurait été le moyen le plus
  simple pour un agent de signer à la place de l'humain.
