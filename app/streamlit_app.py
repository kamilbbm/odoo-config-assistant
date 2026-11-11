"""Streamlit interface (French), one tab per screen of the SFD (2.1.4), shown by role.

E-01 Tableau de bord, E-02 Projet et profil, E-03 Plan, E-04 Fiche étape, E-05 Assistant,
E-06 Livrables, E-07 Administration de l'organisation, E-08 Sources documentaires,
E-09 Référentiel et parcours.

Run: streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from odoo_config_assistant import (  # noqa: E402
    DOC_VERSION,
    ERP,
    conversation,
    repository,
)
from odoo_config_assistant.access import (  # noqa: E402
    AccessDenied,
    allowed_statuses,
    can_admin,
    can_create_project,
    can_edit_profile,
    can_edit_repository,
    can_manage_project,
    can_manage_sources,
    change_status,
    edit_step,
    visible_projects,
)
from odoo_config_assistant.assistant import load_env_file, make_client  # noqa: E402
from odoo_config_assistant.db import ROLE_LABELS, Database, Organisation, Role, User  # noqa: E402
from odoo_config_assistant.engine import (  # noqa: E402
    IncompleteProfileError,
    PrerequisiteError,
    StatusTransitionError,
    create_project,
    prerequisite_info,
    project_progress,
    recompute_plan,
)
from odoo_config_assistant.export import export_bytes  # noqa: E402
from odoo_config_assistant.imports import (  # noqa: E402
    export_templates_zip,
    load_import_templates,
)
from odoo_config_assistant.journeys import JourneyValidationError  # noqa: E402
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
from odoo_config_assistant.repository import catalog_for  # noqa: E402
from odoo_config_assistant.seed import demo_accounts, ensure_ready, setup_organisation  # noqa: E402
from odoo_config_assistant.semantic import HybridRetriever  # noqa: E402
from odoo_config_assistant.semantic import load_retriever as load_semantic_retriever  # noqa: E402
from odoo_config_assistant.sync import (  # noqa: E402
    SyncSettings,
    SyncStatus,
    last_published_report,
    list_reports,
    synchronize,
)
from odoo_config_assistant.word import build_docx  # noqa: E402

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


# --------------------------------------------------------------------------- resources


@st.cache_resource
def get_db(path: str | None) -> Database:
    """Une base par chemin (OCA_DB), partagée par les sessions du processus."""
    return Database(path)


@st.cache_resource
def get_catalog(path: str | None, version: str):
    """Catalogue livré + modifications du référent (E-09) ; ``version`` change à chaque
    modification enregistrée, ce qui recharge le catalogue."""
    return catalog_for(get_db(path))


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


def flash(level: str, message: str) -> None:
    st.session_state["flash"] = (level, message)


def show_flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        getattr(st, message[0])(message[1])


# --------------------------------------------------------------------------- authentication


def setup_screen(db: Database) -> None:
    st.title("Installation")
    st.write(
        "Première connexion : renseigner l'organisation utilisatrice et son premier "
        "administrateur (F-001). Aucune société n'est codée en dur (RG-013)."
    )
    with st.form("setup"):
        org_name = st.text_input("Nom de l'organisation *")
        admin_name = st.text_input("Nom de l'administrateur *")
        email = st.text_input("Courriel *")
        password = st.text_input("Mot de passe (8 caractères ou plus) *", type="password")
        if st.form_submit_button("Créer l'organisation"):
            try:
                user = setup_organisation(db, org_name, email, admin_name, password)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state["user_id"] = user.id
                st.rerun()


def login_screen(db: Database, organisation: Organisation | None) -> None:
    st.title(organisation.name if organisation else "Assistant de configuration Odoo")
    st.subheader("Connexion")
    with st.form("login"):
        email = st.text_input("Courriel")
        password = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Se connecter"):
            user = db.authenticate(email, password)
            if user is None:
                st.error("Courriel ou mot de passe incorrect, ou compte désactivé.")
            else:
                st.session_state["user_id"] = user.id
                st.rerun()
    if organisation and organisation.demo:
        accounts, password = demo_accounts()
        st.divider()
        st.markdown("**Démonstration** : comptes fictifs, mot de passe `" + password + "`.")
        for account in accounts:
            label = f"{account['name']} ({ROLE_LABELS[Role(account['role'])]})"
            if st.button(label, key=f"demo-{account['email']}"):
                user = db.authenticate(account["email"], password)
                if user:
                    st.session_state["user_id"] = user.id
                    st.rerun()


def current_user(db: Database) -> User | None:
    user_id = st.session_state.get("user_id")
    if user_id is None:
        return None
    try:
        user = db.user(int(user_id))
    except KeyError:
        return None
    return user if user.active else None


# --------------------------------------------------------------------------- start

db = get_db(os.environ.get("OCA_DB"))
if not ensure_ready(db):
    setup_screen(db)
    st.stop()
organisation = db.organisation()
user = current_user(db)
if user is None:
    login_screen(db, organisation)
    st.stop()

catalog = get_catalog(os.environ.get("OCA_DB"), db.repository_version())
retriever, index_error = load_retriever()
doc_commit = current_doc_commit()
client = make_client()

projects = visible_projects(db, user)

with st.sidebar:
    if organisation and organisation.logo_b64:
        st.image(base64.b64decode(organisation.logo_b64), width=120)
    st.title(organisation.name if organisation else "Assistant de configuration Odoo")
    st.caption(f"{user.name} · {user.role.label}")
    if st.button("Se déconnecter"):
        st.session_state.clear()
        st.rerun()
    st.divider()
    names = {p.id: p.name for p in projects}
    options = [p.id for p in projects]
    if can_create_project(user):
        options.insert(0, NEW_PROJECT)
    project_id = None
    if options:
        # Choix mémorisé par projet ; par défaut, le dernier projet modifié.
        wanted = st.session_state.get("project_id")
        if st.session_state.get("project_select") not in options:
            st.session_state["project_select"] = (
                wanted
                if wanted in options
                else next((o for o in options if o != NEW_PROJECT), options[0])
            )
        choice = st.selectbox(
            "Projet", options, key="project_select", format_func=lambda o: names.get(o, o)
        )
        project_id = None if choice == NEW_PROJECT else choice
        st.session_state["project_id"] = project_id
    else:
        st.caption("Aucun projet accessible.")

    st.divider()
    st.caption(f"ERP : {ERP} {DOC_VERSION}")
    st.caption(f"Documentation : commit `{doc_commit[:12]}`" if doc_commit else "Commit inconnu")
    if retriever is None:
        st.warning(f"Index indisponible ({index_error}).")
    else:
        st.caption(
            f"Index : {len(retriever.chunks)} sections, "
            + ("recherche hybride" if isinstance(retriever, HybridRetriever) else "BM25")
        )
    st.caption("Réponses rédigées par Claude" if client else "Sans clé d'API : extraits classés")
    st.caption(f"[{LICENSE_NOTICE}]({LICENSE_URL})")

project: Project | None = None
if project_id is not None:
    try:
        project = db.project(project_id)
    except KeyError:
        project = None

last_report = last_published_report()
doc_alerts = last_report.step_alerts() if last_report else {}
if last_report:  # RG-011 : une étape revalidée par le référent n'est plus signalée
    reviewed = db.reviewed_steps(last_report.id)
    doc_alerts = {k: v for k, v in doc_alerts.items() if k not in reviewed}

is_project_user = user.role in (Role.ADMIN, Role.CONSULTANT, Role.CLIENT)
screens: list[str] = []
if is_project_user:
    screens += ["Tableau de bord", "Projet", "Plan", "Fiche étape"]
screens.append("Assistant")
if project is not None and can_manage_project(db, user, project.id):
    screens.append("Livrables")
if can_admin(user):
    screens.append("Administration")
if can_manage_sources(user):
    screens.append("Sources")
if can_edit_repository(user):
    screens.append("Référentiel")
tabs = dict(zip(screens, st.tabs(screens), strict=True))


def catalog_step_ids(current) -> set[str]:
    return {s.id for j in current.journeys for s in j.steps}


def save(updated: Project) -> Project:
    saved = db.save_project(updated)
    st.session_state["project_id"] = saved.id
    st.session_state.pop("project_select", None)  # le sélecteur suit le projet enregistré
    return saved


# --------------------------------------------------------------------------- E-01 dashboard

if "Tableau de bord" in tabs:
    with tabs["Tableau de bord"]:
        st.header("Tableau de bord")
        if not projects:
            st.info("Aucun projet pour l'instant.")
        rows = []
        for item in projects:
            progress = project_progress(item, catalog)
            row = {
                "Projet": item.name,
                "Société": item.profile.company_name,
                "ERP": f"{item.erp} {item.version}",
                "Étapes": progress.total,
                "Faites": progress.done,
                "Validées": progress.validated,
                "Avancement": round(progress.ratio * 100),
            }
            for domain, (done, total) in sorted(progress.by_domain.items()):
                row[domain] = f"{done}/{total}"
            row["Membres"] = ", ".join(m.name for m in db.members(item.id))
            rows.append(row)
        if rows:
            st.dataframe(
                rows,
                hide_index=True,
                width="stretch",
                column_config={
                    "Avancement": st.column_config.ProgressColumn(
                        "Avancement", format="%d %%", min_value=0, max_value=100
                    )
                },
            )


# --------------------------------------------------------------------------- E-02 project

if "Projet" in tabs:
    with tabs["Projet"]:
        st.header("Projet et profil de l'entreprise")
        show_flash()
        creating = project is None
        if creating and not can_create_project(user):
            st.info("Aucun projet : un consultant crée le projet et vous y affecte.")
        else:
            editable = creating or can_edit_profile(db, user, project.id)
            profile = project.profile if project else Profile()
            if project:
                st.caption(
                    f"Projet {project.id}, {project.erp} {project.version}. Un changement de "
                    "version crée un nouveau projet et un nouveau plan (RG-001)."
                )
            with st.form("profile"):
                name = st.text_input(
                    "Nom du projet", value=project.name if project else "", disabled=not editable
                )
                company = st.text_input(
                    "Société", value=profile.company_name, disabled=not editable
                )
                col1, col2 = st.columns(2)
                country = col1.text_input(
                    "Pays (code ISO) *", value=profile.country or "", disabled=not editable
                )
                province = col2.text_input(
                    "Province ou région (code)", value=profile.province or "", disabled=not editable
                )
                activities = [None, *Activity]
                activity = col1.selectbox(
                    "Activité *",
                    activities,
                    index=activities.index(profile.activity),
                    format_func=lambda a: "Choisir" if a is None else ACTIVITY_LABELS[a],
                    disabled=not editable,
                )
                sizes = [None, *CompanySize]
                size = col2.selectbox(
                    "Taille",
                    sizes,
                    index=sizes.index(profile.size),
                    format_func=lambda s: "Non renseignée" if s is None else SIZE_LABELS[s],
                    disabled=not editable,
                )
                editions = [None, *Edition]
                edition = col1.selectbox(
                    "Édition Odoo",
                    editions,
                    index=editions.index(profile.edition),
                    format_func=lambda e: "Non précisée" if e is None else EDITION_LABELS[e],
                    help="En Community, les étapes Enterprise sont hors plan.",
                    disabled=not editable,
                )
                modules = st.multiselect(
                    "Modules souhaités *",
                    list(MODULE_LABELS),
                    default=[m for m in profile.modules if m in MODULE_LABELS],
                    format_func=MODULE_LABELS.get,
                    disabled=not editable,
                )
                col3, col4 = st.columns(2)
                tax_regime = col3.text_input(
                    "Régime fiscal", value=profile.tax_regime or "", disabled=not editable
                )
                fiscal_year_end = col4.text_input(
                    "Fin d'exercice (MM-JJ)", value=profile.fiscal_year_end, disabled=not editable
                )
                foreign = st.multiselect(
                    "Devises étrangères",
                    CURRENCIES,
                    default=profile.foreign_currencies,
                    disabled=not editable,
                )
                uses_checks = st.checkbox(
                    "Paiement des fournisseurs par chèque",
                    profile.uses_checks,
                    disabled=not editable,
                )
                tracks_lots = st.checkbox(
                    "Suivi par lots", profile.tracks_lots, disabled=not editable
                )
                make_to_order = st.checkbox(
                    "Fabrication à la commande", profile.make_to_order, disabled=not editable
                )
                st.caption("Options France")
                uses_direct_debit = st.checkbox(
                    "Encaissement des clients par prélèvement SEPA",
                    profile.uses_direct_debit,
                    disabled=not editable,
                )
                b2g_invoicing = st.checkbox(
                    "Clients du secteur public (factures via Chorus Pro)",
                    profile.b2g_invoicing,
                    disabled=not editable,
                )
                imports_fec_history = st.checkbox(
                    "Reprise de l'historique comptable par fichier FEC",
                    profile.imports_fec_history,
                    disabled=not editable,
                )
                submitted = st.form_submit_button(
                    "Enregistrer et calculer le plan", disabled=not editable
                )

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
                            created = create_project(
                                name or company or "Projet",
                                new_profile,
                                catalog,
                                doc_commit=doc_commit,
                            )
                            created = save(created)
                            if user.role is not Role.ADMIN:
                                db.add_member(created.id, user.id)
                            flash("success", f"Projet créé : {len(created.plan)} étapes au plan.")
                        else:
                            before = {s.step_id for s in project.in_scope()}
                            updated = recompute_plan(
                                project.model_copy(update={"name": name or project.name}),
                                new_profile,
                                catalog,
                            )
                            save(updated)
                            after = {s.step_id for s in updated.in_scope()}
                            flash(
                                "success",
                                f"Plan recalculé (RG-005) : {len(after - before)} étape(s) "
                                f"ajoutée(s), {len(before - after)} passée(s) Hors périmètre.",
                            )
                        st.rerun()
                    except IncompleteProfileError as exc:
                        missing = ", ".join(REQUIRED_FIELD_LABELS[f] for f in exc.missing)
                        st.error(f"Plan non généré (RG-002). Champs à renseigner : {missing}.")

            if project is not None:
                st.subheader("Membres du projet (F-006)")
                members = db.members(project.id)
                st.dataframe(
                    [{"Nom": m.name, "Courriel": m.email, "Rôle": m.role.label} for m in members],
                    hide_index=True,
                    width="stretch",
                )
                if can_manage_project(db, user, project.id):
                    candidates = [
                        u
                        for u in db.users()
                        if u.active
                        and u.role in (Role.CONSULTANT, Role.CLIENT)
                        and u.id not in {m.id for m in members}
                    ]
                    col1, col2 = st.columns(2)
                    with col1.form("add-member"):
                        to_add = st.selectbox(
                            "Ajouter un membre",
                            candidates,
                            format_func=lambda u: u.label,
                            index=None,
                            placeholder="Choisir un utilisateur",
                        )
                        if st.form_submit_button("Ajouter") and to_add is not None:
                            db.add_member(project.id, to_add.id)
                            flash("success", f"{to_add.name} ajouté au projet.")
                            st.rerun()
                    with col2.form("remove-member"):
                        to_remove = st.selectbox(
                            "Retirer un membre",
                            members,
                            format_func=lambda u: u.label,
                            index=None,
                            placeholder="Choisir un membre",
                        )
                        if st.form_submit_button("Retirer") and to_remove is not None:
                            db.remove_member(project.id, to_remove.id)
                            flash("success", f"{to_remove.name} retiré du projet.")
                            st.rerun()


# --------------------------------------------------------------------------- E-03 plan

if "Plan" in tabs:
    with tabs["Plan"]:
        st.header("Plan de configuration")
        if project is None:
            st.info("Aucun projet sélectionné.")
        else:
            progress = project_progress(project, catalog)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Étapes au plan", progress.total)
            col2.metric("Faites ou validées", progress.done + progress.validated)
            col3.metric("Validées par le client", progress.validated)
            col4.metric("Hors périmètre", len(project.plan) - progress.total)
            st.progress(progress.ratio)
            rows = []
            for item in project.plan:
                step = catalog.step(item.step_id)
                journey = catalog.journey_of(item.step_id)
                info = prerequisite_info(project, item.step_id, catalog)
                rec = step.recommendation_for(project.profile)
                location = catalog.location(step)
                rows.append(
                    {
                        "N°": item.order + 1,
                        "Domaine": journey.domain,
                        "Module": location.module.label if location else "",
                        "Processus": location.process.label if location else "",
                        "Parcours": journey.title,
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


# --------------------------------------------------------------------------- E-04 step sheet

if "Fiche étape" in tabs:
    with tabs["Fiche étape"]:
        st.header("Fiche étape")
        show_flash()
        if project is None or not project.plan:
            st.info("Aucun plan pour l'instant.")
        else:
            step_ids = [s.step_id for s in project.plan]
            linked = st.query_params.get("step")  # lien direct : ?step=fin_taxes
            if linked in step_ids and "step_id" not in st.session_state:
                st.session_state["step_id"] = linked
            if st.session_state.get("step_id") not in step_ids:
                st.session_state["step_id"] = step_ids[0]
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
            location = catalog.location(step)
            if location:
                st.caption(location.label)
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

            step_exchanges = conversation.history(db, user, project, selected)
            if step_exchanges:
                with st.expander(
                    f"Échanges avec l'assistant sur cette étape ({len(step_exchanges)})"
                ):
                    for exchange in step_exchanges:
                        st.markdown(
                            f"**{exchange.question}** · {exchange.created_at[:10]} · "
                            + ("couverte" if exchange.covered else "non couverte")
                        )
                        st.write(exchange.text)

            st.markdown("**Sources**")
            for source in step.sources:
                st.markdown(f"[{source.title}]({source.url}) · `{source.path}`")
            st.caption(
                f"Documentation Odoo {project.version}, commit "
                f"`{(item.doc_commit or project.doc_commit or 'inconnu')[:12]}` · "
                f"[{LICENSE_NOTICE}]({LICENSE_URL})"
            )

            statuses = allowed_statuses(db, user, project, selected)
            manager = can_manage_project(db, user, project.id)
            if user.role is Role.CLIENT and item.status in (StepStatus.DONE, StepStatus.VALIDATED):
                st.info("Validation client (RG-004) : passer l'étape à Validé une fois vérifiée.")
            with st.form(f"step-{selected}"):
                new_status = st.radio(
                    "Statut",
                    statuses,
                    index=statuses.index(item.status),
                    format_func=lambda s: s.label,
                    horizontal=True,
                    disabled=len(statuses) == 1,
                )
                retained = st.text_input(
                    "Valeur retenue", value=item.retained_value or "", disabled=not manager
                )
                comment = st.text_area("Commentaire", value=item.comment)
                if st.form_submit_button("Enregistrer l'étape"):
                    try:
                        updated = change_status(db, user, project, selected, new_status, catalog)
                        updated = edit_step(
                            db,
                            user,
                            updated,
                            selected,
                            (retained or None) if manager else item.retained_value,
                            comment,
                        )
                        save(updated)
                        flash("success", "Étape enregistrée.")
                        st.rerun()
                    except PrerequisiteError as exc:
                        names = ", ".join(catalog.step(b).title for b in exc.blocking)
                        st.error(f"Passage à Fait refusé (RG-003). Prérequis à terminer : {names}.")
                    except (StatusTransitionError, AccessDenied) as exc:
                        st.error(str(exc))


# --------------------------------------------------------------------------- E-05 assistant


def render_exchange(exchange, compact: bool = False) -> None:
    with st.container(border=True):
        context = catalog.step(exchange.step_id).title if exchange.step_id in step_ids_all else ""
        st.markdown(f"**{exchange.question}**" + (f"  \n_Étape : {context}_" if context else ""))
        if exchange.covered:
            st.write(exchange.text)
        else:
            st.warning(exchange.text)
        for citation in conversation.citations(exchange)[: 2 if compact else None]:
            if compact:
                st.markdown(citation.markdown())
                continue
            with st.expander(citation.markdown()):
                if citation.translation_note:
                    st.caption(citation.translation_note)
                st.text(citation.excerpt)
        author = users_by_id.get(exchange.user_id)
        st.caption(
            f"{exchange.created_at.replace('T', ' ')[:16]} UTC"
            + (f" · {author.name}" if author else "")
            + f" · Odoo {exchange.version} · commit `{(exchange.doc_commit or 'inconnu')[:12]}`"
        )


def ask_question(question: str, step_id: str | None) -> None:
    try:
        conversation.ask(
            db,
            user,
            retriever,
            catalog,
            question,
            project=project,
            step_id=step_id,
            client=client,
            doc_commit=doc_commit,
        )
    except (AccessDenied, ValueError) as exc:
        flash("error", str(exc))


step_ids_all = catalog_step_ids(catalog)
users_by_id = {u.id: u for u in db.users()}
open_step = st.session_state.get("step_id") if project else None
if project is not None and open_step not in {s.step_id for s in project.plan}:
    open_step = None

with tabs["Assistant"]:
    st.header("Assistant documentaire")
    st.caption(
        "Réponses fondées uniquement sur la documentation Odoo 18.0 indexée, avec sources. "
        "Extraits en français (recomposés depuis les traductions officielles) ; un passage non "
        "traduit est affiché en anglais avec une mention. Les échanges sont conservés avec la "
        "version documentaire utilisée (RG-008)."
    )
    show_flash()
    if retriever is None:
        st.warning(f"Index indisponible : lancer `python scripts/sync_docs.py` ({index_error}).")
    else:
        context_ids = [None] + ([s.step_id for s in project.plan] if project else [])
        with st.form("question"):
            context = st.selectbox(
                "Contexte",
                context_ids,
                index=context_ids.index(open_step) if open_step in context_ids else 0,
                format_func=lambda i: "Aucune étape" if i is None else catalog.step(i).title,
            )
            question = st.text_input("Question", placeholder="Ex. : Comment imprimer des chèques ?")
            asked = st.form_submit_button("Demander")
        if asked and question.strip():
            ask_question(question, context)  # affiché ci-dessous, dans le même passage
            show_flash()
    filter_ids = [None] + ([s.step_id for s in project.plan] if project else [])
    shown = st.selectbox(
        "Historique",
        filter_ids,
        format_func=lambda i: (
            ("Tous les échanges du projet" if project else "Mes échanges")
            if i is None
            else catalog.step(i).title
        ),
        key="history_filter",
    )
    for exchange in conversation.history(db, user, project, shown):
        render_exchange(exchange)

# Panneau de l'assistant accessible depuis toutes les pages (E-05), contextualisé à l'étape
# ouverte dans la fiche étape.
with st.sidebar:
    st.divider()
    label = "Assistant"
    if open_step:
        label += f" · {catalog.step(open_step).title}"
    with st.expander(label, expanded=False):
        if retriever is None:
            st.caption("Index indisponible.")
        else:
            with st.form("sidebar-question", clear_on_submit=True):
                quick = st.text_input("Question sur l'étape ouverte" if open_step else "Question")
                if st.form_submit_button("Demander") and quick.strip():
                    ask_question(quick, open_step)
            latest = conversation.history(db, user, project, open_step)[:1]
            for exchange in latest:
                render_exchange(exchange, compact=True)


# --------------------------------------------------------------------------- E-06 deliverables

if "Livrables" in tabs and project is not None:
    with tabs["Livrables"]:
        st.header("Livrables")
        if not project.plan:
            st.info("Aucun plan à exporter.")
        else:
            st.subheader("Cahier de paramétrage et checklist")
            st.write(
                "Une ligne par étape : statut, valeur recommandée (avec la colonne « À "
                "confirmer »), valeur retenue, commentaire, sources, version documentaire et "
                "édition requise. La feuille Checklist reprend les étapes du plan dans l'ordre."
            )
            col1, col2 = st.columns(2)
            if col1.download_button(
                "Télécharger le cahier (Excel)",
                data=export_bytes(project, catalog, organisation),
                file_name=f"cahier_parametrage_{project.id}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ):
                db.log_deliverable(project.id, "cahier", "xlsx", user.id)
            if col2.download_button(
                "Télécharger le cahier (Word)",
                data=build_docx(project, catalog, organisation, get_menu_labels(doc_commit)),
                file_name=f"cahier_parametrage_{project.id}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ):
                db.log_deliverable(project.id, "cahier", "docx", user.id)
            st.caption(
                "Les livrables portent le nom, le logo et les mentions de l'organisation "
                "(RG-013), définis dans l'écran Administration."
            )

            st.subheader("Modèles de fichiers d'import")
            templates = get_import_templates().for_project(project)
            if not templates:
                st.info("Aucun modèle d'import ne correspond aux étapes du plan.")
            else:
                st.write(
                    "Un fichier Excel par jeu de données à charger dans Odoo, limité aux étapes "
                    "du plan. En-têtes au nom technique des champs, feuille Aide avec le sens et "
                    "un exemple de chaque colonne."
                )
                for template in templates:
                    st.write(f"- {template.title} (`{template.model}`)")
                if st.download_button(
                    "Télécharger les modèles d'import (.zip)",
                    data=export_templates_zip(
                        project, catalog, get_import_templates(), organisation
                    ),
                    file_name=f"modeles_import_{project.id}.zip",
                    mime="application/zip",
                ):
                    db.log_deliverable(project.id, "modeles_import", "zip", user.id)

            history = db.deliverables(project.id)
            if history:
                st.subheader("Historique des livrables")
                st.dataframe(
                    [
                        {
                            "Date (UTC)": d["created_at"].replace("T", " ")[:16],
                            "Livrable": d["kind"],
                            "Format": d["format"],
                            "Par": d["user_name"] or "",
                        }
                        for d in history
                    ],
                    hide_index=True,
                    width="stretch",
                )


# --------------------------------------------------------------------------- E-07 administration

if "Administration" in tabs:
    with tabs["Administration"]:
        st.header("Administration de l'organisation")
        show_flash()
        org = organisation or Organisation(name="Organisation")
        st.subheader("Identité (F-001, RG-013)")
        with st.form("organisation"):
            org_name = st.text_input("Nom de l'organisation *", value=org.name)
            mentions = st.text_area("Mentions des livrables", value=org.mentions)
            logo = st.file_uploader("Logo (PNG ou JPEG)", type=["png", "jpg", "jpeg"])
            remove_logo = st.checkbox("Retirer le logo", value=False) if org.logo_b64 else False
            st.markdown("**Paramètres de synchronisation**")
            col1, col2 = st.columns(2)
            drop = col1.number_input(
                "Seuil de baisse du nombre de pages (ERR-008, Q-004)",
                min_value=0.0,
                max_value=1.0,
                value=org.drop_threshold,
                step=0.01,
            )
            translation = col2.number_input(
                "Seuil de traduction partielle (ERR-004, Q-003)",
                min_value=0.0,
                max_value=1.0,
                value=org.translation_threshold,
                step=0.05,
            )
            if st.form_submit_button("Enregistrer l'identité"):
                changes = {
                    "name": org_name,
                    "mentions": mentions,
                    "drop_threshold": drop,
                    "translation_threshold": translation,
                }
                if logo is not None:
                    changes["logo_b64"] = base64.b64encode(logo.getvalue()).decode()
                    changes["logo_mime"] = logo.type
                elif remove_logo:
                    changes["logo_b64"] = None
                    changes["logo_mime"] = None
                try:
                    db.save_organisation(Organisation.model_validate(org.model_dump() | changes))
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    flash("success", "Identité de l'organisation enregistrée.")
                    st.rerun()

        st.subheader("Utilisateurs et rôles")
        st.dataframe(
            [
                {
                    "Nom": u.name,
                    "Courriel": u.email,
                    "Rôle": u.role.label,
                    "Actif": "oui" if u.active else "non",
                }
                for u in db.users()
            ],
            hide_index=True,
            width="stretch",
        )
        col1, col2 = st.columns(2)
        with col1.form("new-user"):
            st.markdown("**Inviter un utilisateur**")
            new_name = st.text_input("Nom")
            new_email = st.text_input("Courriel")
            new_role = st.selectbox("Rôle", list(Role), format_func=lambda r: r.label)
            new_password = st.text_input("Mot de passe initial", type="password")
            if st.form_submit_button("Créer le compte"):
                try:
                    created_user = db.create_user(new_email, new_name, new_role, new_password)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    flash("success", f"Compte créé : {created_user.label}.")
                    st.rerun()
        with col2.form("edit-user"):
            st.markdown("**Modifier un utilisateur**")
            target = st.selectbox("Utilisateur", db.users(), format_func=lambda u: u.label)
            role = st.selectbox(
                "Nouveau rôle",
                list(Role),
                index=list(Role).index(target.role) if target else 0,
                format_func=lambda r: r.label,
            )
            active = st.checkbox("Compte actif", value=target.active if target else True)
            reset = st.text_input("Nouveau mot de passe (facultatif)", type="password")
            if st.form_submit_button("Enregistrer") and target is not None:
                try:
                    db.update_user(target.id, role=role, active=active, password=reset or None)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    flash("success", f"Utilisateur mis à jour : {target.name}.")
                    st.rerun()


# --------------------------------------------------------------------------- E-08 sources


def run_sync(**kwargs) -> None:
    org = db.organisation()
    settings = SyncSettings(
        retries=1,
        drop_threshold=org.drop_threshold if org else 0.05,
        translation_threshold=org.translation_threshold if org else 0.8,
    )
    with st.spinner("Synchronisation de la documentation Odoo 18.0"):
        try:
            report = synchronize(settings=settings, catalog=catalog, **kwargs)
        except ValueError as exc:
            flash("error", str(exc))
            return
    get_retriever.clear()
    get_menu_labels.clear()
    level = "success" if report.status.published else "info"
    if report.status in (SyncStatus.FAILED, SyncStatus.BLOCKED):
        level = "error"
    flash(level, f"Synchronisation : {report.status.label}.")
    st.rerun()


if "Sources" in tabs:
    with tabs["Sources"]:
        st.header("Sources documentaires")
        st.write(
            "Dépôt odoo/documentation, branche 18.0, pages RST et traductions françaises. La "
            "version active n'est remplacée que si tous les contrôles sont OK (RG-009) ; le "
            "compte rendu liste les étapes dont une page source a changé (RG-011)."
        )
        st.caption(
            f"Version active : commit `{doc_commit[:12] if doc_commit else 'aucune'}`"
            + (f", {len(retriever.chunks)} sections indexées" if retriever else "")
        )
        show_flash()
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
                    "Publication bloquée (ERR-008). Publier la version candidate malgré "
                    "l'alerte, ou attendre la prochaine synchronisation. La décision est tracée."
                )
                if st.button("Publier la version candidate"):
                    run_sync(
                        trigger="relance manuelle",
                        force=True,
                        forced_by=f"{user.name} ({user.email})",
                    )
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
            "Synchronisation planifiée : chaque dimanche à 02:00 UTC (workflow GitHub « Doc "
            "sync »). Sur Streamlit Community Cloud, le disque n'est pas persistant : "
            "l'historique repart à zéro au redémarrage de l'instance."
        )


# --------------------------------------------------------------------------- E-09 repository


def _yaml(value) -> str:
    import yaml

    return "" if value in (None, [], {}) else yaml.safe_dump(value, allow_unicode=True, width=100)


def _from_yaml(text: str, label: str):
    import yaml

    try:
        return yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError as exc:
        raise JourneyValidationError([f"{label} : YAML invalide ({exc})"]) from exc


if "Référentiel" in tabs:
    with tabs["Référentiel"]:
        st.header("Référentiel et parcours")
        show_flash()

        st.subheader("Étapes impactées par une mise à jour documentaire")
        if not last_report or not doc_alerts:
            st.info("Aucune étape à revalider depuis la dernière synchronisation publiée.")
        else:
            st.caption(
                f"Synchronisation du {last_report.started_at:%Y-%m-%d %H:%M} UTC, commit "
                f"`{(last_report.candidate_commit or '')[:12]}`. Vérifier l'étape contre la page "
                "modifiée, la corriger au besoin dans l'éditeur, puis la marquer revalidée."
            )
            for step_id, alerts in sorted(doc_alerts.items()):
                with st.container(border=True):
                    title = (
                        catalog.step(step_id).title
                        if step_id in catalog_step_ids(catalog)
                        else step_id
                    )
                    st.markdown(f"**{title}** (`{step_id}`)")
                    for alert in alerts:
                        st.write(alert)
                    if st.button("Marquer revalidée", key=f"review-{step_id}"):
                        db.review_step(step_id, last_report.id, user.id)
                        flash("success", f"Étape {step_id} revalidée.")
                        st.rerun()

        st.subheader("Arborescence métier (F-004)")
        if catalog.referential is not None:
            counts: dict[str, int] = {}
            for journey in catalog.journeys:
                for step in journey.steps:
                    if step.parameter:
                        counts[step.parameter] = counts.get(step.parameter, 0) + 1
            for domain in catalog.referential.domains:
                with st.expander(f"{domain.label} ({len(domain.modules)} modules)"):
                    for module in domain.modules:
                        st.markdown(
                            f"**{module.label}** · modules Odoo : "
                            + ", ".join(f"`{m}`" for m in module.odoo_modules)
                        )
                        if not module.processes:
                            st.caption("Aucun processus modélisé pour l'instant.")
                        for process in module.processes:
                            st.markdown(f"- {process.label}")
                            for parameter in process.parameters:
                                st.markdown(
                                    f"    - {parameter.label} (`{parameter.id}`) : "
                                    f"{counts.get(parameter.id, 0)} étape(s), "
                                    f"{len(parameter.sources)} page(s) source"
                                )
        files = repository.current_files(db)
        with st.form("referential"):
            text = st.text_area(
                "Référentiel (YAML)", value=files.get("referential.yaml", ""), height=300
            )
            if st.form_submit_button("Enregistrer le référentiel"):
                try:
                    repository.save_referential(db, user, text)
                except (JourneyValidationError, ValueError) as exc:
                    st.error(f"Référentiel refusé : {exc}")
                else:
                    flash("success", "Référentiel enregistré.")
                    st.rerun()

        st.subheader("Éditeur de parcours (F-005)")
        journey = st.selectbox(
            "Parcours", catalog.journeys, format_func=lambda j: f"{j.title} ({j.id})"
        )
        options = [None] + [s.id for s in journey.steps]
        chosen = st.selectbox(
            "Étape",
            options,
            format_func=lambda i: "+ Nouvelle étape" if i is None else catalog.step(i).title,
            key=f"editor-step-{journey.id}",
        )
        current = repository.step_as_dict(db, journey.id, chosen) if chosen else {}
        parameters = list(catalog.referential.paths()) if catalog.referential else []
        with st.form(f"editor-{journey.id}-{chosen}"):
            step_id = st.text_input(
                "Identifiant", value=current.get("id", ""), disabled=chosen is not None
            )
            title = st.text_input("Titre", value=current.get("title", ""))
            parameter = st.selectbox(
                "Paramètre du référentiel",
                [None, *parameters],
                index=(
                    [None, *parameters].index(current.get("parameter"))
                    if current.get("parameter") in parameters
                    else 0
                ),
                format_func=lambda i: "Aucun" if i is None else catalog.referential.path(i).label,
            )
            objective = st.text_area("Objectif", value=current.get("objective", ""))
            menu_path = st.text_input(
                "Chemin de menu (anglais, tel qu'écrit dans la doc)",
                value=current.get("menu_path", ""),
            )
            others = [s.id for j in catalog.journeys for s in j.steps if s.id != chosen]
            prerequisites = st.multiselect(
                "Prérequis", others, default=current.get("prerequisites", [])
            )
            recommendations = st.text_area(
                "Recommandations (YAML : value, when, verified, note)",
                value=_yaml(current.get("recommendations")),
                height=160,
            )
            applies_when = st.text_area(
                "Conditions d'application selon le profil (YAML)",
                value=_yaml(current.get("applies_when")),
            )
            modules = st.text_input(
                "Modules techniques requis (séparés par des virgules)",
                value=", ".join(current.get("modules", [])),
            )
            sources = st.text_area(
                "Sources (YAML : path, title, anchor, url) — au moins une (RG-012)",
                value=_yaml(current.get("sources")),
                height=160,
            )
            col1, col2 = st.columns(2)
            save_clicked = col1.form_submit_button("Enregistrer l'étape")
            delete_clicked = col2.form_submit_button("Supprimer l'étape", disabled=chosen is None)
        if save_clicked:
            try:
                payload = {
                    "id": step_id.strip(),
                    "title": title.strip(),
                    "parameter": parameter,
                    "objective": objective.strip(),
                    "menu_path": menu_path.strip(),
                    "recommendations": _from_yaml(recommendations, "recommandations") or [],
                    "prerequisites": prerequisites,
                    "applies_when": _from_yaml(applies_when, "conditions"),
                    "modules": [m.strip() for m in modules.split(",") if m.strip()],
                    "sources": _from_yaml(sources, "sources") or [],
                }
                repository.save_step(db, user, journey.id, payload, chosen)
            except (JourneyValidationError, ValueError) as exc:
                st.error(f"Étape refusée : {exc}")
            else:
                flash("success", f"Étape {step_id} enregistrée.")
                st.rerun()
        if delete_clicked and chosen:
            try:
                repository.delete_step(db, user, journey.id, chosen)
            except (JourneyValidationError, ValueError) as exc:
                st.error(f"Suppression refusée : {exc}")
            else:
                flash("success", f"Étape {chosen} supprimée.")
                st.rerun()

        overrides = db.repository_overrides()
        if overrides:
            st.subheader("Fichiers modifiés")
            for name in sorted(overrides):
                col1, col2 = st.columns([3, 1])
                col1.write(f"`{name}`")
                if col2.button("Rétablir la version livrée", key=f"reset-{name}"):
                    try:
                        repository.reset_file(db, user, name)
                    except (JourneyValidationError, ValueError) as exc:
                        st.error(str(exc))
                    else:
                        flash("success", f"{name} rétabli.")
                        st.rerun()
        st.download_button(
            "Télécharger le référentiel et les parcours (.zip)",
            data=repository.export_zip(db),
            file_name="referentiel_parcours.zip",
            mime="application/zip",
        )
        history = db.repository_history()
        if history:
            st.subheader("Historique des modifications")
            st.dataframe(
                [
                    {
                        "Date (UTC)": h["created_at"].replace("T", " ")[:16],
                        "Fichier": h["name"],
                        "Action": h["action"],
                        "Détail": h["detail"],
                        "Par": h["user_name"] or "",
                    }
                    for h in history
                ],
                hide_index=True,
                width="stretch",
            )
