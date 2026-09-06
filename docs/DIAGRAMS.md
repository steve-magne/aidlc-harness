---
type: Reference
title: Le harnais AI-DLC en schémas
description: Vue d'ensemble du fonctionnement en diagrammes ASCII — les deux racines, le cycle d'une étape, les conditions de la porte, la découverte des agents, les hooks, les garde-fous, la boucle d'amélioration et le moteur.
tags: [architecture, schemas, harness, vue-ensemble]
generated: { by: human:steve-magne, at: 2026-09-06T00:00:00Z }
---

# Le harnais AI-DLC en schémas

Neuf schémas pour comprendre le fonctionnement sans lire une ligne de code. Chacun tient sur un
écran et répond à **une** question. C'est la carte ; le terrain est dans
[ARCHITECTURE.md](ARCHITECTURE.md), qui reprend chaque mécanisme en détail.

---

## 1. Où vivent les choses

**La question :** qu'est-ce qui est lu, et qu'est-ce qui est écrit ?

```
┌── LE HARNAIS  (${CLAUDE_PLUGIN_ROOT}) ─────────────────────────────────┐
│                                                                        │
│   aidlc-core       pipeline.json  seuils, watchdog, feuille de route   │
│                    scripts/       le moteur, stdlib uniquement         │
│                    hooks/         branchés sur la session              │
│                    agents/ skills/                                     │
│                                                                        │
│   aidlc-plan       agent.json + checks.json + template + review.md     │
│   aidlc-design     agent.json + checks.json + template + review.md     │
│   aidlc-security   agent.json seul — consultatif, pas de livrable      │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                    │  lit les règles                    ▲  n'écrit jamais ici
                    ▼                                    │
┌── LE PROJET  ($CLAUDE_PROJECT_DIR) ────────────────────────────────────┐
│                                                                        │
│   deliverables/plan/intent.md       versionné avec le code             │
│   deliverables/design/spec.md                                          │
│                                                                        │
│   .aidlc/logs/<session>.jsonl       le journal des sessions            │
│   .aidlc/maturity.json              les scores            (protégé)    │
│   .aidlc/reviews/<stage>-<n>.json   vos signatures        (protégé)    │
│   .aidlc/ratchet.json               les planchers figés   (protégé)    │
│                                                                        │
│   knowledge/                        le savoir du projet                │
│   knowledge-sources.json            les bundles OKF distants déclarés  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

Un projet consommateur **installe** le harnais et n'y touche plus : les plugins sont en lecture
seule, tout ce qui est produit atterrit dans le projet. `aidlc.py` résout les deux racines seul.
Quand le dépôt du harnais sert de projet d'essai, les deux se confondent — d'où la présence de
`deliverables/` et `.aidlc/` à sa racine.

---

## 2. Le cycle d'une étape

**La question :** que se passe-t-il entre « lance l'étape » et « l'étape est franchie » ?

```
  vous                 les agents                   le moteur (aidlc.py)
  ────                 ──────────                   ────────────────────

  /aidlc-core:run plan
        │
        ├──── orchestrateur ─────────────────────►  status
        │       « quelle étape, qu'est-ce qui bloque »
        │
        ├──── librarian ─────────────────────────►  knowledge  (projet + OKF distant)
        │       « quel contexte citable pour cette étape »
        │
        ├──── agent d'étape  ◄──── dialogue ────►  VOUS (le référent métier)
        │            │
        │            └─ Write deliverables/plan/intent.md
        │                     │
        │                     └─ hook PostToolUse ─►  validate --touched   ─┐
        │                                             check-python/json     │ à chaque
        │                                             check-okf --touched   │ écriture
        │                                             watchdog-touched     ─┘
        │                     ◄──────────────────── erreurs → l'agent corrige
        │
        ├──── reviewer ───► review.json ─────────►  score plan
        │       0–5 sur 4 axes, chaque note citée   → .aidlc/maturity.json
        │
        └──────────────────────────────────────►   gate plan
                                                     exit 0 → étape franchie
                                                     exit 2 → blocages listés
