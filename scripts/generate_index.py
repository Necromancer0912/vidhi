"""Build the library index the frontend shows (frontend/src/data/statutes.json)
from the extracted text files. Run after ingesting new documents, then
`cd frontend && npm run i18n` to translate the new titles."""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED_TEXT_DIR = str(ROOT / "data/extracted_text")
OUTPUT_FILE = str(ROOT / "frontend/src/data/statutes.json")

def clean_title(filename):
    # Remove extension
    name = filename
    if name.endswith(".pdf.txt"):
        name = name[:-8]
    elif name.endswith(".txt"):
        name = name[:-4]
        
    # Replace underscores with spaces
    name = name.replace("_", " ")
    
    # Clean up formatting: e.g. "Aadhaar Act 2016" -> "Aadhaar Act, 2016"
    name = re.sub(r'(Act|Rules|Regulations|Sanhita|Adhiniyam|Code|Order|Ordinance|Guidelines)\s+(\d{4})', r'\1, \2', name)
    
    # Capitalize acronyms and tidy up spacing
    name = name.strip()
    return name

def classify_type(filename):
    fn_lower = filename.lower()
    
    # Landmark cases
    cases_keywords = ["_vs_", "_vs", "_kaur_", "_bano_", "_kumar_", "_shine_", "_bhashini_", "_sawhney_", "_morcha_", "_kumari_", "_mehta_", "_singh_"]
    if any(k in fn_lower for k in cases_keywords):
        return "Landmark Case"
        
    # Acts / Sanhitas / Codes
    act_keywords = ["_act_", "_act", "_adhiniyam_", "_adhiniyam", "_sanhita_", "_sanhita", "_code_", "_code", "_ordinance_"]
    if any(k in fn_lower for k in act_keywords):
        return "Act / Code"
        
    # Rules / Regulations
    rule_keywords = ["_rules_", "_rules", "_regulations_", "_regulations", "_regulation_"]
    if any(k in fn_lower for k in rule_keywords):
        return "Rule / Regulation"
        
    # Guidelines / Policies / Orders / Plans
    guideline_keywords = ["_guidelines_", "_guidelines", "_guideline_", "_policy_", "_policy", "_plan_", "_sop_", "_order_", "_manual_", "_advisory_"]
    if any(k in fn_lower for k in guideline_keywords):
        return "Guideline / Policy"
        
    # Default fallback
    return "Other Document"

def main():
    if not os.path.exists(EXTRACTED_TEXT_DIR):
        print(f"Directory {EXTRACTED_TEXT_DIR} does not exist.")
        return

    files = sorted(os.listdir(EXTRACTED_TEXT_DIR))
    statutes = []
    
    for f in files:
        if not f.endswith(".txt"):
            continue
        title = clean_title(f)
        category = classify_type(f)
        statutes.append({
            "filename": f,
            "title": title,
            "category": category
        })
        
    # Write to target path
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        json.dump(statutes, out, indent=2, ensure_ascii=False)
        
    print(f"Successfully indexed {len(statutes)} statutes and wrote to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
