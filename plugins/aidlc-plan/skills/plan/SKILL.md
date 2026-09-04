---
name: plan
description: Produit le livrable de cadrage deliverables/plan/intent.md en dialoguant avec le Product Owner, puis le valide avec aidlc.py. À utiliser pour lancer, reprendre ou corriger l'étape Plan du pipeline AI-DLC.
argument-hint: [titre de l'initiative à cadrer]
---

# Étape Plan — produire `deliverables/plan/intent.md`

Recette complète de l'étape Plan du harness AI-DLC. Le livrable unique est
`deliverables/plan/intent.md` : l'intention produit, qui sert d'entrée à l'étape Design.

**Rôle humain de référence : Product Owner / Business Analyst.** C'est lui qui détient le besoin,
c'est lui qui signe. L'agent rédige, l'humain décide.

## Conventions

- Ce plugin (`aidlc-plan`) est `${CLAUDE_PLUGIN_ROOT}` : ton squelette et tes règles s'y trouvent.
- Le livrable est `deliverables/plan/intent.md`, **relatif au projet consommateur**
  (`$CLAUDE_PROJECT_DIR`). Le pipeline (ordre des étapes, entrées) est porté par le plugin
  `aidlc-core` : l'étape Plan n'a **aucune** entrée amont, sa matière première est l'entretien
  avec le Product Owner.
- Tu ne lances pas le script du harnais toi-même (il vit dans `aidlc-core`) : la validation
  déterministe est déclenchée par son hook à chaque écriture du livrable, et l'orchestrateur la
  rejoue avant la revue.

## 0. Avant de commencer

Rassemble le contexte, dans cet ordre :

1. `${CLAUDE_PLUGIN_ROOT}/templates/intent.md` — le squelette à recopier.
2. `${CLAUDE_PLUGIN_ROOT}/checks.json` — les règles automatiques appliquées au rendu.
3. `$CLAUDE_PROJECT_DIR/knowledge/index.md`, `$CLAUDE_PROJECT_DIR/knowledge/glossary.md` et
   `$CLAUDE_PROJECT_DIR/knowledge/conventions.md` — le bundle OKF du projet : sommaire,
   vocabulaire et conventions de la base qui font autorité. Pour une question de contexte
   large, délègue à l'agent `librarian`.

Si un livrable `deliverables/plan/intent.md` existe déjà, lis-le : tu es en **reprise**. Repars
de son contenu, incrémente `version` dans le frontmatter et concentre l'entretien sur les points
signalés par la revue ou par la dernière validation.

## 1. Cadrer l'entretien

Annonce au Product Owner ce que tu vas produire, en une phrase, et le plan de l'entretien :
huit sections, des questions par salves, environ un quart d'heure. Demande le titre court de
l'initiative s'il n'a pas été donné en argument.

## 2. Mener l'entretien, section par section

Pose les questions **par salves de trois à cinq**, jamais une par une : le nombre
d'allers-retours est noté par le reviewer sur l'axe `autonomy`. Après chaque salve, reformule les
réponses en une ou deux phrases et fais-les confirmer.

| Section du livrable | Questions à poser |
| --- | --- |
| `## Contexte` | D'où vient la demande ? Quel évènement l'a déclenchée, et quand ? Qu'existe-t-il déjà (outil, procédure, contournement manuel) ? |
| `## Problème` | Le problème en une phrase, sans nommer de solution ? Quel chiffre le prouve, mesuré où et sur quelle période ? Que coûte l'inaction ? |
| `## Utilisateurs impactés` | Qui subit le problème, combien de personnes, à quelle fréquence ? Quels rôles internes sont touchés indirectement ? |
| `## Solution proposée` | Quel changement observable veut-on obtenir ? Quel bénéfice mesurable, à quelle échéance ? Quelles alternatives ont été écartées, et pourquoi ? |
| `## Contraintes` | Quelles obligations réglementaires, et quel texte de référence ? Quel budget, quelle échéance ferme, quelles dépendances externes ? |
| `## Critères d'acceptation` | À quoi reconnaît-on que c'est fait ? Comment le mesure-t-on, avec quel seuil ? Quel cas d'erreur doit être couvert ? |
| `## Hors périmètre` | Qu'est-ce qui est explicitement exclu de cette itération ? Qu'est-ce qui est reporté, et à quelle échéance ? |
| `## Sources et références` | Qui a été interrogé, quand ? Quels documents du dossier `knowledge/` font autorité ? D'où viennent les chiffres ? |

Règles d'entretien :

- **Ne devine jamais.** Une information manquante se demande. Si elle reste indisponible, écris
  « hypothèse à confirmer par <nom> » dans la section et reporte-la dans
  `## Sources et références`.
- **Relance sur les chiffres.** Un problème sans ordre de grandeur n'est pas cadré ; un critère
  sans seuil n'est pas testable.
- **Refuse la solution technique.** Si le Product Owner décrit une implémentation, note-la comme
  piste dans `## Sources et références` et ramène la conversation au besoin. Le « comment »
  appartient à l'étape Design.

## 3. Rédiger le livrable

Recopie `${CLAUDE_PLUGIN_ROOT}/templates/intent.md` vers `deliverables/plan/intent.md` (relatif
au projet consommateur), puis :

- remplace **chaque** marqueur `<à remplir : ... >` par du contenu réel ;
- supprime le commentaire HTML d'en-tête du squelette ;
- conserve les huit titres de section **au caractère près**, accents compris : ils sont comparés
  littéralement par le contrôle automatique ;
- renseigne le frontmatter : `stage: plan`, `version` (entier, incrémenté à chaque reprise),
  `status` (`draft` puis `review`), `author` (le Product Owner), `date` au format `AAAA-MM-JJ` ;
- rédige au moins **2 puces** dans `## Contraintes` et **3 puces** dans
  `## Critères d'acceptation` ;
- vise 250 à 2000 mots : en dessous, le cadrage est trop pauvre ; au-dessus, il déborde sur le
  Design.

Forme attendue d'un critère d'acceptation : « étant donné <situation>, quand <action>, alors
<résultat observable, chiffré, avec son unité> ».

## 4. Valider — obligatoire avant de rendre

La validation déterministe est déclenchée **automatiquement par le hook du plugin `aidlc-core`**
à chaque écriture de `deliverables/plan/intent.md` : le retour du hook te liste immédiatement les
manques (`errors`) et les avertissements (`warnings`). Corrige et réécris jusqu'à ce que le hook
ne signale plus rien — **aucun livrable ne se rend avec des erreurs de validation.**

Quand le hook ne s'est pas déclenché (session sans plugin `aidlc-core`, ou besoin d'une passe
explicite), rends la main à l'orchestrateur : `/aidlc-core:run plan` rejoue `validate` avant la
revue. Ne cherche pas à appeler le script du harnais depuis ce plugin.

