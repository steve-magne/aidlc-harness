---
name: new-stage
description: Concevoir une nouvelle étape du SDLC avec le professionnel métier qui en est responsable (architecte, tech lead, QA lead, SRE, support), puis générer et remplir son plugin complet — agent, skill, template, checks déterministes. À utiliser quand une étape de pipeline.json est encore au statut planned, ou quand on veut ajouter une étape qui n'existe pas.
argument-hint: "[stage] — id de l'étape à concevoir (ex: design, test, security-review)"
---

# Concevoir une nouvelle étape du pipeline

C'est la pièce maîtresse du harness : le moment où un humain métier transfère son savoir-faire dans
une étape automatisable. Tu **mènes un entretien**, tu ne devines pas. Une étape mal spécifiée
produira des livrables mal notés pendant des mois.

## Conventions — cette skill est une skill d'auteur

Tu travailles dans le **dépôt auteur du harnais** (celui qui contient `plugins/` et
`.claude-plugin/marketplace.json`), pas dans un projet consommateur. Le plugin `aidlc-core`
installé est `${CLAUDE_PLUGIN_ROOT}` ; la racine du dépôt auteur est `${CLAUDE_PLUGIN_ROOT}/../..`
— vérifie qu'elle contient bien `plugins/` et `.claude-plugin/`, sinon arrête-toi : on ne conçoit
pas de nouvelle étape depuis une copie installée du harnais.

Le pipeline à lire et à modifier est celui du noyau : `${CLAUDE_PLUGIN_ROOT}/pipeline.json`. Le
script unique se lance par `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py"`. Les chemins
`plugins/aidlc-<stage>/…` cités plus bas sont relatifs à la racine du dépôt auteur.

## Règle du dialogue

- Une question à la fois, ou par petits blocs de deux ou trois questions liées.
- Tu ne passes jamais au bloc suivant tant que le précédent n'a pas de réponse exploitable.
- Si une réponse est vague (« ça doit être complet », « il faut que ce soit bien »), tu redemandes
  en exigeant un critère observable : « comment un script pourrait-il vérifier ça ? ».
- Tu proposes des exemples par défaut inspirés de l'étape `plan` (`plugins/aidlc-plan/`), mais
  l'humain tranche.
- Tu notes les réponses au fur et à mesure dans `.aidlc/tmp/new-stage-<stage>.md` pour ne rien
  perdre si la session est interrompue.

## 0. Préparer le terrain

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status
```

Lis `${CLAUDE_PLUGIN_ROOT}/pipeline.json` et l'étape ciblée.

- L'étape existe avec `"status": "planned"` -> tu as déjà son `deliverable`, ses `inputs`, son
  `human_role` et son `plugin`. Ce sont des propositions : fais-les valider au bloc 1.
- L'étape n'existe pas -> il faudra créer son entrée dans `pipeline.json` avant le scaffold
  (bloc 8). Demande à quelle position elle s'insère dans la chaîne.
- L'étape existe avec `"status": "implemented"` -> **arrête-toi**. On ne reconçoit pas une étape
  vivante ici ; propose `/aidlc-core:improve <stage>` pour la faire évoluer, ou l'option `--force`
  du scaffold si l'humain veut vraiment tout réécrire (et préviens-le que le contenu sera perdu).

Lis aussi, comme référence de ce que « bon » veut dire :
`plugins/aidlc-plan/skills/plan/SKILL.md`, `plugins/aidlc-plan/templates/intent.md`,
`plugins/aidlc-plan/checks.json`.

## 1. Questions — identité de l'étape

1. « Quel est le nom métier de cette étape, en français, tel que vous l'appelez dans l'équipe ? »
2. « Quel identifiant technique court, en anglais, sans accent ni espace ? (ex : `design`, `test`) »
3. « Où se place-t-elle exactement ? Quelle étape la précède, quelle étape la suit ? »
4. « Que se passe-t-il, concrètement, si on saute cette étape ? » — si la réponse est « rien de
   grave », l'étape ne mérite peut-être pas d'exister. Pose franchement la question.

## 2. Questions — le livrable

5. « Quel est le **seul** fichier que cette étape produit ? Son nom, son extension. »
   Un livrable = un fichier dans `deliverables/<stage>/`. Si l'humain en veut plusieurs, fais-le
   choisir le document maître ; les autres seront des annexes citées dedans.
6. « Qui lit ce document, et pour en faire quoi ? »
7. « Combien de pages ou de mots, dans la vraie vie ? Un minimum en dessous duquel c'est du vent ? »
8. « Montrez-moi le meilleur exemplaire que vous ayez écrit. » — s'il existe, lis-le : c'est la
   meilleure source pour le template.

## 3. Questions — les entrées

9. « De quels documents amont cette étape dépend-elle ? » (chemins dans `deliverables/`)
10. « Le livrable doit-il **citer** ses entrées explicitement ? » -> `must_reference_inputs`.
11. « Quelles sources de vérité hors pipeline faut-il consulter ? » (normes, ADR, glossaire,
    référentiels) -> à inscrire dans `knowledge/index.json`.

## 4. Questions — la structure

12. « Quelles sections doit contenir le document, dans l'ordre, avec leur titre exact ? »
    Note-les au format markdown exact, par exemple `## Contraintes`.
