// UI and answer languages. `font` is the Noto family loaded on demand for the
// script; `speech` is the BCP-47 tag handed to the browser's speech recogniser.
export const LANGUAGES = [
  { code: "en", name: "English", english: "English", speech: "en-IN", font: null },
  { code: "hi", name: "हिन्दी", english: "Hindi", speech: "hi-IN", font: "Noto Sans Devanagari" },
  { code: "bn", name: "বাংলা", english: "Bengali", speech: "bn-IN", font: "Noto Sans Bengali" },
  { code: "pa", name: "ਪੰਜਾਬੀ", english: "Punjabi", speech: "pa-IN", font: "Noto Sans Gurmukhi" },
  { code: "gu", name: "ગુજરાતી", english: "Gujarati", speech: "gu-IN", font: "Noto Sans Gujarati" },
  { code: "mr", name: "मराठी", english: "Marathi", speech: "mr-IN", font: "Noto Sans Devanagari" },
  { code: "ta", name: "தமிழ்", english: "Tamil", speech: "ta-IN", font: "Noto Sans Tamil" },
  { code: "te", name: "తెలుగు", english: "Telugu", speech: "te-IN", font: "Noto Sans Telugu" },
  { code: "kn", name: "ಕನ್ನಡ", english: "Kannada", speech: "kn-IN", font: "Noto Sans Kannada" },
  { code: "ml", name: "മലയാളം", english: "Malayalam", speech: "ml-IN", font: "Noto Sans Malayalam" },
  { code: "or", name: "ଓଡ଼ିଆ", english: "Odia", speech: "or-IN", font: "Noto Sans Oriya" },
];

export const LANGUAGE_CODES = LANGUAGES.map((l) => l.code);

export function languageInfo(code) {
  return LANGUAGES.find((l) => l.code === code) || LANGUAGES[0];
}
