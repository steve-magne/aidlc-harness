> Qui est publié, qui est branché sur l'initiative en cours, et comment composer la chaîne. À utiliser quand on demande quels agents existent, d'ajouter ou de retirer une équipe du workflow, ou pourquoi une étape attendue n'apparaît nulle part.

# Les agents, et lesquels traversent cette initiative

Deux listes, à ne pas confondre : **ce qui est publié** (les manifestes `agent.json` que
l'orchestrateur découvre) et **ce qui est branché** (la clé `agents` d'`aidlc.json`, le workflow de
l'initiative en cours). Un agent publié mais non branché ne joue pas ; un agent branché mais non
publié laisse un trou dans la chaîne.

Pour un projet qui n'est pas encore amorcé, c'est [init.md](init.md) qu'il faut, pas cette page.

## Voir

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/aidlc" workflow
"${CLAUDE_PLUGIN_ROOT}/bin/aidlc" agents --json
```

`workflow` répond à « qui joue » ; `agents` au détail de chaque manifeste — équipe propriétaire,
capacités, invocation par plateforme, `produces`, `consumes`, contrat.

Trois situations, trois réponses :

| Ce que dit la sortie | Ce que ça veut dire | Ce que tu fais |
|---|---|---|
| branché | il compose la chaîne | rien |
| « découverts, hors de ce workflow » | l'équipe a publié, personne n'a branché | demande si elle intervient, **puis** ajoute |
| « introuvable » | déclaré, plugin non installé | nomme l'équipe qui doit le publier ou l'installer |
| `contract_problems` | son `checks.json` est absent ou incohérent | nomme l'équipe : ça se corrige dans **son** dépôt |

Un agent sans `produces` est **consultatif** : il n'est jamais une étape, jamais noté. Il ne se
branche pas au workflow, il s'invoque par `/aidlc ask`.

## Brancher

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/aidlc" workflow --add <agent> --remove <agent>
```

Répétable, combinable en un seul appel, et la commande **refuse** un identifiant qu'aucun manifeste
ne porte — un agent fantôme rétrécirait la chaîne en silence.

Demande avant d'ajouter ou de retirer : cette liste est une décision d'équipe, pas une déduction.
Un retrait qui casse la chaîne producteur → consommateur est signalé ; relaie l'avertissement tel
quel, il annonce une porte qui restera fermée.

## Ce qui manque encore

Une étape que le process de l'entreprise connaît mais qu'aucun manifeste ne porte figure dans la
feuille de route consultative (`planned_stages`). Elle n'est pas jouable : ne l'improvise pas,
propose `/aidlc new-agent <stage>`, qui la conçoit avec son référent métier.

## Ce que tu ne fais pas

Tu n'écris jamais `aidlc.json` avec l'outil Write — un hook le refuse, et `workflow` est le seul
chemin parce qu'elle valide ce qu'elle écrit. Tu ne touches pas aux seuils : c'est une décision
d'équipe, à prendre à la main dans un terminal.
