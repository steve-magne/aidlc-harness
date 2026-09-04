# Plugin `aidlc-plan` — l'étape Plan du harness AI-DLC

`aidlc-plan` est le plugin de la première étape du pipeline : **Plan**. C'est la tranche verticale
de référence du harnais : elle démontre de bout en bout comment une étape est conçue (agent,
skill, template, checks déterministes) et sert de modèle aux autres étapes, générées par
`aidlc.py scaffold <stage>` dans le dépôt auteur.

## Deux racines

Ce plugin est **installé par Claude Code** (marketplace `aidlc`, copie en cache désignée par
`${CLAUDE_PLUGIN_ROOT}`) et s'exécute dans un **projet consommateur** (`$CLAUDE_PROJECT_DIR`).
Le livrable `deliverables/plan/intent.md` est produit **dans le projet consommateur** ; le
squelette (`templates/`), le contrat (`checks.json`) et l'agent/skill de ce plugin restent dans le
plugin. Le pipeline est porté par le plugin `aidlc-core` (avec le miroir `checks/plan.json` de ce
contrat). Les skills et agents de ce plugin ne lancent pas le script du harnais : la validation
est déclenchée par le hook de `aidlc-core` à chaque écriture et rejouée par l'orchestrateur.

## Ce que fait ce plugin

- **Cadre le besoin réel** en dialoguant avec le **Product Owner / Business Analyst** — le rôle
  humain qui détient le besoin et qui signe le livrable.
- **Produit l'unique livrable de l'étape** : `deliverables/plan/intent.md` **dans le projet
  consommateur**, l'*intention produit* (ce qu'il faut faire et pourquoi — jamais le comment
  technique, qui appartient à l'étape Design).
