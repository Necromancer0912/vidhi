"""
NyayaBot — Document loaders for PDF and HTML sources.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import shutil
import pdfplumber
import requests
from bs4 import BeautifulSoup

logging.getLogger("pdfminer").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


class DocumentLoader:
    """Loads raw text from PDF or HTML files/URLs."""

    @staticmethod
    def load_pdf(path: str | Path) -> str:
        """Extract text from a PDF file using pypdf/pdfplumber, falling back to OCR if scanned."""
        pdf_path = Path(path)
        cache_dir = Path("data/extracted_text")
        cache_file = cache_dir / f"{pdf_path.name}.txt"

        # 1. Check if cached text file already exists
        if cache_file.exists():
            logger.info(f"Loading cached text for {pdf_path.name}...")
            return cache_file.read_text(encoding="utf-8", errors="ignore")

        text_parts = []
        
        # 1. Try pypdf (extremely fast, very low memory footprint)
        try:
            import pypdf
            with open(pdf_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                total_pages = len(reader.pages)
                logger.info(f"Extracting text from {pdf_path.name} using pypdf ({total_pages} pages)...")
                for page_num, page in enumerate(reader.pages):
                    if (page_num + 1) % 100 == 0 or page_num == 0 or page_num == total_pages - 1:
                        logger.info(f"  → Page {page_num + 1}/{total_pages} extracted...")
                    text = page.extract_text()
                    if text:
                        text_parts.append(text.strip())
        except Exception as e:
            logger.warning(f"pypdf failed to read {pdf_path}: {e}. Falling back to pdfplumber...")
            text_parts = []

        # 2. Fallback to pdfplumber (better layout extraction, but uses far more memory)
        if not text_parts:
            try:
                logger.info(f"Extracting text from {pdf_path.name} using pdfplumber...")
                with pdfplumber.open(str(pdf_path)) as pdf:
                    total_pages = len(pdf.pages)
                    for page_num, page in enumerate(pdf.pages):
                        if (page_num + 1) % 100 == 0 or page_num == 0 or page_num == total_pages - 1:
                            logger.info(f"  [pdfplumber] → Page {page_num + 1}/{total_pages} extracted...")
                        text = page.extract_text()
                        if text:
                            text_parts.append(text.strip())
            except Exception as e:
                logger.warning(f"pdfplumber failed to read {pdf_path}: {e}")

        full_text = "\n\n".join(text_parts).strip()
        
        # Free up reader references and trigger garbage collection immediately
        del text_parts
        import gc
        gc.collect()
        
        # Check if text is empty or too short (scanned PDF / image-only)
        if len(full_text) < 100 or full_text.count("\n") < 2:
            logger.info(f"PDF {pdf_path} appears to be scanned or image-only. Attempting OCR...")
            ocr_text = DocumentLoader.ocr_pdf(pdf_path)
            if ocr_text:
                full_text = ocr_text

        # 2. Cache the extracted text to disk for future runs
        if full_text.strip():
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(full_text, encoding="utf-8")
            logger.info(f"Cached extracted text to {cache_file}")

        return full_text

    @staticmethod
    def ocr_pdf(path: str | Path) -> str:
        """Convert scanned PDF pages to images and run Tesseract OCR on them."""
        # 1. Check system dependencies
        tesseract_exists = shutil.which("tesseract") is not None
        pdftoppm_exists = shutil.which("pdftoppm") is not None
        
        if not tesseract_exists or not pdftoppm_exists:
            missing = []
            if not tesseract_exists:
                missing.append("tesseract")
            if not pdftoppm_exists:
                missing.append("poppler (pdftoppm)")
            
            logger.error(
                f"Cannot run OCR on {path}. Missing system dependencies: {', '.join(missing)}.\n"
                "Please install them using:\n"
                "  macOS: brew install tesseract poppler\n"
                "  Linux: sudo apt-get install tesseract-ocr poppler-utils"
            )
            return ""

        # 2. Check Python dependencies
        try:
            from pdf2image import convert_from_path
            import pytesseract
        except ImportError:
            logger.error(
                f"Cannot run OCR on {path}. Python dependencies 'pytesseract' and 'pdf2image' are not installed.\n"
                "Please run:\n"
                "  uv pip install pytesseract pdf2image"
            )
            return ""

        try:
            logger.info(f"Starting OCR for {path} (this might take a few moments)...")
            images = convert_from_path(str(path))
            ocr_pages = []
            for i, img in enumerate(images):
                logger.info(f"  → Running OCR on page {i+1}/{len(images)}...")
                page_text = pytesseract.image_to_string(img)
                if page_text:
                    ocr_pages.append(page_text.strip())
            
            logger.info(f"✓ OCR completed for {path}")
            return "\n\n".join(ocr_pages)
        except Exception as e:
            logger.error(f"OCR failed for {path}: {e}")
            return ""

    @staticmethod
    def load_html_url(url: str, timeout: int = 30) -> str:
        """Fetch and parse HTML from a URL, returning clean text."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; NyayaBot/1.0; +https://nyayabot.in)"
            )
        }
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return DocumentLoader.parse_html(resp.text)
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return ""

    @staticmethod
    def parse_html(html: str) -> str:
        """Extract readable text from HTML, removing nav/footer/script noise."""
        soup = BeautifulSoup(html, "lxml")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "iframe", "noscript"]):
            tag.decompose()

        # Prefer main content areas
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", {"class": ["content", "main-content", "body-content"]})
            or soup.find("body")
        )

        if main:
            text = main.get_text(separator="\n")
        else:
            text = soup.get_text(separator="\n")

        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines()]
        non_empty = [line for line in lines if len(line) > 20]  # skip tiny lines
        return "\n".join(non_empty)

    @staticmethod
    def load_html_file(path: str | Path) -> str:
        """Load and parse a saved HTML file."""
        with open(str(path), encoding="utf-8", errors="ignore") as f:
            return DocumentLoader.parse_html(f.read())

    @classmethod
    def load(cls, source: str | Path) -> str:
        """Auto-detect source type and load text."""
        source_str = str(source)
        if source_str.startswith("http://") or source_str.startswith("https://"):
            return cls.load_html_url(source_str)
        path = Path(source_str)
        if path.suffix.lower() == ".pdf":
            return cls.load_pdf(path)
        if path.suffix.lower() in (".html", ".htm"):
            return cls.load_html_file(path)
        # Plain text fallback
        return path.read_text(encoding="utf-8", errors="ignore")
