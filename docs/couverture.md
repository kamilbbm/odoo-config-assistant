# Couverture de la SFD

Correspondance entre la spécification fonctionnelle ([SFD.md](SFD.md)) et la réalisation : code,
écran et tests. Les tests s'exécutent avec `pytest` ; ceux qui lisent la documentation Odoo ou le
code Community téléchargés sont exécutés par le job CI `docs-truth`.

## Fonctionnalités (2.1.2)

| ID | Fonctionnalité | Réalisation | Tests |
| --- | --- | --- | --- |
| F-001 | Configuration de l'organisation | `db.py` (Organisation, utilisateurs, rôles), `seed.py`, écran Administration (E-07), fournisseur d'identité OIDC optionnel | `test_access.py` |
| F-002 | Gestion des sources documentaires | `sync.py`, `sources.py`, `scripts/sync_docs.py`, workflow `Doc sync`, source déclarée, écran Sources (E-08) | `test_sync.py`, `test_fetch_docs.py` |
| F-003 | Ingestion et indexation | `translation.py` (recomposition française .po), `knowledge.py` (découpage, étiquetage ERP, version, application, pays, modules, menus), `semantic.py` (index sémantique) | `test_translation.py`, `test_knowledge.py`, `test_semantic.py` |
| F-004 | Référentiel métier | `data/referential.yaml`, `referential.py`, écran Référentiel (E-09) | `test_repository.py` |
| F-005 | Modèles de parcours | `data/journeys/*.yaml`, `journeys.py`, `repository.py` (éditeur E-09) | `test_journeys.py`, `test_journeys_data.py`, `test_repository.py` |
| F-006 | Projets clients | `db.py` (projets, membres), `access.py`, écran Projet (E-02) | `test_access.py`, `test_app.py` |
| F-007 | Questionnaire de profil | `models.Profile`, écran Projet (E-02) | `test_engine.py`, `test_journeys_data.py` |
| F-008 | Génération du plan | `engine.py` (filtrage, édition Community/Enterprise, tri topologique) | `test_engine.py`, `test_journeys_data.py` |
| F-009 | Exécution guidée | écran Fiche étape (E-04) : objectif, menu en français, valeur recommandée, sources | `test_app.py` |
| F-010 | Assistant conversationnel | `assistant.py`, `conversation.py`, panneau latéral et écran Assistant (E-05) | `test_knowledge.py`, `test_conversation.py`, `test_semantic.py` |
| F-011 | Suivi et validation | `access.change_status` (RG-003, RG-004), commentaires, notifications de validation | `test_access.py`, `test_app.py`, `test_notify.py` |
| F-012 | Livrables | `export.py` (cahier Excel et checklist), `word.py` (cahier Word), `imports.py` (modèles d'import), écran Livrables (E-06) | `test_export.py`, `test_deliverables.py`, `test_imports.py` |
| F-013 | Alertes de mise à jour documentaire | compte rendu de synchronisation, `notify.py`, revalidation des étapes (E-09), mention « À revalider » | `test_sync.py`, `test_notify.py`, `test_repository.py` |
| F-014 | Contrôle d'écart (phase 2) | `odoo_client.py` (lecture seule), `gap.py`, écran Contrôle d'écart | `test_gap.py` |

## Écrans (2.1.4)

| ID | Écran | Onglet | Rôles |
| --- | --- | --- | --- |
| E-01 | Tableau de bord | Tableau de bord : projets, avancement global et par domaine | Administrateur, Consultant, Utilisateur client |
| E-02 | Projet et profil | Projet : profil, recalcul du plan, membres | idem |
| E-03 | Plan de configuration | Plan : étapes par domaine, module et processus, statuts, prérequis bloquants, alertes | idem |
| E-04 | Fiche étape | Fiche étape : paramétrage, sources, échanges, commentaires, validation | idem |
| E-05 | Assistant | panneau de la barre latérale (toutes les pages, étape ouverte) et onglet Assistant | tous |
| E-06 | Livrables | Livrables : cahier Excel et Word, modèles d'import, historique | Consultant du projet, Administrateur |
| E-07 | Administration de l'organisation | Administration : identité, logo, mentions, seuils, messagerie, utilisateurs et rôles | Administrateur |
| E-08 | Administration des sources | Sources : source déclarée, synchronisation, comptes rendus, publication forcée | Administrateur, Référent contenu |
| E-09 | Référentiel et parcours | Référentiel : étapes à revalider, arborescence, éditeur d'étapes, historique | Référent contenu, Administrateur |
| Phase 2 | Contrôle d'écart | Contrôle d'écart | Consultant du projet, Administrateur |

## Règles de gestion (3.4)

| Code | Règle | Réalisation | Tests |
| --- | --- | --- | --- |
| RG-001 | Un projet = un ERP et une version | `Project` (champs figés), `engine.change_version` | `test_engine.py::test_rg001_*` |
| RG-002 | Plan seulement si pays, activité, modules | `engine.generate_plan` | `test_engine.py::test_rg002_*` |
| RG-003 | Fait seulement si prérequis Fait ou Validé | `engine.set_status` | `test_engine.py::test_rg003_*`, `test_access.py` |
| RG-004 | Validé réservé à l'utilisateur client membre | `access.change_status` | `test_access.py::test_rg004_*`, `test_app.py::test_rg004_*` |
| RG-005 | Profil modifié : recalcul, Hors périmètre sans suppression | `engine.recompute_plan` | `test_engine.py::test_rg005_*` |
| RG-006 | Réponse sourcée ou « non couverte » | `knowledge.is_covered` (lexical, par mot de la question) | `test_knowledge.py::test_rg006_*`, `test_semantic.py` |
| RG-007 | Sources de l'ERP et de la version du projet | filtres BM25 et sémantique | `test_knowledge.py::test_rg007_*`, `test_semantic.py` |
| RG-008 | Version documentaire conservée | commit sur les étapes, réponses et échanges | `test_engine.py`, `test_knowledge.py`, `test_conversation.py` |
| RG-009 | Publication si tous les contrôles OK | `sync.synchronize`, bascule atomique | `test_sync.py::test_rg009_*` |
| RG-010 | Passage non traduit en anglais avec mention | `knowledge.translation_note`, citations | `test_translation.py` |
| RG-011 | Alerte sur changement de page source | compte rendu, `notify.notify_sync`, revalidation E-09 | `test_sync.py::test_rg011_*`, `test_notify.py`, `test_repository.py` |
| RG-012 | Étape sans source rejetée | `models.Step`, éditeur E-09 | `test_journeys.py::test_rg012_*`, `test_repository.py` |
| RG-013 | Livrables à l'identité de l'organisation | `export.py`, `word.py`, `imports.py`, `notify.py` | `test_deliverables.py` |
| RG-014 | Lien vers la page source et licence | `Citation`, fiche étape, livrables | `test_knowledge.py::test_rg014_*`, `test_journeys_data.py` |
| RG-015 | Accès aux projets des seuls membres, administrateur excepté | `access.visible_projects`, `require_view` | `test_access.py::test_rg015_*`, `test_app.py`, `test_conversation.py` |
| RG-016 | Instance du client en lecture seule | `odoo_client.READ_METHODS` | `test_gap.py::test_rg016_*` |

## Gestion des erreurs de synchronisation (3.3.4)

| Code | Condition | Effet réalisé | Notification | Tests |
| --- | --- | --- | --- | --- |
| ERR-001 | Dépôt inaccessible | 3 tentatives espacées (15 min par défaut), version active conservée | Administrateur | `test_sync.py`, `test_fetch_docs.py` |
| ERR-002 | Branche ou commit introuvable | Arrêt, version active conservée | Administrateur | `test_sync.py`, `test_fetch_docs.py` |
| ERR-003 | Fichier de traduction illisible | Pages du domaine en anglais, signalées | Référent contenu | `test_sync.py`, `test_translation.py` |
| ERR-004 | Taux de traduction sous le seuil | Page publiée avec la mention « traduction partielle » | Référent contenu | `test_sync.py`, `test_translation.py` |
| ERR-005 | Page RST non analysable | Page exclue, sections précédentes conservées | Référent contenu | `test_sync.py` |
| ERR-006 | Indexation ou vectorisation interrompue | Version candidate abandonnée | Administrateur | `test_sync.py`, `test_semantic.py` |
| ERR-007 | Page ou ancre source d'une étape absente | Étape signalée « Source introuvable », rattachement dans E-09 | Référent contenu | `test_sync.py` |
| ERR-008 | Pages en baisse au-delà du seuil | Publication bloquée ; publication forcée tracée (auteur) | Administrateur | `test_sync.py` |

## User stories (4.5)

| US | Critère | Tests |
| --- | --- | --- |
| US-001 | Plan Finance France depuis un profil complet ; refus sans pays | `test_journeys_data.py::test_us001_*`, `test_engine.py::test_rg002_*` |
| US-002 | Refus de Fait si un prérequis n'est pas terminé | `test_engine.py::test_rg003_*` |
| US-003 | Réponse sourcée, ou « non couverte » | `test_knowledge.py`, `test_semantic.py` |
| US-004 | Synchronisation en échec sans effet pour les utilisateurs | `test_sync.py::test_err006_*` |
| US-005 | Alerte quand une page source d'une étape change | `test_sync.py::test_rg011_*`, `test_notify.py` |
| US-006 | Livrables au nom et au logo de l'organisation, sans autre identité | `test_deliverables.py::test_us006_*` |

## Points d'intégration (2.1.5)

| Système | Réalisation |
| --- | --- |
| Dépôt odoo/documentation | clone partiel (RST et .po français), synchronisation hebdomadaire et manuelle |
| Service de modèle de langage | Claude (facultatif, `ANTHROPIC_API_KEY`) ; sans clé, extraits classés |
| Service de vectorisation | local : analyse sémantique latente calculée à la synchronisation (`semantic.py`), remplaçable |
| Messagerie | SMTP de l'organisation (`notify.py`), mot de passe `OCA_SMTP_PASSWORD` |
| Fournisseur d'identité | OIDC via `st.login` quand la section `[auth]` des secrets est renseignée (optionnel) |
| Instance Odoo du client | API externe XML-RPC, lecture seule (phase 2) |

## Questions ouvertes (4.7)

Les questions restent à arbitrer par leurs destinataires ; la réalisation retient un choix par
défaut, paramétrable quand c'est possible.

| ID | Choix par défaut de la réalisation |
| --- | --- |
| Q-001 | Mention de licence CC BY-SA 4.0 sur chaque citation et livrable ; décision juridique à prendre |
| Q-002 | Claude, facultatif ; l'application fonctionne sans service de modèle de langage |
| Q-003 | Seuil de traduction partielle 80 %, paramétrable (Administration) |
| Q-004 | Seuil de baisse du nombre de pages 5 %, paramétrable (Administration) |
| Q-005 | Synchronisation le dimanche à 02:00 UTC (workflow `Doc sync`) |
| Q-006 | Rôle Référent contenu disponible ; la personne reste à désigner |
| Q-007 | Pas de source réglementaire complémentaire ; valeurs non confirmées marquées « À confirmer » |
| Q-008 | Édition dans le profil ; étapes Enterprise hors plan en Community |
| Q-009 | Fournisseur d'identité optionnel (OIDC), comptes locaux sinon |
| Q-010 | Cahier en Excel et Word, modèles d'import en Excel |
| Q-011 | Interface en français uniquement |
| Q-012 | Référentiel et modèle de données portent l'ERP et la version ; un seul ERP en V1 |
| Q-013 | Sans objet pour la réalisation |
