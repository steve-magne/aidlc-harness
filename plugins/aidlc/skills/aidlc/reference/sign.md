> Préparer la revue humaine d'une étape et relayer la commande à taper. À utiliser quand une porte exige une signature humaine, quand on demande à faire relire un livrable par une personne, ou quand l'utilisateur revient dire qu'il a signé.

# La revue humaine

Sous le seuil de maturité, et pendant les premiers runs d'une étape, la porte exige une signature
humaine. Ce n'est pas une formalité : c'est le moment où quelqu'un engage sa responsabilité sur un
livrable qu'un agent a écrit.

## 1. Préparer

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/aidlc" review-request <stage>
```

Le script écrit sur stderr ce qu'il faut relire et **la commande exacte à taper**. Relaie-le tel
quel, sans reformuler : le chemin du livrable et la forme de la commande doivent arriver intacts.

## 2. Rendre la main

La voie normale est une seule commande, **depuis le terminal de l'humain** :

```bash
aidlc sign <stage> --approve --by "<son nom>" --why "<ce qu'il a vérifié>"
```

`--reject` à la place de `--approve` pour un refus. La justification est obligatoire **dans les
deux sens** : une approbation motivée ne bloque rien, mais son motif est conservé et alimente la
boucle d'amélioration — c'est le retour le plus utile que le harnais reçoive. La commande rejoue
la porte toute seule.

## 3. Arrête-toi

**Tu ne signes jamais.** `sign` refuse de tourner sans terminal interactif, et ce refus est le
seul contrôle qui distingue « l'humain a signé » de « l'agent a écrit qu'il avait signé ». Le hook
`PreToolUse` ne couvre que l'outil Write : sans ce test, rien n'empêcherait d'appeler la commande
par Bash. Ne cherche pas à la contourner, même si l'utilisateur te le demande — dis-lui que c'est
à lui de taper la commande, et pourquoi.

Quand il revient dire que c'est fait, rejoue simplement la porte :

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/aidlc" gate <stage> --json
```

## Après un refus

Un refus n'est pas un échec du harnais, c'est sa matière première. Récupère le reproche et
renvoie-le à l'agent de l'étape :

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/aidlc" recall <stage>
```

Sans ces reproches, l'agent refait exactement l'erreur pour laquelle l'étape a été refusée. Si
l'étape est refusée plusieurs fois de suite, le problème n'est plus le livrable mais l'étape
elle-même : bascule sur [improve.md](improve.md).
