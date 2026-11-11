"""Streamlit interface (French): profile, plan, step sheet, assistant, export.

Run: streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from odoo_config_assistant import DOC_VERSION, ERP  # noqa: E402
from odoo_config_assistant.assistant import answer, load_env_file, make_client  # noqa: E402
from odoo_config_assistant.engine import (  # noqa: E402
    IncompleteProfileError,
    PrerequisiteError,
    StatusTransitionError,
    create_project,
    prerequisite_info,
    recompute_plan,
    set_status,
    update_step,
)
from odoo_config_assistant.export import export_bytes  # noqa: E402
from odoo_config_assistant.imports import (  # noqa: E402
    export_templates_zip,
    load_import_templates,
)
from odoo_config_assistant.journeys import load_catalog  # noqa: E402
from odoo_config_assistant.knowledge import (  # noqa: E402
    DEFAULT_INDEX_PATH,
    BM25Retriever,
    KnowledgeIndex,
    current_doc_commit,
)
from odoo_config_assistant.models import (  # noqa: E402
    ACTIVITY_LABELS,
    EDITION_LABELS,
    LICENSE_NOTICE,
    LICENSE_URL,
    REQUIRED_FIELD_LABELS,
    SIZE_LABELS,
    Activity,
    CompanySize,
    Edition,
    Profile,
    Project,
    StepStatus,
)
from odoo_config_assistant.semantic import HybridRetriever  # noqa: E402
from odoo_config_assistant.semantic import load_retriever as load_semantic_retriever  # noqa: E402
from odoo_config_assistant.storage import list_projects, load_project, save_project  # noqa: E402
from odoo_config_assistant.sync import (  # noqa: E402
    SyncSettings,
    SyncStatus,
    last_published_report,
    list_reports,
    synchronize,
)

MODULE_LABELS = {
    "account": "Comptabilité (account)",
    "stock": "Inventaire (stock)",
    "mrp": "Fabrication (mrp)",
    "purchase": "Achats (purchase)",
    "sale": "Ventes (sale)",
}
CURRENCIES = ["USD", "EUR", "CAD", "GBP", "CHF", "MXN"]
NEW_PROJECT = "+ Nouveau projet"

st.set_page_config(page_title="Assistant de configuration Odoo", layout="wide")
load_env_file(ROOT / ".env")


@st.cache_resource
def get_catalog():
    return load_catalog()


@st.cache_resource
def get_import_templates():
    return load_import_templates()


@st.cache_resource(show_spinner=False)
def get_retriever():
    """Index chargé une fois par processus : BM25 et index sémantique s'il correspond (hybride).
    Au premier démarrage (Streamlit Community Cloud), une première synchronisation télécharge la
    documentation et construit les index. Une exception n'est pas mise en cache : un échec sera
    retenté au rechargement suivant."""
    if DEFAULT_INDEX_PATH.exists():
        index = KnowledgeIndex.load(DEFAULT_INDEX_PATH)
    elif os.environ.get("OCA_AUTO_FETCH", "1") == "0":
        raise FileNotFoundError("index absent, téléchargement automatique désactivé")
    else:
        from odoo_config_assistant.sources import ensure_index

        index = ensure_index()
    return load_semantic_retriever(index.chunks, DEFAULT_INDEX_PATH)


@st.cache_resource(show_spinner=False)
def get_menu_labels(commit: str | None) -> dict[str, str]:
    """Libellés de menus anglais -> français de la version active (F-003)."""
    if not DEFAULT_INDEX_PATH.exists():
        return {}
    data = json.loads(DEFAULT_INDEX_PATH.read_text(encoding="utf-8"))
    return data.get("menu_labels", {})


def french_menu_path(items: list[str], labels: dict[str, str]) -> str | None:
    french = [labels.get(item) for item in items]
    return None if None in french else " > ".join(french)


def load_retriever() -> tuple[BM25Retriever | None, str | None]:
    if not DEFAULT_INDEX_PATH.exists():
        message = "Premier démarrage : téléchargement de la documentation Odoo 18.0 et indexation"
        with st.spinner(message):
            return _try_retriever()
    return _try_retriever()


def _try_retriever() -> tuple[BM25Retriever | None, str | None]:
    try:
        return get_retriever(), None
    except (OSError, RuntimeError, SystemExit, ValueError) as exc:
        return None, str(exc)


def save(project: Project) -> None:
    save_project(project)
    st.session_state["project_id"] = project.id


def current_project() -> Project | None:
    project_id = st.session_state.get("project_id")
    if not project_id:
        return None
    try:
        return load_project(project_id)
    except (FileNotFoundError, ValueError):
        return None


def status_of(project: Project, step_id: str) -> StepStatus:
    return project.plan_step(step_id).status


# --------------------------------------------------------------------------- sidebar

catalog = get_catalog()
retriever, index_error = load_retriever()
doc_commit = current_doc_commit()

with st.sidebar:
    st.title("Assistant de configuration Odoo")
    st.caption(f"ERP : {ERP} {DOC_VERSION}")
    projects = list_projects()
    labels = [NEW_PROJECT] + [f"{p.name} ({p.id})" for p in projects]
    ids = [None] + [p.id for p in projects]
    current_id = st.session_state.get("project_id")
    if current_id is not None and current_id in ids:
        index = ids.index(current_id)
    else:
        index = 1 if projects else 0  # dernier projet modifié, sinon nouveau projet
    choice = st.selectbox("Projet", labels, index=index)
    st.session_state["project_id"] = ids[labels.index(choice)]

    st.divider()
    st.caption("Documentation Odoo 18.0")
    st.caption(f"Commit : `{doc_commit[:12]}`" if doc_commit else "Commit inconnu")
    if retriever is None:
        st.warning(f"Index indisponible ({index_error}).")
    else:
        st.caption(f"Index : {len(retriever.chunks)} sections")
        st.caption(
            "Recherche hybride : BM25 et index sémantique"
            if isinstance(retriever, HybridRetriever)
            else "Recherche BM25 (index sémantique absent)"
        )
    client = make_client()
    st.caption("Réponses rédigées par Claude" if client else "Sans clé d'API : extraits classés")
    st.caption(f"[{LICENSE_NOTICE}]({LICENSE_URL})")

project = current_project()

# Alertes documentaires (RG-011) : dernière synchronisation publiée.
last_report = last_published_report()
doc_alerts = last_report.step_alerts() if last_report else {}

tab_profile, tab_plan, tab_step, tab_assistant, tab_export, tab_sources = st.tabs(
    ["Profil", "Plan", "Fiche étape", "Assistant", "Export", "Sources"]
)

# --------------------------------------------------------------------------- profile

with tab_profile:
    st.header("Projet et profil de l'entreprise")
    profile = project.profile if project else Profile(country="CA", province="QC")
    if project:
        st.caption(
            f"Projet {project.id}, {project.erp} {project.version}. Un changement de version "
            "crée un nouveau projet et un nouveau plan (RG-001)."
        )
    with st.form("profile"):
        name = st.text_input("Nom du projet", value=project.name if project else "")
        company = st.text_input("Société", value=profile.company_name)
        col1, col2 = st.columns(2)
        country = col1.text_input("Pays (code ISO) *", value=profile.country or "")
        province = col2.text_input("Province ou région (code)", value=profile.province or "")
        activities = [None, *Activity]
        activity = col1.selectbox(
            "Activité *",
            activities,
            index=activities.index(profile.activity),
            format_func=lambda a: "Choisir" if a is None else ACTIVITY_LABELS[a],
        )
        sizes = [None, *CompanySize]
        size = col2.selectbox(
            "Taille",
            sizes,
            index=sizes.index(profile.size),
            format_func=lambda s: "Non renseignée" if s is None else SIZE_LABELS[s],
        )
        editions = [None, *Edition]
        edition = col1.selectbox(
            "Édition Odoo",
            editions,
            index=editions.index(profile.edition),
            format_func=lambda e: "Non précisée" if e is None else EDITION_LABELS[e],
            help="En Community, les étapes qui exigent un module Enterprise sont hors plan.",
        )
        modules = st.multiselect(
            "Modules souhaités *",
            list(MODULE_LABELS),
            default=[m for m in profile.modules if m in MODULE_LABELS],
            format_func=MODULE_LABELS.get,
        )
        col3, col4 = st.columns(2)
        tax_regime = col3.text_input("Régime fiscal", value=profile.tax_regime or "")
        fiscal_year_end = col4.text_input("Fin d'exercice (MM-JJ)", value=profile.fiscal_year_end)
        foreign = st.multiselect(
            "Devises étrangères", CURRENCIES, default=profile.foreign_currencies
        )
        uses_checks = st.checkbox("Paiement des fournisseurs par chèque", profile.uses_checks)
        tracks_lots = st.checkbox("Suivi par lots", profile.tracks_lots)
        make_to_order = st.checkbox("Fabrication à la commande", profile.make_to_order)
        st.caption("Options France")
        uses_direct_debit = st.checkbox(
            "Encaissement des clients par prélèvement SEPA", profile.uses_direct_debit
        )
        b2g_invoicing = st.checkbox(
            "Clients du secteur public (factures via Chorus Pro)", profile.b2g_invoicing
        )
        imports_fec_history = st.checkbox(
            "Reprise de l'historique comptable par fichier FEC", profile.imports_fec_history
        )
        submitted = st.form_submit_button("Enregistrer et calculer le plan")

    if submitted:
        try:
            new_profile = Profile(
                company_name=company,
                country=country,
                province=province,
                activity=activity,
                size=size,
                edition=edition,
                tax_regime=tax_regime or None,
                modules=modules,
                fiscal_year_end=fiscal_year_end,
                foreign_currencies=foreign,
                uses_checks=uses_checks,
                tracks_lots=tracks_lots,
                make_to_order=make_to_order,
                uses_direct_debit=uses_direct_debit,
                b2g_invoicing=b2g_invoicing,
                imports_fec_history=imports_fec_history,
            )
        except ValueError as exc:
            st.error(f"Profil invalide : {exc}")
        else:
            try:
                if project is None:
                    project = create_project(
                        name or company or "Projet", new_profile, catalog, doc_commit=doc_commit
                    )
                    st.success(f"Projet créé : {len(project.plan)} étapes au plan.")
                else:
                    before = {s.step_id for s in project.in_scope()}
                    project = recompute_plan(
                        project.model_copy(update={"name": name or project.name}),
                        new_profile,
                        catalog,
                    )
                    after = {s.step_id for s in project.in_scope()}
                    st.success(
                        f"Plan recalculé (RG-005) : {len(after - before)} étape(s) ajoutée(s), "
                        f"{len(before - after)} passée(s) Hors périmètre."
                    )
                save(project)
            except IncompleteProfileError as exc:
                missing = ", ".join(REQUIRED_FIELD_LABELS[f] for f in exc.missing)
                st.error(f"Plan non généré (RG-002). Champs à renseigner : {missing}.")

# --------------------------------------------------------------------------- plan

with tab_plan:
    st.header("Plan de configuration")
    if project is None:
        st.info("Créer un projet dans l'onglet Profil.")
    else:
        in_scope = project.in_scope()
        done = [s for s in in_scope if s.status.is_complete]
        col1, col2, col3 = st.columns(3)
        col1.metric("Étapes au plan", len(in_scope))
        col2.metric("Faites ou validées", len(done))
        col3.metric("Hors périmètre", len(project.plan) - len(in_scope))
        st.progress(len(done) / len(in_scope) if in_scope else 0.0)
        rows = []
        for item in project.plan:
            step = catalog.step(item.step_id)
            info = prerequisite_info(project, item.step_id, catalog)
            rec = step.recommendation_for(project.profile)
            rows.append(
                {
                    "N°": item.order + 1,
                    "Parcours": catalog.journey_of(item.step_id).title,
                    "Étape": step.title,
                    "Statut": item.status.label,
                    "Prérequis bloquants": ", ".join(info.blocking),
                    "À confirmer": "" if rec.verified else "À confirmer",
                    "Édition": "Enterprise" if catalog.enterprise_modules(step) else "",
                    "Alerte doc": "À revalider" if item.step_id in doc_alerts else "",
                    "Identifiant": step.id,
                }
            )
        # Hauteur ajustée au contenu : toutes les étapes du plan sont visibles.
        st.dataframe(rows, hide_index=True, width="stretch", height="content")

# --------------------------------------------------------------------------- step sheet

with tab_step:
    st.header("Fiche étape")
    if project is None or not project.plan:
        st.info("Aucun plan pour l'instant.")
    else:
        step_ids = [s.step_id for s in project.plan]
        linked = st.query_params.get("step")  # lien direct : ?step=fin_taxes
        if linked in step_ids and "step_id" not in st.session_state:
            st.session_state["step_id"] = linked
        selected = st.selectbox(
            "Étape",
            step_ids,
            format_func=lambda i: (
                f"{project.plan_step(i).order + 1}. {catalog.step(i).title} "
                f"[{project.plan_step(i).status.label}]"
            ),
            key="step_id",
        )
        step = catalog.step(selected)
        item = project.plan_step(selected)
        rec = step.recommendation_for(project.profile)

        st.subheader(step.title)
        for alert in doc_alerts.get(selected, []):
            st.warning(alert)
        st.write(step.objective)
        enterprise = catalog.enterprise_modules(step)
        if enterprise:
            st.markdown(
                f":violet[**Enterprise**] module(s) absent(s) de l'édition Community : "
                f"{', '.join(f'`{m}`' for m in enterprise)}"
            )
        st.markdown("**Chemin de menu**")
        menu_fr = french_menu_path(step.menu_items, get_menu_labels(doc_commit))
        if menu_fr:
            st.code(menu_fr, language=None)
            st.caption(f"Interface en anglais : {step.menu_path}")
        else:
            st.code(step.menu_path, language=None)
            st.caption("Libellés de menu en anglais : traduction absente de la documentation.")
        if (
            project.profile.edition is Edition.COMMUNITY
            and step.menu_items[0].removesuffix(" app") == "Accounting"
        ):
            st.caption(
                "En Community, l'application comptable s'appelle Invoicing (Facturation) : "
                "le chemin commence par Invoicing au lieu d'Accounting."
            )
        st.markdown("**Valeur recommandée**")
        st.write(rec.value)
        if not rec.verified:
            st.markdown(":orange[**À confirmer**]")
            st.warning(rec.note)
        elif rec.note:
            st.caption(rec.note)

        info = prerequisite_info(project, selected, catalog)
        if step.prerequisites:
            st.markdown("**Prérequis**")
            for prerequisite in info.finished:
                st.write(f"Terminé : {catalog.step(prerequisite).title}")
            for prerequisite in info.blocking:
                st.write(f"Bloquant : {catalog.step(prerequisite).title}")
            for prerequisite in info.outside_plan:
                st.info(
                    f"Hors du plan, non bloquant : {catalog.step(prerequisite).title} "
                    f"({prerequisite})"
                )

        st.markdown("**Sources**")
        for source in step.sources:
            st.markdown(f"[{source.title}]({source.url}) · `{source.path}`")
        st.caption(
            f"Documentation Odoo {project.version}, commit "
            f"`{(item.doc_commit or project.doc_commit or 'inconnu')[:12]}` · "
            f"[{LICENSE_NOTICE}]({LICENSE_URL})"
        )

        with st.form(f"step-{selected}"):
            statuses = list(StepStatus)
            new_status = st.radio(
                "Statut",
                statuses,
                index=statuses.index(item.status),
                format_func=lambda s: s.label,
                horizontal=True,
            )
            retained = st.text_input("Valeur retenue", value=item.retained_value or "")
            comment = st.text_area("Commentaire", value=item.comment)
            if st.form_submit_button("Enregistrer l'étape"):
                try:
                    updated = project
                    if new_status is not item.status:
                        updated = set_status(updated, selected, new_status, catalog)
                    updated = update_step(
                        updated, selected, retained_value=retained or None, comment=comment
                    )
                    save(updated)
                    st.success("Étape enregistrée.")
                    st.rerun()
                except PrerequisiteError as exc:
                    names = ", ".join(catalog.step(b).title for b in exc.blocking)
                    st.error(f"Passage à Fait refusé (RG-003). Prérequis à terminer : {names}.")
                except StatusTransitionError as exc:
                    st.error(str(exc))

# --------------------------------------------------------------------------- assistant

with tab_assistant:
    st.header("Assistant documentaire")
    st.caption(
        "Réponses fondées uniquement sur la documentation Odoo 18.0 indexée, avec sources. "
        "Les extraits sont en anglais."
    )
    if retriever is None:
        st.warning(
            "Index indisponible : lancer `python scripts/fetch_docs.py` puis "
            f"`python scripts/build_index.py` ({index_error})."
        )
    else:
        context_ids = [None] + ([s.step_id for s in project.plan] if project else [])
        with st.form("question"):
            context = st.selectbox(
                "Contexte",
                context_ids,
                format_func=lambda i: "Aucune étape" if i is None else catalog.step(i).title,
            )
            question = st.text_input("Question", placeholder="Ex. : Comment imprimer des chèques ?")
            asked = st.form_submit_button("Demander")
        if asked and question.strip():
            result = answer(
                question,
                retriever,
                erp=project.erp if project else ERP,
                version=project.version if project else DOC_VERSION,
                doc_commit=doc_commit,
                step=catalog.step(context) if context else None,
                country=project.profile.country if project else None,
                client=client,
            )
            history = st.session_state.setdefault("history", [])
            history.insert(0, result)
        for result in st.session_state.get("history", []):
            with st.container(border=True):
                st.markdown(f"**{result.question}**")
                if result.covered:
                    st.write(result.text)
                else:
                    st.warning(result.text)
                for citation in result.citations:
                    with st.expander(citation.markdown()):
                        if citation.translation_note:
                            st.caption(citation.translation_note)
                        st.text(citation.excerpt)
                st.caption(
                    f"Mode : {result.mode} · Odoo {result.version} · "
                    f"commit `{(result.doc_commit or 'inconnu')[:12]}`"
                )

# --------------------------------------------------------------------------- export

with tab_export:
    st.header("Cahier de paramétrage")
    if project is None or not project.plan:
        st.info("Aucun plan à exporter.")
    else:
        st.write(
            "Une ligne par étape : statut, valeur recommandée (avec la colonne « À confirmer »), "
            "valeur retenue, commentaire, sources, version documentaire et édition requise. "
            "La feuille Checklist reprend les étapes du plan dans l'ordre, prête à imprimer."
        )
        st.download_button(
            "Télécharger le cahier (Excel)",
            data=export_bytes(project, catalog),
            file_name=f"cahier_parametrage_{project.id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.subheader("Modèles de fichiers d'import")
        templates = get_import_templates().for_project(project)
        if not templates:
            st.info("Aucun modèle d'import ne correspond aux étapes du plan.")
        else:
            st.write(
                "Un fichier Excel par jeu de données à charger dans Odoo, limité aux étapes du "
                "plan. En-têtes au nom technique des champs, feuille Aide avec le sens et un "
                "exemple de chaque colonne."
            )
            for template in templates:
                st.write(f"- {template.title} (`{template.model}`)")
            st.download_button(
                "Télécharger les modèles d'import (.zip)",
                data=export_templates_zip(project, catalog, get_import_templates()),
                file_name=f"modeles_import_{project.id}.zip",
                mime="application/zip",
            )


# --------------------------------------------------------------------------- sources (E-08)


def run_sync(**kwargs) -> None:
    with st.spinner("Synchronisation de la documentation Odoo 18.0"):
        try:
            report = synchronize(settings=SyncSettings(retries=1), **kwargs)
        except ValueError as exc:
            st.session_state["sync_message"] = ("error", str(exc))
            return
    get_retriever.clear()
    level = "success" if report.status.published else "info"
    if report.status in (SyncStatus.FAILED, SyncStatus.BLOCKED):
        level = "error"
    st.session_state["sync_message"] = (level, f"Synchronisation : {report.status.label}.")
    st.rerun()


with tab_sources:
    st.header("Sources documentaires")
    st.write(
        "Dépôt odoo/documentation, branche 18.0. La version active n'est remplacée que si tous "
        "les contrôles sont OK (RG-009) ; le compte rendu liste les étapes dont une page source "
        "a changé (RG-011)."
    )
    st.caption(
        f"Version active : commit `{doc_commit[:12] if doc_commit else 'aucune'}`"
        + (f", {len(retriever.chunks)} sections indexées" if retriever else "")
    )
    message = st.session_state.pop("sync_message", None)
    if message:
        getattr(st, message[0])(message[1])
    if st.button("Synchroniser maintenant"):
        run_sync(trigger="manuelle")

    reports = list_reports()
    if not reports:
        st.info("Aucune synchronisation enregistrée.")
    else:
        latest = reports[0]
        st.subheader("Dernier compte rendu")
        st.markdown(latest.markdown().replace("## ", "#### ", 1))
        if latest.status is SyncStatus.BLOCKED:
            st.warning(
                "Publication bloquée (ERR-008). Publier la version candidate malgré l'alerte, "
                "ou attendre la prochaine synchronisation. La décision est tracée."
            )
            author = st.text_input("Auteur de la décision")
            if st.button("Publier la version candidate", disabled=not author.strip()):
                run_sync(trigger="relance manuelle", force=True, forced_by=author)
        st.subheader("Historique")
        st.dataframe(
            [
                {
                    "Date (UTC)": r.started_at.strftime("%Y-%m-%d %H:%M"),
                    "Déclencheur": r.trigger,
                    "Statut": r.status.label,
                    "Avant": (r.active_commit or "")[:7],
                    "Candidate": (r.candidate_commit or "")[:7],
                    "Ajoutées": len(r.added),
                    "Modifiées": len(r.modified),
                    "Supprimées": len(r.deleted),
                    "Étapes impactées": len(r.impacted_steps),
                    "Anomalies": ", ".join(sorted({a.code for a in r.anomalies})),
                }
                for r in reports
            ],
            hide_index=True,
            width="stretch",
        )
    st.caption(
        "Synchronisation planifiée : chaque dimanche à 02:00 UTC (workflow GitHub « Doc sync »). "
        "Sur Streamlit Community Cloud, le disque n'est pas persistant : l'historique repart à "
        "zéro au redémarrage de l'instance."
    )
