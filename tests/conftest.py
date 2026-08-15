import os


os.environ.setdefault("COERIA_AUTH_MODE", "disabled")

pytest_plugins = ("nicegui.testing.user_plugin",)
