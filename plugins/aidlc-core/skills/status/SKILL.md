---
name: status
description: Afficher le tableau de bord du pipeline AI-DLC — pour chaque étape, le plugin, le livrable, la validation, le dernier score de maturité, l'autonomie et la prochaine action. À utiliser quand on demande où en est le projet, ce qu'il reste à faire, ou pourquoi une étape est bloquée.
argument-hint: "[stage] — id d'étape pour un détail ciblé ; vide = toutes les étapes"
---

# Tableau de bord du pipeline

## Conventions

Le script unique vit dans le plugin `aidlc-core` (`${CLAUDE_PLUGIN_ROOT}`) ; le tableau de bord se
lance dans le projet consommateur (`$CLAUDE_PROJECT_DIR`), là où vivent les livrables et `.aidlc/`.
Les étapes affichées viennent du **registre d'agents** (les manifestes `agent.json` des plugins
installés, dans l'ordre dérivé de leurs livrables) ; la gouvernance — seuils, feuille de route —
vient de `${CLAUDE_PLUGIN_ROOT}/pipeline.json`.

## 1. Lire l'état

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status
```

C'est la sortie de référence, déjà mise en forme pour un terminal. **Affiche-la telle quelle.**
Ne la reformate pas, ne la résume pas, n'invente pas de colonnes.

Si tu as besoin des données brutes pour raisonner (comparer des scores, calculer une tendance) :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status --json
```

## 2. Ajouter la lecture, pas les données

Sous le tableau, ajoute au maximum cinq lignes de commentaire en français :  1. **Où en est le pipeline** : dernière étape franchie, étape courante.
2. **Ce qui bloque**, si quelque chose bloque : erreur de validation, score sous le seuil, revue
   humaine en attente. Cite le motif exact renvoyé par le script, pas une paraphrase.
3. **La prochaine action concrète**, sous forme de commande ou de skill à lancer :
   - livrable absent -> `/aidlc-core:run <stage>`
   - livrable présent mais validation en échec -> `/aidlc-core:run <stage>` (boucle de correction)
   - validation ok mais pas de score -> `/aidlc-core:review <stage>`
   - revue humaine requise -> `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" review-request <stage>`
   - étape listée en « prévu, plugin non installé » -> `/aidlc-core:new-stage <stage>`
   - « producteur absent » -> le plugin qui produit cette entrée n'est pas installé : dis lequel
   - « manifeste rejeté » -> nomme l'équipe propriétaire, c'est à elle de corriger son `agent.json`
   - scores faibles et répétés -> `/aidlc-core:improve <stage>`

## 3. Si un argument d'étape est fourni

Restreins le commentaire à cette étape et complète avec :

- le contenu de son manifeste, lu par
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" agents --json` (équipe, version, capacités,
  invocation, livrable, entrées, rôle humain, contrat) ;
- le détail de la dernière validation :
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" validate <stage> --json` ;
- l'historique de ses runs dans `.aidlc/maturity.json` (scores par axe, tendance, autonomie).

## 4. Cas particuliers

- **`.aidlc/` absent** : aucun run n'a encore eu lieu. Dis-le simplement et propose
  `/aidlc-core:run plan`. Ce n'est pas une erreur.
- **`${CLAUDE_PLUGIN_ROOT}/pipeline.json` introuvable** : le plugin `aidlc-core` est mal
  installé. Signale-le et arrête-toi ; ne crée pas de fichier de secours.
- **Registre vide** : aucun plugin d'agent n'est installé ou activé. Dis-le, et rappelle les deux
  voies — installer le plugin d'une équipe, ou pointer `AIDLC_AGENT_PATH` sur un répertoire qui
  contient des manifestes.
- **Le script sort en erreur** : affiche stderr tel quel. C'est un diagnostic, pas un incident à
  masquer.

## Condition d'arrêt

Cette skill est en **lecture seule**. Elle n'écrit aucun fichier, ne lance ni validation corrective,
ni revue, ni étape. Elle affiche, elle commente, elle propose une commande — et elle s'arrête.
