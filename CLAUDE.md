# Conventions du dépôt aidlc-harness

Ce fichier est lu par **tout agent** qui travaille dans ce dépôt. Il prime sur les habitudes générales.

## Rôle du dépôt

`aidlc-harness` est un harnais agentique d'entreprise pour le **AI-native SDLC**. Un orchestrateur
instancie une session agentique par étape du cycle de vie (Plan → Design → Build → Test → Deploy →
Maintain). Le livrable d'une étape est l'entrée de la suivante. Chaque étape est un **plugin Claude
Code** : un agent, une ou plusieurs skills, un template, des vérifications déterministes (`checks.json`)
et des hooks. Chaque session est journalisée en JSONL. Après chaque livrable, un agent *reviewer* note
la maturité ; sous le seuil, une revue humaine est obligatoire ; les refus alimentent une boucle
d'auto-amélioration.

## Langue

- **Français** (accents corrects) : documentation, `SKILL.md`, prompts d'agents, messages destinés à
  l'utilisateur.
- **Anglais** : identifiants, noms de fichiers, chemins, clés JSON, code Python.

## Arborescence

```
README.md                     présentation et quickstart
CLAUDE.md                     ce fichier
pipeline.json                 source de vérité des étapes du SDLC
.claude-plugin/               marketplace local (marketplace.json)
docs/ARCHITECTURE.md          architecture, grille de maturité, cycle de vie
knowledge/                    base de connaissance servie par l'agent librarian
plugins/aidlc-core/           noyau : orchestrator, reviewer, librarian, aidlc.py, hooks, skills
plugins/aidlc-<stage>/        une étape = un plugin (agent, skill, template, checks.json)
deliverables/<stage>/         les livrables versionnés
.aidlc/                       état runtime (logs, maturity.json, reviews, tmp)
```

## Règles non négociables

1. **Un livrable = un fichier dans `deliverables/<stage>/`**, au chemin exact déclaré par
   `pipeline.json`. Pas de livrable ailleurs, pas de livrable éclaté en plusieurs fichiers.
2. **Toute logique déterministe va dans `plugins/aidlc-core/scripts/aidlc.py`.** Jamais dans un
   nouveau script, jamais dans un `Makefile`, jamais dans un shell inline dans un hook. Si une
   nouvelle vérification est nécessaire, elle s'exprime d'abord de façon **déclarative** dans le
   `checks.json` de l'étape ; on ne touche au Python que si aucune règle existante ne convient.
3. **Aucune dépendance externe.** Bibliothèque standard Python uniquement (`json`, `os`, `sys`, `re`,
   `pathlib`, `argparse`, `datetime`, `uuid`, `subprocess`, `statistics`). Pas de `pip install`, pas
   de YAML, pas de framework de test.
4. **`.aidlc/maturity.json` et `.aidlc/reviews/*.json` ne sont jamais édités à la main par un agent.**
   Seuls `aidlc.py score` (pour les scores) et l'humain (pour les revues) y écrivent. Un hook
   `PreToolUse` refuse activement ces écritures : c'est un garde-fou d'intégrité, pas une gêne à
   contourner.
5. **Aucun placeholder non résolu** (`TODO`, `TBD`, `<à remplir>`, « lorem ») dans un fichier livré.
   Seule exception : les marqueurs entre chevrons des `templates/`, qui sont documentés comme tels.
6. **Tout JSON doit parser, tout Python doit compiler** (`python3 -m py_compile`). Les chemins écrits
   dans `hooks.json` et dans les `SKILL.md` doivent correspondre exactement à l'arborescence réelle.
7. Les raccourcis assumés sont marqués par un commentaire `# ponytail: ...` expliquant le compromis.
   Pas d'abstraction spéculative : le moins de fichiers possible.

## Lancer les commandes

Toute la logique déterministe passe par un seul script. Depuis la racine du dépôt :

```bash
S=plugins/aidlc-core/scripts/aidlc.py

python3 $S status                       # tableau de bord du pipeline
python3 $S validate plan                # vérifie le livrable de l'étape plan
python3 $S score plan --file review.json  # enregistre une revue du reviewer
python3 $S gate plan                    # décide si l'étape est franchie (exit 2 = bloquant)
python3 $S review-request plan          # prépare le formulaire de revue humaine
python3 $S improve --stage plan         # diagnostic pour la boucle d'amélioration
python3 $S scaffold design              # génère le plugin d'une nouvelle étape
python3 $S --selftest                   # auto-test : le seul test du projet, il doit passer
```

`aidlc.py` trouve la racine du projet via `CLAUDE_PROJECT_DIR`, sinon en remontant jusqu'à
`pipeline.json`. Les sorties machine sont du JSON sur **stdout**, les messages humains sur **stderr**.
Dans les hooks, le script est appelé via `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py"`.

## Ajouter une étape

Ne créez pas un plugin d'étape à la main. Utilisez la skill `/aidlc-core:new-stage`, qui dialogue avec
le référent métier puis appelle `aidlc.py scaffold <stage>` : celui-ci génère le plugin complet, met le
`status` à `implemented` dans `pipeline.json` et ajoute l'entrée dans `.claude-plugin/marketplace.json`.
