# GoScan

Aplikasi desktop untuk membaca dokumen gambar dengan Tesseract atau EasyOCR.

## Persiapan macOS

1. Gunakan Python 3.13 atau versi yang kompatibel dengan dependensi proyek.
2. Instal Tesseract melalui Homebrew: `brew install tesseract`.
3. Pastikan data bahasa Tesseract `eng` dan `ind` tersedia. Periksa dengan `tesseract --list-langs`.
4. Buat environment dan instal dependensi Python:

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

5. Jalankan aplikasi dari direktori proyek: `python main.py`.

EasyOCR mengunduh model bahasa saat pertama kali dipilih; koneksi internet diperlukan pada penggunaan pertama. Anotasi kata ditampilkan langsung pada pratinjau dan tidak membuat file hasil otomatis.

## Tabel Data

Tabel manual berada di bawah pratinjau dan hasil OCR. Tabel mulai dengan 10 baris × 10 kolom. Enter menyimpan edit dan berpindah ke sel di bawah; pengurutan hanya berjalan setelah kolom dipilih lalu tombol `Urutkan` ditekan. Klik header memilih dan menandai seluruh kolom untuk tombol `Hapus Kolom`. Tombol `Kosongkan` meminta dua konfirmasi dan hanya menghapus isi sel, bukan baris atau kolom. Pengguna dapat menambah/menghapus baris dan kolom, mengimpor `.xlsx`/`.xlsm`/`.csv`, dan mengekspor `.xlsx`/`.csv`. Header kolom dapat diberi validasi teks, angka, atau tanggal ISO (`YYYY-MM-DD`). Nilai yang tidak valid tetap bisa diedit, tetapi ditandai merah agar dapat diperbaiki.

Tabel mendukung Undo/Redo dan salin-tempel rentang sel menggunakan tab-delimited clipboard. Filter berlaku di semua kolom; klik header untuk mengurutkan tampilan dan klik ganda nama header untuk menggantinya. Demi menjaga penggunaan memori, impor dibatasi 50 MB, 10.000 baris data, dan 64 kolom. Ekspor CSV meng-escape nilai yang dapat ditafsirkan spreadsheet sebagai formula.

Draf lokal disimpan otomatis di `~/Library/Application Support/GoScan/table_draft.json` dengan penulisan atomik dan ditawarkan untuk dipulihkan saat aplikasi berikutnya dibuka. Ekspor Excel/CSV tetap perlu dilakukan untuk membuat file yang bisa dibagikan; draf lokal bukan pengganti ekspor.

Gambar dapat dipilih melalui dialog atau di-drag ke tombol/area pratinjau. Setelah OCR selesai, tombol **Asli** dan **Hasil Pembersihan** mengubah tampilan tanpa memodifikasi file sumber. Kontrol `+`, `−`, `Fit`, dan `100%` mengatur zoom; gambar besar dapat digeser dengan scrollbar. Pemisah antara pratinjau dan tabel dapat ditarik untuk mengatur ruang kerja.

## Pengujian

Jalankan pengujian inti dengan `python -m unittest discover -s tests -v`.