13. Pour chaque section : « qu'est-ce qu'une section vide-mais-remplie, celle qu'on voit passer en
    revue et qui ne sert à rien ? » — la réponse alimente les motifs interdits.
14. « Quelles sections doivent contenir une liste, et combien d'éléments au minimum ? »
    -> `min_items_per_section`.
15. « Quelles métadonnées en tête de document ? » (par défaut : `stage`, `version`, `status`,
    `author`, `date`) -> `required_frontmatter`.

## 5. Questions — les critères vérifiables par machine

C'est le bloc le plus important. Traduis chaque exigence métier en une règle de `checks.json`.
Les règles disponibles sont **exactement** celles-ci — n'en invente aucune autre :

| Règle | Ce qu'elle vérifie |
|---|---|
| `required_frontmatter` | clés obligatoires du bloc `---` en tête |
| `required_sections` | titres markdown exacts obligatoires |
| `min_words` / `max_words` | volume du document |
| `forbidden_patterns` | regex interdites (marqueurs de brouillon, texte de remplissage) |
| `required_patterns` | regex obligatoires (un identifiant, une date, une unité…) |
| `must_reference_inputs` | chaque entrée de l'étape est citée dans le texte |
| `min_items_per_section` | nombre minimum de puces par section |

16. « Citez trois défauts que vous refusez systématiquement en relecture. » Pour chacun :
    « quelle règle du tableau ci-dessus l'attrape ? ». Si aucune ne l'attrape, c'est un critère
    humain : garde-le pour l'agent et le reviewer, pas pour `checks.json`.
17. « Y a-t-il un format imposé quelque part ? » (identifiant de ticket, semver, date ISO, unité
    chiffrée) -> `required_patterns`.
18. « Quels mots signalent à coup sûr un document non fini chez vous ? » -> `forbidden_patterns`.

Rappelle la frontière : `checks.json` vérifie la **forme**, le reviewer juge le **fond**. Ne fais pas
porter à une expression régulière un jugement de qualité.

## 6. Questions — le facteur humain

19. « Quel rôle valide ce livrable ? » -> `human_role` (ex : « Architecte de solution »).
20. « Quelles questions cette personne pose-t-elle systématiquement ? » -> ce sont les questions que
    l'agent de l'étape devra poser **avant** elle, pour lui faire gagner ce tour.
21. « Après combien de livrables conformes d'affilée accepteriez-vous de ne plus relire ? »
    Compare à `consecutive_runs_to_autonomy` de `pipeline.json` ; si l'humain veut un autre chiffre,
    signale-le, mais ce seuil est global au pipeline — ne le change pas sans son accord explicite.
22. « Sur les quatre axes de maturité — complétude, précision, traçabilité, autonomie — lequel est le
    plus critique pour cette étape ? » -> à rappeler dans le SKILL.md généré.

## 7. Récapituler avant d'écrire

Affiche une fiche de synthèse : id, nom, livrable, entrées, sections, règles de checks, rôle humain.
Demande explicitement : « Est-ce que je génère le plugin sur cette base ? »
**N'appelle pas `scaffold` avant un oui clair.**

## 8. Générer le plugin

