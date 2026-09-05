# Rubrique de revue — étape Plan

Ce fichier appartient à l'équipe **Produit**. Il ne remplace pas la grille universelle du
reviewer (`aidlc-core`) : il dit ce que chaque axe veut dire **pour une intention produit**, et
quelles fautes de ce métier sont rédhibitoires. Le barème (0-5), le calcul de la note globale, le
plancher par axe et l'enregistrement restent au noyau — cette équipe ne note pas sa propre copie.

## `completeness` — ce que « complet » veut dire ici

- Le **problème** est décrit comme un manque constaté, pas comme l'absence de la solution
  envisagée. « Nous n'avons pas de portail client » n'est pas un problème, c'est une solution
  retournée.
- Chaque persona de `## Utilisateurs impactés` porte son **volume** et sa **fréquence d'usage**.
  Un persona sans ordre de grandeur ne permet aucun arbitrage de priorité : plafonner à 2.
- `## Hors périmètre` est renseigné avec de vraies exclusions arbitrées, pas des évidences. Une
  section hors périmètre vide ou décorative vaut 2 au maximum : c'est elle qui protège l'aval,
  et `must_not_violate_scope` s'appuie dessus à l'étape Design.

## `precision` — ce que « testable » veut dire ici

- Chaque bénéfice de `## Solution proposée` porte **son KPI, sa valeur de départ observée et sa
  cible datée**. Un bénéfice sans les trois est une intention, pas un engagement : plafonner à 2.
- Un critère d'acceptation se lit comme un test qui peut échouer. « L'utilisateur doit pouvoir
  retrouver sa commande facilement » n'en est pas un ; « 95 % des recherches par numéro de
  commande aboutissent en moins de 2 s » en est un.
- Les contraintes budgétaires ou réglementaires sont chiffrées ou référencées par leur texte.

## `traceability` — ce que « tracé » veut dire ici

L'étape Plan est en **tête de chaîne** : elle n'a pas d'entrée `consumes`, donc la traçabilité ne
se juge pas sur la citation d'un livrable amont mais sur l'**origine des faits** :

- le fait mesuré du `## Contexte` porte sa source et sa date (extraction, ticket, tableau de bord) ;
- une norme d'entreprise est citée par sa référence exacte du savoir OKF (`<source>/<concept-id>`,
  voir `aidlc.py knowledge`), jamais recopiée ni paraphrasée ;
- un chiffre sans origine est une invention jusqu'à preuve du contraire : le signaler en
  `findings` et ne pas dépasser 2 sur cet axe.

## `autonomy`

Grille universelle. Nuance propre à l'étape : le dialogue avec le Product Owner **est** le
travail attendu — les questions métier ne pénalisent jamais. Ne pénalise que les reprises de
forme et les relances dues à une procédure oubliée.

## Fautes rédhibitoires (verdict `rejected`, quelle que soit la moyenne)

- Une solution technique imposée dans `## Solution proposée` sans que le problème la justifie :
  l'étape Plan cadre le besoin, l'architecture est tranchée en Design.
- Un critère d'acceptation qui décrit une implémentation plutôt qu'un résultat observable.
- Un engagement de délai ou de coût que rien dans le livrable ne soutient.
