import csv
from pathlib import Path

from PySide6.QtCore import QEvent, QRegularExpression, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QStandardItem, QStandardItemModel, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QAbstractItemDelegate,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.spreadsheet import SpreadsheetError, SpreadsheetStore


class SnapshotCommand(QUndoCommand):
    def __init__(self, panel, before, after, description):
        super().__init__(description)
        self.panel = panel
        self.before = before
        self.after = after
        self._initial_redo = True

    def undo(self):
        self.panel.restore_snapshot(self.before)

    def redo(self):
        if self._initial_redo:
            self._initial_redo = False
            return
        self.panel.restore_snapshot(self.after)


class CellEditCommand(QUndoCommand):
    def __init__(self, panel, row, column, before, after):
        super().__init__("Edit sel")
        self.panel = panel
        self.row = row
        self.column = column
        self.before = before
        self.after = after

    def undo(self):
        self.panel._set_cell_from_history(self.row, self.column, self.before)

    def redo(self):
        self.panel._set_cell_from_history(self.row, self.column, self.after)


class ValidationDelegate(QStyledItemDelegate):
    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel

    def paint(self, painter, option, index):
        value = index.data(Qt.ItemDataRole.EditRole)
        column_type = self.panel.column_types[index.column()]
        if not self.panel.store.validate_value(value, column_type):
            option.palette.setColor(option.palette.ColorRole.Text, QColor("#9f2d24"))
            option.backgroundBrush = QBrush(QColor("#fde8e6"))
        super().paint(painter, option, index)


class EnterNavigationDelegate(ValidationDelegate):
    def __init__(self, panel, parent=None):
        super().__init__(panel, parent)
        self.navigateRequested = Signal()

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.SubmitModelCache)
            QTimer.singleShot(0, self.panel.move_to_cell_below)
            return True
        return super().eventFilter(editor, event)


