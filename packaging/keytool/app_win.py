#!/usr/bin/env python3
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from recoder import RECODE_MAX_UNIQUE, recode_unique, verify


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Key Tool")
        self.setFixedWidth(460)
        self._build()

    def _build(self):
        mono = QFont("Consolas", 10)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(QLabel("Ключ продукта:"))
        self.key_input = QLineEdit()
        self.key_input.setFont(mono)
        self.key_input.setPlaceholderText("XXXXX-XXXXX-XXXXX-XXXXX-XXXXX")
        self.key_input.textChanged.connect(self._auto_format)
        layout.addWidget(self.key_input)

        row = QHBoxLayout()
        row.addWidget(QLabel("Количество вариантов:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, RECODE_MAX_UNIQUE)
        self.count_spin.setValue(5)
        row.addWidget(self.count_spin)
        hint = QLabel(f"(макс. {RECODE_MAX_UNIQUE}, все уникальные)")
        hint.setStyleSheet("color: #666;")
        row.addWidget(hint)
        row.addStretch()
        layout.addLayout(row)

        self.gen_btn = QPushButton("Сгенерировать")
        self.gen_btn.clicked.connect(self._generate)
        layout.addWidget(self.gen_btn)

        self.output = QTextEdit()
        self.output.setFont(mono)
        self.output.setReadOnly(True)
        self.output.setFixedHeight(180)
        layout.addWidget(self.output)

        self.copy_btn = QPushButton("Скопировать всё")
        self.copy_btn.clicked.connect(self._copy)
        layout.addWidget(self.copy_btn)

    def _auto_format(self, text):
        raw = text.replace("-", "").upper()
        if len(raw) > 25:
            raw = raw[:25]
        formatted = "-".join(raw[i:i + 5] for i in range(0, len(raw), 5))
        if formatted != text:
            self.key_input.blockSignals(True)
            self.key_input.setText(formatted)
            self.key_input.setCursorPosition(len(formatted))
            self.key_input.blockSignals(False)

    def _generate(self):
        key = self.key_input.text().strip()
        count = self.count_spin.value()
        try:
            if not verify(key):
                QMessageBox.critical(
                    self, "Ошибка", "Ключ не прошёл проверку.\nПроверь правильность ввода.",
                )
                return
            results = recode_unique(key, count)
            if len(results) < count:
                QMessageBox.warning(
                    self,
                    "Внимание",
                    f"Запрошено {count}, доступно только {len(results)} уникальных вариантов.",
                )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Неверный ключ:\n{e}")
            return
        self.output.setPlainText("\n".join(results))

    def _copy(self):
        text = self.output.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
