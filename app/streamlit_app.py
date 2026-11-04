"""Streamlit interface (French): profile, plan, step sheet, assistant, export.

Run: streamlit run app/streamlit_app.py
"""

from __future__ import annotations

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
from odoo_config_assistant.journeys import load_catalog  # noqa: E402
from odoo_config_assistant.knowledge import (  # noqa: E402
    DEFAULT_INDEX_PATH,
    BM25Retriever,
    KnowledgeIndex,
    current_doc_commit,
)
from odoo_config_assistant.models import (  # noqa: E402
    ACTIVITY_LABELS,
    LICENSE_NOTICE,
    LICENSE_URL,
    REQUIRED_FIELD_LABELS,
    SIZE_LABELS,
    Activity,
    CompanySize,
    Profile,
    Project,
    StepStatus,
)
from odoo_config_assistant.storage import list_projects, load_project, save_project  # noqa: E402

MODULE_LABELS = {
    "account": "Comptabilité (account)",
    "stock": "Inventaire (stock)",
    "mrp": "Fabrication (mrp)",
    "purchase": "Achats (purchase)",
    "sale": "Ventes (sale)",
}
CURRENCIES = ["USD", "EUR", "GBP", "MXN"]
NEW_PROJECT = "+ Nouveau projet"

st.set_page_config(page_title="Assistant de configuration Odoo", layout="wide")
load_env_file(ROOT / ".env")


@st.cache_resource
def get_catalog():
    return load_catalog()


@st.cache_resource(show_spinner=False)
def get_retriever() -> BM25Retriever:
    """Index chargé une fois par processus. Au premier démarrage (Streamlit Community Cloud),
    la documentation est téléchargée et l'index construit. Une exception n'est pas mise en
    cache : un échec sera retenté au rechargement suivant."""
    if DEFAULT_INDEX_PATH.exists():
        return BM25Retriever(KnowledgeIndex.load(DEFAULT_INDEX_PATH).chunks)
    if os.environ.get("OCA_AUTO_FETCH", "1") == "0":
        raise FileNotFoundError("index absent, téléchargement automatique désactivé")
    from odoo_config_assistant.sources import ensure_index

    return BM25Retriever(ensure_index().chunks)


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
    client = make_client()
    st.caption("Réponses rédigées par Claude" if client else "Sans clé d'API : extraits classés")
    st.caption(f"[{LICENSE_NOTICE}]({LICENSE_URL})")

project = current_project()

tab_profile, tab_plan, tab_step, tab_assistant, tab_export = st.tabs(
    ["Profil", "Plan", "Fiche étape", "Assistant", "Export"]
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
        submitted = st.form_submit_button("Enregistrer et calculer le plan")

    if submitted:
        try:
            new_profile = Profile(
                company_name=company,
                country=country,
                province=province,
                activity=activity,
                size=size,
                tax_regime=tax_regime or None,
                modules=modules,
                fiscal_year_end=fiscal_year_end,
                foreign_currencies=foreign,
                uses_checks=uses_checks,
                tracks_lots=tracks_lots,
                make_to_order=make_to_order,
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
        st.write(step.objective)
        st.markdown("**Chemin de menu**")
        st.code(step.menu_path, language=None)
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
            "valeur retenue, commentaire, sources et version documentaire."
        )
        st.download_button(
            "Télécharger le cahier (Excel)",
            data=export_bytes(project, catalog),
            file_name=f"cahier_parametrage_{project.id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
