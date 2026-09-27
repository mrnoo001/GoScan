import cv2
import os
import tempfile

class ImageProcessor:
    def __init__(self):
        pass

    def preprocess_image(self, image_path):
        """
        Memproses gambar mentah untuk dioptimalkan sebelum masuk ke mesin OCR.
        Pipeline: Grayscale -> Denoising -> Unsharp Masking -> Otsu's Thresholding
        """
        print(f"[LOG] Memulai pra-pemrosesan gambar: {image_path}")
        
        thresh = self.preprocess_image_array(image_path)

        file_descriptor, temp_path = tempfile.mkstemp(prefix="goscan_", suffix=".png")
        os.close(file_descriptor)
        if not cv2.imwrite(temp_path, thresh):
            os.unlink(temp_path)
            raise OSError(f"Tidak dapat menyimpan gambar hasil pra-pemrosesan: {temp_path}")
        print(f"[LOG] Gambar hasil pra-pemrosesan disimpan di: {temp_path}")

        return temp_path

    def preprocess_image_array(self, image_path):
        """Return the Tesseract-oriented monochrome preview without writing a file."""
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Tidak dapat membaca gambar di path: {image_path}")

        # 2. Konversi ke Grayscale (Hitam Putih)
        # Warna tidak diperlukan untuk membaca teks dan hanya menambah beban komputasi
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 3. Menghilangkan Noise (Denoising)
        # Membersihkan bintik-bintik atau kotoran pada hasil scan
        denoised = cv2.fastNlMeansDenoising(gray, h=30)

        # 4. Mempertajam Gambar (Unsharp Masking)
        # Membuat Gaussian Blur, lalu menguranginya dari gambar asli untuk menonjolkan tepi huruf
        gaussian = cv2.GaussianBlur(denoised, (9, 9), 10.0)
        sharpened = cv2.addWeighted(denoised, 1.5, gaussian, -0.5, 0, denoised)

        # 5. Binarisasi (Otsu's Thresholding)
        # Membuat latar belakang menjadi putih bersih murni dan teks hitam pekat murni
        _, thresh = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    def preprocess_easyocr_image(self, image_path):
        """Enhance a color image gently for handwriting OCR without changing geometry."""
        print(f"[LOG] Memulai peningkatan warna untuk EasyOCR: {image_path}")
        img = cv2.imread(image_path, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Tidak dapat membaca gambar di path: {image_path}")

        denoised = cv2.fastNlMeansDenoisingColored(
            img, None, h=3, hColor=3, templateWindowSize=7, searchWindowSize=21
        )
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        lightness, channel_a, channel_b = cv2.split(lab)
        lightness = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(lightness)
        contrast_enhanced = cv2.cvtColor(
            cv2.merge((lightness, channel_a, channel_b)), cv2.COLOR_LAB2BGR
        )
        blurred = cv2.GaussianBlur(contrast_enhanced, (0, 0), 1.0)
        sharpened = cv2.addWeighted(contrast_enhanced, 1.25, blurred, -0.25, 0)
        return sharpened

    def draw_annotations(self, image_path, filter_results, output_path=None):
        """
        Menggambar garis bawah merah pada teks yang berhasil difilter.
        Hasil dikembalikan di memori kecuali output_path diberikan.
        Parameter `filter_results` diharapkan berupa list dictionary:
        [{'teks': 'kata_ditemukan', 'koordinat': (x, y, w, h)}]
        """
        # Kita menggunakan gambar asli (bukan yang hitam putih) untuk di-highlight
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Tidak dapat membaca gambar untuk anotasi: {image_path}")

        # Draw only the matched character spans within each OCR text box.
        for item in filter_results:
            x, y, w, h = item['koordinat']
            text_length = max(1, len(item.get('teks', '')))
            spans = item.get('highlight_spans', [(0, text_length)])
            thickness = max(1, round(h * 0.1))

            for start, end in spans:
                start = max(0, min(start, text_length))
                end = max(start, min(end, text_length))
                if start == end:
                    continue

                start_x = x + round(w * start / text_length)
                end_x = x + round(w * end / text_length)
                underline_y = y + h + max(1, thickness)
                cv2.line(
                    img,
                    (start_x, underline_y),
                    (max(start_x + 1, end_x), underline_y),
                    (0, 0, 255),
                    thickness,
                )

        if output_path is None:
            return img

        if not cv2.imwrite(output_path, img):
            raise OSError(f"Tidak dapat menyimpan gambar hasil anotasi: {output_path}")
        print(f"[LOG] Gambar beranotasi disimpan di: {output_path}")
        return output_path