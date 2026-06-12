"""Главное окно KeyStore: категории слева, таблица ключей справа."""
from __future__ import annotations
import time
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QShortcut, QClipboard, QGuiApplication, QColor, QBrush
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QInputDialog, QPlainTextEdit, QLineEdit, QDialog,
    QDialogButtonBox, QCheckBox, QComboBox, QStatusBar, QMenu, QApplication,
)

from .db import DB, Key, Category, Section
from .checker import CheckerClient
from .recoder import recode_unique, verify as verify_key
from . import policy


# Преднастроенные разделы. Создаются по требованию (при первой категории в них).
DEFAULT_SECTION_NAMES = ["Windows", "Office", "PSN"]
NO_SECTION_LABEL = "Без раздела"  # виртуальный раздел для категорий без section_id


STATUS_LABELS = {
    "available":  "✓ свободен",
    "phone_only": "☎ телефон",
    "sold":       "→ продан",
    "blocked":    "✗ заблокирован",
    "exhausted":  "✗ исчерпан",
    "unknown":    "? не проверен",
}
STATUS_COLORS = {
    "available":  QColor("#4ade80"),   # ярко-зелёный
    "phone_only": QColor("#86efac"),   # светло-зелёный — рабочий товар по телефону
    "sold":       QColor("#94a3b8"),   # серый
    "blocked":    QColor("#f87171"),   # красный
    "exhausted":  QColor("#f87171"),   # красный
    "unknown":    QColor("#fbbf24"),   # жёлтый
}


class CheckWorker(QThread):
    """Параллельная проверка списка ключей в фоне."""
    progress = pyqtSignal(int, int, str)         # done, total, current_key
    one_done = pyqtSignal(int, dict)             # key_id, result
    finished_all = pyqtSignal()

    def __init__(self, items: list[tuple[int, str]], client: CheckerClient,
                 *, consume: bool, mak_count: bool, online: bool,
                 allow_consume_retail: bool = False):
        super().__init__()
        self.items = items
        self.client = client
        self.consume = consume
        self.mak_count = mak_count
        self.online = online
        self.allow_consume_retail = allow_consume_retail

    def run(self):
        total = len(self.items)
        for i, (key_id, key) in enumerate(self.items, 1):
            self.progress.emit(i, total, key)
            try:
                res = self.client.check(
                    key, online=self.online,
                    mak_count=self.mak_count, consume=self.consume,
                    allow_consume_retail=self.allow_consume_retail,
                )
            except Exception as e:
                res = {"key": key, "ok": False, "error": str(e)}
            self.one_done.emit(key_id, res)
        self.finished_all.emit()


class AddKeysDialog(QDialog):
    def __init__(self, parent, category_name: str):
        super().__init__(parent)
        self.setWindowTitle(f"Добавить ключи: {category_name}")
        self.resize(500, 400)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Вставь ключи (по одному на строку):"))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("XXXXX-XXXXX-XXXXX-XXXXX-XXXXX")
        v.addWidget(self.text)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def keys(self) -> list[str]:
        import re
        text = self.text.toPlainText().upper()
        # ловим как разделённые так и любые целые ключи в тексте
        return re.findall(r"[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}", text)


