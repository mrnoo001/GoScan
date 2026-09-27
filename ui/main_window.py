import logging
import os
from pathlib import Path

import cv2
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot, QTimer, QEvent
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                               QRadioButton, QButtonGroup, QLineEdit, QTextEdit, 
                               QGroupBox, QMessageBox, QToolButton, QSplitter,
                               QGraphicsView, QGraphicsScene, QGraphicsPixmapItem)
from PySide6.QtGui import QImage, QPixmap, QFont, QPainter, QColor

# Import logika dari folder core
from core.image_processor import ImageProcessor
from core.ocr_engine import OCREngine
from ui.spreadsheet_panel import SpreadsheetPanel


class DocumentPreviewView(QGraphicsView):
    """Komponen penampil gambar dengan dukungan drag-and-drop banyak file, zoom, dan pan."""
    imagesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setStyleSheet("border: 2px dashed #aaa; background-color: #f9f9f9; border-radius: 5px;")
        self.current_zoom = 1.0

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.pixmap_item.pixmap().isNull():
            painter.setPen(QColor("#aaaaaa"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Pilih atau seret banyak gambar dokumen ke sini")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            url.isLocalFile() for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        urls = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if urls:
            self.imagesDropped.emit(urls)
            event.acceptProposedAction()
        else:
            event.ignore()

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            zoom_in_factor = 1.15
            zoom_out_factor = 1.0 / zoom_in_factor
            if event.angleDelta().y() > 0:
                self.scale(zoom_in_factor, zoom_in_factor)
                self.current_zoom *= zoom_in_factor
            else:
                self.scale(zoom_out_factor, zoom_out_factor)
                self.current_zoom *= zoom_out_factor
            event.accept()
        else:
            super().wheelEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.NativeGesture:
            if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                zoom_factor = 1.0 + event.value()
                if zoom_factor > 0:
                    self.scale(zoom_factor, zoom_factor)
                    self.current_zoom *= zoom_factor
                return True
        return super().viewportEvent(event)

    def set_image(self, pixmap):
        self.pixmap_item.setPixmap(pixmap)
        self.scene.setSceneRect(self.pixmap_item.boundingRect())
        self.fit_in_view()
        self.viewport().update()

    def fit_in_view(self):
        if not self.pixmap_item.pixmap().isNull():
            self.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.current_zoom = self.transform().m11()

    def zoom_in(self):
        if not self.pixmap_item.pixmap().isNull():
            self.scale(1.15, 1.15)
            self.current_zoom *= 1.15

    def zoom_out(self):
        if not self.pixmap_item.pixmap().isNull():
            self.scale(1 / 1.15, 1 / 1.15)
            self.current_zoom /= 1.15

    def zoom_reset(self):
        if not self.pixmap_item.pixmap().isNull():
            self.resetTransform()
            self.current_zoom = 1.0


class ImageDropButton(QPushButton):
    imagesDropped = Signal(list)

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            url.isLocalFile() for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        urls = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if urls:
            self.imagesDropped.emit(urls)
            event.acceptProposedAction()
        else:
            event.ignore()


class OCRWorker(QObject):
    completed = Signal(str, object, object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, image_path, use_tesseract, processor, ocr):
        super().__init__()
        self.image_path = image_path
        self.use_tesseract = use_tesseract
        self.processor = processor
        self.ocr = ocr

    @Slot()
    def run(self):
        temp_image_path = None
        try:
            if self.use_tesseract:
                temp_image_path = self.processor.preprocess_image(self.image_path)
                ocr_results = self.ocr.process_tesseract(temp_image_path)
                cleaned_preview = cv2.imread(temp_image_path, cv2.IMREAD_GRAYSCALE)
            else:
                enhanced_image = self.processor.preprocess_easyocr_image(self.image_path)
                ocr_results = self.ocr.process_easyocr(enhanced_image)
                cleaned_preview = enhanced_image

            extracted_text = self.ocr.reconstruct_text(ocr_results)
            self.completed.emit(extracted_text, ocr_results, cleaned_preview)
        except Exception as error:
            logging.exception("Pemrosesan dokumen gagal")
            self.failed.emit(str(error))
        finally:
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.remove(temp_image_path)
                except OSError:
                    logging.exception("Gagal menghapus gambar sementara")
            self.finished.emit()


class OCRDocumentScanner(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sistem Pemindai & Analisis Dokumen (Batch Processing)")
        self.resize(1100, 650)
        
        # State Manajemen Batch
        self.image_paths = []
        self.current_image_index = -1
        self.document_data = {}  # Cache hasil OCR: {path: {'extracted_text': ..., 'ocr_results': ..., 'cleaned_preview': ...}}
        
        # Variabel untuk dokumen yang sedang aktif dilihat
        self.ocr_results = None
        self.extracted_text = ""
        self.cleaned_preview = None
        self.current_preview_mode = "original"
        self._source_preview_pixmap = QPixmap()

        # Inisialisasi Backend Core
        self.processor = ImageProcessor()
        self.ocr = OCREngine()
        self.processing_thread = None
        self.ocr_worker = None

        app_font = QFont("Segoe UI", 10)
        self.setFont(app_font)
        self.init_ui()

    @property
    def current_image_path(self):
        if 0 <= self.current_image_index < len(self.image_paths):
            return self.image_paths[self.current_image_index]
        return None

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        top_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- PANEL KIRI (Kontrol) ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)

        control_group = QGroupBox("Kontrol Pengaturan")
        control_layout = QVBoxLayout()

        self.btn_upload = ImageDropButton("Pilih Dokumen (Bisa Banyak Gambar)")
        self.btn_upload.setMinimumHeight(40)
        self.btn_upload.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_upload.clicked.connect(self.upload_images)
        self.btn_upload.imagesDropped.connect(self.load_images)
        control_layout.addWidget(self.btn_upload)

        tipe_layout = QHBoxLayout()
        self.radio_ketik = QRadioButton("Teks Ketik (Tesseract)")
        self.radio_tulis = QRadioButton("Tulis Tangan (EasyOCR)")
        self.radio_ketik.setChecked(True)
        self.btn_group_tipe = QButtonGroup()
        self.btn_group_tipe.addButton(self.radio_ketik)
        self.btn_group_tipe.addButton(self.radio_tulis)
        tipe_layout.addWidget(self.radio_ketik)
        tipe_layout.addWidget(self.radio_tulis)
        control_layout.addLayout(tipe_layout)

        search_layout = QHBoxLayout()
        self.input_filter = QLineEdit()
        self.input_filter.setPlaceholderText("Filter kata (misal: alamat, kontak)")
        self.input_filter.setMinimumHeight(35)
        self.input_filter.returnPressed.connect(self.search_keyword)
        search_layout.addWidget(self.input_filter, stretch=1)

        self.btn_search = QToolButton()
        self.btn_search.setText("Cari")
        self.btn_search.setToolTip("Cari kata pada hasil OCR dan tandai di gambar")
        self.btn_search.setMinimumSize(54, 35)
        self.btn_search.setStyleSheet(
            "QToolButton { background-color: #f2c14e; color: #202124; font-weight: bold; border-radius: 4px; }"
            "QToolButton:hover { background-color: #ffd166; }"
        )
        self.btn_search.clicked.connect(self.search_keyword)
        self.btn_search.setEnabled(False)
        search_layout.addWidget(self.btn_search)
        control_layout.addLayout(search_layout)

        self.btn_process = QPushButton("Proses Dokumen Saat Ini")
        self.btn_process.setMinimumHeight(40)
        self.btn_process.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; border-radius: 5px;")
        self.btn_process.clicked.connect(self.process_document)
        self.btn_process.setEnabled(False)
        control_layout.addWidget(self.btn_process)

        control_group.setLayout(control_layout)
        left_layout.addWidget(control_group)

        # --- PANEL PRATINJAU ---
        preview_panel = QGroupBox("Pratinjau Dokumen")
        preview_layout = QVBoxLayout(preview_panel)
        preview_controls = QHBoxLayout()
        
        # 1. Mode Gambar (KIRI)
        self.btn_preview_original = QToolButton()
        self.btn_preview_original.setText("Asli")
        self.btn_preview_original.setCheckable(True)
        self.btn_preview_original.setChecked(True)
        self.btn_preview_cleaned = QToolButton()
        self.btn_preview_cleaned.setText("Hasil Pembersihan")
        self.btn_preview_cleaned.setCheckable(True)
        
        for button in (self.btn_preview_original, self.btn_preview_cleaned):
            button.setEnabled(False)
            button.setStyleSheet(
                "QToolButton { padding: 5px 9px; border: 1px solid #aab3b0; border-radius: 4px; background: #f4f6f5; color: #26332f; }"
                "QToolButton:checked { background: #dcece7; border-color: #2c7a67; }"
            )
            preview_controls.addWidget(button)

        # Spacer pemisah antara Mode Gambar dan Navigasi
        preview_controls.addStretch(1)

        # 2. Kontrol Navigasi Gambar (TENGAH)
        self.btn_prev = QToolButton()
        self.btn_prev.setText("◄ Mundur")
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(self.prev_document)
        
        self.lbl_counter = QLabel("0 / 0")
        self.lbl_counter.setAlignment(Qt.AlignCenter)
        self.lbl_counter.setMinimumWidth(80)
        self.lbl_counter.setStyleSheet("font-weight: bold; color: #2c7a67;")
        
        self.btn_next = QToolButton()
        self.btn_next.setText("Maju ►")
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(self.next_document)
        
        preview_controls.addWidget(self.btn_prev)
        preview_controls.addWidget(self.lbl_counter)
        preview_controls.addWidget(self.btn_next)
        
        # Spacer pemisah antara Navigasi dan Zoom
        preview_controls.addStretch(1)

        # 3. Kontrol Zoom (KANAN)
        self.btn_zoom_out = QToolButton()
        self.btn_zoom_out.setText("−")
        self.btn_zoom_in = QToolButton()
        self.btn_zoom_in.setText("+")
        self.btn_zoom_fit = QToolButton()
        self.btn_zoom_fit.setText("Fit")
        self.btn_zoom_100 = QToolButton()
        self.btn_zoom_100.setText("100%")
        
        for button in (self.btn_zoom_out, self.btn_zoom_in, self.btn_zoom_fit, self.btn_zoom_100):
            button.setStyleSheet("QToolButton { padding: 4px; font-weight: bold; border: 1px solid #ccc; border-radius: 3px; }")
            preview_controls.addWidget(button)

        preview_layout.addLayout(preview_controls)

        # Area penampil gambar zoomable
        self.image_view = DocumentPreviewView()
        self.image_view.setMinimumSize(380, 300)
        self.image_view.imagesDropped.connect(self.load_images)
        preview_layout.addWidget(self.image_view, stretch=1)
        left_layout.addWidget(preview_panel, stretch=1)

        # Koneksi sinyal
        self.btn_preview_original.clicked.connect(self.show_original_preview)
        self.btn_preview_cleaned.clicked.connect(self.show_cleaned_preview)
        self.btn_zoom_out.clicked.connect(self.image_view.zoom_out)
        self.btn_zoom_in.clicked.connect(self.image_view.zoom_in)
        self.btn_zoom_fit.clicked.connect(self.image_view.fit_in_view)
        self.btn_zoom_100.clicked.connect(self.image_view.zoom_reset)

        # --- PANEL KANAN (Hasil Teks) ---
        right_panel = QGroupBox("Hasil Ekstraksi Teks")
        right_layout = QVBoxLayout(right_panel)
        self.text_result = QTextEdit()
        self.text_result.setReadOnly(True)
        self.text_result.setPlaceholderText("Hasil OCR akan dipertahankan sesuai format baris aslinya di sini...")
        self.text_result.setStyleSheet("background-color: #ffffff; color: #202124; selection-background-color: #b3d7ff; selection-color: #202124; border: 1px solid #ccc; border-radius: 5px; padding: 10px; font-family: 'Courier New';")
        right_layout.addWidget(self.text_result)

        top_splitter.addWidget(left_panel)
        top_splitter.addWidget(right_panel)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([550, 550])

        self.spreadsheet_panel = SpreadsheetPanel()
        vertical_splitter.addWidget(top_splitter)
        vertical_splitter.addWidget(self.spreadsheet_panel)
        vertical_splitter.setStretchFactor(0, 3)
        vertical_splitter.setStretchFactor(1, 2)
        vertical_splitter.setSizes([420, 280])
        main_layout.addWidget(vertical_splitter)
        QTimer.singleShot(0, self._offer_draft_recovery)

    def upload_images(self):
        file_names, _ = QFileDialog.getOpenFileNames(
            self, "Pilih Banyak Gambar", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )
        if file_names:
            self.load_images(file_names)

    @Slot(list)
    def load_images(self, file_names):
        valid_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
        valid_files = [f for f in file_names if Path(f).suffix.lower() in valid_exts]
        
        if not valid_files:
            QMessageBox.warning(self, "Format Tidak Didukung", "Tidak ada file gambar yang didukung dalam pilihan Anda.")
            return

        if self.image_paths and self.spreadsheet_panel.has_unsaved_changes():
            answer = QMessageBox.question(
                self, "Ganti Antrean Dokumen", "Apakah Anda ingin mengganti daftar dokumen saat ini? Draf tabel tetap tersimpan.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.image_paths = valid_files
        self.document_data.clear() # Bersihkan cache OCR lama
        self.show_document(0)

    def prev_document(self):
        if self.current_image_index > 0:
            self.show_document(self.current_image_index - 1)

    def next_document(self):
        if self.current_image_index < len(self.image_paths) - 1:
            self.show_document(self.current_image_index + 1)

    def show_document(self, index):
        if not self.image_paths or index < 0 or index >= len(self.image_paths):
            return

        self.current_image_index = index
        path = self.image_paths[index]

        # Update Counter & Navigasi
        self.lbl_counter.setText(f"{index + 1} / {len(self.image_paths)}")
        self.btn_prev.setEnabled(index > 0)
        self.btn_next.setEnabled(index < len(self.image_paths) - 1)

        # Reset Pratinjau
        pixmap = QPixmap(path)
        self.current_preview_mode = "original"
        self.btn_preview_original.setChecked(True)
        self.btn_preview_original.setEnabled(True)

        # Ambil cache data OCR jika dokumen ini sudah pernah diproses sebelumnya
        data = self.document_data.get(path, {})
        self.ocr_results = data.get("ocr_results")
        self.extracted_text = data.get("extracted_text", "")
        self.cleaned_preview = data.get("cleaned_preview")

        self.btn_preview_cleaned.setEnabled(self.cleaned_preview is not None)
        self.btn_preview_cleaned.setChecked(False)

        self._set_preview_image(pixmap)
        
        if self.ocr_results:
            self.text_result.setPlainText(self.extracted_text)
        else:
            self.text_result.clear()

        self.btn_process.setEnabled(True)
        self.btn_search.setEnabled(self.ocr_results is not None)

    def process_document(self):
        path = self.current_image_path
        if not path:
            return

        # Kunci semua tombol selama pemrosesan agar navigasi aman
        self.btn_process.setEnabled(False)
        self.btn_search.setEnabled(False)
        self.btn_upload.setEnabled(False)
        self.radio_ketik.setEnabled(False)
        self.radio_tulis.setEnabled(False)
        self.input_filter.setEnabled(False)
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)
        
        self.btn_process.setText("Memproses...")
        self.ocr_results = None
        self.extracted_text = ""
        engine_name = "Tesseract" if self.radio_ketik.isChecked() else "EasyOCR"
        self.text_result.setPlainText(f"Memproses dokumen dengan {engine_name}...\nAplikasi tetap dapat digunakan selama proses berlangsung.")

        self.processing_thread = QThread(self)
        self.ocr_worker = OCRWorker(
            path,
            self.radio_ketik.isChecked(),
            self.processor,
            self.ocr,
        )
        self.ocr_worker.moveToThread(self.processing_thread)
        self.processing_thread.started.connect(self.ocr_worker.run)
        self.ocr_worker.completed.connect(self._on_processing_completed)
        self.ocr_worker.failed.connect(self._on_processing_failed)
        self.ocr_worker.finished.connect(
            self.processing_thread.quit, Qt.ConnectionType.DirectConnection
        )
        self.ocr_worker.finished.connect(self.ocr_worker.deleteLater)
        self.processing_thread.finished.connect(self._on_processing_finished)
        self.processing_thread.finished.connect(self.processing_thread.deleteLater)
        self.processing_thread.start()

    @Slot(str, object, object)
    def _on_processing_completed(self, text, ocr_results, cleaned_preview):
        path = self.current_image_path
        
        # Simpan ke cache
        if path:
            self.document_data[path] = {
                "extracted_text": text or "Tidak ada teks yang berhasil dikenali.",
                "ocr_results": ocr_results,
                "cleaned_preview": cleaned_preview
            }

        self.ocr_results = ocr_results
        self.extracted_text = text or "Tidak ada teks yang berhasil dikenali."
        self.cleaned_preview = cleaned_preview
        self.text_result.setPlainText(self.extracted_text)
        self.btn_preview_cleaned.setEnabled(cleaned_preview is not None)
        
        if self.current_preview_mode == "cleaned" and cleaned_preview is not None:
            self._set_preview_image(self._pixmap_from_array(cleaned_preview))
        else:
            self.btn_preview_original.setChecked(True)
            self._set_preview_image(QPixmap(self.current_image_path))
            
        self.btn_search.setEnabled(True)

    def search_keyword(self):
        if self.ocr_results is None:
            QMessageBox.information(
                self, "Hasil OCR Belum Tersedia", "Proses dokumen terlebih dahulu."
            )
            return

        keywords = self.input_filter.text().strip()
        if not keywords:
            QMessageBox.information(
                self, "Kata Kunci Kosong", "Masukkan kata yang ingin dicari."
            )
            return

        matches = self.ocr.filter_text(self.ocr_results, keywords)
        path = self.current_image_path
        if not matches or not path:
            self._set_preview_image(QPixmap(path))
            self.text_result.setPlainText(
                f"{self.extracted_text}\n\nTidak ditemukan kata: {keywords}"
            )
            return

        annotated_image = self.processor.draw_annotations(path, matches)
        height, width, channels = annotated_image.shape
        image = QImage(
            annotated_image.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_BGR888,
        ).copy()
        self._set_preview_image(QPixmap.fromImage(image))
        self.text_result.setPlainText(
            f"{self.extracted_text}\n\nDitemukan {len(matches)} bagian untuk: {keywords}"
        )

    def _set_preview_image(self, pixmap):
        if not pixmap.isNull():
            self._source_preview_pixmap = pixmap
            self.image_view.set_image(self._source_preview_pixmap)

    @staticmethod
    def _pixmap_from_array(image_array):
        if image_array is None:
            return QPixmap()
        if image_array.ndim == 2:
            height, width = image_array.shape
            image = QImage(
                image_array.data, width, height, width, QImage.Format.Format_Grayscale8
            ).copy()
        else:
            height, width, channels = image_array.shape
            if channels == 4:
                image = QImage(
                    image_array.data, width, height, channels * width,
                    QImage.Format.Format_BGRA8888,
                ).copy()
            else:
                image = QImage(
                    image_array.data, width, height, channels * width,
                    QImage.Format.Format_BGR888,
                ).copy()
        return QPixmap.fromImage(image)

    def show_original_preview(self):
        self.current_preview_mode = "original"
        self.btn_preview_cleaned.setChecked(False)
        self.btn_preview_original.setChecked(True)
        if self.current_image_path:
            self._set_preview_image(QPixmap(self.current_image_path))

    def show_cleaned_preview(self):
        if self.cleaned_preview is None:
            self.btn_preview_original.setChecked(True)
            return
        self.current_preview_mode = "cleaned"
        self.btn_preview_original.setChecked(False)
        self.btn_preview_cleaned.setChecked(True)
        self._set_preview_image(self._pixmap_from_array(self.cleaned_preview))

    def _offer_draft_recovery(self):
        self.spreadsheet_panel.restore_draft_if_available(
            lambda: QMessageBox.question(
                self,
                "Pulihkan Draf Tabel",
                "Ditemukan draf tabel otomatis. Pulihkan sekarang?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
        )

    @Slot(str)
    def _on_processing_failed(self, error_message):
        self.text_result.setPlainText("Pemrosesan gagal. Periksa pesan error untuk detailnya.")
        QMessageBox.critical(
            self,
            "Gagal Memproses Dokumen",
            f"Pemrosesan dokumen gagal:\n{error_message}",
        )

    @Slot()
    def _on_processing_finished(self):
        self.btn_process.setEnabled(bool(self.current_image_path))
        self.btn_search.setEnabled(self.ocr_results is not None)
        self.btn_upload.setEnabled(True)
        self.radio_ketik.setEnabled(True)
        self.radio_tulis.setEnabled(True)
        self.input_filter.setEnabled(True)
        self.btn_process.setText("Proses Dokumen Saat Ini")
        
        # Buka kembali navigasi sesuai index
        self.btn_prev.setEnabled(self.current_image_index > 0)
        self.btn_next.setEnabled(self.current_image_index < len(self.image_paths) - 1)
        
        self.ocr_worker = None
        self.processing_thread = None

    def closeEvent(self, event):
        if self.processing_thread and self.processing_thread.isRunning():
            QMessageBox.warning(
                self,
                "Pemrosesan Masih Berjalan",
                "Tunggu sampai pemrosesan dokumen selesai sebelum menutup aplikasi.",
            )
            event.ignore()
            return

        self.spreadsheet_panel.flush_autosave()

        if self.spreadsheet_panel.has_unsaved_changes():
            answer = QMessageBox.question(
                self,
                "Perubahan Tabel",
                "Tabel sudah tersimpan sebagai draf lokal. Tetap keluar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        event.accept()