"""
NyayaBot — Semantic text chunker for Indian legal documents.
Uses RecursiveCharacterTextSplitter with legal-aware separators.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.models import ActCategory, Chunk, ChunkMetadata


# Legal-specific separators (ordered by preference — largest structural break first)
LEGAL_SEPARATORS = [
    "\n\nCHAPTER",
    "\n\nPART",
    "\n\nSCHEDULE",
    "\n\nSection",
    "\n\nArticle",
    "\n\n",
    "\nSection",
    "\nArticle",
    "\nProvided",   # Indian law "Provided that..." clauses
    "\n\n(",        # numbered provisions
    "\n",
    ". ",
    " ",
]


class LegalChunker:
    """
    Chunks legal documents with:
    - 512-token chunk size (measured in chars ≈ 2048 chars, conservative)
    - 64-token overlap (≈256 chars)
    - Legal-aware separators
    - Metadata injection per chunk
    """

    # Approximate: 1 token ≈ 4 chars for English legal text
    CHARS_PER_TOKEN = 4

    def __init__(
        self,
        chunk_tokens: int = 512,
        overlap_tokens: int = 64,
    ):
        chunk_size = chunk_tokens * self.CHARS_PER_TOKEN
        chunk_overlap = overlap_tokens * self.CHARS_PER_TOKEN

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=LEGAL_SEPARATORS,
            keep_separator=True,
            is_separator_regex=False,
        )

    def chunk_document(
        self,
        text: str,
        source_url: str,
        document_title: str,
        act_category: ActCategory = ActCategory.GENERAL,
        section: str = "",
        page_number: int = 0,
        last_updated: str = "",
        language: str = "en",
    ) -> list[Chunk]:
        """Split a document text into chunks with rich metadata."""
        if not text or not text.strip():
            return []

        # Pre-clean text
        text = self._clean_text(text)

        raw_chunks = self.splitter.split_text(text)

        chunks = []
        for i, chunk_text in enumerate(raw_chunks):
            if len(chunk_text.strip()) < 100:  # skip trivially small chunks
                continue

            # Try to detect section from chunk content if not provided
            detected_section = section or self._detect_section(chunk_text)

            metadata = ChunkMetadata(
                chunk_id=str(uuid.uuid4()),
                source_url=source_url,
                document_title=document_title,
                section=detected_section,
                act_category=act_category,
                last_updated=last_updated,
                language=language,
                page_number=page_number,
                chunk_index=i,
            )

            chunks.append(Chunk(
                id=metadata.chunk_id,
                text=chunk_text.strip(),
                metadata=metadata,
            ))

        return chunks

    def _clean_text(self, text: str) -> str:
        """Remove common PDF/HTML extraction artifacts and garbage characters."""
        # 1. Replace soft hyphens, zero-width spaces, and replacement characters ()
        text = text.replace('\xad', '').replace('\u200b', '').replace('\ufffd', ' ')
        
        # 2. Normalize smart quotes and dashes to standard ASCII
        text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
        text = text.replace('–', '-').replace('—', '-') # en-dash and em-dash
        
        # 3. Join words split across lines with a hyphen (e.g., "consti-\ntution" -> "constitution")
        text = re.sub(r'(\w+)-\n\s*(\w+)', r'\1\2', text)
        
        # 4. Remove page numbers (common pattern in Indian legal PDFs: standalone digit on a line)
        text = re.sub(r"\n\s*\d+\s*\n", "\n", text)
        
        # 5. Clean up duplicate symbols (like long form fields or dot lines: ....... -> ...)
        text = re.sub(r'\.{4,}', '...', text)
        text = re.sub(r'-{4,}', '---', text)
        text = re.sub(r'_{4,}', '___', text)
        
        # 6. Clean control characters but preserve Unicode (Devanagari, Bengali, Tamil, etc.)
        text = "".join(ch if (ch.isprintable() or ch in "\n\r\t") else " " for ch in text)
        
        # 7. Remove trailing whitespaces on individual lines
        text = re.sub(r'[ \t]+\n', '\n', text)
        text = re.sub(r'\n[ \t]+', '\n', text)
        
        # 8. Remove excessive whitespace and linebreaks
        text = re.sub(r'\n{4,}', '\n\n\n', text)
        text = re.sub(r' {3,}', ' ', text)
        
        return text.strip()

    def _detect_section(self, text: str) -> str:
        """Try to detect the section/article heading from chunk text."""
        patterns = [
            r"^(Section\s+\d+[A-Z]?\.?\s*[^\n]{0,80})",
            r"^(Article\s+\d+[A-Z]?\.?\s*[^\n]{0,80})",
            r"^(\d+\.\s+[A-Z][^\n]{0,80})",          # "6. Right to information"
            r"^(CHAPTER\s+[IVX\d]+\.?\s*[^\n]{0,80})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text.strip(), re.MULTILINE)
            if match:
                return match.group(1).strip()[:200]
        return ""