class SpreadsheetPanel(QWidget):
    statusChanged = Signal(str)

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store or SpreadsheetStore()
        self._restoring = False
        self._last_snapshot = None
        self._baseline = None
        self.headers = [f"Kolom {index}" for index in range(1, 11)]
        self.column_types = ["text"] * len(self.headers)
        self.rows = [[""] * len(self.headers) for _ in range(10)]
        self.model = QStandardItemModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(50)
        self._build_ui()
        self._load_state(self.headers, self.rows, self.column_types)
        self._last_snapshot = self.snapshot()
        self._baseline = self.snapshot()
        self.model.itemChanged.connect(self._on_item_changed)
        self.undo_stack.indexChanged.connect(self._schedule_autosave)
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._autosave)
        self._restore_timer.setInterval(800)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        toolbar = QToolBar()
        toolbar.setMovable(False)
        title = QLabel("Tabel Data")
        title.setStyleSheet("font-size: 15px; font-weight: 600; color: #26332f; padding: 4px 2px;")
        layout.addWidget(title)

        self.btn_add_row = QPushButton("+ Baris")
        self.btn_delete_rows = QPushButton("Hapus Baris")
        self.btn_add_column = QPushButton("+ Kolom")
        self.btn_delete_column = QPushButton("Hapus Kolom")
        self.btn_import = QPushButton("Impor")
        self.btn_export = QPushButton("Ekspor")
        self.btn_clear = QPushButton("Kosongkan")
        self.btn_undo = self.undo_stack.createUndoAction(self, "Undo")
        self.btn_redo = self.undo_stack.createRedoAction(self, "Redo")
        for widget in (
            self.btn_add_row,
            self.btn_delete_rows,
            self.btn_add_column,
            self.btn_delete_column,
            self.btn_import,
            self.btn_export,
            self.btn_clear,
        ):
            toolbar.addWidget(widget)
        toolbar.addAction(self.btn_undo)
        toolbar.addAction(self.btn_redo)

        toolbar.addSeparator()
        self.type_selector = QComboBox()
        self.type_selector.addItem("Teks", "text")
        self.type_selector.addItem("Angka", "number")
        self.type_selector.addItem("Tanggal", "date")
        self.type_selector.setToolTip("Tipe validasi untuk kolom terpilih")
        toolbar.addWidget(self.type_selector)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter semua kolom")
        self.search.setMaximumWidth(220)
        toolbar.addWidget(self.search)
        layout.addWidget(toolbar)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(False)
        self.proxy.setDynamicSortFilter(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegate(EnterNavigationDelegate(self, self.table))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_menu)
        self.table.horizontalHeader().sectionClicked.connect(self.select_column)
        self.table.horizontalHeader().sectionDoubleClicked.connect(self.rename_column)
        layout.addWidget(self.table, stretch=1)

        self.status = QLabel("Draf disimpan otomatis di komputer ini")
        self.status.setStyleSheet("color: #65706f; padding: 2px 4px;")
        layout.addWidget(self.status)

        self.btn_add_row.clicked.connect(lambda: self.add_rows(1))
        self.btn_delete_rows.clicked.connect(self.delete_selected_rows)
        self.btn_add_column.clicked.connect(self.add_column)
        self.btn_delete_column.clicked.connect(self.delete_selected_column)
        self.btn_import.clicked.connect(self.import_dialog)
        self.btn_export.clicked.connect(self.export_dialog)
        self.btn_clear.clicked.connect(lambda: self.clear_table())
        self.search.textChanged.connect(self._set_filter)
        self.type_selector.currentIndexChanged.connect(self._set_selected_column_type)
        self.table.installEventFilter(self)
        self.table.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched in (self.table, self.table.viewport()) and event.type() == event.Type.KeyPress:
            if event.matches(QKeySequence.StandardKey.Copy):
                self.copy_selection()
                return True
            if event.matches(QKeySequence.StandardKey.Paste):
                self.paste_selection()
                return True
        return super().eventFilter(watched, event)

    def snapshot(self):
        rows = []
        for row in range(self.model.rowCount()):
            rows.append([
                self.model.item(row, column).text() if self.model.item(row, column) else ""
                for column in range(self.model.columnCount())
            ])
        return {
            "headers": [self.model.headerData(c, Qt.Orientation.Horizontal) for c in range(self.model.columnCount())],
            "rows": rows,
            "column_types": list(self.column_types),
        }

    def restore_snapshot(self, snapshot):
        self._restoring = True
        self._load_state(snapshot["headers"], snapshot["rows"], snapshot["column_types"])
        self._last_snapshot = self.snapshot()
        self._restoring = False
        self._schedule_autosave()

    def _load_state(self, headers, rows, column_types):
        self.headers = list(headers)
        self.column_types = list(column_types)
        self.rows = [list(row) for row in rows]
        self.model.clear()
        self.model.setColumnCount(len(self.headers))
        self.model.setHorizontalHeaderLabels(self.headers)
        self.model.setRowCount(len(self.rows))
        for row_index, row in enumerate(self.rows):
            for column_index in range(len(self.headers)):
                value = row[column_index] if column_index < len(row) else ""
                self.model.setItem(row_index, column_index, QStandardItem(str(value)))
        self.proxy.invalidate()
        self._select_column_type(self.table.currentIndex().column() if self.table.currentIndex().isValid() else -1)

    def _record_change(self, before, description):
        after = self.snapshot()
        if before == after:
            return
        self._last_snapshot = after
        self.undo_stack.push(SnapshotCommand(self, before, after, description))

    def _on_item_changed(self, _item):
        if self._restoring:
            return
        before = self._last_snapshot or self.snapshot()
        row = _item.row()
        column = _item.column()
        old_value = before["rows"][row][column]
        new_value = _item.text()
        if old_value == new_value:
            return
        after = self.snapshot()
        self._last_snapshot = after
        self.undo_stack.push(CellEditCommand(self, row, column, old_value, new_value))

    def _set_cell_from_history(self, row, column, value):
        self._restoring = True
        self.model.item(row, column).setText(value)
        self._restoring = False
        self._last_snapshot = self.snapshot()
        self._schedule_autosave()

    def _schedule_autosave(self, *_args):
        self._restore_timer.start()
        self.status.setText("Perubahan belum disimpan ke file; draf lokal diperbarui otomatis…")

    def _autosave(self):
        try:
            current = self.snapshot()
            self.store.save_draft(**current)
            self.status.setText("Draf tersimpan otomatis di komputer ini")
            self.statusChanged.emit("saved")
        except (OSError, SpreadsheetError) as error:
            self.status.setText(f"Gagal menyimpan draf: {error}")
            self.statusChanged.emit("error")

    def flush_autosave(self):
        has_pending_save = self._restore_timer.isActive()
        if has_pending_save:
            self._restore_timer.stop()
        if not (has_pending_save or self.has_unsaved_changes()):
            return
        current = self.snapshot()
        is_default_empty = self._is_default_empty(current)
        if is_default_empty:
            try:
                self.store.clear_draft()
                self.status.setText("Tidak ada draf tabel yang perlu dipulihkan")
            except SpreadsheetError as error:
                self.status.setText(f"Gagal membersihkan draf: {error}")
        else:
            self._autosave()

    def restore_draft_if_available(self, confirm):
        try:
            draft = self.store.load_draft()
        except SpreadsheetError as error:
            self.status.setText(str(error))
            return False
        if not draft:
            return False
        if not confirm():
            return False
        self.restore_snapshot(draft)
        self._baseline = self.snapshot()
        self.undo_stack.clear()
        self.status.setText("Draf terakhir dipulihkan")
        return True

    def has_unsaved_changes(self):
        return self.snapshot() != self._baseline

    @staticmethod
    def _is_default_empty(snapshot):
        return (
            snapshot["headers"] == [f"Kolom {index}" for index in range(1, 11)]
            and snapshot["column_types"] == ["text"] * 10
            and snapshot["rows"] == [[""] * 10 for _ in range(10)]
        )

    def mark_saved(self):
        self._baseline = self.snapshot()
        self.status.setText("Tabel tersimpan")

    def add_rows(self, count):
        if self.model.rowCount() + count > SpreadsheetStore.MAX_IMPORT_ROWS:
            QMessageBox.warning(self, "Batas Baris", "Tabel dibatasi hingga 10.000 baris.")
            return
        before = self.snapshot()
        self._restoring = True
        try:
            for _ in range(count):
                row = self.model.rowCount()
                self.model.insertRow(row)
                for column in range(self.model.columnCount()):
                    self.model.setItem(row, column, QStandardItem(""))
        finally:
            self._restoring = False
        self._record_change(before, "Tambah baris")

    def add_column(self):
        if self.model.columnCount() >= SpreadsheetStore.MAX_IMPORT_COLUMNS:
            QMessageBox.warning(self, "Batas Kolom", "Tabel dibatasi hingga 64 kolom.")
            return
        before = self.snapshot()
        self._restoring = True
        try:
            self.add_column_without_history()
        finally:
            self._restoring = False
        self._record_change(before, "Tambah kolom")

    def delete_selected_rows(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected_rows:
            selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
        if not selected_rows:
            return
        before = self.snapshot()
        source_rows = sorted({
            self.proxy.mapToSource(self.proxy.index(row, 0)).row()
            for row in selected_rows
        }, reverse=True)
        self._restoring = True
        try:
            for row in source_rows:
                self.model.removeRow(row)
        finally:
            self._restoring = False
        self._record_change(before, "Hapus baris")

    def model_index(self, row, column):
        return self.proxy.mapToSource(self.proxy.index(row, column))

    def delete_selected_column(self):
        source_column = getattr(self, "_selected_source_column", None)
        if source_column is None or self.model.columnCount() <= 1:
            return
        before = self.snapshot()
        self._restoring = True
        try:
            self.model.removeColumn(source_column)
            del self.column_types[source_column]
        finally:
            self._restoring = False
        self._selected_source_column = None
        self._select_column_type(-1)
        self._record_change(before, "Hapus kolom")

    def clear_table(self, confirm=True):
        if confirm:
            # 1. Peringatan Pertama
            first = QMessageBox.warning(
                self,
                "Konfirmasi 1 dari 2",
                "Kosongkan semua isi sel? Struktur 10 baris dan 10 kolom tetap dipertahankan.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if first != QMessageBox.StandardButton.Yes:
                return
                
            # 2. Validasi dengan Input Teks
            text, accepted = QInputDialog.getText(
                self,
                "Validasi Terakhir",
                "Pastikan: seluruh data dalam tabel akan dihapus.\n\nKetik 'KOSONGKAN' untuk melanjutkan:"
            )
            
            # Cek apakah input valid dan benar
            if not accepted or text.strip() != "KOSONGKAN":
                QMessageBox.information(
                    self, 
                    "Dibatalkan", 
                    "Proses pengosongan tabel dibatalkan."
                )
                return

        before = self.snapshot()
        self._restoring = True
        try:
            for row in range(self.model.rowCount()):
                for column in range(self.model.columnCount()):
                    item = self.model.item(row, column)
                    if item is not None:
                        item.setText("")
        finally:
            self._restoring = False
        self._record_change(before, "Kosongkan tabel")
        self.status.setText("Isi sel dikosongkan; baris dan kolom tetap")

    def import_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Impor tabel", "", "Spreadsheet (*.xlsx *.xlsm *.csv);;Semua file (*)"
        )
        if file_path:
            self.import_path(file_path)

    def import_path(self, file_path, confirm_replace=None):
        if self.has_unsaved_changes():
            accepted = confirm_replace() if confirm_replace else QMessageBox.question(
                self, "Ganti Tabel", "Impor akan mengganti isi tabel saat ini. Lanjutkan?"
            ) == QMessageBox.StandardButton.Yes
            if not accepted:
                return False
        try:
            headers, rows = self.store.import_file(file_path)
        except (OSError, SpreadsheetError, csv.Error) as error:
            QMessageBox.critical(self, "Impor Gagal", str(error))
            return False
        if not headers:
            QMessageBox.information(self, "File Kosong", "File tidak berisi header dan data.")
            return False
        before = self.snapshot()
        types = ["text"] * len(headers)
        self.restore_snapshot({"headers": headers, "rows": rows, "column_types": types})
        self._record_change(before, "Impor tabel")
        self._baseline = before
        self.status.setText(f"Diimpor dari {Path(file_path).name}")
        return True

    def export_dialog(self):
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Ekspor tabel", "data.xlsx", "Excel (*.xlsx);;CSV (*.csv)"
        )
        if not file_path:
            return
        if not Path(file_path).suffix:
            file_path += ".csv" if "CSV" in selected_filter else ".xlsx"
        try:
            self.store.export_file(file_path, self.snapshot()["headers"], self.snapshot()["rows"])
        except (OSError, SpreadsheetError) as error:
            QMessageBox.critical(self, "Ekspor Gagal", str(error))
            return
        self.mark_saved()

    def _set_filter(self, text):
        expression = QRegularExpression.escape(text)
        self.proxy.setFilterRegularExpression(QRegularExpression(expression))

    def select_column(self, visible_column):
        if not 0 <= visible_column < self.proxy.columnCount():
            self._selected_source_column = None
            self._select_column_type(-1)
            return
        if self.proxy.rowCount():
            source_column = self.proxy.mapToSource(
                self.proxy.index(0, visible_column)
            ).column()
        else:
            source_column = visible_column
        self._selected_source_column = source_column
        selection = self.table.selectionModel()
        selection.clearSelection()
        selection.select(
            self.proxy.index(0, visible_column),
            selection.SelectionFlag.Select | selection.SelectionFlag.Columns,
        )
        self.table.setCurrentIndex(self.proxy.index(0, visible_column))
        self._select_column_type(visible_column)
        self.status.setText(
            f"Kolom '{self.headers[source_column]}' dipilih; klik Hapus Kolom untuk menghapusnya"
        )

    def move_to_cell_below(self):
        current = self.table.currentIndex()
        if not current.isValid() or self.model.columnCount() == 0:
            return
        source = self.proxy.mapToSource(current)
        target_row = source.row() + 1
        if target_row >= self.model.rowCount():
            self.add_rows(1)
            target_row = self.model.rowCount() - 1
        target = self.proxy.mapFromSource(self.model.index(target_row, source.column()))
        if not target.isValid():
            self.proxy.setFilterRegularExpression(QRegularExpression())
            target = self.proxy.mapFromSource(self.model.index(target_row, source.column()))
        if target.isValid():
            self.table.setCurrentIndex(target)
            self.table.scrollTo(target)

    def sort_column(self, visible_column):
        if not 0 <= visible_column < self.proxy.columnCount():
            return
        source_column = (
            self.proxy.mapToSource(self.proxy.index(0, visible_column)).column()
            if self.proxy.rowCount()
            else visible_column
        )
        order = self._sort_orders.get(source_column, Qt.SortOrder.DescendingOrder)
        self._sort_orders[source_column] = (
            Qt.SortOrder.DescendingOrder
            if order == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )
        self.proxy.setDynamicSortFilter(False)
        self.proxy.sort(source_column, order)
        self._select_column_type(visible_column)

    def _select_column_type(self, visible_column):
        if visible_column < 0 or visible_column >= self.proxy.columnCount():
            self.type_selector.setEnabled(False)
            return
        source_column = self.proxy.mapToSource(self.proxy.index(0, visible_column)).column() if self.proxy.rowCount() else visible_column
        if source_column < 0 or source_column >= len(self.column_types):
            self.type_selector.setEnabled(False)
            return
        self.type_selector.setEnabled(True)
        index = self.type_selector.findData(self.column_types[source_column])
        if index >= 0:
            self.type_selector.blockSignals(True)
            self.type_selector.setCurrentIndex(index)
            self.type_selector.blockSignals(False)
        self._selected_source_column = source_column

    def _set_selected_column_type(self, combo_index):
        if not hasattr(self, "_selected_source_column"):
            return
        column = self._selected_source_column
        new_type = self.type_selector.itemData(combo_index)
        if not new_type or column >= len(self.column_types):
            return
        before = self.snapshot()
        self.column_types[column] = new_type
        self.table.viewport().update()
        self._record_change(before, "Ubah tipe kolom")

    def rename_column(self, visible_column):
        if not 0 <= visible_column < self.proxy.columnCount():
            return
        source_column = (
            self.proxy.mapToSource(self.proxy.index(0, visible_column)).column()
            if self.proxy.rowCount()
            else visible_column
        )
        old_name = str(self.model.headerData(source_column, Qt.Orientation.Horizontal))
        new_name, accepted = QInputDialog.getText(
            self, "Nama Kolom", "Nama kolom:", text=old_name
        )
        if not accepted or not new_name.strip():
            return
        before = self.snapshot()
        self.model.setHeaderData(
            source_column, Qt.Orientation.Horizontal, new_name.strip()
        )
        self._record_change(before, "Ubah nama kolom")

    def _show_table_menu(self, position):
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("Tambah baris", lambda: self.add_rows(1))
        menu.addAction("Tambah kolom", self.add_column)
        menu.addAction("Hapus baris terpilih", self.delete_selected_rows)
        menu.addAction("Hapus kolom terpilih", self.delete_selected_column)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def copy_selection(self):
        selected = self.table.selectionModel().selectedIndexes()
        if not selected:
            return
        rows = {}
        for proxy_index in selected:
            source_index = self.proxy.mapToSource(proxy_index)
            rows.setdefault(source_index.row(), {})[source_index.column()] = source_index.data() or ""
        min_row, max_row = min(rows), max(rows)
        min_column = min(column for values in rows.values() for column in values)
        max_column = max(column for values in rows.values() for column in values)
        text = "\n".join(
            "\t".join(str(rows.get(row, {}).get(column, "")) for column in range(min_column, max_column + 1))
            for row in range(min_row, max_row + 1)
        )
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)

    def paste_selection(self):
        from PySide6.QtWidgets import QApplication
        text = QApplication.clipboard().text()
        if not text:
            return
        start = self.table.currentIndex()
        if not start.isValid():
            start_row, start_column = 0, 0
        else:
            source_index = self.proxy.mapToSource(start)
            start_row, start_column = source_index.row(), source_index.column()
        values = list(csv.reader(text.splitlines(), delimiter="\t"))
        if (
            start_column + max(len(row) for row in values) > SpreadsheetStore.MAX_IMPORT_COLUMNS
            or start_row + len(values) > SpreadsheetStore.MAX_IMPORT_ROWS
        ):
            QMessageBox.warning(
                self,
                "Batas Tabel",
                "Tempelan melewati batas 10.000 baris atau 64 kolom.",
            )
            return
        before = self.snapshot()
        self._restoring = True
        needed_columns = start_column + max(len(row) for row in values)
        while self.model.columnCount() < needed_columns:
            self.add_column_without_history()
        needed_rows = start_row + len(values)
        while self.model.rowCount() < needed_rows:
            row_index = self.model.rowCount()
            self.model.insertRow(row_index)
            for column in range(self.model.columnCount()):
                self.model.setItem(row_index, column, QStandardItem(""))
        for row_offset, row_values in enumerate(values):
            for column_offset, value in enumerate(row_values):
                self.model.item(start_row + row_offset, start_column + column_offset).setText(value)
        self._restoring = False
        self._record_change(before, "Tempel data")

    def add_column_without_history(self):
        column = self.model.columnCount()
        self.model.insertColumn(column)
        self.model.setHeaderData(column, Qt.Orientation.Horizontal, f"Kolom {column + 1}")
        self.column_types.append("text")
        for row in range(self.model.rowCount()):
            self.model.setItem(row, column, QStandardItem(""))