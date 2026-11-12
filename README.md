# Assistant de configuration Odoo 18

> **In short (EN).** An Odoo 18 configuration assistant implementing its functional
> specification (V1 and phase 2). Consultants create client projects; the company profile
> drives a configuration plan ordered by prerequisites, grouped by domain, module and process;
> each step sheet gives the goal, the menu path (in French), the recommended value and its
> sources; the client user validates the steps. A documentation assistant answers with
> citations from the official Odoo documentation, recomposed in French from the official
> translations, with hybrid lexical and semantic search. The documentation is synchronized
> weekly with controls, alerts on changed source pages and e-mail notifications. Deliverables
> (Excel and Word workbook, checklist, import templates) carry the organisation identity. A
> read-only gap control compares the plan with the client's Odoo instance. Three journeys
> (Finance Quebec, Finance France, Inventory and manufacturing), 56 steps checked against the
> odoo/documentation 18.0 repository by tests.
> Live demo: https://odoo-config-assistant-quirerfrcwkuhiugt6aejy.streamlit.app/

[![CI](https://github.com/kamilbbm/odoo-config-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/kamilbbm/odoo-config-assistant/actions/workflows/ci.yml)
[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://odoo-config-assistant-quirerfrcwkuhiugt6aejy.streamlit.app/)

**Démo en ligne : [odoo-config-assistant-quirerfrcwkuhiugt6aejy.streamlit.app](https://odoo-config-assistant-quirerfrcwkuhiugt6aejy.streamlit.app/)**

## Le problème

Configurer Odoo pour un domaine complet, par exemple la comptabilité d'une société québécoise,
demande de connaître l'ordre des étapes, leurs dépendances et les obligations locales. La
documentation éditeur est organisée par application, pas par métier. Ce savoir reste dans la tête
des consultants : il n'est ni capitalisé ni outillé, et chaque projet le reconstitue.

Cet outil structure ce savoir en parcours vérifiables, rattachés à la documentation officielle,
et produit un paramétrage documenté et traçable. Il réalise la spécification fonctionnelle
([docs/SFD.md](docs/SFD.md)) : la correspondance exigence par exigence est dans
[docs/couverture.md](docs/couverture.md).

## Démo

La démo s'ouvre sur l'écran de connexion. Les comptes fictifs de l'organisation de
démonstration se choisissent en un clic (mot de passe `demo-odoo-18`) :

| Compte | Rôle | Ce qu'il voit |
| --- | --- | --- |
| Camille Consultante | Consultant | les deux projets, plan, fiches, livrables, contrôle d'écart |
| Benoît Boréal | Utilisateur client | le projet Atelier Boréal, valide les étapes faites |
| Valérie Vauban | Utilisateur client | le projet Cabinet Vauban, valide les étapes faites |
| Romane Référente | Référent contenu | sources documentaires, référentiel et éditeur de parcours |
| Alex Administrateur | Administrateur | tout, plus l'identité de l'organisation, les utilisateurs et la messagerie |

Projets exemples fictifs : Atelier Boréal inc., PME manufacturière au Québec
([projects/exemple.json](projects/exemple.json)) ; Cabinet Vauban Conseil SAS, société de conseil
à Lille ([projects/exemple-fr.json](projects/exemple-fr.json)), parcours Finance France avec
prélèvement SEPA, Chorus Pro et reprise de l'historique par FEC.

| Plan de configuration | Fiche étape |
| --- | --- |
| ![Plan ordonné par prérequis, par domaine, module et processus](docs/img/01-plan.png) | ![Fiche étape : menu en français, badge « À confirmer », sources](docs/img/02-fiche-etape.png) |
| **Assistant documentaire** | **Projet et profil** |
| ![Réponse avec citations en français et licence](docs/img/03-assistant.png) | ![Questionnaire de profil et membres du projet](docs/img/04-profil.png) |

Les captures sont produites par `scripts/capture_screens.py` (workflow `Screenshots`).

## Fonctionnalités

| Écran | Rôle | Contenu |
| --- | --- | --- |
| Tableau de bord (E-01) | Consultant, client, administrateur | projets accessibles, avancement global et par domaine |
| Projet (E-02) | idem | profil de l'entreprise (pays, activité, taille, édition Odoo, modules, options), recalcul du plan, membres du projet |
| Plan (E-03) | idem | étapes ordonnées par prérequis, domaine, module et processus, statuts, prérequis bloquants, « À confirmer », « Enterprise », « À revalider » |
| Fiche étape (E-04) | idem | objectif, chemin de menu en français (et en anglais), valeur recommandée selon le profil, prérequis, sources, échanges avec l'assistant, statut, valeur retenue, commentaire, validation client |
| Assistant (E-05) | tous | panneau latéral sur toutes les pages, contextualisé à l'étape ouverte ; historique des échanges du projet |
| Livrables (E-06) | Consultant du projet | cahier de paramétrage Excel (avec checklist) et Word, modèles de fichiers d'import, historique |
| Contrôle d'écart (phase 2) | Consultant du projet | lecture seule de l'instance Odoo du client et comparaison avec le plan |
| Administration (E-07) | Administrateur | identité de l'organisation (nom, logo, mentions), seuils, messagerie, utilisateurs et rôles |
| Sources (E-08) | Administrateur, référent | source déclarée, synchronisation, comptes rendus, publication forcée |
| Référentiel (E-09) | Référent contenu | étapes à revalider, arborescence Domaine > Module > Processus > Paramètre, éditeur de parcours, historique |

### Parcours

Trois parcours, 56 étapes, dans [data/journeys](data/journeys), rattachées au référentiel métier
([data/referential.yaml](data/referential.yaml), sept domaines de la SFD) :

- **Finance, société québécoise** (18 étapes) : localisation canadienne, TPS et TVQ, positions
  fiscales par province, plan comptable, journaux, banque, soldes d'ouverture, exercice, devise,
  conditions de paiement, chèques, verrouillage, rapports.
- **Finance, société française** (19 étapes) : localisation française, TVA et positions
  fiscales, plan comptable, journaux, banque, paiements SEPA, soldes d'ouverture ou import FEC,
  conditions de paiement, facturation électronique par plateforme agréée, Chorus Pro, rapport de
  TVA, export FEC, liasse fiscale et verrouillage.
- **Inventaire et fabrication** (19 étapes) : entrepôt et emplacements, routes, réceptions et
  livraisons, unités de mesure, catégories et valorisation, composants achetés, lots, postes de
  travail, nomenclatures, réapprovisionnement, fabrication à la commande, stock initial, ordre de
  fabrication de recette.

Les autres domaines de la SFD (Ventes, Services, RH, Marketing, Site web) sont présents dans le
référentiel avec leurs modules, sans parcours modélisé pour l'instant.

### Véracité du contenu

Le contenu des parcours vient de la documentation officielle (dépôt
[odoo/documentation](https://github.com/odoo/documentation), branche 18.0), pas de la mémoire
d'un consultant ou d'un modèle :

- chaque étape cite au moins une page RST, avec son ancre et son URL publique (RG-012, RG-014) ;
- les tests vérifient, dans le clone de la documentation, que la page existe, que l'ancre y est
  déclarée, que le titre correspond et que le chemin de menu y figure mot pour mot ;
- une valeur que la documentation ne confirme pas (taux de taxe, périodicité des déclarations,
  délais de paiement…) est marquée `verified: false` avec une note et le badge « À confirmer » ;
- le commit de la documentation est conservé sur chaque étape, chaque réponse et chaque livrable ;
- les chemins de menu sont écrits en anglais, tels que dans la documentation, et affichés en
  français grâce aux traductions officielles.

### Documentation en français et recherche

La synchronisation récupère les pages RST et les traductions françaises (.po). Chaque page est
recomposée en français en remplaçant chaque segment dont le texte anglais correspond exactement ;
un passage non traduit reste en anglais avec une mention (RG-010), et une page sous le seuil de
traduction est publiée avec la mention « traduction partielle » (ERR-004). Sur la branche 18.0,
325 pages indexées sont traduites à 97 % en moyenne.

La recherche est hybride : BM25 sur le texte anglais et français, et index sémantique (analyse
sémantique latente des sections bilingues, calculée à la synchronisation), fusionnés par rang.
La décision « non couverte par la documentation » (RG-006) reste lexicale, pour ne jamais
inventer une couverture. Avec `ANTHROPIC_API_KEY`, un modèle Claude rédige la réponse à partir des
seuls extraits trouvés ; une réponse qui ne cite aucun extrait est rejetée.

### Éditions Community et Enterprise

Le profil précise l'édition d'Odoo (Q-008). Chaque étape déclare ses modules techniques ; un
module absent du dépôt public [odoo/odoo](https://github.com/odoo/odoo) 18.0 relève d'Enterprise
([data/editions.json](data/editions.json), produit par `scripts/fetch_editions.py`). En Community,
les étapes Enterprise sont hors plan et la fiche rappelle que l'application comptable s'y appelle
Invoicing.

### Synchronisation de la documentation

```bash
python scripts/sync_docs.py
```

La version candidate est comparée page par page à la version active, indexée à part, puis
contrôlée ; elle remplace la version active en une seule bascule si tous les contrôles sont OK
(RG-009), et l'ancienne est archivée. Le compte rendu liste les pages ajoutées, modifiées et
supprimées et les étapes dont une page source a changé (RG-011) : elles sont signalées « À
revalider » jusqu'à leur revalidation par le référent contenu (E-09).

| Code | Contrôle | Effet | Notification |
| --- | --- | --- | --- |
| ERR-001 | Dépôt inaccessible | 3 tentatives espacées, version active conservée | Administrateur |
| ERR-002 | Branche ou commit introuvable | Arrêt, version active conservée | Administrateur |
| ERR-003 | Traduction illisible | Pages du domaine en anglais | Référent contenu |
| ERR-004 | Traduction partielle | Page publiée avec la mention | Référent contenu |
| ERR-005 | Page RST illisible | Page exclue, sections précédentes conservées | Référent contenu |
| ERR-006 | Indexation ou vectorisation interrompue | Version candidate abandonnée | Administrateur |
| ERR-007 | Page ou ancre d'une étape absente | Étape « Source introuvable » | Référent contenu |
| ERR-008 | Pages en baisse au-delà du seuil | Publication bloquée, forçage tracé | Administrateur |

Le workflow [Doc sync](.github/workflows/doc-sync.yml) l'exécute chaque dimanche à 02:00 UTC à
partir du commit de vérification des parcours ([data/doc_version.json](data/doc_version.json)) ;
il échoue en cas d'alerte (notification GitHub) et publie le compte rendu dans le résumé du job.
`--notify` envoie aussi les courriels de la matrice ci-dessus et aux consultants des projets
concernés.

### Contrôle d'écart (phase 2)

Le consultant saisit l'adresse de l'instance Odoo du client, la base, l'identifiant et une clé
d'API. L'application lit la société, les modules installés, les devises, taxes, journaux,
comptes, positions fiscales, conditions de paiement et données de stock et de fabrication, puis
contrôle chaque étape du plan : Conforme, Écart ou Non vérifiable. Une étape Faite ou Validée en
écart est signalée « à reprendre ». Seules les méthodes de lecture de l'API externe sont
autorisées (RG-016) ; la clé d'API n'est pas enregistrée.

## Lancer l'application

Python 3.11 ou plus récent, depuis la racine du dépôt (un environnement virtuel est conseillé) :

```bash
pip install -e .
```

```bash
python scripts/sync_docs.py
```

```bash
streamlit run app/streamlit_app.py
```

La synchronisation est facultative : sans index, l'application la lance à son premier démarrage
(clone partiel des pages RST et des traductions françaises, environ 34 Mo, dans `vendor/`, non
versionné). La base de données SQLite est créée dans `var/assistant.db`.

| Variable | Rôle |
| --- | --- |
| `OCA_DB` | chemin de la base de données (par défaut `var/assistant.db`) |
| `OCA_DEMO` | `0` : base vide, installation de l'organisation et de son administrateur au premier lancement ; sinon données de démonstration |
| `ANTHROPIC_API_KEY` | réponses rédigées par Claude (facultatif) |
| `OCA_SMTP_PASSWORD` | mot de passe du serveur SMTP réglé dans l'écran Administration |
| `OCA_AUTO_FETCH` | `0` : pas de téléchargement automatique de la documentation (tests) |

Fournisseur d'identité de l'organisation (OIDC, facultatif) : renseigner la section `[auth]` des
secrets Streamlit (`redirect_uri`, `cookie_secret`, `client_id`, `client_secret`,
`server_metadata_url`) ; l'identité est rattachée au compte de même courriel.

Tests et contrôle du code :

```bash
pip install -e ".[dev]" && ruff check . && pytest
```

Les tests de véracité sont ignorés tant que la documentation n'est pas téléchargée ; le job CI
`docs-truth` les exécute sur un clone frais, avec les données Community rafraîchies.

## Démo en ligne

L'application est déployée sur Streamlit Community Cloud, branche `main`. Pour redéployer :

1. New app, dépôt `kamilbbm/odoo-config-assistant`, branche `main`, fichier principal
   `app/streamlit_app.py`, Python 3.11 ou plus récent.
2. Facultatif, dans Advanced settings, Secrets : `ANTHROPIC_API_KEY`, `OCA_SMTP_PASSWORD`,
   section `[auth]`.
3. Déployer. Au premier démarrage, l'application synchronise la documentation et construit les
   index en moins d'une minute ; le résultat est gardé en cache pour la durée de vie de
   l'instance.

Sur Community Cloud, le disque n'est pas persistant : la base repart des données de
démonstration à chaque redémarrage. Pour une utilisation réelle, pointer `OCA_DB` vers un disque
persistant. Le job CI `app-smoke` reproduit le démarrage sur un dépôt neuf, se connecte avec le
compte administrateur, parcourt les dix écrans et échoue si les logs contiennent une erreur.

## Architecture

Modules, flux et choix techniques : [docs/architecture.md](docs/architecture.md). Correspondance
avec la SFD : [docs/couverture.md](docs/couverture.md).

## Licence et attribution

- Code : licence MIT, voir [LICENSE](LICENSE).
- Documentation Odoo : CC BY-SA 4.0, Odoo S.A. et contributeurs. Elle n'est pas copiée dans ce
  dépôt ; elle est téléchargée à la synchronisation. Détails dans [NOTICE.md](NOTICE.md).
- Odoo est une marque d'Odoo S.A. Ce projet est indépendant.
- Toutes les données de démonstration sont fictives.

## Auteur

Kamil Baba-Moussa, consultant ERP (Odoo, Infor M3, SAP S/4HANA), Montréal.
