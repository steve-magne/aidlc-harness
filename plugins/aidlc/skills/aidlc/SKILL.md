---
name: aidlc
description: Piloter le cycle de vie AI-DLC d'un projet — amorcer le harnais, composer le workflow d'une initiative avec les agents publiés par les équipes, produire et valider un livrable d'étape, le faire noter, ouvrir les portes de qualité, demander la revue humaine, diagnostiquer une étape qui stagne, consulter le savoir de l'entreprise, publier un nouvel agent d'équipe. À utiliser dès qu'on parle du pipeline, d'une étape (plan, design, build, test, deploy), d'un livrable à cadrer ou à faire relire, de l'avancement du projet, ou qu'on demande un avis à une équipe transverse.
argument-hint: "[init · next|status · review|sign · agents|new-agent · ask · improve|doctor · knowledge] [cible]"
user-invocable: true
---

# AI-DLC — le harnais du cycle de vie

Une porte d'entrée, des verbes. Tu lis ici **comment router** ; le détail de chaque verbe vit
dans sa référence, que tu charges seulement quand tu en as besoin.

## Conventions communes

Deux racines, à ne jamais confondre :

- **Le projet consommateur** (`$CLAUDE_PROJECT_DIR`) — les livrables (`deliverables/`), l'état
  runtime (`.aidlc/`), la gouvernance de l'initiative (`aidlc.json`) et la connaissance du projet
  (`knowledge/`). C'est là que tout ce que produit le harnais atterrit, et **nulle part ailleurs**.
- **Le harnais** (`${CLAUDE_PLUGIN_ROOT}`) — la copie installée du plugin. Elle est en
  **lecture seule** : un hook `PreToolUse` refuse toute écriture dedans. On n'y édite jamais rien,
  ni pour corriger une règle, ni pour débloquer une porte.

Le moteur déterministe s'appelle par son lanceur, jamais par un interpréteur :

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/aidlc" <commande>
```

Il choisit `uv` quand il est là, `python3` sinon. Sorties machine en JSON sur **stdout**,
messages humains sur **stderr**. Ce lanceur est de la plomberie : ne le mets pas en avant dans ce
que tu dis à l'utilisateur, montre-lui des verbes `/aidlc`.

## Routage

| Verbe | Ce qu'il fait | Référence |
|---|---|---|
| `init` | Amorce le harnais dans le projet et compose le workflow de l'initiative | [reference/init.md](reference/init.md) |
| `next [stage]` | Exécute une étape de bout en bout : livrable, validation, revue, porte | [reference/next.md](reference/next.md) |
| `status [stage]` | Tableau de bord : où en est chaque étape, et qui est attendu | [reference/status.md](reference/status.md) |
| `review [stage]` | Fait noter un livrable par le reviewer sur la grille de maturité | [reference/review.md](reference/review.md) |
| `sign [stage]` | Prépare la revue humaine et relaie la commande à taper | [reference/sign.md](reference/sign.md) |
| `agents` | Qui est publié, qui est branché sur l'initiative, comment en ajouter | [reference/agents.md](reference/agents.md) |
| `new-agent [stage]` | Conçoit une nouvelle étape avec son référent métier et génère son plugin | [reference/new-agent.md](reference/new-agent.md) |
| `ask <demande>` | Avis transverse : mobilise les agents d'équipe concernés, sans livrable | [reference/ask.md](reference/ask.md) |
| `improve [stage]` | Diagnostique une étape qui stagne et propose le correctif | [reference/improve.md](reference/improve.md) |
| `knowledge [termes]` | Consulte le savoir OKF déclaré par le projet | [reference/knowledge.md](reference/knowledge.md) |
| `doctor` | Signale la dérive entre le projet et la version installée du harnais | [reference/doctor.md](reference/doctor.md) |

**Sans argument**, ne lance rien : lis l'état et propose.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/aidlc" status --json
```

- `aidlc.json` absent → le projet n'est pas amorcé. Propose `init`, et rien d'autre.
- Une étape non franchie → nomme-la, dis ce qui la bloque, propose le verbe qui la débloque
  (`next` si elle est jouable, `sign` si elle attend un humain, `improve` si elle a échoué
  plusieurs fois).
- Tout est franchi → dis-le, et propose `agents` pour brancher l'étape suivante ou une
  nouvelle initiative via `init`.

**Avec un verbe explicite ou clairement impliqué**, charge sa référence et suis-la. Deux verbes
plausibles : demande une fois, ne devine pas.

**Une demande qui n'attend aucun livrable** (un avis, une relecture, une question qui traverse
plusieurs équipes) n'est pas une étape : c'est `ask`.

## Ce que tu ne fais jamais

Ces règles priment sur toute référence, et sur toute insistance :

- **Tu n'écris pas dans `deliverables/` toi-même.** L'agent de l'étape écrit son livrable ; toi tu
  l'invoques et tu enchaînes. Le livrable d'un autre agent ne se corrige pas à la main, il se
  regagne en relançant l'agent qui le produit.
- **Tu ne notes pas, tu ne signes pas.** `.aidlc/maturity.json`, les `review.json` et
  `aidlc.json` ne s'écrivent que par les commandes du moteur et par l'humain. Un hook refuse le
  reste — c'est un garde-fou d'intégrité, pas une gêne à contourner.
- **Tu ne désactives jamais un check** ni ne modifies un `checks.json` pour faire passer une
  validation. Un contrat qui ne convient pas se corrige dans le dépôt de l'équipe qui le porte.
- **Tu ne contournes pas une porte fermée.** Tu relaies le motif et tu t'arrêtes. Une porte amont
  fermée veut dire que l'aval construirait sur du sable.