Les erreurs les plus fréquentes et leurs corrections :

| Erreur | Correction |
| --- | --- |
| Section manquante | Le titre a été reformulé ou désaccentué : recopie-le depuis le squelette. |
| Motif interdit | Un `TODO`, `TBD`, `XXX`, « à compléter » ou un marqueur `<à remplir : ... >` subsiste. |
| Clé de frontmatter manquante | Complète le bloc `---` en tête : `stage`, `version`, `status`, `author`, `date`. |
| Trop peu de puces | Ajoute de vraies puces (`-`) dans `## Contraintes` ou `## Critères d'acceptation` — pas de puce vide pour faire le compte. |
| Livrable trop court (erreur) | Enrichis les sections pauvres : moins de 250 mots, le cadrage n'est pas exploitable par l'étape Design. |
| Livrable long (avertissement) | Au-delà de 2000 mots le contrôle passe mais signale le débordement : coupe ce qui relève du Design. |

Ne contourne jamais un contrôle en modifiant `checks.json` ou le squelette. Si une règle est
jugée fausse, signale-le : c'est la skill `aidlc-core:improve` qui fait évoluer les règles, avec
l'accord de l'humain.

## 5. Rendre

Une fois la validation au vert :

1. Résume au Product Owner, en cinq lignes maximum : le problème retenu, le bénéfice visé, les
   critères d'acceptation, les hypothèses restées ouvertes.
2. Donne le chemin du livrable : `deliverables/plan/intent.md` (relatif au projet consommateur).
3. Passe la main à la revue — `/aidlc-core:review` puis `gate` via `/aidlc-core:run plan`. Tu ne
   notes pas ton propre livrable et tu n'écris jamais dans `.aidlc/`.

## Critères de qualité que le reviewer va appliquer

| Axe (0 à 5) | Ce qui est vérifié |
| --- | --- |
| completeness | Les huit sections sont présentes et réellement remplies. |
| precision | Critères chiffrés, testables, sans ambiguïté. |
| traceability | Les affirmations citent leurs sources et le dossier `knowledge/`. |
| autonomy | Peu d'allers-retours humains dans les journaux de la session. |

Le seuil de passage est défini par `maturity_threshold` dans `pipeline.json`.