- **Fait valider le livrable de façon déterministe** par le harnais (hook de `aidlc-core` à
  chaque écriture, puis `validate plan` rejoué par l'orchestrateur) contre son `checks.json`.
- **Passe la main** à la revue de maturité (agent `reviewer` de `aidlc-core`) puis à la porte
  (`gate`) via `/aidlc-core:run plan`.

## Place dans le pipeline

```
[besoin métier]
     |
     v
  plan  --> intent.md --------> design --> spec.md --> build --> ...
```

L'étape Plan n'a **aucune entrée amont** (`"inputs": []` dans `pipeline.json`) : sa matière
première est l'entretien avec le Product Owner. Son livrable, lui, est l'entrée **obligatoire**
de l'étape Design (`"inputs": ["deliverables/plan/intent.md"]`).

## Arborescence

```
plugins/aidlc-plan/
  .claude-plugin/plugin.json      déclaration du plugin (nom, description, version)
  agents/
    plan-analyst.md               profil de l'analyste de cadrage (dialogue avec le PO)
  skills/
    plan/SKILL.md                 la recette complète de l'étape, exécutée par l'agent
  templates/
    intent.md                     le squelette du livrable (frontmatter + 8 sections)
  checks.json                     les règles de validation déterministes du livrable
```

## Déroulé d'un run

Le plugin est déclenché par l'orchestrateur (`/aidlc-core:run plan`), qui invoque la skill
`aidlc-plan:plan`. Déroulé type :

1. **Contexte** — l'analyste lit le squelette `${CLAUDE_PLUGIN_ROOT}/templates/intent.md`, le
   contrat `${CLAUDE_PLUGIN_ROOT}/checks.json` et le dossier `$CLAUDE_PROJECT_DIR/knowledge/`
   du projet. Pour une question de contexte large, il délègue à l'agent `librarian`. S'il
   existe déjà un livrable, il repart de lui (reprise : `version` incrémentée, entretien
   recentré sur les points de la dernière revue).
2. **Entretien avec le Product Owner** — questions **par salves de trois à cinq**, section par
   section, en reformulant chaque réponse pour la faire confirmer. L'analyste **ne devine
   jamais** : une information manquante se demande, ou s'écrit « hypothèse à confirmer par
   <nom> » dans la section et dans `## Sources et références`. Il relance sur les chiffres (un
   problème sans ordre de grandeur n'est pas cadré) et refuse la solution technique (le «
   comment » appartient au Design).
3. **Rédaction** — recopie `${CLAUDE_PLUGIN_ROOT}/templates/intent.md` vers
   `deliverables/plan/intent.md` (dans le projet consommateur), remplace
   chaque marqueur `<à remplir : ... >` par du contenu réel, supprime le commentaire d'en-tête,
   conserve les huit titres de section **au caractère près** (comparés littéralement par le
   contrôle automatique) et renseigne le frontmatter (`stage: plan`, `version`, `status`,
   `author` = le Product Owner, `date` AAAA-MM-JJ).
4. **Validation** — déclenchée par le hook de `aidlc-core` à chaque écriture (corrigé jusqu'à ce
   qu'il ne signale plus rien), rejouée par l'orchestrateur (`/aidlc-core:run plan`) avant la
   revue. Aucun livrable ne se rend avec des erreurs de validation ; on ne contourne jamais un
   contrôle en éditant `checks.json` ou le squelette.
5. **Restitution** — résumé en cinq lignes au Product Owner (problème retenu, bénéfice visé,
   critères d'acceptation, hypothèses ouvertes), chemin du livrable (relatif au projet), puis
   passage à la revue : `/aidlc-core:review plan` puis `gate`.

## `checks.json` — le contrat déterministe

Les règles applicables au livrable, déclarées sans code :

| Règle | Exigence pour `intent.md` |
| --- | --- |
| `required_frontmatter` | clés obligatoires : `stage`, `version`, `status`, `author`, `date` |
| `required_sections` | huit titres markdown exacts, de `## Contexte` à `## Sources et références` |
| `min_words` / `max_words` | 250 à 2000 mots (au-delà : avertissement, pas un blocage) |
| `forbidden_patterns` | aucun `TODO`, `TBD`, `XXX`, « lorem », « à compléter », marqueur `<à remplir ... >` |
| `required_patterns` | le frontmatter doit porter `stage: plan` |
| `must_reference_inputs` | désactivé (l'étape n'a pas d'entrée) |
| `min_items_per_section` | ≥ 2 puces dans `## Contraintes`, ≥ 3 puces dans `## Critères d'acceptation` |

Le contrôle vérifie la **forme** ; le jugement du fond appartient au reviewer.

## La grille de maturité appliquée ensuite

Le reviewer de `aidlc-core` note le livrable de 0 à 5 sur quatre axes, chaque note justifiée par
une citation. Pour l'étape Plan :

| Axe | Ce qui est vérifié |
| --- | --- |
| `completeness` | les huit sections sont présentes et réellement remplies |
| `precision` | critères chiffrés, testables, sans ambiguïté (pas de « rapide », « robuste ») |
| `traceability` | les affirmations citent leurs sources et le dossier `knowledge/` |
| `autonomy` | peu d'allers-retours humains dans les journaux de session |

Le seuil de passage est `maturity_threshold` (4.0) dans `pipeline.json`.

## Règles de conception du livrable

- Un livrable = **un seul fichier** : `deliverables/plan/intent.md`, et rien d'autre.
- Chaque critère d'acceptation suit la forme « étant donné <situation>, quand <action>, alors
  <résultat observable et chiffré> ».
- Toute affirmation quantifiée cite sa source dans `## Sources et références`.
- Aucune solution technique dans ce livrable (pas de composant, de schéma, de bibliothèque).

## Relations avec `aidlc-core`

Ce plugin n'embarque aucune logique : tout le déterminisme est dans
`${CLAUDE_PLUGIN_ROOT}/../aidlc-core/scripts/aidlc.py` une fois installé (en dépôt auteur :
`plugins/aidlc-core/scripts/aidlc.py`), et le pilotage dans les skills/agents de `aidlc-core`.
`aidlc-plan` apporte uniquement le **métier** de l'étape : la recette du dialogue (`SKILL.md`),
le profil de l'interlocuteur pour l'humain (`plan-analyst.md`), le squelette du livrable
(`templates/intent.md`) et le contrat de forme (`checks.json`), dont `aidlc-core` garde un miroir
(`checks/plan.json`).