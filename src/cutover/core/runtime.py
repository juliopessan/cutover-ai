from .plugin_catalog import PluginCatalog


class AgentRuntime:
    def __init__(self, catalog=None):
        self.catalog = catalog or PluginCatalog()
