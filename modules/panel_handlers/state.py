from modules.panel_support import *

class PersistentPendingInputs(dict):
    """Dicionário que persiste automaticamente todas as alterações em config.json."""
    def __init__(self, panel_handler, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.panel_handler = panel_handler

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if self.panel_handler:
            self.panel_handler._save_pending_inputs()

    def __delitem__(self, key):
        super().__delitem__(key)
        if self.panel_handler:
            self.panel_handler._save_pending_inputs()

    def pop(self, key, default=None):
        val = super().pop(key, default)
        if self.panel_handler:
            self.panel_handler._save_pending_inputs()
        return val

    def clear(self):
        super().clear()
        if self.panel_handler:
            self.panel_handler._save_pending_inputs()
