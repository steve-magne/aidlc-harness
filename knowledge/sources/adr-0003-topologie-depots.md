---
type: Architecture Decision
title: ADR-0003 — Topologie des dépôts et péremption des entrées amont
description: Un dépôt par équipe pour les agents, un dépôt par initiative pour les livrables ; le handoff entre personas reste un fichier versionné, et une entrée amont modifiée après la revue rouvre la porte de l'aval.
tags: [architecture, decisions, orchestration, collaboration]
id: adr-0003
date: 2026-09-05
deciders: Steve Magne
decision_status: accepted
stages: [plan, design, build]
generated: { by: human:steve-magne, at: 2026-09-05T00:00:00Z }
---

# ADR-0003 — Topologie des dépôts et péremption des entrées amont

## Contexte

Le harnais orchestre des **personas de directions différentes** : un Business Analyst cadre le
besoin (personas, bénéfices, KPIs de succès), un architecte d'entreprise instruit ce cadrage pour
arrêter l'architecture cible, un tech lead, un QA lead et un SRE suivent. Chacun travaille avec son
propre agent, publié dans son propre plugin.

Deux questions restaient sans réponse écrite.

**Où vit le travail ?** L'ADR-0002 a rendu le registre ouvert : chaque équipe publie son agent sans
toucher au noyau. Mais rien ne disait où poser les **dépôts git** — un dépôt commun où tout le monde
écrit, un dépôt par persona, une base partagée ? La question n'est pas cosmétique : le handoff entre
deux étapes est un **chemin de fichier** (`consumes`), et la topologie décide si ce chemin résout.

**Que devient l'aval quand l'amont bouge ?** Le mécanisme de dépendance ne regardait que
l'existence de l'entrée et l'état de sa porte, au moment où l'aval démarrait. Une fois `design`
noté et franchi, une révision de `deliverables/plan/intent.md` — un KPI corrigé, un persona
retiré — ne produisait **aucun signal** : la spec restait verte alors qu'elle avait été bâtie sur
une version disparue. Dans un cycle synchrone où un seul agent enchaîne les étapes, le cas ne se
présente pas. Entre équipes travaillant en asynchrone, c'est le mode de panne le plus probable, et
le plus silencieux.

## Décision

**Deux dépôts, deux propriétaires, deux rythmes.**

1. **Un dépôt par équipe pour les agents.** Le plugin du BA appartient à Produit, celui de
   l'architecte à Architecture, celui de l'AppSec au RSSI. Chaque équipe fait évoluer son prompt,
   son `checks.json`, sa version et son cycle de release seule. Cette frontière est déjà *active* :
   le hook `PreToolUse` refuse à un agent d'écrire dans le plugin d'une autre équipe installé hors
   du projet — son manifeste est lu, pas réécrit.
2. **Un dépôt par initiative pour les livrables.** `deliverables/`, `.aidlc/` et `knowledge/` vivent
   dans le projet consommateur, et **tous les personas y écrivent**. Pas un dépôt commun
   d'entreprise : un dépôt par produit ou par initiative, dont le périmètre est celui du cycle de
   vie en cours.
3. **Le handoff reste un fichier versionné.** Rien ne circule entre deux étapes en dehors du chemin
   déclaré par `produces` / `consumes`.
4. **Une entrée amont modifiée après la revue rouvre la porte de l'aval.** Au moment où un run est
   noté, l'empreinte de chaque entrée déclarée dans `consumes` est figée avec lui dans
   `.aidlc/maturity.json`. `gate` et `status` comparent cette empreinte à l'état courant : toute
   divergence est bloquante et nomme le fichier qui a bougé.

**Amorçage assumé** : aujourd'hui les plugins cohabitent dans `aidlc-harness`. C'est correct tant
qu'il y a peu d'équipes. Le signal de sortie est le rythme de release : dès qu'une équipe veut
publier sans attendre le dépôt commun, elle sort son plugin — `AIDLC_AGENT_PATH` et le marketplace
font de cet éclatement un changement de configuration, pas un remaniement.

## Conséquences

- **Ce que git apporte gratuitement** au dépôt d'initiative : l'historique de qui a changé quel KPI,
  la *pull request* comme lieu naturel de la revue humaine (`review-request`), le `blame` sur une
  contrainte, et le diff exact quand le BA révise après que l'architecte a livré.
- **Un livrable aval peut redevenir « à faire » sans avoir été touché.** C'est voulu : le
  tableau de bord affiche « Entrée amont modifiée », et l'agent aval doit dire quelles décisions la
  révision remet en cause avant d'être renoté.
- **La comparaison porte sur l'octet, pas sur le sens.** Une correction de typo dans l'amont périme
  l'aval. Plafond assumé : une relance de reviewer de trop. Le compromis est marqué en clair dans
  `util.digest`.
- **Compatibilité ascendante** : un run noté avant l'existence des empreintes ne périme rien. On ne
  périme que ce dont on connaît l'état d'origine.

## Alternatives écartées

- **Un dépôt par persona.** Le chemin `deliverables/plan/intent.md` ne résout plus depuis le dépôt
  de l'architecte : il faudrait un mécanisme de synchronisation (sous-modules, copie, artefacts de
  CI) dont le coût dépasse largement le problème. Le mécanisme de dépendance du harnais deviendrait
  inopérant.
- **Une base de données ou un bus de messages partagé.** Ajoute une dépendance externe et un service
  à exploiter, contre la règle « bibliothèque standard uniquement ». Et perd ce que git donne sans
  rien coder : l'historique, la revue, le diff.
- **Les livrables dans le dépôt du harnais.** Confond l'outil et le produit, contre la règle « un
  livrable = un fichier dans `deliverables/` du projet consommateur ». Un harnais installé chez
  trois clients écrirait leurs livrables au même endroit.
- **Périmer l'aval sur la seule date de modification (`mtime`).** Un `git checkout` ou une copie de
  travail suffit à changer la date sans changer le contenu : fausses alertes garanties, et la
  confiance dans le signal disparaît au premier faux positif.
