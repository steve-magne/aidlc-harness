> Signaler la dérive entre ce projet et la version installée du harnais — agent branché dont le plugin a disparu, contrat devenu incohérent, livrable qu'aucun manifeste ne réclame plus. À utiliser quand une porte refuse sans raison lisible, après une mise à jour des plugins, ou quand on demande « pourquoi ça ne marche plus ».

# Le diagnostic d'installation

Le harnais est un plugin : il se met à jour **sous les pieds du projet**, sans que rien dans le
projet ne bouge. Aucun de ces écarts ne casse quoi que ce soit sur le coup — ils se voient trois
semaines plus tard, sur une porte qui refuse sans motif lisible.

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/aidlc" doctor
```

Exit 0 si le projet et le harnais sont d'accord, **exit 2** dès qu'un constat est bloquant — même
convention que les portes, pour qu'une CI puisse s'en servir.

## Lire le rapport

Chaque constat porte sa sévérité et **le geste qui le corrige**.

| Sévérité | Ce que ça veut dire | Qui agit |
|---|---|---|
| `BLOQUANT` | le harnais ne peut pas fonctionner en l'état | à traiter avant toute autre chose |
| `écart` | il fonctionne, mais il ment quelque part | à traiter bientôt |
| `info` | à savoir, aucune action requise | personne |

Ce que la passe sait voir :

- **`aidlc.json` absent** — le projet n'est pas amorcé. Un seul geste : `/aidlc init`.
- **Clé inconnue dans `aidlc.json`** — le projet croit tenir un seuil, il tourne sur celui du
  harnais. Une gouvernance ne se relit qu'une fois par trimestre : c'est exactement le genre
  d'écart qui y survit.
- **Agent branché sans plugin installé** — le workflow réclame un agent que plus rien ne porte.
  C'est le cas qui motive la commande : sans elle, la porte refuse en nommant un fichier, jamais
  la cause.
- **Contrat incohérent** — le `checks.json` d'une équipe est absent ou insatisfiable. Le rapport
  **nomme l'équipe propriétaire** : ça se corrige dans son dépôt, pas ici.
- **Livrable orphelin** — un fichier sous `deliverables/` qu'aucun manifeste ne déclare plus. La
  dérive la plus silencieuse : une équipe change son `produces`, l'ancien fichier reste, et
  personne ne sait plus lequel des deux fait foi.
- **Bundle OKF non conforme** — le savoir du projet a un écart de forme. Détail par
  `aidlc check-okf knowledge`.
- **Version du harnais qui a changé** — depuis le dernier diagnostic. Simple information : relis
  les notes de version si une porte se comporte autrement.

## Ce que tu en fais

**Tu rapportes, tu ne répares pas de toi-même.** Chaque geste appartient à l'humain ou à l'équipe
propriétaire — un agent qui « répare » un contrat voisin ou débranche un agent gênant vient de
contourner la gouvernance qu'il est censé servir.

Deux exceptions, parce qu'elles sont sans ambiguïté : proposer `/aidlc init` sur un projet non
amorcé, et proposer `/aidlc agents` quand un agent branché n'a plus de plugin. Dans les deux cas,
tu proposes — tu attends le oui.

Ne lance pas `doctor` de ta propre initiative après chaque commande : c'est un diagnostic, pas une
passe de fond. On l'appelle quand quelque chose cloche, ou après une mise à jour des plugins.