Si l'étape n'existe pas dans `pipeline.json`, ajoute d'abord son entrée à la bonne position, sur le
modèle exact des autres :

```json
{"id":"<stage>","name":"<Nom>","plugin":"aidlc-<stage>","skill":"aidlc-<stage>:<stage>",
 "deliverable":"deliverables/<stage>/<fichier>","inputs":["..."],
 "checks":"checks/<stage>.json","human_role":"<rôle>","status":"planned"}
```

Puis :

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" scaffold <stage>
```

Le script crée `plugins/aidlc-<stage>/` (plugin.json, `agents/<stage>-analyst.md`,
`skills/<stage>/SKILL.md`, le template, `checks.json`), bascule `status` à `implemented` dans
`${CLAUDE_PLUGIN_ROOT}/pipeline.json`, crée le miroir `${CLAUDE_PLUGIN_ROOT}/checks/<stage>.json`
et ajoute l'entrée dans `.claude-plugin/marketplace.json` (racine du dépôt auteur).
Il refuse d'écraser un dossier existant sans `--force` : si tu tombes sur ce refus, **ne force pas
de ta propre initiative**, demande.

## 9. Remplir les fichiers générés

Le scaffold produit des squelettes. C'est toi qui les rends utiles, avec le contenu de l'entretien.

1. **`plugins/aidlc-<stage>/checks.json`** — d'abord, car il fixe le contrat.
   Traduis les blocs 4 et 5. Ne mets que des règles du tableau. Le JSON doit parser.
2. **`plugins/aidlc-<stage>/templates/<fichier>`** — le squelette du livrable : frontmatter YAML avec
   les clés de `required_frontmatter`, puis les `required_sections` dans l'ordre, chacune avec une
   ligne d'intention. Les marqueurs à remplir sont entre chevrons (`<…>`) et sont le **seul**
   endroit du dépôt où un marqueur de remplissage est autorisé.
3. **`plugins/aidlc-<stage>/skills/<stage>/SKILL.md`** — la recette : les questions du bloc 6.20 à
   poser au métier, la structure attendue, l'obligation de citer les entrées, et la remise de la
   validation à l'orchestrateur (`/aidlc-core:run <stage>`) qui la rejoue avant la revue.
4. **`plugins/aidlc-<stage>/agents/<stage>-analyst.md`** — le profil de l'interlocuteur : il dialogue
   avec le `human_role`, ne devine pas, interroge le `librarian` pour le contexte existant.
5. **`knowledge/index.json`** — ajoute les sources de vérité citées au bloc 3.11.

## 10. Vérifier avant de rendre

```bash
python3 -c "import json;[json.load(open(p)) for p in ['${CLAUDE_PLUGIN_ROOT}/pipeline.json','.claude-plugin/marketplace.json']]" && echo "JSON racine OK"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py" status
```

Vérifie de la même façon que `plugins/aidlc-<stage>/checks.json` et
`plugins/aidlc-<stage>/.claude-plugin/plugin.json` parsent.

Puis teste les checks à blanc : copie le template dans `deliverables/<stage>/<fichier>`, lance
`validate <stage>`, et vérifie qu'il **échoue** — un template non rempli doit être rejeté. S'il
passe, tes checks sont trop lâches : retourne au bloc 5. Supprime ensuite le fichier de test.

## 11. Faire relire par l'humain

Présente au professionnel métier, en clair :

- le template, section par section ;
- la liste des règles de `checks.json` **traduites en français** (« le document doit contenir au
  moins 3 puces sous *Critères d'acceptation* »), pas le JSON brut ;
- les questions que l'agent lui posera au prochain run.

Demande : « Est-ce que vous signeriez un document conforme à ça sans le relire ? »
Si la réponse est non, demande ce qui manque et boucle sur les blocs 4, 5 et 9. C'est normal : deux
ou trois tours ici valent mieux que dix livrables refusés plus tard.

## Conditions d'arrêt

Tu t'arrêtes si : l'étape est déjà `implemented`, l'humain ne valide pas la fiche du bloc 7, le
scaffold refuse d'écraser un dossier, ou un JSON généré ne parse pas. Tu ne génères jamais un plugin
sur des réponses devinées, et tu n'écris jamais de second script — toute logique déterministe
appartient à `aidlc.py`.
