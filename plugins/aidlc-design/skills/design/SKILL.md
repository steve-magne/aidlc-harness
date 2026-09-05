---
name: design
description: Produit le livrable de conception deliverables/design/spec.md à partir de l'intention produit, en dialoguant avec l'architecte d'entreprise, puis le valide avec aidlc.py. À utiliser pour lancer, reprendre ou corriger l'étape Design du pipeline AI-DLC.
argument-hint: [titre de l'initiative à concevoir]
---

# Étape Design — produire `deliverables/design/spec.md`

Recette complète de l'étape Design du harness AI-DLC. Le livrable unique est
`deliverables/design/spec.md` : la conception d'entreprise qui répond à l'intention produit et
sert d'entrée à l'étape Build.

**Rôle humain de référence : Architecte d'entreprise.** C'est lui qui engage le SI, c'est lui qui
signe. L'agent rédige, l'humain décide.

## Conventions

- Ce plugin (`aidlc-design`) est `${CLAUDE_PLUGIN_ROOT}` : ton squelette et tes règles s'y trouvent.
- Le livrable est `deliverables/design/spec.md`, **relatif au projet consommateur**
  (`$CLAUDE_PROJECT_DIR`).
- **Ton entrée est `deliverables/plan/intent.md`.** Elle n'est pas optionnelle : c'est le contrat
  que tu instruis. Si elle manque ou si sa porte n'est pas franchie, arrête-toi et dis-le —
  l'orchestrateur lancera `/aidlc-core:run plan` d'abord. On ne conçoit pas sur du sable.
- Tu ne lances pas le script du harnais toi-même (il vit dans `aidlc-core`) : la validation
  déterministe est déclenchée par son hook à chaque écriture du livrable, et l'orchestrateur la
  rejoue avant la revue.

## 0. Avant de commencer

Rassemble le contexte, dans cet ordre :

1. **`deliverables/plan/intent.md`** — lis-la en entier. Retiens nommément : le problème retenu,
   les personas et leur volumétrie, les bénéfices attendus et leurs KPIs chiffrés, les
   contraintes, les critères d'acceptation, et surtout la section `## Hors périmètre`.
2. `${CLAUDE_PLUGIN_ROOT}/templates/spec.md` — le squelette à recopier.
3. `${CLAUDE_PLUGIN_ROOT}/checks.json` — les règles automatiques appliquées au rendu.
4. `$CLAUDE_PROJECT_DIR/knowledge/index.md`, `glossary.md` et `conventions.md` — le bundle OKF du
   projet. Pour une question de contexte large, délègue à l'agent `librarian`.

Si un livrable `deliverables/design/spec.md` existe déjà, lis-le : tu es en **reprise**. Repars de
son contenu, incrémente `version` dans le frontmatter et concentre l'entretien sur les points
signalés par la revue ou par la dernière validation.

**Cas particulier — l'intention a changé depuis ta dernière revue.** L'orchestrateur te le dira
(`status` affiche « Entrée amont modifiée »). Ce n'est pas une reprise ordinaire : commence par
diffuser ce qui a bougé dans `intent.md` et demande à l'architecte quelles décisions de conception
cela remet en cause. Une spec qui ignore une intention révisée est un livrable faux, pas un
livrable en retard.

## 1. Cadrer l'entretien

Annonce à l'architecte ce que tu vas produire, en une phrase, et le plan de l'entretien : neuf
sections, des questions par salves, environ vingt minutes. Commence par lui restituer l'intention
en cinq lignes et fais-la confirmer — c'est la base de tout le reste.

## 2. Mener l'entretien, section par section

Pose les questions **par salves de trois à cinq**, jamais une par une : le nombre d'allers-retours
est noté par le reviewer sur l'axe `autonomy`. Après chaque salve, reformule et fais confirmer.

| Section du livrable | Questions à poser |
| --- | --- |
| `## Contexte` | Qu'est-ce que l'intention demande, dans tes mots ? Quel fait mesuré justifie de concevoir maintenant ? Quels personas et quels volumes retiens-tu ? |
| `## Capacités et dépendances SI` | Quelles capacités métier sont touchées, et quelle application les porte ? Qu'est-ce qu'on crée, qu'est-ce qu'on étend, qu'est-ce qu'on remplace ? De quelles équipes dépend-on, et sur quel contrat d'interface ? |
| `## Architecture cible` | Quels composants, quels flux, quels points d'intégration ? Où vit la donnée de référence, et qui en est propriétaire ? Quelle est la décision la plus coûteuse à défaire ? |
| `## Options écartées` | Quelles autres architectures ont été envisagées ? Quel critère a tranché — coût, délai, dépendance, risque ? Qu'est-ce qui ferait rouvrir ce choix ? |
| `## Exigences non fonctionnelles` | Quel seuil de performance, mesuré où et sur quel parcours (p95, p99) ? Quel objectif de disponibilité, sur quelle fenêtre ? Quelle exigence de sécurité ou de conformité, et quel texte de référence ? |
| `## Risques et mitigations` | Qu'est-ce qui peut faire échouer cette conception ? Quelle probabilité, quel impact ? Quelle mitigation, portée par qui ? |
| `## Critères d'acceptation` | À quoi reconnaît-on que la conception est respectée ? Comment le mesure-t-on, avec quel seuil ? Quel mode dégradé doit être couvert ? |
| `## Hors périmètre` | Que ne traite-t-on pas ici, et pourquoi ? Qu'est-ce qui est reporté, à quelle échéance ? |
| `## Sources et références` | Sur quelle version de l'intention conçois-tu ? Qui a été interrogé, quand ? Quels documents de `knowledge/` font autorité ? |

Règles d'entretien :

- **Ne devine jamais.** Une information manquante se demande. Si elle reste indisponible, écris
  « hypothèse à confirmer par <nom> » dans la section et reporte-la dans
  `## Sources et références`.
- **Le hors périmètre de l'intention est opposable.** Ce que le Product Owner a exclu reste exclu :
  si l'architecte veut le réintroduire, c'est une reprise de l'étape Plan, pas une décision de
  conception. Le contrôle `must_not_violate_scope` le vérifie et rejette le livrable.
- **Refuse le niveau implémentation.** Choix de bibliothèque, structure de classes, découpage de
  tickets : c'est l'étape Build. Note-les comme pistes dans `## Sources et références`.
- **Relance sur les chiffres.** Une exigence non fonctionnelle sans seuil et sans unité n'est pas
  une exigence, c'est un souhait.

## 3. Rédiger le livrable

Recopie `${CLAUDE_PLUGIN_ROOT}/templates/spec.md` vers `deliverables/design/spec.md` (relatif au
projet consommateur), puis :

- remplace **chaque** marqueur `<à remplir : ... >` par du contenu réel ;
- supprime le commentaire HTML d'en-tête du squelette ;
- conserve les neuf titres de section **au caractère près**, accents compris ;
- renseigne le frontmatter : `stage: design`, `version` (entier, incrémenté à chaque reprise),
  `status` (`draft` puis `review`), `author` (l'architecte), `date` au format `AAAA-MM-JJ` ;
- vise 350 à 2500 mots.

**Citation de l'entrée (règle `required_input_section`)** — le chemin
`deliverables/plan/intent.md` doit apparaître **dans la section `## Contexte`**, pas seulement
ailleurs dans le document. C'est plus strict que `must_reference_inputs` : la conception doit
s'ouvrir sur ce qu'elle instruit.

**Preuve d'exécution (règle `proof_of_run`)** — `## Contexte`,
`## Exigences non fonctionnelles` et `## Critères d'acceptation` doivent chacun contenir une
valeur observée concrète (chiffre + unité, date, chemin, id, p95/p99). Une exigence qui reformule
l'attendu sans seuil est rejetée.

**Holdout (règle `checks_do_not_self_reference`)** — ne citez jamais le contenu de votre
`checks.json` dans le livrable. La spec s'écrit contre l'ouvrage, pas contre le mètre.

## 4. Valider — obligatoire avant de rendre

La validation déterministe est déclenchée **automatiquement par le hook du plugin `aidlc-core`** à
chaque écriture de `deliverables/design/spec.md`. Corrige et réécris jusqu'à ce que le hook ne
signale plus rien — **aucun livrable ne se rend avec des erreurs de validation.**

| Erreur | Correction |
| --- | --- |
| Section manquante | Le titre a été reformulé ou désaccentué : recopie-le depuis le squelette. |
| Motif interdit | Un `TODO`, `TBD`, `XXX`, « à compléter » ou un marqueur `<à remplir : ... >` subsiste. |
| Input non référencé dans `## Contexte` | Cite `deliverables/plan/intent.md` dans le Contexte lui-même. |
| Périmètre : item hors périmètre du plan non déclaré | L'intention exclut quelque chose que la spec traite : soit tu l'exclus aussi dans `## Hors périmètre`, soit tu n'y touches pas. |
| Preuve d'exécution absente | Une section déclarée « preuve » n'affiche aucune valeur observée : chiffre les exigences et les critères, cite la source. |
| Trop peu de puces | Ajoute de vraies puces dans la section signalée — pas de puce vide pour faire le compte. |
| Livrable trop court | Moins de 350 mots : la conception n'est pas exploitable par l'étape Build. |

Ne contourne jamais un contrôle en modifiant `checks.json` ou le squelette. Si une règle est jugée
fausse, signale-le : c'est la skill `aidlc-core:improve` qui fait évoluer les règles, avec l'accord
de l'humain.

## 5. Rendre

Une fois la validation au vert :

1. Résume à l'architecte, en cinq lignes maximum : l'architecture retenue, la décision
   structurante, les options écartées, les risques ouverts.
2. Donne le chemin du livrable : `deliverables/design/spec.md`.
3. Passe la main à la revue — `/aidlc-core:review` puis `gate` via `/aidlc-core:run design`. Tu ne
   notes pas ton propre livrable et tu n'écris jamais dans `.aidlc/`.

## Critères de qualité que le reviewer va appliquer

| Axe (0 à 5) | Ce qui est vérifié |
| --- | --- |
| completeness | Les neuf sections sont présentes et réellement remplies. |
| precision | Exigences chiffrées avec leur unité, décisions tranchées et non énumérées. |
| traceability | L'intention amont est citée et correctement interprétée ; les sources font autorité. |
| autonomy | Peu d'allers-retours humains dans les journaux de la session. |

Le seuil de passage est défini par `maturity_threshold` dans `pipeline.json`.
