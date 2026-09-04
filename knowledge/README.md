# Base de connaissance

Ce dossier est la mémoire longue du harness. Les livrables de `deliverables/` disent *ce qui est
décidé pour ce cycle* ; `knowledge/` dit *ce qui est vrai dans l'organisation, cycle après cycle* :
normes internes, décisions d'architecture, retours d'expérience, documents de référence.

L'agent `librarian` est le seul consommateur automatique de ce dossier. Il n'invente pas de
contexte : il répond à la question « quel contexte pour l'étape X » en lisant `index.json`, puis en
ouvrant les sources qui concernent cette étape.

```
knowledge/
  README.md      ce fichier
  index.json     l'index machine lu par le librarian
  glossary.md    le vocabulaire du harness
  sources/       (optionnel) les documents hébergés dans le dépôt
```

---

## 1. L'index

`index.json` est la seule chose que le librarian lit en premier. Son schéma :

```json
{
  "version": 1,
  "sources": [
    {
      "id": "identifiant-stable-en-kebab-case",
      "title": "Titre lisible par un humain",
      "path_or_url": "chemin/relatif/depuis/la/racine.md ou https://...",
      "kind": "doc",
      "stages": ["design", "build"],
      "summary": "Une à trois phrases disant ce que la source contient et quand la consulter."
    }
  ]
}
```

| Champ | Règle |
| ----- | ----- |
| `id` | kebab-case, unique, **stable dans le temps** : c'est ce que les livrables citent pour tracer une décision. On ne renomme pas un `id`, on en crée un nouveau. |
| `title` | titre lisible, en français, tel qu'il apparaîtrait dans un sommaire. |
| `path_or_url` | chemin relatif à la racine du dépôt, ou URL absolue pour une source externe ou intranet. |
| `kind` | `doc` (documentation), `standard` (norme ou convention opposable), `adr` (décision d'architecture), `deliverable` (livrable produit par le pipeline). |
| `stages` | identifiants d'étapes concernées, pris dans `pipeline.json` : `plan`, `design`, `build`, `test`, `deploy`, `maintain`. C'est le filtre principal du librarian. |
| `summary` | ce qui décide de la consultation. Il dit *quand* la source est utile, pas seulement ce qu'elle contient. Un résumé qui paraphrase le titre ne sert à rien. |

---

## 2. Ajouter une source

1. **Rendre la source atteignable.** Soit le document vit dans le dépôt — le poser dans
   `knowledge/sources/` — soit il vit ailleurs et on retient son URL stable (pas un lien de
   partage temporaire, pas un lien vers une conversation).
2. **Ajouter une entrée dans `index.json`**, en respectant les six champs du schéma. Aucun champ
   n'est optionnel.
3. **Choisir les `stages` avec parcimonie.** Une source rattachée aux six étapes sera lue partout
   et diluera le contexte. En cas d'hésitation, ne rattacher la source qu'aux étapes où son
   absence ferait commettre une erreur.
4. **Écrire un `summary` actionnable.** Bon : « Fixe les règles de nommage, de versionnage et de
   gestion des erreurs de toute nouvelle interface exposée. » Inutile : « Document sur les API. »
5. **Vérifier que le fichier se parse** avant de commiter :
   `python3 -m json.tool knowledge/index.json > /dev/null`

Retirer une source obsolète se fait de la même façon : supprimer l'entrée. Si des livrables
existants citent son `id`, remplacer l'entrée plutôt que la supprimer, en pointant vers la version
à jour et en le disant dans le `summary`.

### Les entrées d'exemple

Les entrées dont l'`id` commence par `example-` sont des exemples de sources d'entreprise typiques
(une décision d'architecture, deux normes internes). Elles montrent la forme attendue et leurs
cibles n'existent pas dans ce dépôt. Les remplacer par les références réelles de l'organisation
lors de la mise en service ; le librarian doit signaler, et non inventer, une source injoignable.

---

## 3. Ce que le librarian en fait

Séquence type, quand un agent d'étape ou l'orchestrateur lui demande le contexte de l'étape
`design` :

1. Il lit `knowledge/index.json`.
2. Il retient les sources dont `stages` contient `design`.
3. Il y ajoute les livrables amont déclarés dans le champ `inputs` de l'étape dans
   `pipeline.json`.
4. Il ouvre ce qui est atteignable et compose un briefing : par source, son `id`, son titre, et ce
   qu'elle impose ou apporte à cette étape précise.
5. Il signale explicitement toute source annoncée par l'index mais introuvable, plutôt que de
   combler le vide.

Le briefing est fait pour être cité. Les livrables tracent leurs décisions en reprenant l'`id` des
sources utilisées : c'est ce qui alimente l'axe *traceability* de la grille de maturité, où une
référence locale et vérifiable sépare un 4 d'un 3.

Le librarian est en lecture seule en dehors de `knowledge/`. Il ne rédige aucun livrable et ne
modifie ni les scores ni les revues.

---

## 4. Règles d'hygiène

- Une source, une entrée. Pas de doublon, pas d'entrée qui pointe vers un dossier.
- Le `summary` est écrit pour un lecteur qui ne connaît pas la source, pas pour celui qui l'a
  rédigée.
- Une source contredite par une plus récente est remplacée, pas laissée en concurrence : deux
  normes opposées dans l'index produisent des livrables incohérents.
- `glossary.md` est la source de vérité du vocabulaire. Un terme employé dans un livrable et
  absent du glossaire est soit à définir, soit à remplacer par un terme déjà défini.
