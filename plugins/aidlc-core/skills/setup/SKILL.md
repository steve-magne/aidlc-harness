---
name: setup
description: Amorcer le harnais dans un projet existant et composer le workflow de l'initiative — poser aidlc.json, nommer l'idée en cours, choisir les agents d'équipe qui composent la chaîne. À utiliser au premier contact avec un projet, quand on demande d'installer, de démarrer, de configurer le harnais, d'ajouter ou de retirer un agent du workflow, ou de lancer une nouvelle initiative dans un projet qui en a déjà mené une.
argument-hint: "[nom de l'initiative] — vide = amorçage seul"
---

# Amorcer le harnais et composer le workflow

C'est le premier contact. Le projet existe déjà — son code, son histoire, ses équipes — et une idée
d'évolution vient d'arriver. Ta tâche : poser la gouvernance, nommer l'idée, et **brancher les
agents des équipes qui vont la porter**. Rien d'autre : tu ne produis aucun livrable ici.

## Conventions

Le script unique vit dans le plugin `aidlc-core` (`${CLAUDE_PLUGIN_ROOT}`) ; tout ce que tu poses
vit dans le projet consommateur (`$CLAUDE_PROJECT_DIR`).

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" <sous-commande>
```

## 1. Amorcer, une fois pour toutes

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" init
```

Idempotent : il ne remplace jamais un fichier existant. Il pose `aidlc.json` (l'exigence et le
workflow), `deliverables/`, le bundle `knowledge/` et un inventaire des sources déjà présentes dans
le dépôt d'accueil.

Si `aidlc.json` existait déjà, `init` le laisse tel quel et le dit : passe directement à l'étape 2.

## 2. Voir ce qu'on a, et ce qu'on joue

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow
```

Trois cas dans la sortie, et ils appellent trois réponses différentes :

- **un agent branché** — il compose la chaîne, avec son équipe et son livrable ;
- **« découverts, hors de ce workflow »** — l'équipe a publié son plugin, personne ne l'a branché.
  Demande à l'utilisateur si cette équipe intervient sur cette initiative avant d'ajouter quoi que
  ce soit ;
- **« introuvable »** — un agent est déclaré mais son plugin n'est pas installé. Dis quelle équipe
  doit le publier ou l'installer ; ne le retire pas de ta propre initiative.

## 3. Nommer l'initiative — si le projet en a déjà mené une

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow --initiative "<nom-court>"
```

Un projet vit plus longtemps qu'une idée. Sans ce nom, les livrables et les scores de la deuxième
idée écrasent ceux de la première : les chemins sont fixes. Avec lui, chaque idée a son dossier
(`deliverables/<nom>/`, `.aidlc/<nom>/`) et l'histoire de la précédente reste lisible.

Pose la question dès qu'un `deliverables/` non vide existe déjà, ou que l'utilisateur parle d'une
« nouvelle » évolution. Un nom court, en minuscules, sans espace : `reco-panier`, `refonte-sso`.

## 4. Composer la chaîne

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" workflow --add <agent> --remove <agent>
```

Répétable, et les deux options se combinent en un seul appel. La commande **refuse** un identifiant
qu'aucun manifeste ne porte : c'est voulu, un agent fantôme rétrécirait la chaîne en silence.

Avant d'ajouter ou de retirer, demande. Cette liste est une décision d'équipe, pas une déduction :

- « Quelles directions interviennent sur cette évolution ? »
- « Qui produit le cadrage ? la conception ? qui valide la sécurité ? »
- « Une étape de votre process n'a-t-elle pas encore d'agent ? »

Un retrait qui casse la chaîne producteur → consommateur est signalé : relaie l'avertissement tel
quel, il annonce une porte qui restera fermée.

## 5. Vérifier, et rendre la main

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status
```

Lis la sortie à voix haute pour l'utilisateur : quelle étape est courante, **qui est attendu**, ce
qui bloque. Puis propose `/aidlc-core:run` et arrête-toi.

## Ce que tu ne fais pas

- Tu n'écris jamais `aidlc.json` avec l'outil Write : un hook `PreToolUse` le refuse, et c'est
  voulu — un agent n'édite pas les règles qui le jugent. La sous-commande `workflow` est le seul
  chemin, parce qu'elle valide ce qu'elle écrit.
- Tu ne touches pas aux seuils (`maturity_threshold`, `min_axis_score`,
  `consecutive_runs_to_autonomy`). Si l'utilisateur veut les changer, dis-lui que c'est une
  décision d'équipe, à prendre à la main dans un terminal.
- Tu ne produis aucun livrable. Si l'utilisateur enchaîne sur le cadrage, bascule sur
  `/aidlc-core:run`.
