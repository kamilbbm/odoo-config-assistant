# Mentions et attribution

## Code

Le code de ce dépôt est publié sous licence MIT (voir [LICENSE](LICENSE)).

## Documentation Odoo

L'application s'appuie sur la documentation officielle d'Odoo, dépôt
[odoo/documentation](https://github.com/odoo/documentation), branche 18.0.

- Auteur : Odoo S.A. et les contributeurs du dépôt odoo/documentation.
- Licence : [Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/deed.fr).
- Version utilisée : commit enregistré dans [data/doc_version.json](data/doc_version.json)
  (commit de vérification des parcours) et, à l'exécution, dans `vendor/odoo-docs.version.json`.

La documentation n'est pas copiée dans ce dépôt. Les pages RST et les traductions françaises
(`locale/fr/LC_MESSAGES/*.po`) sont téléchargées par `scripts/sync_docs.py` (ou
`scripts/fetch_docs.py`) dans `vendor/` (ignoré par git). Les index construits à partir de cette
documentation (`index/`, y compris les textes recomposés en français et les vecteurs sémantiques)
ne sont pas versionnés non plus.

Ce que le dépôt contient en lien avec cette documentation :

- les chemins des pages RST, les ancres et les URL publiques citées par les parcours ;
- les libellés de menus et de champs de l'interface Odoo, repris tels qu'ils apparaissent dans la
  documentation (chemins de menu en anglais) ;
- les objectifs et valeurs recommandées des étapes, rédigés pour ce projet, avec renvoi à leurs
  sources.

Chaque citation affichée par l'application (fiche étape, assistant, cahier de paramétrage) porte
le lien vers la page source et la mention de licence CC BY-SA 4.0 (règle RG-014 de la SFD).
Un livrable qui reprend des extraits de la documentation est une œuvre dérivée soumise aux mêmes
conditions de partage ; la question est ouverte dans la SFD (Q-001).

## Code Odoo Community

`scripts/fetch_editions.py` lit le dépôt [odoo/odoo](https://github.com/odoo/odoo), branche 18.0
(licence LGPL-3.0), sans le copier : il en extrait la liste des noms de modules
([data/editions.json](data/editions.json)) et les noms des champs des objets utilisés par les
modèles d'import ([data/odoo_fields.json](data/odoo_fields.json)), avec le commit lu. Ces noms
servent à vérifier les éditions et les en-têtes des modèles d'import.

## Marques

Odoo est une marque d'Odoo S.A. Ce projet est indépendant et n'est ni affilié à Odoo S.A. ni
approuvé par elle.

## Données

Les données de démonstration (« Atelier Boréal inc. », projet `projects/exemple.json`, et
« Cabinet Vauban Conseil SAS », projet `projects/exemple-fr.json`) sont entièrement fictives.
