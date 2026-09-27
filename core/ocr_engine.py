import os

import pytesseract
from pytesseract import Output

TESSERACT_TIMEOUT_SECONDS = 60


class OCREngine:
    def __init__(self):
        self.easyocr_reader = None

    @staticmethod
    def _configure_ssl_certificates():
        import certifi

        ca_bundle = certifi.where()
        for variable in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
            configured_bundle = os.environ.get(variable)
            if not configured_bundle or not os.path.isfile(configured_bundle):
                os.environ[variable] = ca_bundle

    def process_tesseract(self, image_path):
        """Membaca dokumen ketik menggunakan Tesseract OCR"""
        print("[LOG] Menjalankan Tesseract OCR (Teks Ketik)...")
        results = []
        ocr_data = pytesseract.image_to_data(
            image_path,
            lang='ind+eng',
            config='--oem 3 --psm 6 -c preserve_interword_spaces=1',
            output_type=Output.DICT,
            timeout=TESSERACT_TIMEOUT_SECONDS,
        )

        for i, raw_text in enumerate(ocr_data['text']):
            text = raw_text.strip()
            confidence = float(ocr_data['conf'][i])
            if text and confidence >= 0:
                results.append({
                    'teks': text,
                    'koordinat': (
                        ocr_data['left'][i],
                        ocr_data['top'][i],
                        ocr_data['width'][i],
                        ocr_data['height'][i],
                    ),
                    'baris': (
                        ocr_data['block_num'][i],
                        ocr_data['par_num'][i],
                        ocr_data['line_num'][i],
                    ),
                })
        return results

    def process_easyocr(self, image_path):
        """Membaca dokumen tulis tangan menggunakan EasyOCR"""
        print("[LOG] Menjalankan EasyOCR (Tulis Tangan)...")
        if self.easyocr_reader is None:
            self._configure_ssl_certificates()
            import easyocr

            self.easyocr_reader = easyocr.Reader(['id', 'en'], gpu=False)

        results = []
        ocr_data = self.easyocr_reader.readtext(image_path)
        for bbox, text, confidence in ocr_data:
            if text.strip() and confidence > 0.3:
                x_coords = [point[0] for point in bbox]
                y_coords = [point[1] for point in bbox]
                x = int(min(x_coords))
                y = int(min(y_coords))
                results.append({
                    'teks': text,
                    'koordinat': (
                        x,
                        y,
                        int(max(x_coords) - x),
                        int(max(y_coords) - y),
                    ),
                })
        return results

    def filter_text(self, ocr_results, keywords_str):
        """
        Mencari kata kunci di dalam hasil OCR.
        Menerima input string seperti "alamat, kontak, jalan"
        """
        if not keywords_str.strip():
            return [] 

        keywords = [
            keyword.strip().casefold()
            for keyword in keywords_str.split(',')
            if keyword.strip()
        ]
        filtered_results = []

        for item in ocr_results:
            normalized_text = item['teks'].casefold()
            spans = []
            for keyword in keywords:
                start = 0
                while (match_start := normalized_text.find(keyword, start)) >= 0:
                    spans.append((match_start, match_start + len(keyword)))
                    start = match_start + len(keyword)

            if spans:
                matched_item = dict(item)
                matched_item['highlight_spans'] = sorted(set(spans))
                filtered_results.append(matched_item)

        return filtered_results

    def reconstruct_text(self, ocr_results):
        """
        Merekonstruksi teks ke dalam bentuk paragraf dengan memanfaatkan
        koordinat vertikal (Y) dan mereplikasi spasi horizontal (X).
        """
        if not ocr_results:
            return ""

        total_chars = sum(len(item['teks']) for item in ocr_results if item['teks'].strip())
        total_width = sum(item['koordinat'][2] for item in ocr_results if item['teks'].strip())
        avg_char_width = (total_width / total_chars) if total_chars > 0 else 10
        avg_char_width = max(avg_char_width, 5)

        if all('baris' in item for item in ocr_results):
            lines = {}
            for item in ocr_results:
                lines.setdefault(tuple(item['baris']), []).append(item)

            reconstructed_lines = []
            previous_paragraph = None
            for line_key in sorted(lines):
                paragraph_key = line_key[:2]
                if reconstructed_lines and paragraph_key != previous_paragraph:
                    reconstructed_lines.append("")
                
                words = sorted(lines[line_key], key=lambda item: item['koordinat'][0])
                line_text = ""
                last_x_end = 0
                
                for i, item in enumerate(words):
                    x, y, w, h = item['koordinat']
                    if i == 0:
                        indent_spaces = max(0, int(x / avg_char_width))
                        indent_spaces = min(indent_spaces, 40)
                        line_text += (" " * indent_spaces) + item['teks']
                    else:
                        gap = x - last_x_end
                        num_spaces = max(1, int(gap / avg_char_width)) if gap > 0 else 1
                        num_spaces = min(num_spaces, 50)
                        line_text += (" " * num_spaces) + item['teks']
                    last_x_end = x + w
                    
                reconstructed_lines.append(line_text.rstrip())
                previous_paragraph = paragraph_key

            return "\n".join(reconstructed_lines).strip()

        sorted_results = sorted(
            ocr_results,
            key=lambda item: (
                item['koordinat'][1] + item['koordinat'][3] / 2,
                item['koordinat'][0],
            ),
        )
        lines = []
        for item in sorted_results:
            x, y, width, height = item['koordinat']
            center_y = y + height / 2
            matching_line = None
            matching_distance = None

            for line in lines:
                line_height = line['height']
                overlap = min(y + height, line['bottom']) - max(y, line['top'])
                overlap_ratio = overlap / max(1, min(height, line_height))
                if overlap_ratio >= 0.5:
                    distance = abs(center_y - line['center_y'])
                    if matching_distance is None or distance < matching_distance:
                        matching_line = line
                        matching_distance = distance

            if matching_line is None:
                lines.append({
                    'items': [item],
                    'top': y,
                    'bottom': y + height,
                    'height': height,
                    'center_y': center_y,
                })
            else:
                matching_line['items'].append(item)
                matching_line['top'] = min(matching_line['top'], y)
                matching_line['bottom'] = max(matching_line['bottom'], y + height)
                matching_line['height'] = (
                    matching_line['bottom'] - matching_line['top']
                )
                matching_line['center_y'] = (
                    matching_line['top'] + matching_line['bottom']
                ) / 2

        lines.sort(key=lambda line: line['top'])
        
        reconstructed_lines = []
        for line in lines:
            words = sorted(line['items'], key=lambda item: item['koordinat'][0])
            line_text = ""
            last_x_end = 0
            
            for i, item in enumerate(words):
                x, y, w, h = item['koordinat']
                if i == 0:
                    indent_spaces = max(0, int(x / avg_char_width))
                    indent_spaces = min(indent_spaces, 40)
                    line_text += (" " * indent_spaces) + item['teks']
                else:
                    gap = x - last_x_end
                    num_spaces = max(1, int(gap / avg_char_width)) if gap > 0 else 1
                    num_spaces = min(num_spaces, 50)
                    line_text += (" " * num_spaces) + item['teks']
                last_x_end = x + w
                
            reconstructed_lines.append(line_text.rstrip())
            
        return "\n".join(reconstructed_lines).strip()

    def create_searchable_pdf(self, image_path, output_pdf_path):
        """
        Membuat Searchable PDF murni menggunakan engine Tesseract.
        Tesseract secara otomatis menanamkan teks transparan persis di atas gambar asli.
        """
        print(f"[LOG] Membangun Searchable PDF untuk: {image_path}")
        pdf_bytes = pytesseract.image_to_pdf_or_hocr(
            image_path,
            lang='ind+eng',
            extension='pdf',
            config='--oem 3 --psm 6'
        )
        with open(output_pdf_path, 'wb') as output_file:
            output_file.write(pdf_bytes)