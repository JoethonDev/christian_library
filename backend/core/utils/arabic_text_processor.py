"""
High-Performance Arabic OCR Cleaning Pipeline (CPU-Only)

Designed for 100,000+ pages of Coptic Orthodox library content.
Focuses on noise removal, linguistic normalization, and search optimization.

Key Features:
- Structural noise removal (OCR hallucinations, watermarks, metadata)
- Arabic character normalization for search consistency
- CPU-optimized with pre-compiled regex and memory-efficient processing
- PostgreSQL GIN index and trigram matching optimization
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from functools import lru_cache
import time

logger = logging.getLogger(__name__)


@dataclass
class CleaningStats:
    """Statistics for text cleaning operations"""
    original_length: int
    cleaned_length: int
    noise_patterns_removed: int
    characters_normalized: int
    processing_time: float
    
    @property
    def compression_ratio(self) -> float:
        """Calculate how much text was removed as noise"""
        if self.original_length == 0:
            return 0.0
        return (self.original_length - self.cleaned_length) / self.original_length * 100


class ArabicTextCleaner:
    """
    High-performance Arabic text cleaning optimized for OCR content.
    
    Features:
    - Pre-compiled regex patterns for maximum performance
    - Memory-efficient line-by-line processing
    - Comprehensive noise removal for Coptic Orthodox content
    - Arabic linguistic normalization for search consistency
    """
    
    def __init__(self):
        """Initialize cleaner with pre-compiled regex patterns for performance"""
        self.stats = CleaningStats(0, 0, 0, 0, 0.0)
        self._compile_patterns()
        self._build_normalization_maps()
        self._build_liturgical_corrections()
    
    def _compile_patterns(self):
        """Pre-compile all regex patterns to avoid recompilation overhead"""
        
        # === 1. STRUCTURAL NOISE REMOVAL PATTERNS ===
        
        # OCR Hallucination Patterns - Common OCR gibberish
        self.hallucination_patterns = [
            re.compile(r'[0-9]+\.[0-9]+\s*][\u0627-\u06FF0-9\-\[\]/:\u0660-\u0669]+', re.UNICODE),  # 5.01 ]لا635]-10أم00//:مقاط
            re.compile(r'[\[\]{}()<>]+[0-9\u0660-\u0669\-/:\\]+[\[\]{}()<>]*', re.UNICODE),  # [635]-10 patterns
            re.compile(r'[0-9\u0660-\u0669]+[:/\-\\]+[0-9\u0660-\u0669]+[:/\-\\]*', re.UNICODE),  # Time/date patterns
            re.compile(r'[\u0627-\u06FF]*[0-9\u0660-\u0669]{3,}[\u0627-\u06FF]*[0-9\u0660-\u0669]*', re.UNICODE),  # Mixed number-Arabic
            re.compile(r'[^\u0600-\u06FF\u0750-\u077F\s\d\.\,\!\?\:\;\-\(\)]{2,}', re.UNICODE),  # Non-Arabic character strings
        ]
        
        # Watermark & URL Patterns - Common in Coptic content
        self.watermark_patterns = [
            re.compile(r'https?://[^\s\u0627-\u06FF]+', re.IGNORECASE | re.UNICODE),  # URLs
            re.compile(r'www\.[^\s\u0627-\u06FF]+', re.IGNORECASE | re.UNICODE),  # www domains
            re.compile(r'كنيسة\s*الأقباط\s*الأرثوذكس', re.IGNORECASE | re.UNICODE),  # Church watermark
            re.compile(r'coptic[-\s]*treasures?\.com?', re.IGNORECASE | re.UNICODE),  # Website watermarks
            re.compile(r'المكتبة\s*القبطية\s*الأرثوذكسية', re.IGNORECASE | re.UNICODE),  # Library watermarks
            re.compile(r'جميع\s*الحقوق\s*محفوظة', re.IGNORECASE | re.UNICODE),  # Copyright notices
            re.compile(r'copyright\s*©?\s*[0-9]{4}', re.IGNORECASE | re.UNICODE),  # Copyright years
        ]
        
        # Metadata & Source Tag Patterns
        self.metadata_patterns = [
            re.compile(r'<[^>]*>', re.UNICODE),  # HTML/XML tags like <>
            re.compile(r'\[[^\]]*المصدر[^\]]*\]', re.IGNORECASE | re.UNICODE),  # Source references
            re.compile(r'\([^\)]*المرجع[^\)]*\)', re.IGNORECASE | re.UNICODE),  # Reference citations
            re.compile(r'صفحة\s*[0-9\u0660-\u0669]+', re.IGNORECASE | re.UNICODE),  # Page numbers
            re.compile(r'ص\s*[0-9\u0660-\u0669]+', re.IGNORECASE | re.UNICODE),  # Page abbreviations
            re.compile(r'الطبعة\s*[الأول\u0660-\u0669]*', re.IGNORECASE | re.UNICODE),  # Edition info
        ]
        
        # === 2. WHITESPACE & FORMATTING PATTERNS ===
        
        # Excessive whitespace patterns that break token splitting
        self.whitespace_patterns = [
            re.compile(r'\s+', re.UNICODE),  # Multiple spaces/tabs/newlines → single space
            re.compile(r'^[\s\u200B\u200C\u200D\uFEFF]+', re.UNICODE),  # Leading whitespace/invisible chars
            re.compile(r'[\s\u200B\u200C\u200D\uFEFF]+$', re.UNICODE),  # Trailing whitespace/invisible chars
            re.compile(r'[\u200B\u200C\u200D\uFEFF]+', re.UNICODE),  # Zero-width characters
        ]
        
        # === 3. OCR-SPECIFIC ARTIFACTS ===
        
        # Common OCR splitting errors that break liturgical terms and general Arabic prefixes
        # Each item is a tuple of (compiled_regex, replacement_string)
        self.ocr_splitting_rules = [
            # Specific high-value terms (Coptic Orthodox context)
            (re.compile(r'(\u0627\u0644)\s+(\u0623\u0646\u0628\u0627)', re.UNICODE), r'\1\2'),  # ال أنبا → الأنبا
            (re.compile(r'(\u0645\u0637\u0631\u0627)\s+(\u0646\u064A\u0629)', re.UNICODE), r'\1\2'),  # مطرا نية → مطرانية
            (re.compile(r'(\u0627\u0644)\s+(\u0642\u062F\u0627\u0633)', re.UNICODE), r'\1\2'),  # ال قداس → القداس
            (re.compile(r'(\u0639\u064A\u062F)\s+(\u0627\u0644)', re.UNICODE), r'\1\2'),  # عيد ال → عيدال
            
            # General Arabic prefixes (common OCR artifacts where spaces are incorrectly inserted)
            (re.compile(r'\b(\u0627\u0644)\s+([\u0621-\u064A])', re.UNICODE), r'\1\2'),      # الـ (Definite article)
            (re.compile(r'\b(\u0648)\s+([\u0621-\u064A])', re.UNICODE), r'\1\2'),           # و (And)
            (re.compile(r'\b(\u0641)\s+([\u0621-\u064A])', re.UNICODE), r'\1\2'),           # ف (Then/So)
            (re.compile(r'\b(\u0628)\s+([\u0621-\u064A])', re.UNICODE), r'\1\2'),           # ب (By/With)
            (re.compile(r'\b\u0644\s+\u0627\u0644', re.UNICODE), '\u0644\u0644'),           # ل + ال → لل (Special case)
            (re.compile(r'\b(\u0644)\s+([\u0621-\u064A])', re.UNICODE), r'\1\2'),           # ل (For/To)
            (re.compile(r'\b(\u0643)\s+([\u0621-\u064A])', re.UNICODE), r'\1\2'),           # ك (As/Like)
        ]
        
        # === 4. DIACRITICS PATTERN (TASHKEEL) ===
        
        # Arabic diacritics that should be removed for search normalization
        self.diacritics_pattern = re.compile(r'[\u064B-\u0652\u0670\u0640]', re.UNICODE)  # All tashkeel marks + tatweel
    
    def _build_normalization_maps(self):
        """Build character normalization mappings for Arabic search consistency"""
        
        # === ALIF NORMALIZATION ===
        # Convert all Alif variations to plain Alif for consistent search
        self.alif_normalizations = {
            'أ': 'ا',  # Alif with hamza above
            'إ': 'ا',  # Alif with hamza below
            'آ': 'ا',  # Alif with madda
            'ء': '',   # Hamza alone (often OCR artifact)
        }
        
        # === YAA & TEH MARBUTA NORMALIZATION ===
        self.other_normalizations = {
            'ة': 'ه',  # Teh marbuta to Heh
            'ى': 'ي',  # Alif maksura to Yaa
            'ئ': 'ي',  # Yaa with hamza to Yaa
            'ؤ': 'و',  # Waw with hamza to Waw
        }
        
        # Combine all normalizations
        self.char_normalizations = {**self.alif_normalizations, **self.other_normalizations}
        
        # Create reverse lookup for statistics
        self.normalization_chars = set(self.char_normalizations.keys())
    
    def _build_liturgical_corrections(self):
        """Build corrections for common OCR errors in liturgical terms"""
        
        # Common OCR errors in Coptic Orthodox liturgical terminology
        self.liturgical_corrections = {
            # Bishop/Metropolitan titles
            'مطراذية': 'مطرانية',
            'مطراذ': 'مطران',
            'الأذبا': 'الأنبا',
            'أذبا': 'أنبا',
            
            # Feast/Holiday names
            'النبروز': 'النيروز',
            'الغبطاس': 'الغطاس',
            'القبامة': 'القيامة',
            'الصلبب': 'الصليب',
            
            # Liturgical terms
            'قداذ': 'قداس',
            'البخوذ': 'البخور',
            'التسبحة': 'التسبحة',
            'الذكصولوجية': 'الذكصولوجية',
            'العداس': 'القداس',
            'المسبح': 'المسيح',
            'بظريرك': 'بطريرك',
            'أسكف': 'أسقف',
            'إسبسموس': 'إسباسموس',
            
            # Church calendar
            'برمهآت': 'برمهات',
            'بؤونة': 'بؤونه',
            'أمشبر': 'أمشير',
            'كبهك': 'كيهك',
            
            # Common prayer terms
            'الصالة': 'الصلاة',
            'الكنبسة': 'الكنيسة',
            'المذبح': 'المذبح',
            'التناول': 'التناول',
        }
        
        # Pre-compile patterns for liturgical corrections
        self.liturgical_patterns = {}
        for wrong, correct in self.liturgical_corrections.items():
            # Word boundary patterns to avoid partial matches
            pattern = re.compile(r'\b' + re.escape(wrong) + r'\b', re.IGNORECASE | re.UNICODE)
            self.liturgical_patterns[pattern] = correct
    
    def remove_structural_noise(self, text: str) -> Tuple[str, int]:
        """
        Remove OCR hallucinations, watermarks, and metadata tags.
        
        Args:
            text: Raw OCR text
            
        Returns:
            Tuple of (cleaned_text, patterns_removed_count)
        """
        cleaned_text = text
        patterns_removed = 0
        
        # Remove hallucination patterns
        for pattern in self.hallucination_patterns:
            matches = len(pattern.findall(cleaned_text))
            if matches > 0:
                cleaned_text = pattern.sub(' ', cleaned_text)
                patterns_removed += matches
        
        # Remove watermarks and URLs
        for pattern in self.watermark_patterns:
            matches = len(pattern.findall(cleaned_text))
            if matches > 0:
                cleaned_text = pattern.sub(' ', cleaned_text)
                patterns_removed += matches
        
        # Remove metadata tags
        for pattern in self.metadata_patterns:
            matches = len(pattern.findall(cleaned_text))
            if matches > 0:
                cleaned_text = pattern.sub(' ', cleaned_text)
                patterns_removed += matches
        
        # Fix OCR splitting errors in liturgical terms and prefixes
        for pattern, replacement in self.ocr_splitting_rules:
            matches = len(pattern.findall(cleaned_text))
            if matches > 0:
                cleaned_text = pattern.sub(replacement, cleaned_text)
                patterns_removed += matches
        
        return cleaned_text, patterns_removed
    
    def normalize_arabic_characters(self, text: str) -> Tuple[str, int]:
        """
        Normalize Arabic characters for consistent search matching.
        
        Args:
            text: Text to normalize
            
        Returns:
            Tuple of (normalized_text, characters_normalized_count)
        """
        normalized_text = text
        chars_normalized = 0
        
        # Apply character normalizations
        for original, replacement in self.char_normalizations.items():
            count = normalized_text.count(original)
            if count > 0:
                normalized_text = normalized_text.replace(original, replacement)
                chars_normalized += count
        
        return normalized_text, chars_normalized
    
    def remove_diacritics(self, text: str) -> str:
        """
        Remove Arabic diacritics (tashkeel) for search-ready text.
        
        Args:
            text: Text with diacritics
            
        Returns:
            Text without diacritics
        """
        return self.diacritics_pattern.sub('', text)
    
    def apply_liturgical_corrections(self, text: str) -> str:
        """
        Correct common OCR errors in liturgical terminology.
        
        Args:
            text: Text to correct
            
        Returns:
            Text with liturgical corrections applied
        """
        corrected_text = text
        
        for pattern, correction in self.liturgical_patterns.items():
            corrected_text = pattern.sub(correction, corrected_text)
        
        return corrected_text
    
    def normalize_whitespace(self, text: str) -> str:
        """
        Normalize whitespace to fix token splitting issues.
        
        Args:
            text: Text with irregular whitespace
            
        Returns:
            Text with normalized whitespace
        """
        normalized = text
        
        for pattern in self.whitespace_patterns:
            normalized = pattern.sub(' ', normalized)
        
        return normalized.strip()
    
    def clean_text(self, text: str, preserve_original: bool = True) -> Dict[str, any]:
        """
        Complete text cleaning pipeline for Arabic OCR content.
        
        Args:
            text: Raw OCR text to clean
            preserve_original: Whether to keep original text statistics
            
        Returns:
            Dictionary containing:
            - cleaned_text: Fully cleaned text ready for search indexing
            - search_text: Diacritic-free version for search matching
            - original_text: Original text (if preserve_original=True)
            - stats: Cleaning statistics
        """
        start_time = time.time()
        original_length = len(text)
        
        if not text or not text.strip():
            return {
                'cleaned_text': '',
                'search_text': '',
                'original_text': text if preserve_original else None,
                'stats': CleaningStats(0, 0, 0, 0, 0.0)
            }
        
        # Step 1: Remove structural noise
        cleaned, noise_removed = self.remove_structural_noise(text)
        
        # Step 2: Apply liturgical corrections
        cleaned = self.apply_liturgical_corrections(cleaned)
        
        # Step 3: Normalize Arabic characters
        cleaned, chars_normalized = self.normalize_arabic_characters(cleaned)
        
        # Step 4: Normalize whitespace
        cleaned = self.normalize_whitespace(cleaned)
        
        # Step 5: Create search-ready version (without diacritics)
        search_text = self.remove_diacritics(cleaned)
        search_text = self.normalize_whitespace(search_text)
        
        # Calculate statistics
        processing_time = time.time() - start_time
        stats = CleaningStats(
            original_length=original_length,
            cleaned_length=len(cleaned),
            noise_patterns_removed=noise_removed,
            characters_normalized=chars_normalized,
            processing_time=processing_time
        )
        
        return {
            'cleaned_text': cleaned,
            'search_text': search_text,
            'original_text': text if preserve_original else None,
            'stats': stats
        }
    
    def process_text_chunks(self, text: str, chunk_size: int = 10000):
        """
        Memory-efficient processing of large texts using generators.
        
        Args:
            text: Large text to process
            chunk_size: Size of each chunk in characters
            
        Yields:
            Cleaned text chunks with statistics
        """
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            yield self.clean_text(chunk, preserve_original=False)


class ArabicTextProcessor:
    """
    High-performance text processor with multiprocessing support for large-scale operations.
    Designed for processing 100,000+ pages efficiently on CPU-only systems.
    """
    
    def __init__(self, max_workers: Optional[int] = None):
        """
        Initialize processor with multiprocessing capability.
        
        Args:
            max_workers: Number of worker processes (defaults to CPU count)
        """
        self.max_workers = max_workers or cpu_count()
        self.cleaner = ArabicTextCleaner()
        logger.info(f"Initialized Arabic text processor with {self.max_workers} workers")
    
    def process_single_document(self, text: str) -> Dict[str, any]:
        """
        Process a single document with full cleaning pipeline.
        
        Args:
            text: Document text to process
            
        Returns:
            Cleaned document with statistics
        """
        return self.cleaner.clean_text(text)
    
    def process_documents_batch(self, documents: List[str]) -> List[Dict[str, any]]:
        """
        Process multiple documents in parallel using multiprocessing.
        
        Args:
            documents: List of document texts
            
        Returns:
            List of processed documents with statistics
        """
        if len(documents) <= 1:
            return [self.process_single_document(doc) for doc in documents]
        
        logger.info(f"Processing {len(documents)} documents with {self.max_workers} workers")
        
        with Pool(processes=self.max_workers) as pool:
            results = pool.map(self._process_document_worker, documents)
        
        return results
    
    @staticmethod
    def _process_document_worker(text: str) -> Dict[str, any]:
        """
        Worker function for multiprocessing.
        Creates a new cleaner instance for each worker to avoid shared state issues.
        """
        cleaner = ArabicTextCleaner()
        return cleaner.clean_text(text, preserve_original=False)
    
    def get_processing_statistics(self, results: List[Dict[str, any]]) -> Dict[str, any]:
        """
        Aggregate processing statistics from multiple documents.
        
        Args:
            results: List of processing results
            
        Returns:
            Aggregated statistics
        """
        if not results:
            return {}
        
        total_stats = {
            'documents_processed': len(results),
            'total_original_chars': sum(r['stats'].original_length for r in results),
            'total_cleaned_chars': sum(r['stats'].cleaned_length for r in results),
            'total_noise_patterns': sum(r['stats'].noise_patterns_removed for r in results),
            'total_chars_normalized': sum(r['stats'].characters_normalized for r in results),
            'total_processing_time': sum(r['stats'].processing_time for r in results),
            'average_compression_ratio': sum(r['stats'].compression_ratio for r in results) / len(results),
        }
        
        total_stats['processing_rate_chars_per_second'] = (
            total_stats['total_original_chars'] / total_stats['total_processing_time']
            if total_stats['total_processing_time'] > 0 else 0
        )
        
        return total_stats


# === UTILITY FUNCTIONS ===

@lru_cache(maxsize=1000)
def quick_arabic_normalize(text: str) -> str:
    """
    Fast Arabic normalization function with LRU cache for frequently accessed terms.
    Useful for search queries and repeated processing.
    
    Args:
        text: Short text to normalize (recommended < 100 chars for cache efficiency)
        
    Returns:
        Normalized text
    """
    if not text:
        return text
    
    # Quick normalizations without full pipeline
    normalizations = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ء': '',
        'ة': 'ه', 'ى': 'ي', 'ئ': 'ي', 'ؤ': 'و'
    }
    
    result = text
    for original, replacement in normalizations.items():
        result = result.replace(original, replacement)
    
    # Remove diacritics
    result = re.sub(r'[\u064B-\u0652\u0670\u0640]', '', result)
    
    return result


def create_search_ready_text(original_text: str) -> str:
    """
    Quick function to create search-ready text from original content.
    Optimized for database operations and search indexing.
    
    Args:
        original_text: Original Arabic text
        
    Returns:
        Search-optimized text
    """
    processor = ArabicTextProcessor(max_workers=1)
    result = processor.process_single_document(original_text)
    return result['search_text']


# === CONSTANTS FOR DATABASE INTEGRATION ===

# PostgreSQL trigram similarity threshold for fuzzy matching
TRIGRAM_SIMILARITY_THRESHOLD = 0.3

# Minimum text length for processing (avoid processing very short strings)
MIN_TEXT_LENGTH = 10

# Maximum chunk size for memory-efficient processing
DEFAULT_CHUNK_SIZE = 10000