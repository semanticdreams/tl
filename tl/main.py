from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .constants import APP_NAME
from .window import MainWindow


def main():
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)

    window = MainWindow()
    window.resize(1200, 700)
    window.show()
    QTimer.singleShot(0, window.apply_startup_visibility)

    app.exec()


if __name__ == "__main__":
    main()