```

L'orchestrateur **ne rédige jamais** un livrable, le reviewer **ne peut pas éditer** sa note :
la séparation des droits est structurelle, pas une consigne de prompt.

---

## 3. Les six conditions de la porte

**La question :** pourquoi mon étape ne passe-t-elle pas ?

```
   validation déterministe passe   ─┐
   verdict du reviewer = accepted   │
   moyenne ≥ 4.0                    ├──  TOUTES vraies  ──►  exit 0   franchie
   aucun axe sous 3.0               │
   entrées amont inchangées         │
   revue humaine signée             ─┘   une seule fausse ──►  exit 2   + la liste
                                                                        des blocages
```

Trois pièges fréquents, dans l'ordre où on les rencontre :

- **`aucun axe sous 3.0`** — une moyenne suffisante ne rachète pas un axe effondré. Un livrable
  noté `{5, 5, 5, 1}` fait 4,0 de moyenne et **ne passe pas**.
- **`entrées amont inchangées`** — le livrable amont a bougé depuis la revue : la note ne porte
  plus sur ce qui est là. Il faut refaire noter.
- **`revue humaine signée`** — exigée tant que l'étape n'est pas autonome. Après **3 runs
  consécutifs** au-dessus du seuil et approuvés, l'étape passe `autonomous` et la signature n'est
  plus demandée à chaque passage.

---

## 4. Comment les agents sont découverts

**La question :** comment le harnais sait-il quels agents existent ?

```
   AIDLC_AGENT_PATH=/depots/equipe-x        précédence 1  (agents hors dépôt)
   plugins/ du dépôt et du projet           précédence 2
   plugins installés dans le cache          précédence 3
                    │
                    │  scan de profondeur 1 : un agent.json par plugin
                    ▼
          ┌───────────────────┐
          │     REGISTRE      │  id · team · capabilities · version · invocation
          │  (aidlc.py agents)│  produces · consumes · checks · review · human_role
          └───────────────────┘
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
    « produces » déclaré ?   pas de « produces » ?
          │                    │
    ÉTAPE GOUVERNÉE        AGENT CONSULTATIF
    validée, notée,        invocable pour un avis,
    soumise à la porte     jamais noté
    ex. plan, design       ex. security-review
```

**Le noyau ne tient aucune liste.** Publier un agent, c'est publier un plugin avec son manifeste —
le noyau n'est jamais modifié. C'est la condition de la modularité : chaque équipe maintient son
agent dans son dépôt, et `/aidlc-core:dispatch` mobilise les agents consultatifs par capacité.

---

## 5. L'ordre des étapes se dérive, il ne se déclare pas

**La question :** qui décide que `design` vient après `plan` ?

```
   plan  ──produces──►  deliverables/plan/intent.md  ──consumes──►  design
                                                                        │
                                                                    produces
                                                                        ▼
   build  ◄──consumes──  deliverables/design/spec.md  ◄──────────────────┘
   (prévu, plugin
    non installé)
```

L'ordre sort de la **chaîne producteur → consommateur** lue dans les manifestes, jamais d'une
position dans un fichier de configuration. Une entrée que personne ne produit apparaît dans
`status` sous `missing_producers` : le registre est ouvert, mais il ne rétrécit pas en silence.

---

## 6. Les hooks branchés sur la session

**La question :** qu'est-ce qui tourne automatiquement, sans que je le demande ?

```
   SessionStart          ──►  log                    trace l'ouverture
   UserPromptSubmit      ──►  log                    trace la demande
   SubagentStart / Stop  ──►  log                    trace les délégations

   PreToolUse            ──►  guard                  AVANT l'écriture : refuse
     (Write | Edit)                                  ce qui ne doit pas être écrit

   PostToolUse           ──►  validate --touched     le livrable respecte son contrat
     (Write | Edit)           check-okf --touched    le bundle de savoir reste conforme
                              check-python --touched le Python compile
                              check-json --touched   le JSON parse
                              watchdog-touched       détecte la stagnation (non bloquant)

   Stop                  ──►  log
                              check-okf --stop       refuse la fin de session si un
                                                     bundle est non conforme