class NewCategoryDialog(QDialog):
    """Имя + выбор раздела. Список разделов = реальные строки в `sections`.
    Можно вписать новый раздел — он будет создан при сохранении."""

    def __init__(self, db: DB, parent=None, preselect_section_id: int | None = None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Новая категория")
        self.resize(420, 200)

        v = QVBoxLayout(self)

        v.addWidget(QLabel("Имя категории:"))
        self.input = QLineEdit()
        self.input.setPlaceholderText("например: Steam Keys")
        self.input.returnPressed.connect(self.accept)
        v.addWidget(self.input)

        v.addWidget(QLabel("Раздел (можно вписать новый):"))
        self.section_combo = QComboBox()
        self.section_combo.setEditable(True)

        # Виртуальный «Без раздела» (с section_id = None) + реальные секции из БД
        self.section_combo.addItem(NO_SECTION_LABEL, userData=None)
        sections = self.db.list_sections()
        for s in sections:
            self.section_combo.addItem(s.name, userData=s.id)
        # Преднастроенные имена, если их ещё нет (создадутся только при сохранении)
        existing_names = {s.name for s in sections}
        for name in DEFAULT_SECTION_NAMES:
            if name not in existing_names:
                self.section_combo.addItem(name, userData=None)  # None — потом создадим

        # Preselect
        if preselect_section_id is not None:
            for i in range(self.section_combo.count()):
                if self.section_combo.itemData(i) == preselect_section_id:
                    self.section_combo.setCurrentIndex(i)
                    break
        else:
            self.section_combo.setCurrentIndex(0)  # «Без раздела»

        v.addWidget(self.section_combo)

        hint = QLabel(
            "💡 Если в списке нет нужного раздела — впиши его имя руками.\n"
            "Новый раздел создастся автоматически вместе с категорией."
        )
        hint.setStyleSheet("color:#9ca3af; font-size:11px;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        # Кнопки
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = QPushButton("Отмена")
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_cancel)
        b_create = QPushButton("Создать")
        b_create.setStyleSheet("background:#16a34a;")
        b_create.clicked.connect(self.accept)
        b_create.setDefault(True)
        btns.addWidget(b_create)
        v.addLayout(btns)

        self.input.setFocus()

    def get_data(self) -> tuple[str, str]:
        """Возвращает (имя_категории, имя_раздела)."""
        name = self.input.text().strip()
        section_name = self.section_combo.currentText().strip()
        return name, section_name


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vault")
        self.resize(1100, 700)
        self.db = DB()
        self.client = CheckerClient()
        self.current_category_id: int | None = None
        self.worker: CheckWorker | None = None

        self._build_ui()
        self._reload_categories()
        self._poll_server()

    # ----- UI build -----
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(6)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        # --- LEFT: категории ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Категории"))
        self.cat_list = QTreeWidget()
        self.cat_list.setHeaderHidden(True)
        self.cat_list.setIndentation(14)
        self.cat_list.itemSelectionChanged.connect(self._on_category_changed)
        self.cat_list.itemDoubleClicked.connect(self._on_cat_double_clicked)
        self.cat_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cat_list.customContextMenuRequested.connect(self._cat_context_menu)
        lv.addWidget(self.cat_list, 1)

        cat_btns = QHBoxLayout()
        b_new_cat = QPushButton("+ Новая категория")
        b_new_cat.setStyleSheet("background:#16a34a;")
        b_new_cat.clicked.connect(lambda: self._new_category())
        cat_btns.addWidget(b_new_cat)
        lv.addLayout(cat_btns)

        # Левая панель должна уметь сжиматься, чтобы сплиттер можно было тянуть влево
        left.setMinimumWidth(120)
        split.addWidget(left)

        # --- RIGHT: ключи ---
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("—")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        rv.addWidget(self.title_label)
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #9ca3af; font-size: 12px;")
        rv.addWidget(self.stats_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Ключ", "Статус", "MAK", "Эдишн", "Тип"])
        hh = self.table.horizontalHeader()
        # Все колонки руками изменяемые (Interactive). Иначе колонка «Ключ»
        # в режиме ResizeToContents расталкивает таблицу и блокирует сплиттер.
        for i in range(5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        hh.setMinimumSectionSize(40)
        hh.setStretchLastSection(True)
        # Стартовые ширины (можно тянуть мышкой по краям заголовка)
        self.table.setColumnWidth(0, 280)  # Ключ
        self.table.setColumnWidth(1, 100)  # Статус
        self.table.setColumnWidth(2, 60)   # MAK
        self.table.setColumnWidth(3, 130)  # Эдишн
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
        rv.addWidget(self.table, 1)

        btns = QHBoxLayout()
        self.b_add_keys = QPushButton("+ Добавить ключи")
        self.b_add_keys.clicked.connect(self._add_keys)
        btns.addWidget(self.b_add_keys)

        self.b_check_sel = QPushButton("Проверить выделенные")
        self.b_check_sel.clicked.connect(lambda: self._check(selected_only=True))
        btns.addWidget(self.b_check_sel)

        self.b_check_unknown = QPushButton("Проверить непроверенные")
        self.b_check_unknown.clicked.connect(lambda: self._check(only_unknown=True))
        btns.addWidget(self.b_check_unknown)

        self.b_archive = QPushButton("В архив")
        self.b_archive.setStyleSheet("background:#9ca3af;")
        self.b_archive.clicked.connect(self._move_selected_to_archive)
        btns.addWidget(self.b_archive)

        rv.addLayout(btns)

        # Online и MAK Count всегда включены (бесплатные, всегда нужны) — скрыты.
        # Видим только Consume — он опасный, тратит активацию.
        self.cb_online = QCheckBox()
        self.cb_online.setChecked(True)
        self.cb_online.setVisible(False)
        self.cb_mak = QCheckBox()
        self.cb_mak.setChecked(True)
        self.cb_mak.setVisible(False)

        opts = QHBoxLayout()
        self.cb_consume = QCheckBox("Consume — точные коды ошибок (тратит активацию)")
        self.cb_consume.setChecked(True)
        opts.addWidget(self.cb_consume)
        opts.addStretch(1)
        rv.addLayout(opts)

        right.setMinimumWidth(300)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([260, 800])

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.server_dot = QLabel("● сервер")
        self.server_dot.setStyleSheet("color: #ef4444;")
        self.status.addPermanentWidget(self.server_dot)

        # тёмная тема
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #1e1e1e; color: #e6e6e6; }
            QTreeWidget, QTableWidget, QPlainTextEdit { background: #2a2a2a; color: #e6e6e6; border: 1px solid #3a3a3a; }
            QTreeWidget::item:hover { background: #333; }
            QTreeWidget::item:selected { background: #2563eb; color: white; }
            QHeaderView::section { background: #2a2a2a; color: #cccccc; padding: 4px; border: 1px solid #3a3a3a; }
            QPushButton { background: #2563eb; color: white; padding: 6px 12px; border: none; border-radius: 4px; }
            QPushButton:hover { background: #1d4ed8; }
            QPushButton:disabled { background: #555; }
            QLineEdit { background: #2a2a2a; color: #e6e6e6; border: 1px solid #3a3a3a; padding: 4px; }
            QSplitter::handle { background: #444; }
            QSplitter::handle:horizontal { width: 6px; }
            QSplitter::handle:hover { background: #2563eb; }
        """)

    # ----- категории -----
    def _reload_categories(self):
        """Перестраивает дерево из БД. Источник истины: таблицы sections + categories."""
        cur_id = self.current_category_id
        # Запомним свёрнутые/развёрнутые разделы перед перезагрузкой
        prev_expanded: dict[str, bool] = {}
        for i in range(self.cat_list.topLevelItemCount()):
            top = self.cat_list.topLevelItem(i)
            prev_expanded[top.text(0)] = top.isExpanded()

        self.cat_list.clear()
        sections = self.db.list_sections()
        cats = self.db.list_categories()

        # Группируем категории по section_id (None — отдельная корзина «Без раздела»)
        by_section: dict[int | None, list[Category]] = {}
        for c in cats:
            by_section.setdefault(c.section_id, []).append(c)

        item_to_select = None

        def add_section_node(title: str, section_id: int | None, cats_in: list[Category]):
            nonlocal item_to_select
            top = QTreeWidgetItem([title])
            # Раздел сам не выбираем — только сворачивает/разворачивает
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            # Положим section_id (или None) — пригодится контекстному меню
            top.setData(0, Qt.ItemDataRole.UserRole + 1, section_id)
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            self.cat_list.addTopLevelItem(top)
            top.setExpanded(prev_expanded.get(title, True))
            for c in cats_in:
                stats = self.db.category_stats(c.id)
                label = f"{c.name}  ({stats['working']}/{stats['total']})"
                child = QTreeWidgetItem([label])
                child.setData(0, Qt.ItemDataRole.UserRole, c.id)
                top.addChild(child)
                if cur_id is not None and c.id == cur_id:
                    item_to_select = child

        # Сначала отображаем все РЕАЛЬНЫЕ разделы (даже пустые)
        for s in sections:
            add_section_node(s.name, s.id, by_section.get(s.id, []))

        # Затем «Без раздела» — если есть категории без section_id
        no_section_cats = by_section.get(None, [])
        if no_section_cats:
            add_section_node(NO_SECTION_LABEL, None, no_section_cats)

        if item_to_select is not None:
            self.cat_list.setCurrentItem(item_to_select)
            return
        # Иначе — первый листовой узел
        for i in range(self.cat_list.topLevelItemCount()):
            top = self.cat_list.topLevelItem(i)
            if top.childCount() > 0:
                self.cat_list.setCurrentItem(top.child(0))
                return

    def _on_category_changed(self):
        it = self.cat_list.currentItem()
        if not it:
            return
        cat_id = it.data(0, Qt.ItemDataRole.UserRole)
        if cat_id is None:
            # Группа выбрана (не лист) — игнорируем
            return
        self.current_category_id = cat_id
        self._reload_keys()

    def _new_category(self, preselect_section_id: int | None = None):
        """Создать новую категорию через мини-диалог."""
        dlg = NewCategoryDialog(self.db, self, preselect_section_id=preselect_section_id)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, section_name = dlg.get_data()
        if not name:
            return
        if self.db.find_category_by_name(name):
            QMessageBox.warning(self, "Уже есть",
                                f"Категория «{name}» уже существует.")
            return

        # Определяем section_id:
        # - «Без раздела» (или пусто) → None
        # - Имя уже существует → используем его id
        # - Имя НОВОЕ → подтверждаем создание раздела и создаём
        section_id: int | None = None
        if section_name and section_name != NO_SECTION_LABEL:
            existing = self.db.find_section_by_name(section_name)
            if existing:
                section_id = existing.id
            else:
                # Новый раздел — подтверждение
                ans = QMessageBox.question(
                    self, "Новый раздел",
                    f"Раздел «{section_name}» ещё не существует. Создать его?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return
                section_id = self.db.add_section(section_name)

        self.db.add_category(name, section_id=section_id)
        new_cat = self.db.find_category_by_name(name)
        # Выделяем новую категорию сразу — _reload_categories найдёт её
        if new_cat:
            self.current_category_id = new_cat.id
        self._reload_categories()
        # Гарантия что раздел развёрнут и виден
        if new_cat:
            for i in range(self.cat_list.topLevelItemCount()):
                top = self.cat_list.topLevelItem(i)
                top_section_id = top.data(0, Qt.ItemDataRole.UserRole + 1)
                if top_section_id == new_cat.section_id:
                    top.setExpanded(True)
                    for j in range(top.childCount()):
                        child = top.child(j)
                        if child.data(0, Qt.ItemDataRole.UserRole) == new_cat.id:
                            self.cat_list.scrollToItem(child)
                            break
                    break
        self.statusBar().showMessage(
            f"Создана категория «{name}»" +
            (f" в разделе «{section_name}»" if section_id is not None else " (без раздела)"),
            5000,
        )

    def _rename_category_inplace(self, cat_id: int):
        cat = next((c for c in self.db.list_categories() if c.id == cat_id), None)
        if not cat:
            return
        new_name, ok = QInputDialog.getText(
            self, "Переименовать категорию", "Новое имя:", text=cat.name
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == cat.name:
            return
        dup = self.db.find_category_by_name(new_name)
        if dup and dup.id != cat_id:
            QMessageBox.warning(self, "Уже есть",
                                f"Категория «{new_name}» уже существует.")
            return
        self.db.rename_category(cat_id, new_name)
        self._reload_categories()

    def _delete_category_with_confirm(self, cat_id: int):
        cat = next((c for c in self.db.list_categories() if c.id == cat_id), None)
        if not cat:
            return
        stats = self.db.category_stats(cat_id)
        msg = (f"Удалить категорию «{cat.name}»?\n\n"
               f"В ней {stats['total']} ключ(а) — они будут удалены безвозвратно.")
        ok = QMessageBox.question(
            self, "Удалить?", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_category(cat_id)
        self.current_category_id = None
        self._reload_categories()

    def _rename_section(self, section_id: int):
        section = next((s for s in self.db.list_sections() if s.id == section_id), None)
        if not section:
            return
        new_name, ok = QInputDialog.getText(
            self, "Переименовать раздел", "Новое имя раздела:", text=section.name
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == section.name:
            return
        # Конфликт имён
        dup = self.db.find_section_by_name(new_name)
        if dup and dup.id != section_id:
            QMessageBox.warning(self, "Уже есть",
                                f"Раздел «{new_name}» уже существует.")
            return
        self.db.rename_section(section_id, new_name)
        self._reload_categories()
        self.statusBar().showMessage(
            f"Раздел «{section.name}» → «{new_name}»", 5000
        )

    def _delete_section(self, section_id: int):
        section = next((s for s in self.db.list_sections() if s.id == section_id), None)
        if not section:
            return
        cats_in = [c for c in self.db.list_categories() if c.section_id == section_id]
        msg = (f"Удалить раздел «{section.name}»?\n\n"
               f"Категории внутри ({len(cats_in)} шт.) переедут в «Без раздела». "
               f"Ключи не пострадают.")
        ok = QMessageBox.question(
            self, "Удалить раздел?", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        self.db.delete_section(section_id)  # внутри расцепит категории
        self._reload_categories()

    def _move_category_to_section(self, cat_id: int, section_id: int | None = -1):
        """Переместить категорию в раздел. section_id=-1 → запросить новое имя.
        None → «Без раздела»."""
        if section_id == -1:
            name, ok = QInputDialog.getText(
                self, "Новый раздел", "Имя нового раздела:"
            )
            if not ok or not name.strip():
                return
            name = name.strip()
            existing = self.db.find_section_by_name(name)
            section_id = existing.id if existing else self.db.add_section(name)
        self.db.set_category_section(cat_id, section_id)
        self._reload_categories()

    def _on_cat_double_clicked(self, item, _col):
        """Двойной клик — переименовать (категорию или раздел)."""
        cat_id = item.data(0, Qt.ItemDataRole.UserRole)
        if cat_id is None:
            # Раздел — переименовать раздел (если это реальная секция, не «Без раздела»)
            section_id = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if section_id is not None:
                self._rename_section(section_id)
            return
        self._rename_category_inplace(cat_id)

    def _cat_context_menu(self, pos):
        it = self.cat_list.itemAt(pos)
        # Клик по пустому месту — предлагаем создать новую категорию
        if not it:
            m = QMenu()
            a_new = QAction("+ Новая категория", m)
            m.addAction(a_new)
            chosen = m.exec(self.cat_list.mapToGlobal(pos))
            if chosen is a_new:
                self._new_category()
            return

        cat_id = it.data(0, Qt.ItemDataRole.UserRole)

        # Клик по разделу (верхнеуровневый узел)
        if cat_id is None:
            section_id = it.data(0, Qt.ItemDataRole.UserRole + 1)
            section_name = it.text(0)
            m = QMenu()
            a_add = QAction(f"+ Добавить категорию в «{section_name}»", m)
            m.addAction(a_add)
            m.addSeparator()
            # «Без раздела» — виртуальный, переименовать/удалить нельзя
            if section_id is not None:
                a_rename = QAction("✏ Переименовать раздел", m)
                a_delete = QAction("✕ Удалить раздел (категории → «Без раздела»)", m)
                m.addAction(a_rename)
                m.addAction(a_delete)
            else:
                a_rename = a_delete = None
            chosen = m.exec(self.cat_list.mapToGlobal(pos))
            if chosen is a_add:
                self._new_category(preselect_section_id=section_id)
            elif chosen is a_rename:
                self._rename_section(section_id)
            elif chosen is a_delete:
                self._delete_section(section_id)
            return

        # Клик по категории
        cat = next((c for c in self.db.list_categories() if c.id == cat_id), None)
        if not cat:
            return
        archive_id = self.db.get_archive_category_id()

        m = QMenu()
        a_rename = QAction("✏ Переименовать", m)
        a_delete = QAction("✕ Удалить", m)
        m.addAction(a_rename)
        m.addAction(a_delete)

        # Подменю «Переместить в раздел»
        a_new_section = None
        a_to_no_section = None
        move_actions: dict[QAction, int | None] = {}
        m.addSeparator()
        move_menu = m.addMenu("📁 Переместить в раздел")
        sections = self.db.list_sections()
        for s in sections:
            if s.id == cat.section_id:
                continue
            a = QAction(s.name, move_menu)
            move_menu.addAction(a)
            move_actions[a] = s.id
        if cat.section_id is not None:
            move_menu.addSeparator()
            a_to_no_section = QAction(f"→ {NO_SECTION_LABEL}", move_menu)
            move_menu.addAction(a_to_no_section)
        move_menu.addSeparator()
        a_new_section = QAction("+ В новый раздел...", move_menu)
        move_menu.addAction(a_new_section)

        chosen = m.exec(self.cat_list.mapToGlobal(pos))
        if chosen is a_rename:
            self._rename_category_inplace(cat_id)
        elif chosen is a_delete:
            self._delete_category_with_confirm(cat_id)
        elif chosen is a_new_section:
            self._move_category_to_section(cat_id, -1)  # запросит имя
        elif chosen is a_to_no_section:
            self._move_category_to_section(cat_id, None)
        elif chosen in move_actions:
            self._move_category_to_section(cat_id, move_actions[chosen])

    # ----- таблица ключей -----
    def _reload_keys(self):
        if self.current_category_id is None:
            return
        cats = {c.id: c for c in self.db.list_categories()}
        cat = cats.get(self.current_category_id)
        if not cat:
            return
        self.title_label.setText(cat.name)
        stats = self.db.category_stats(cat.id)
        parts = [
            f"всего: {stats['total']}",
            f"✓ свободно: {stats['available']}",
            f"☎ телефон: {stats['phone_only']}",
            f"→ продано: {stats['sold']}",
            f"✗ заблокировано: {stats['blocked']}",
            f"? не проверено: {stats['unknown']}",
        ]
        if stats.get("exhausted"):
            parts.append(f"✗ исчерпано: {stats['exhausted']}")
        self.stats_label.setText("  ·  ".join(parts))

        keys = self.db.list_keys(category_id=cat.id)
        self.table.setRowCount(len(keys))
        for row, k in enumerate(keys):
            self._set_row(row, k)

    def _set_row(self, row: int, k: Key):
        cells = [
            k.key,
            STATUS_LABELS.get(k.status, k.status),
            str(k.mak_count) if k.mak_count is not None else ("—" if k.is_mak else ""),
            k.edition or "",
            k.type_label or "",
        ]
        color = STATUS_COLORS.get(k.status)
        for col, val in enumerate(cells):
            item = QTableWidgetItem(val)
            item.setData(Qt.ItemDataRole.UserRole, k.id)
            if color is not None and col == 1:
                item.setForeground(QBrush(color))
            self.table.setItem(row, col, item)

    def _selected_key_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        ids = []
        for r in rows:
            it = self.table.item(r, 0)
            if it:
                ids.append(it.data(Qt.ItemDataRole.UserRole))
        return ids

    def _selected_keys(self) -> list[tuple[int, str]]:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        out = []
        for r in rows:
            it = self.table.item(r, 0)
            if it:
                out.append((it.data(Qt.ItemDataRole.UserRole), it.text()))
        return out

    def _move_selected_to_archive(self):
        """Переносит все выделенные ключи в архив. Подтверждение если >0 ключей."""
        ids = self._selected_key_ids()
        if not ids:
            self.status.showMessage("Не выделено ни одного ключа.", 3000)
            return
        archive_id = self.db.get_archive_category_id()
        if self.current_category_id == archive_id:
            self.status.showMessage("Эти ключи уже в архиве.", 3000)
            return
        ans = QMessageBox.question(
            self, "В архив?",
            f"Переместить {len(ids)} ключ(а) в архив?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        for kid in ids:
            self.db.move_key(kid, archive_id)
        self.status.showMessage(f"Перемещено в архив: {len(ids)}", 5000)
        self._reload_keys()
        self._reload_categories()

    def _table_context_menu(self, pos):
        if not self.table.selectedItems():
            return
        m = QMenu()
        a_copy = QAction("Скопировать ключ(и)", m)
        a_sold = QAction("Пометить продано", m)
        a_avail = QAction("Вернуть в свободные", m)
        a_check = QAction("Проверить", m)
        a_dup = QAction("Дублировать (recode)…", m)
        a_archive = QAction("📦 В архив", m)
        a_del = QAction("Удалить", m)
        for a in (a_copy, a_sold, a_avail, a_check, a_dup, a_archive, a_del):
            m.addAction(a)
        chosen = m.exec(self.table.mapToGlobal(pos))
        items = self._selected_keys()
        if not items:
            return
        if chosen is a_copy:
            QGuiApplication.clipboard().setText("\n".join(k for _, k in items))
            self.status.showMessage(f"Скопировано: {len(items)} ключ(а)", 3000)
        elif chosen is a_sold:
            for kid, _ in items:
                self.db.mark_sold(kid)
            self._reload_keys()
            self._reload_categories()
        elif chosen is a_avail:
            for kid, _ in items:
                self.db.mark_available(kid)
            self._reload_keys()
            self._reload_categories()
        elif chosen is a_check:
            self._check(selected_only=True)
        elif chosen is a_dup:
            self._recode_dialog(items)
        elif chosen is a_archive:
            self._move_selected_to_archive()
        elif chosen is a_del:
            ok = QMessageBox.question(
                self, "Удалить?", f"Удалить {len(items)} ключ(а)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ok == QMessageBox.StandardButton.Yes:
                self.db.delete_keys([kid for kid, _ in items])
                self._reload_keys()
                self._reload_categories()

    def _recode_dialog(self, items: list[tuple[int, str]]):
        """Дублирует выделенные ключи (recode): для каждого делает N визуально-разных копий.
        Свойства родителя (статус, эдишн, MAK count, и т.д.) копируются в клоны —
        это один и тот же ключ для MS, значит и параметры те же."""
        n, ok = QInputDialog.getInt(
            self, "Дублировать (recode)",
            f"Сколько копий сделать для каждого из {len(items)} ключ(а)?\n"
            "(максимум 255 — 8-битный counter в структуре ключа)",
            value=5, min=1, max=255,
        )
        if not ok:
            return

        total_created = 0
        total_dups = 0
        for src_id, src_key in items:
            new_keys = recode_unique(src_key, n)
            added, dups = self.db.add_clones(src_id, new_keys)
            total_created += added
            total_dups += dups

        msg = f"Создано клонов: {total_created}"
        if total_dups:
            msg += f" (дубликатов в базе: {total_dups})"
        msg += ".\nСвойства родителя (статус/MAK count/эдишн) скопированы в клоны."
        QMessageBox.information(self, "Готово", msg)
        self._reload_keys()
        self._reload_categories()

    def _on_row_double_clicked(self, item):
        # двойной клик копирует ключ
        kid = item.data(Qt.ItemDataRole.UserRole)
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == kid:
                k = self.table.item(r, 0).text()
                QGuiApplication.clipboard().setText(k)
                self.status.showMessage(f"Скопировано: {k}", 3000)
                return

    # ----- действия -----
    def _add_keys(self):
        if self.current_category_id is None:
            QMessageBox.warning(self, "Нет категории", "Сначала выбери или создай категорию.")
            return
        cat = next(c for c in self.db.list_categories() if c.id == self.current_category_id)
        dlg = AddKeysDialog(self, cat.name)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            keys_to_add = dlg.keys()
            added, dups = self.db.add_keys(self.current_category_id, keys_to_add)
            self.status.showMessage(f"Добавлено: {added}, дубликатов: {dups}", 4000)
            self._reload_keys()
            self._reload_categories()

            # Автопроверка добавленных — с тем же consume что и для ручной кнопки.
            # Свежие = ключи в этой категории со status='unknown' и last_checked_at IS NULL.
            if added > 0:
                fresh = [k for k in self.db.list_keys(category_id=self.current_category_id)
                         if k.status == "unknown" and k.last_checked_at is None
                         and k.key in {x.strip().upper() for x in keys_to_add}]
                if fresh:
                    items = [(k.id, k.key) for k in fresh]
                    self._start_worker(
                        items,
                        consume=self.cb_consume.isChecked(),
                        mak_count=self.cb_mak.isChecked(),
                        online=self.cb_online.isChecked(),
                    )

    def _start_worker(self, items: list[tuple[int, str]], *, consume: bool, mak_count: bool, online: bool):
        """Общий старт CheckWorker для массовой проверки.

        allow_consume_retail вычисляется автоматически по имени текущей категории:
        если в имени есть 'phone' (Office PP 21 Phone, Windows Pro Phone...) —
        consume Retail-ключей разрешён (онлайн нам не нужен).
        Иначе сервер защитит дорогие онлайн-активации.
        """
        if not self.client.health():
            self.status.showMessage("Жду сервер проверки (до 2 мин)…", 0)
            QApplication.processEvents()
            info = self.client.wait_until_ready(120.0)
            if not info:
                QMessageBox.warning(
                    self,
                    "Сервер недоступен",
                    "Сервер winkeycheck не отвечает на 127.0.0.1:17777.\n\n"
                    "Подождите 1–2 мин после запуска Vault или запустите Diagnose.bat "
                    "в папке с Vault.exe.\n"
                    "Не запускайте Vault дважды подряд.",
                )
                return
            self._poll_server()
        self._set_buttons_enabled(False)
        # Пользователь сам решает что проверять (Consume-галочка),
        # никаких автоматических защит по «фразам в имени категории».
        self.worker = CheckWorker(items, self.client,
                                  consume=consume, mak_count=mak_count, online=online,
                                  allow_consume_retail=True)
        self.worker.progress.connect(
            lambda i, n, k: self.status.showMessage(f"Проверяю {i}/{n}: {k}", 60000)
        )
        self.worker.one_done.connect(self._on_one_done)
        self.worker.finished_all.connect(self._on_check_finished)
        self.worker.start()

    def _copy_first_available(self):
        if self.current_category_id is None:
            return
        # сначала «онлайн свободные», потом «только по телефону» — тоже рабочий товар
        keys = self.db.list_keys(category_id=self.current_category_id, status="available")
        if not keys:
            keys = self.db.list_keys(category_id=self.current_category_id, status="phone_only")
        if not keys:
            QMessageBox.information(self, "Пусто", "Нет рабочих ключей в этой категории.")
            return
        k = keys[0]
        QGuiApplication.clipboard().setText(k.key)
        suffix = " (телефон)" if k.status == "phone_only" else ""
        self.status.showMessage(f"Скопировано в буфер: {k.key}{suffix}", 5000)

    def _check(self, *, selected_only: bool = False, only_unknown: bool = False):
        if self.current_category_id is None:
            return
        if selected_only:
            items = self._selected_keys()
        elif only_unknown:
            ks = self.db.list_keys(category_id=self.current_category_id, status="unknown")
            items = [(k.id, k.key) for k in ks]
        else:
            ks = self.db.list_keys(category_id=self.current_category_id)
            items = [(k.id, k.key) for k in ks]
        if not items:
            self.status.showMessage("Нечего проверять.", 3000)
            return

        self._start_worker(
            items,
            consume=self.cb_consume.isChecked(),
            mak_count=self.cb_mak.isChecked(),
            online=self.cb_online.isChecked(),
        )

    def _on_one_done(self, key_id: int, result: dict):
        # Прочитаем текущее состояние ключа ДО обновления статуса —
        # чтобы знать: продан ли, в архиве ли.
        before = next((k for k in self.db.get_keys_by_ids([key_id])), None)

        # 1. Сохраним результат проверки в БД
        self.db.update_check_result(key_id, result)

        # 2. Защита: проданные ключи и ключи в архиве — не трогаем автоматически.
        archive_id = self.db.get_archive_category_id()
        skip_auto = bool(before) and (
            before.status == "sold" or before.category_id == archive_id
        )
        if skip_auto:
            self._refresh_table_row(key_id)
            return

        # 3. Применим политику: удалить / в архив / оставить
        action = policy.classify(result, in_pool=True)
        if action.kind == "delete":
            self.db.delete_keys([key_id])
            self._policy_log(action.reason, key_id)
        elif action.kind == "archive":
            self.db.move_key(key_id, archive_id)
            self._policy_log(action.reason, key_id)
        # keep / skip — статус уже обновлён, ничего не делаем

        # 4. Обновим UI
        self._refresh_table_row(key_id)

    def _policy_log(self, reason: str, key_id: int):
        """Лог-сообщение в статус-баре + копим в журнал для дебага."""
        msg = f"[авто] {reason}"
        self.status.showMessage(msg, 5000)

    def _refresh_table_row(self, key_id: int):
        """Обновить или удалить строку в таблице для ключа."""
        # Текущий ключ в БД (может быть в другой категории или удалён)
        all_in_cat = {k.id: k for k in self.db.list_keys(category_id=self.current_category_id)}
        for row in range(self.table.rowCount() - 1, -1, -1):
            it = self.table.item(row, 0)
            if it and it.data(Qt.ItemDataRole.UserRole) == key_id:
                if key_id in all_in_cat:
                    self._set_row(row, all_in_cat[key_id])
                else:
                    self.table.removeRow(row)
                return

    def _on_check_finished(self):
        self.status.showMessage("Готово.", 4000)
        self._set_buttons_enabled(True)
        self._reload_categories()  # обновить счётчики
        self._reload_keys()

    def _set_buttons_enabled(self, enabled: bool):
        for b in (self.b_check_sel, self.b_check_unknown, self.b_add_keys):
            b.setEnabled(enabled)

    # ----- сервер -----
    def _poll_server(self):
        info = self.client.health_info()
        ok = bool(info and info.get("ok"))
        n = int((info or {}).get("pkeyconfigs_loaded") or 0)
        mode = (info or {}).get("mode") or "http"
        if ok:
            self.server_dot.setStyleSheet("color: #4ade80;")
            label = "● проверка" if mode == "direct" else "● сервер"
            self.server_dot.setText(label)
            tip = (
                f"Встроенная проверка ({n} pkeyconfig)"
                if mode == "direct"
                else f"Сервер winkeycheck на связи ({n} pkeyconfig)"
            )
            self.server_dot.setToolTip(tip)
        elif info is not None and n == 0:
            self.server_dot.setStyleSheet("color: #fbbf24;")
            self.server_dot.setText("● сервер")
            self.server_dot.setToolTip(
                "Сервер отвечает, но pkeyconfig не загружены — проверка ключей не работает"
            )
        else:
            self.server_dot.setStyleSheet("color: #ef4444;")
            self.server_dot.setText("● сервер")
            self.server_dot.setToolTip("Сервер winkeycheck не отвечает")
        QTimer.singleShot(5000, self._poll_server)
