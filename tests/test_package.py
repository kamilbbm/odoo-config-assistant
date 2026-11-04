import odoo_config_assistant


def test_package_targets_odoo_18():
    assert odoo_config_assistant.ERP == "odoo"
    assert odoo_config_assistant.DOC_VERSION == "18.0"
