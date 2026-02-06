"""
PDF Processing Service for Christian Library

This service handles:
1. Text extraction from PDFs using multiple methods (PyMuPDF, pdfminer, OCR)
2. Arabic text normalization and cleaning
3. Search vector generation for PostgreSQL FTS

Extracted from ContentItem model to improve separation of concerns and testability.
"""

import os
import re
import logging
import subprocess
import tempfile
from typing import Dict, Optional, Tuple

import fitz  # PyMuPDF
import cv2
import numpy as np
from pdfminer.high_level import extract_text
from django.db import connection

logger = logging.getLogger(__name__)


class PdfProcessorService:
    """
    Service for processing PDF files: text extraction, OCR, and normalization.
    Designed for Arabic text with OCR fallback for scanned documents.
    """
    
    def __init__(self, content_item_id: str):
        """
        Initialize PDF processor for a specific content item.
        
        Args:
            content_item_id: UUID of the ContentItem being processed
        """
        self.content_item_id = content_item_id
        self.logger = logging.getLogger(f"{__name__}.{content_item_id}")
    
    def extract_text_from_pdf(self, pdf_path: str, page_count: int = 0) -> str:
        """
        Extract Arabic text from PDF using multiple methods for best results.
        
        Process:
        1. Try PyMuPDF (best for Arabic digital text)
        2. Try pdfminer as alternative
        3. Use OCR (Tesseract) if text-based extraction yields insufficient results
        4. Apply Arabic text cleaning pipeline
        
        Args:
            pdf_path: Absolute path to the PDF file
            page_count: Number of pages in PDF (for heuristic threshold)
            
        Returns:
            Cleaned Arabic text content
        """
        if not os.path.exists(pdf_path):
            self.logger.error(f"PDF file does not exist at path: {pdf_path}")
            return ''
        
        self.logger.info(f"Starting text extraction for PDF: {self.content_item_id} ({page_count} pages)")
        
        # 1. Try PyMuPDF (usually best results for Arabic)
        text_fitz = self._extract_with_pymupdf(pdf_path)
        filtered_fitz = self._filter_arabic_text(text_fitz)
        
        # 2. Try pdfminer
        text_miner = self._extract_with_pdfminer(pdf_path)
        filtered_miner = self._filter_arabic_text(text_miner)
        
        # Pick the best of textual extraction
        if len(filtered_fitz) >= len(filtered_miner):
            best_text = filtered_fitz
            method_used = "PyMuPDF"
        else:
            best_text = filtered_miner
            method_used = "pdfminer"
        
        # Heuristic: if text is too short compared to page count, try OCR
        # Average page is ~2000 chars. We use 300 chars per page as a "low quality" threshold.
        threshold = max(500, page_count * 300)
        
        if len(best_text) < threshold:
            self.logger.info(
                f"Text-based extraction ({method_used}) seems incomplete "
                f"({len(best_text)} characters for {page_count} pages). Attempting OCR."
            )
            text_ocr = self._extract_with_ocr(pdf_path)
            filtered_ocr = self._filter_arabic_text(text_ocr)
            
            if len(filtered_ocr) > len(best_text):
                best_text = filtered_ocr
                method_used = "Tesseract OCR"
                self.logger.info(f"OCR provided better results: {len(best_text)} characters")
        
        # Apply comprehensive Arabic cleaning pipeline for search optimization
        if best_text:
            try:
                cleaned_text = self._apply_arabic_cleaning_pipeline(best_text)
                self.logger.info(
                    f"Applied Arabic cleaning pipeline: {len(best_text)} → {len(cleaned_text)} characters"
                )
                return cleaned_text
            except Exception as e:
                self.logger.error(f"Error in Arabic cleaning pipeline: {e}")
                # Keep filtered text if cleaning fails
                return best_text
        else:
            self.logger.warning(f"No Arabic text could be extracted for PDF {self.content_item_id}")
            return ''
    
    def _extract_with_pymupdf(self, pdf_path: str) -> str:
        """
        Extract text using PyMuPDF (fitz) which often works better than pdfminer for Arabic.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Raw extracted text
        """
        try:
            text_content = []
            with fitz.open(pdf_path) as doc:
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    page_text = page.get_text()
                    if page_text.strip():
                        text_content.append(page_text)
            
            return '\n\n'.join(text_content) if text_content else ''
        except Exception as e:
            self.logger.warning(f"PyMuPDF extraction failed: {str(e)}")
            return ''
    
    def _extract_with_pdfminer(self, pdf_path: str) -> str:
        """
        Extract text using pdfminer library.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Raw extracted text
        """
        try:
            return extract_text(pdf_path)
        except Exception as e:
            self.logger.warning(f"pdfminer extraction failed: {str(e)}")
            return ''
    
    def _extract_with_ocr(self, pdf_path: str) -> str:
        """
        Extract text using OCR (Tesseract) for image-based PDFs.
        Optimized for Arabic text recognition with preprocessing.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            OCR-extracted text
        """
        # Check if Tesseract is available
        if not self._is_tesseract_available():
            self.logger.warning("Tesseract OCR not available, skipping OCR extraction")
            return ''
        
        try:
            text_content = []
            
            # Convert PDF pages to images and perform OCR
            with fitz.open(pdf_path) as doc:
                for page_num in range(len(doc)):
                    page_text = self._ocr_single_page(doc, page_num)
                    if page_text:
                        text_content.append(page_text)
            
            # Join all page texts
            full_text = '\n\n'.join(text_content) if text_content else ''
            
            if full_text:
                self.logger.info(
                    f"OCR extraction completed for PDF {self.content_item_id}: "
                    f"{len(full_text)} characters"
                )
            
            return full_text
            
        except Exception as e:
            self.logger.error(f"OCR extraction failed for PDF {self.content_item_id}: {str(e)}", exc_info=True)
            return ''
    
    def _ocr_single_page(self, doc, page_num: int) -> str:
        """
        Perform OCR on a single PDF page.
        
        Args:
            doc: PyMuPDF document object
            page_num: Page number to process
            
        Returns:
            Extracted text from the page
        """
        try:
            page = doc.load_page(page_num)
            
            # Convert page to image at higher resolution for better OCR
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            # Create temporary files for Tesseract
            temp_dir = tempfile.gettempdir()
            temp_image_path = os.path.join(temp_dir, f"ocr_page_{self.content_item_id}_{page_num}.png")
            temp_text_path = os.path.join(temp_dir, f"ocr_text_{self.content_item_id}_{page_num}")
            
            try:
                # Save image temporarily
                with open(temp_image_path, "wb") as img_file:
                    img_file.write(img_data)
                
                # Apply preprocessing to improve Arabic OCR results
                self._preprocess_image_for_ocr(temp_image_path)
                
                # Run Tesseract OCR with Arabic (Primary mode: PSM 6 for blocks of text)
                cmd = [
                    'tesseract', 
                    temp_image_path, 
                    temp_text_path, 
                    '-l', 'ara',      
                    '--oem', '3',     
                    '--psm', '6',
                    'txt', 'tsv'  # Generate both text and confidence output
                ]
                
                subprocess.run(cmd, check=True, capture_output=True)
                
                # Calculate confidence from TSV
                tsv_file = f"{temp_text_path}.tsv"
                avg_conf = self._calculate_ocr_confidence(tsv_file)
                
                # Read primary OCR output
                output_file = f"{temp_text_path}.txt"
                page_text = ""
                if os.path.exists(output_file):
                    with open(output_file, 'r', encoding='utf-8') as f:
                        page_text = f.read().strip()
                
                # Adaptive Fallback: If primary results are low quality, try PSM 3
                if avg_conf < 70 or len(page_text) < 50:
                    cmd_alt = cmd.copy()
                    cmd_alt[7] = '3'  # Try PSM 3 (Fully automatic page segmentation)
                    subprocess.run(cmd_alt, check=True, capture_output=True)
                    
                    if os.path.exists(output_file):
                        with open(output_file, 'r', encoding='utf-8') as f:
                            page_text_alt = f.read().strip()
                            new_conf = self._calculate_ocr_confidence(tsv_file)
                            # Keep the better result
                            if new_conf > avg_conf or len(page_text_alt) > len(page_text):
                                page_text = page_text_alt
                                avg_conf = new_conf
                                self.logger.info(
                                    f"Page {page_num}: PSM 3 improved results (conf: {avg_conf:.1f}%)"
                                )
                
                return page_text
            
            except Exception as page_error:
                self.logger.warning(f"OCR failed for page {page_num}: {str(page_error)}")
                return ''
            
            finally:
                # Clean up temporary files (.png, .txt, .tsv)
                for ext in ['.png', '.txt', '.tsv']:
                    temp_file = temp_image_path if ext == '.png' else f"{temp_text_path}{ext}"
                    if os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                        except:
                            pass
        
        except Exception as e:
            self.logger.warning(f"Error processing page {page_num}: {str(e)}")
            return ''
    
    def _preprocess_image_for_ocr(self, image_path: str) -> bool:
        """
        Preprocess image to improve OCR accuracy for Arabic text.
        Steps: Grayscale, Denoising, Adaptive Thresholding, Deskewing.
        
        Args:
            image_path: Path to image file to preprocess
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Load image
            img = cv2.imread(image_path)
            if img is None:
                return False

            # 1. Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 2. Denoising (fastNlMeansDenoising provides clean results for scans)
            denoised = cv2.fastNlMeansDenoising(gray, h=10)

            # 3. Adaptive Thresholding (Binarization)
            # Helps with uneven illumination in page scans
            thresh = cv2.adaptiveThreshold(
                denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY, 11, 2
            )

            # 4. Deskewing (Auto-rotation)
            # Detect text orientation and rotate if necessary
            coords = np.column_stack(np.where(thresh > 0))
            if len(coords) > 0:
                angle = cv2.minAreaRect(coords)[-1]
                if angle < -45:
                    angle = -(90 + angle)
                else:
                    angle = -angle
                
                if abs(angle) > 0.5:
                    (h, w) = thresh.shape[:2]
                    center = (w // 2, h // 2)
                    M = cv2.getRotationMatrix2D(center, angle, 1.0)
                    thresh = cv2.warpAffine(
                        thresh, M, (w, h), 
                        flags=cv2.INTER_CUBIC, 
                        borderMode=cv2.BORDER_REPLICATE
                    )

            # Save processed image back to original path
            cv2.imwrite(image_path, thresh)
            return True
        except Exception as e:
            self.logger.error(f"Image preprocessing failed for {image_path}: {e}")
            return False
    
    def _calculate_ocr_confidence(self, tsv_path: str) -> float:
        """
        Calculate average confidence score from Tesseract TSV output.
        
        Args:
            tsv_path: Path to TSV file with OCR results
            
        Returns:
            Average confidence score (0-100)
        """
        try:
            if not os.path.exists(tsv_path):
                return 0
            
            conf_scores = []
            with open(tsv_path, 'r', encoding='utf-8') as f:
                # TSV header: level, page_num, block_num, par_num, line_num, word_num, 
                # left, top, width, height, conf, text
                header = f.readline()
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) >= 11:
                        try:
                            conf = float(parts[10])
                            # Tesseract uses -1 for non-word blocks
                            if conf > 0:
                                conf_scores.append(conf)
                        except (ValueError, IndexError):
                            continue
            
            if not conf_scores:
                return 0
            
            return sum(conf_scores) / len(conf_scores)
        except Exception as e:
            self.logger.error(f"Error calculating OCR confidence: {e}")
            return 0
    
    def _is_tesseract_available(self) -> bool:
        """
        Check if Tesseract OCR is installed and available.
        
        Returns:
            True if Tesseract is available, False otherwise
        """
        try:
            result = subprocess.run(
                ['tesseract', '--version'], 
                capture_output=True, 
                text=True, 
                check=True
            )
            return 'tesseract' in result.stdout.lower()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    def _filter_arabic_text(self, text: str) -> str:
        """
        Filter and keep only Arabic characters and whitespace.
        Removes English characters and other scripts.
        
        This is a basic filter applied before the comprehensive cleaning pipeline.
        
        Args:
            text: Raw text to filter
            
        Returns:
            Filtered text with Arabic characters only
        """
        if not text:
            return ""
        
        # Arabic character ranges + whitespace + digits + basic punctuation
        # Ranges: 0600-06FF (Arabic), 0750-077F (Arabic Supplement), 
        # 08A0-08FF (Arabic Extended-A), FB50-FDFF (Arabic Presentation Forms-A),
        # FE70-FEFF (Arabic Presentation Forms-B)
        arabic_pattern = re.compile(
            r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\s0-9\.\,\!\?\(\)\[\]\-\_\:\/]+'
        )
        
        matches = arabic_pattern.findall(text)
        filtered = "".join(matches)
        
        # Clean up: replace multiple spaces/newlines with a single space
        filtered = re.sub(r'\s+', ' ', filtered)
        return filtered.strip()
    
    def _apply_arabic_cleaning_pipeline(self, text: str) -> str:
        """
        Apply comprehensive Arabic text cleaning pipeline for search optimization.
        Uses the high-performance Arabic text processor.
        
        Args:
            text: Text to clean
            
        Returns:
            Search-ready cleaned text
        """
        try:
            from core.utils.arabic_text_processor import create_search_ready_text
            return create_search_ready_text(text)
        except ImportError:
            self.logger.warning("Arabic text processor not available, using basic filtering")
            return self._filter_arabic_text(text)
        except Exception as e:
            self.logger.error(f"Error in Arabic cleaning pipeline: {e}")
            return text  # Fallback to original text


def create_pdf_processor(content_item_id: str) -> PdfProcessorService:
    """
    Factory function to create a PDF processor instance.
    
    Args:
        content_item_id: UUID of the ContentItem
        
    Returns:
        PdfProcessorService instance
    """
    return PdfProcessorService(content_item_id)
