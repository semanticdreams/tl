from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .constants import APP_NAME
from .history import HistoryListModel
from .languages import LANGUAGES
from .widgets import LanguageComboBox


def build_main_ui(window: QMainWindow) -> None:
    window.setStatusBar(QStatusBar(window))
    window.status_label = QLabel("Idle")
    window.statusBar().addPermanentWidget(window.status_label)

    mb = window.menuBar()

    file_menu = mb.addMenu("&File")
    window.act_show_hide = QAction("Hide", window)
    window.act_show_hide.setShortcut("Ctrl+W")
    window.act_show_hide.triggered.connect(window.toggle_visible)
    file_menu.addAction(window.act_show_hide)

    file_menu.addSeparator()
    act_quit = QAction("Quit", window)
    act_quit.setShortcut("Ctrl+Q")
    act_quit.triggered.connect(window.quit_app)
    file_menu.addAction(act_quit)

    backend_menu = mb.addMenu("&Backend")
    window.backend_actions = {}  # type: Dict[str, QAction]

    def add_backend_action(name: str, enabled: bool) -> None:
        act = QAction(name, window)
        act.setCheckable(True)
        act.setEnabled(enabled)
        act.triggered.connect(lambda _=False, n=name: window.set_backend(n))
        backend_menu.addAction(act)
        window.backend_actions[name] = act

    add_backend_action("OpenAI", True)
    add_backend_action("DeepL (coming soon)", False)
    add_backend_action("Google Translate (coming soon)", False)
    window.backend_actions["OpenAI"].setChecked(True)

    about_menu = mb.addMenu("&About")
    act_about = QAction("About tl", window)
    act_about.triggered.connect(window.show_about)
    about_menu.addAction(act_about)

    root = QWidget(window)
    root_layout = QHBoxLayout(root)
    root_layout.setContentsMargins(8, 8, 8, 8)

    splitter = QSplitter(Qt.Horizontal, root)

    # Main pane
    main_pane = QWidget(splitter)
    main_layout = QHBoxLayout(main_pane)
    main_layout.setContentsMargins(0, 0, 0, 0)
    main_layout.setSpacing(8)

    window.src_lang = LanguageComboBox(LANGUAGES, allow_auto=True)
    window.tgt_lang = LanguageComboBox(LANGUAGES, allow_auto=False)

    window.src_text = QPlainTextEdit()
    window.src_text.setPlaceholderText("Type text to translate…")
    window.context_text = QPlainTextEdit()
    window.context_text.setPlaceholderText("Optional context (tone, source, audience)…")
    window.context_text.setMinimumHeight(64)
    window.context_text.setMaximumHeight(120)
    window.tgt_text = QPlainTextEdit()
    window.tgt_text.setPlaceholderText("Translation appears here…")
    window.tgt_text.setReadOnly(False)  # allow editing if user wants; translation overwrites
    window.extra_text = QPlainTextEdit()
    window.extra_text.setReadOnly(True)
    window.extra_text.setEnabled(False)
    window.extra_text.setPlaceholderText("Extra info will appear here.")
    window.extra_text.setMinimumHeight(80)
    window.extra_text.setContextMenuPolicy(Qt.CustomContextMenu)
    window.extra_text.customContextMenuRequested.connect(
        window._show_extra_text_context_menu
    )

    # source pane
    src_pane = QWidget()
    src_layout = QVBoxLayout(src_pane)
    src_layout.setContentsMargins(0, 0, 0, 0)
    src_layout.setSpacing(6)
    src_layout.addWidget(window.src_lang)
    src_layout.addWidget(window.src_text)
    src_layout.addWidget(window.context_text)

    src_controls = QHBoxLayout()
    window.auto_translate_checkbox = QCheckBox("A&uto-translate")
    window.auto_translate_checkbox.setChecked(True)
    window.submit_btn = QPushButton("&Translate")
    window.submit_btn.setEnabled(False)
    window.submit_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    window.clear_src_btn = QPushButton("Clea&r")
    window.clear_src_btn.setToolTip("Clear source and context.")
    src_controls.addWidget(window.auto_translate_checkbox)
    src_controls.addWidget(window.submit_btn, 1)
    src_controls.addWidget(window.clear_src_btn)
    src_layout.addLayout(src_controls)

    # target pane
    tgt_pane = QWidget()
    tgt_layout = QVBoxLayout(tgt_pane)
    tgt_layout.setContentsMargins(0, 0, 0, 0)
    tgt_layout.setSpacing(6)
    tgt_layout.addWidget(window.tgt_lang)
    tgt_layout.addWidget(window.tgt_text, 4)
    speak_row = QHBoxLayout()
    window.speak_btn = QPushButton("S&peak")
    window.speak_btn.setToolTip("Speak the translated text.")
    window.speak_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    speak_row.addWidget(window.speak_btn, 1)
    tgt_layout.addLayout(speak_row)
    extra_section = QHBoxLayout()
    extra_section.addWidget(window.extra_text, 1)

    extra_btn_col = QVBoxLayout()
    window.examples_btn = QPushButton("&Examples")
    window.examples_btn.setToolTip(
        "Generate example sentences in the target language."
    )
    window.alternatives_btn = QPushButton("Alternati&ves")
    window.alternatives_btn.setToolTip(
        "Suggest alternative translations of the source text."
    )
    window.etymology_btn = QPushButton("Ety&mology")
    window.etymology_btn.setToolTip(
        "Show a short etymology for a single translated word."
    )
    window.synonyms_btn = QPushButton("Synon&yms")
    window.synonyms_btn.setToolTip(
        "List synonyms based on the translated text."
    )
    window.antonyms_btn = QPushButton("Anto&nyms")
    window.antonyms_btn.setToolTip(
        "List antonyms based on the translated text."
    )
    window.usage_btn = QPushButton("U&sage")
    window.usage_btn.setToolTip(
        "Explain how, why, and when the translated phrase is used."
    )
    window.grammar_btn = QPushButton("&Grammar")
    window.grammar_btn.setToolTip(
        "Provide a short grammar explanation for the translated text."
    )
    for btn in (
        window.examples_btn,
        window.alternatives_btn,
        window.etymology_btn,
        window.synonyms_btn,
        window.antonyms_btn,
        window.usage_btn,
        window.grammar_btn,
    ):
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        extra_btn_col.addWidget(btn)
    extra_btn_col.addStretch(1)

    extra_section.addLayout(extra_btn_col)
    tgt_layout.addLayout(extra_section, 1)

    swap_wrap = QWidget()
    swap_layout = QVBoxLayout(swap_wrap)
    swap_layout.setContentsMargins(0, 0, 0, 0)
    window.swap_btn = QPushButton("⇄")
    window.swap_btn.setShortcut("Ctrl+S")
    window.swap_btn.setToolTip("Swap languages and text. (Ctrl+S)")
    window.swap_btn.setFixedWidth(44)
    window.swap_btn.clicked.connect(window.swap_languages_and_text)
    swap_layout.addWidget(window.swap_btn, alignment=Qt.AlignHCenter)
    swap_layout.addStretch(1)

    main_layout.addWidget(src_pane, stretch=1)
    main_layout.addWidget(swap_wrap, stretch=0)
    main_layout.addWidget(tgt_pane, stretch=1)

    # Sidebar: history list view
    sidebar = QWidget(splitter)
    side_layout = QVBoxLayout(sidebar)
    side_layout.setContentsMargins(0, 0, 0, 0)
    side_layout.setSpacing(6)

    side_layout.addWidget(QLabel("History"))
    window.history_model = HistoryListModel(window)
    window.history_view = QListView()
    window.history_view.setModel(window.history_model)
    window.history_view.clicked.connect(window.on_history_clicked)
    side_layout.addWidget(window.history_view, 1)

    window.clear_history_btn = QPushButton("C&lear History")
    window.clear_history_btn.setToolTip("Clear history.")
    window.clear_history_btn.clicked.connect(window.clear_history)
    side_layout.addWidget(window.clear_history_btn)

    splitter.addWidget(main_pane)
    splitter.addWidget(sidebar)
    splitter.setStretchFactor(0, 4)
    splitter.setStretchFactor(1, 2)

    root_layout.addWidget(splitter)
    window.setCentralWidget(root)

    window.src_text.textChanged.connect(window.schedule_translation)
    window.context_text.textChanged.connect(window.schedule_translation)
    window.src_lang.changed.connect(window.schedule_translation)
    window.tgt_lang.changed.connect(window.schedule_translation)
    window.auto_translate_checkbox.toggled.connect(window._on_auto_translate_toggled)
    window.submit_btn.clicked.connect(window.trigger_translation_now)
    window.clear_src_btn.clicked.connect(window.clear_source_and_context)
    window.speak_btn.clicked.connect(window.request_speak)
    window.translate_shortcut = QShortcut(QKeySequence("Ctrl+Enter"), window)
    window.translate_shortcut.setContext(Qt.ApplicationShortcut)
    window.translate_shortcut.activated.connect(window.trigger_translation_now)
    window.translate_shortcut_return = QShortcut(QKeySequence("Ctrl+Return"), window)
    window.translate_shortcut_return.setContext(Qt.ApplicationShortcut)
    window.translate_shortcut_return.activated.connect(window.trigger_translation_now)
    window.examples_btn.clicked.connect(lambda: window.request_extra_info("examples"))
    window.alternatives_btn.clicked.connect(
        lambda: window.request_extra_info("alternatives")
    )
    window.etymology_btn.clicked.connect(lambda: window.request_extra_info("etymology"))
    window.synonyms_btn.clicked.connect(lambda: window.request_extra_info("synonyms"))
    window.antonyms_btn.clicked.connect(lambda: window.request_extra_info("antonyms"))
    window.usage_btn.clicked.connect(lambda: window.request_extra_info("usage"))
    window.grammar_btn.clicked.connect(lambda: window.request_extra_info("grammar"))

    sb = window.history_view.verticalScrollBar()
    sb.valueChanged.connect(window._history_scroll_changed)


def build_tray(window: QMainWindow) -> None:
    window.tray = QSystemTrayIcon(window.app_icon, window)
    window.tray.setToolTip(APP_NAME)

    menu = QMenu()
    window.tray_act_show_hide = QAction("Show", window)
    window.tray_act_show_hide.triggered.connect(window.toggle_visible)
    menu.addAction(window.tray_act_show_hide)

    menu.addSeparator()
    act_quit = QAction("Quit", window)
    act_quit.triggered.connect(window.quit_app)
    menu.addAction(act_quit)

    window.tray.setContextMenu(menu)
    window.tray.activated.connect(window._tray_activated)
    window.tray.show()
