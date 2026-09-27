# GoScan

Aplikasi desktop untuk memindai dan menganalisis dokumen (batch processing) menggunakan OCR. Mendukung teks ketik (Tesseract) maupun tulisan tangan (EasyOCR), dengan fitur pencarian kata kunci, anotasi hasil pencarian pada gambar, serta editor tabel data (spreadsheet) terintegrasi dengan autosave.

## Fitur

- **Batch processing** — unggah atau drag-and-drop banyak gambar sekaligus, lalu navigasi antar dokumen.
- **Dua mesin OCR**
  - **Tesseract** untuk teks ketik (dengan pra-pemrosesan: grayscale, denoising, unsharp masking, Otsu's thresholding).
  - **EasyOCR** untuk tulisan tangan (dengan peningkatan kontras/CLAHE tanpa mengubah geometri gambar).
- **Rekonstruksi tata letak teks** — hasil OCR disusun ulang menjadi paragraf dengan indentasi dan spasi yang menyerupai dokumen asli.
- **Pencarian & anotasi** — cari kata kunci pada hasil OCR, lalu tandai bagian yang cocok langsung di atas gambar.
- **Panel spreadsheet** — tabel data dengan validasi tipe kolom (teks/angka/tanggal), undo/redo, impor/ekspor CSV & Excel, serta autosave draf lokal yang aman dari crash.
- **Pratinjau interaktif** — zoom, pan, dan toggle antara gambar asli dan hasil pembersihan gambar.

## Struktur Proyek

```
GoScan/
├── core/
│   ├── image_processor.py   # Pra-pemrosesan gambar & anotasi
│   ├── ocr_engine.py        # Mesin OCR (Tesseract & EasyOCR), filter, rekonstruksi teks
│   └── spreadsheet.py       # Impor/ekspor & penyimpanan draf tabel
├── ui/
│   ├── main_window.py       # Jendela utama aplikasi
│   └── spreadsheet_panel.py # Panel tabel data (editor, undo/redo, autosave)
└── main.py                  # Entry point aplikasi
```

## Prasyarat

Selain dependensi Python, aplikasi ini membutuhkan **Tesseract OCR** terpasang di sistem (paket `pytesseract` hanya wrapper, bukan mesin OCR itu sendiri):

- **Windows**: unduh installer dari [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki), lalu pastikan path-nya masuk ke `PATH` sistem.
- **macOS**: `brew install tesseract`
- **Linux (Debian/Ubuntu)**: `sudo apt install tesseract-ocr`

Untuk hasil terbaik pada dokumen berbahasa Indonesia, pastikan paket bahasa `ind` tersedia (biasanya `tesseract-ocr-ind` di Linux, atau data bahasa tambahan di Windows/macOS).

## Instalasi

```bash
git clone https://github.com/mrnoo001git/GoScan.git
cd GoScan
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Menjalankan Aplikasi

```bash
python main.py
```

## Catatan

- EasyOCR akan mengunduh model bahasa (id, en) secara otomatis saat pertama kali digunakan — pastikan koneksi internet tersedia pada penggunaan pertama.
- Draf tabel disimpan otomatis secara lokal (macOS: `~/Library/Application Support/GoScan/table_draft.json`) sehingga perubahan tidak hilang meskipun aplikasi ditutup tanpa ekspor manual.

## Lisensi

Proyek ini dilisensikan di bawah MIT License.