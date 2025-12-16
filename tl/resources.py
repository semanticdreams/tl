from importlib import resources

from PySide6.QtGui import QIcon


def load_icon() -> QIcon:
    with resources.path("tl.assets", "icon.png") as path:
        return QIcon(str(path))