```

Le journal (`.aidlc/logs/<session>.jsonl`) n'est pas décoratif : c'est la matière première de
l'axe **autonomy**, du watchdog et du diagnostic d'amélioration.

---

## 7. Ce qu'un agent ne peut pas écrire

**La question :** qu'est-ce qui empêche l'IA de s'auto-attribuer une bonne note ?

```
                    ╳  .aidlc/maturity.json          il n'édite pas sa propre note
                    ╳  .aidlc/reviews/*.json         il ne signe pas à votre place
   agent            ╳  .aidlc/ratchet.json           il ne desserre pas les planchers
     │              ╳  .aidlc/logs/                  il ne réécrit pas l'histoire
     ├── Write ──►  ╳  le harnais installé           il n'édite pas les règles
     │                 (pipeline, hooks, script,        qui le jugent
     │                  agents, skills, templates)
     │              ╳  le plugin d'une autre équipe  son manifeste se lit,
     │                                                 il ne se réécrit pas
     │
     │              ✓  deliverables/<stage>/…        son livrable
     └────────────► ✓  .aidlc/tmp/                   son brouillon de travail
```

Le hook `guard` (`PreToolUse`) refuse **avant** l'écriture. C'est un garde-fou d'intégrité, pas
une gêne à contourner : un agent évolue dans le dépôt de son équipe.

---

## 8. La boucle d'amélioration

**La question :** que devient un refus ?

```
   refus humain       ─┐   justification obligatoire
                       │
   refus du gate OKF  ─┼──►  .aidlc/improvement-queue.jsonl
   (hook Stop)         │                 │
                       │                 │       + .aidlc/logs/
   halte du watchdog  ─┘                 │       + .aidlc/maturity.json
   (stagnation)                          ▼
                                   aidlc.py improve
                                   diagnostic JSON : la faiblesse, la session
                                   fautive, le correctif candidat
                                          │
                                          ▼
                                   /aidlc-core:improve
                                   PROPOSE un diff sur le SKILL.md, le template,
                                   le checks.json ou le concept fautif
                                          │
                                          ▼
                                   accord humain explicite  ──► appliqué
                                   (sinon : rien n'est touché)
```

La correction porte sur **le harnais**, jamais sur le livrable : on ne rattrape pas une note, on
répare ce qui a produit la mauvaise note. Et jamais sur la copie installée — toujours sur la source.

---

## 9. Le moteur

**La question :** où est le code, et comment il répond ?

```
   hooks   ─┐
   skills  ─┼──►  scripts/aidlc.py   ──►  _aidlc/   util · checks · maturity · registry
   CLI     ─┘     le point d'entrée         │       scaffold · improve · hookslog · okf
                  unique et stable          │       knowledge · syntax · ratchet
                                            │       watchdog · coverage · commands · cli
                                            └──►    tests/   un test_<module>.py par module

   Ce qui sort :   JSON              ──►  stdout      (pour les agents et la CI)
                   message humain    ──►  stderr      (pour vous)
                   verdict           ──►  code de sortie   0 = passe · 2 = bloque
```

Bibliothèque standard Python **uniquement** — y compris pour tester (`unittest`) et mesurer la
couverture (`trace`). La suite tourne chez n'importe quel consommateur avec `python3` seul.

---

## Pour aller plus loin

| Document | Ce qu'il ajoute à ces schémas |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | le détail de chaque mécanisme, et les décisions derrière |
| [CONSUMER.md](CONSUMER.md) | le mode d'emploi côté projet : installer, lancer, signer |
| [MAINTAINER.md](MAINTAINER.md) | le mode d'emploi côté auteur : concevoir, vérifier, publier |
| [TESTING.md](TESTING.md) | ce qui est testé, comment, et pourquoi |
