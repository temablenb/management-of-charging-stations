import importlib

import pytest

MODULES = [
    "ui.helpers", "ui.map_view", "ui.auth_screen",
    "ui.legacy.user_cabinet", "ui.legacy.admin_panel",
    "ui.navigation", "ui.simulation_page", "ui.admin_app", "ui.scenarios",
]


@pytest.mark.parametrize("name", MODULES)
def test_ui_module_imports(name):
    importlib.import_module(name)