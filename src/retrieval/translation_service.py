import logging
from typing import Optional
from src.config import settings

logger = logging.getLogger(__name__)

# IndicTrans2 Language Codes mapping
INDIC_LANG_CODES = {
    "hi": "hin_Deva",   # Hindi
    "bn": "ben_Beng",   # Bengali
    "ta": "tam_Taml",   # Tamil
    "te": "tel_Telu",   # Telugu
    "mr": "mar_Deva",   # Marathi
    "gu": "guj_Gujr",   # Gujarati
    "kn": "kan_Knda",   # Kannada
    "ml": "mal_Mlym",   # Malayalam
    "pa": "pan_Guru",   # Punjabi
    "or": "ory_Orya",   # Odia
    "as": "asm_Beng",   # Assamese
    "ur": "urd_Arab",   # Urdu
}

class TranslationService:
    _instance = None
    _translator = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.indic_available = False
        self.device = "cpu"
        
        import os
        disable_indictrans = os.environ.get("DISABLE_INDICTRANS2", "false").lower() in ("true", "1", "yes")
        if not disable_indictrans:
            try:
                from src.config import settings
                if getattr(settings, "disable_indictrans2", False):
                    disable_indictrans = True
            except Exception:
                pass
                
        if disable_indictrans:
            logger.info("IndicTrans2 is disabled via settings/environment. Using LLM fallback.")
            return

        try:
            from IndicTransToolkit import IndicProcessor
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            import torch
            
            self.IndicProcessor = IndicProcessor
            self.AutoModelForSeq2SeqLM = AutoModelForSeq2SeqLM
            self.AutoTokenizer = AutoTokenizer
            self.torch = torch
            self.indic_available = True
            logger.info("IndicTrans2 dependencies imported successfully.")
        except Exception as e:
            logger.info(f"IndicTrans2 not available (using LLM fallback): {e}")

    def _init_models(self):
        if not self.indic_available or self._translator is not None:
            return
        
        try:
            device = "cuda" if self.torch.cuda.is_available() else "cpu"
            logger.info(f"Loading IndicTrans2 models on {device.upper()}...")
            self.device = device
            
            # Indic -> English model
            self.i2e_tokenizer = self.AutoTokenizer.from_pretrained(
                "ai4bharat/indictrans2-indic-en-dist-200M", trust_remote_code=True
            )
            self.i2e_model = self.AutoModelForSeq2SeqLM.from_pretrained(
                "ai4bharat/indictrans2-indic-en-dist-200M", trust_remote_code=True
            ).to(self.device)
            
            # English -> Indic model
            self.e2i_tokenizer = self.AutoTokenizer.from_pretrained(
                "ai4bharat/indictrans2-en-indic-dist-200M", trust_remote_code=True
            )
            self.e2i_model = self.AutoModelForSeq2SeqLM.from_pretrained(
                "ai4bharat/indictrans2-en-indic-dist-200M", trust_remote_code=True
            ).to(self.device)
            
            self.ip = self.IndicProcessor(inference=True)
            self._translator = True
            logger.info(f"IndicTrans2 models loaded successfully on {device.upper()}.")
        except Exception as e:
            logger.warning(f"Failed to load IndicTrans2 models: {e}. Falling back to LLM.")
            self.indic_available = False

    async def translate_to_english(self, text: str, src_lang: str) -> str:
        """Translate Indic text to English."""
        if not text or not text.strip():
            return text
            
        src_lang = src_lang.lower().strip()
        if src_lang == "en" or src_lang not in INDIC_LANG_CODES:
            return text

        # Try IndicTrans2 first
        if self.indic_available:
            try:
                self._init_models()
                if self._translator:
                    lang_code = INDIC_LANG_CODES[src_lang]
                    batch = self.ip.preprocess_batch([text], src_lang=lang_code, tgt_lang="eng_Latn")
                    inputs = self.i2e_tokenizer(batch, return_tensors="pt", padding=True)
                    inputs = {k: v.to(self.device) for k, v in inputs.items()}
                    with self.torch.no_grad():
                        outputs = self.i2e_model.generate(**inputs, num_beams=4, max_length=512)
                    decoded = self.i2e_tokenizer.batch_decode(outputs, skip_special_tokens=True)
                    result = self.ip.postprocess_batch(decoded, lang="eng_Latn")[0]
                    logger.debug(f"IndicTrans2 (to_english): '{text}' -> '{result}'")
                    return result
            except Exception as e:
                logger.warning(f"IndicTrans2 translation failed: {e}. Falling back to LLM.")

        # LLM fallback
        from src.graph.nodes import get_llm
        llm = get_llm()
        from src.agents.generator import translate_to_english as llm_translate
        return await llm_translate(text, llm)

    async def translate_from_english(self, text: str, tgt_lang: str) -> str:
        """Translate English text to target Indic language."""
        if not text or not text.strip():
            return text
            
        tgt_lang = tgt_lang.lower().strip()
        if tgt_lang == "en" or tgt_lang not in INDIC_LANG_CODES:
            return text

        # Try IndicTrans2 first
        if self.indic_available:
            try:
                self._init_models()
                if self._translator:
                    lang_code = INDIC_LANG_CODES[tgt_lang]
                    batch = self.ip.preprocess_batch([text], src_lang="eng_Latn", tgt_lang=lang_code)
                    inputs = self.e2i_tokenizer(batch, return_tensors="pt", padding=True)
                    inputs = {k: v.to(self.device) for k, v in inputs.items()}
                    with self.torch.no_grad():
                        outputs = self.e2i_model.generate(**inputs, num_beams=4, max_length=512)
                    decoded = self.e2i_tokenizer.batch_decode(outputs, skip_special_tokens=True)
                    result = self.ip.postprocess_batch(decoded, lang=lang_code)[0]
                    logger.debug(f"IndicTrans2 (from_english): '{text}' -> '{result}'")
                    return result
            except Exception as e:
                logger.warning(f"IndicTrans2 translation failed: {e}. Falling back to LLM.")

        # LLM fallback
        lang_names = {
            "hi": "Hindi (Devanagari script)",
            "bn": "Bengali (Bangla script)",
            "ta": "Tamil (Tamil script)",
            "te": "Telugu (Telugu script)",
            "mr": "Marathi (Devanagari script)",
            "gu": "Gujarati (Gujarati script)",
            "kn": "Kannada (Kannada script)",
            "ml": "Malayalam (Malayalam script)",
            "pa": "Punjabi (Gurmukhi script)",
            "or": "Odia (Odia script)",
            "as": "Assamese (Assamese script)",
            "ur": "Urdu (Arabic script)",
        }
        lang_name = lang_names.get(tgt_lang, tgt_lang)
        prompt = (
            f"Translate this legal text into {lang_name}. "
            "Keep all Act names, Section numbers, and citation tags in English/Roman script. "
            "Maintain all markdown formatting. "
            "Return ONLY the translated text, no preamble or commentary.\n\n"
            f"Text to translate:\n{text}"
        )
        from src.graph.nodes import get_llm
        llm = get_llm()
        try:
            response = await llm.ainvoke(prompt)
            translated = response.content if hasattr(response, "content") else str(response)
            return translated.strip()
        except Exception as e:
            logger.error(f"Semantic translation to {lang_name} failed: {e}")
            return text
