"""
NyayaBot — Hand-crafted static legal knowledge summaries.
"""
from src.models import ActCategory

STATIC_KNOWLEDGE: list[dict] = [
    {
        "title": "RTI Act 2005 — Section 6: Request for Information",
        "text": """Under Section 6 of the Right to Information Act 2005, any citizen of India can request information from a Public Authority.

How to file an RTI:
1. Write a request in English, Hindi, or the official language of the area to the Public Information Officer (PIO).
2. Pay the prescribed fee: Rs. 10 for Central Government departments (by cash, DD, banker's cheque, or postal order). No fee for BPL cardholders.
3. Submit to the PIO of the concerned department, or file online at https://rtionline.gov.in.
4. The PIO must respond within 30 days. If information concerns life or liberty, the response must come within 48 hours.
5. If unsatisfied, file First Appeal within 30 days of receiving the response (or of deadline expiry) to the First Appellate Authority.
6. If still unsatisfied, file Second Appeal within 90 days to the Central/State Information Commission.

Key rights: You can ask for any information held by public authorities including government files, records, memos, emails, contracts, and reports. RTI cannot be used for personal information of others that has no public interest.""",
        "category": ActCategory.TRANSPARENCY_LAW,
        "url": "https://rti.india.gov.in",
        "section": "Section 6 - Procedure for filing RTI",
    },
    {
        "title": "Consumer Protection Act 2019 — Filing a Complaint",
        "text": """Under the Consumer Protection Act 2019, a consumer can file a complaint against unfair trade practices, defective goods, or deficient services.

Jurisdiction based on claim amount:
- District Consumer Commission: Claims up to Rs. 1 crore
- State Consumer Commission: Claims from Rs. 1 crore to Rs. 10 crore
- National Consumer Commission: Claims above Rs. 10 crore

How to file:
1. Online: Visit https://edaakhil.nic.in (e-Daakhil portal) — file from home without a lawyer.
2. Offline: Submit written complaint to the nearest District Consumer Forum.
3. No court fee needed for claims up to Rs. 5 lakh.
4. Court fee for claims above Rs. 5 lakh: Rs. 200 per lakh (subject to revisions).

Documents needed: Purchase bill, warranty card, correspondence with seller, photos of defect.
Time limit: File within 2 years from the date of cause of action.
Key right: Consumer can also file complaint against e-commerce companies, misleading advertisements, and spurious goods.""",
        "category": ActCategory.CONSUMER_RIGHTS,
        "url": "https://consumerhelpline.gov.in",
        "section": "Filing Consumer Complaint Procedure",
    },
    {
        "title": "EPF — PF Withdrawal Procedure",
        "text": """Employees' Provident Fund (EPF) withdrawal rules under EPF & MP Act 1952:

Types of withdrawal:
1. Full withdrawal: Allowed only after 2 months of unemployment (after leaving job). Apply using Form 19 (PF) + Form 10C (pension).
2. Partial withdrawal (Advance): Allowed for specific purposes:
   - Medical emergency: Up to 6 months' wages
   - Marriage/Education (self, sibling, children): Up to 50% of employee's share after 7 years of service
   - House purchase/construction: Up to 36 months' wages after 5 years service
   - Home loan repayment: Up to 90% of PF balance after 10 years
   - Unemployment for 1 month: Up to 75% of PF balance

Online process (UAN-based):
1. Activate UAN at https://unifiedportal-mem.epfindia.gov.in
2. Link Aadhaar + bank account (IFSC) to UAN
3. Go to "Online Services" → "Claim (Form-31, 19 & 10C)"
4. Select withdrawal type, enter details, submit
5. Amount credited to bank account within 5-10 working days

Tax: PF withdrawal before 5 years of continuous service is taxable. After 5 years, it is tax-free.""",
        "category": ActCategory.LABOUR_LAW,
        "url": "https://www.epfindia.gov.in",
        "section": "EPF Withdrawal — PF and Pension",
    },
    {
        "title": "Labour Law — Minimum Wages and Payment of Wages",
        "text": """Under the Code on Wages 2019 (which combines 4 old labour laws):

Minimum Wages:
- The Central Government sets a Floor Wage below which no state can set minimum wages.
- Minimum wages are notified by state governments for different scheduled employments and skill categories (unskilled, semi-skilled, skilled, highly skilled).
- Employers must pay not less than the applicable minimum wage.

Payment of Wages Rules:
- Wages must be paid before the 7th day of the following month (for establishments with <1000 workers: before 10th day).
- Wages must be paid in cash or via bank transfer/cheque (not kind, except with government permission).
- Deductions from wages are limited: PF, ESI, fines (max 3% of wages), advances, income tax.
- Unauthorized deductions are a criminal offense.

Grievance: File complaint with the Labour Commissioner or Inspector under the Code on Wages for non-payment or underpayment of wages. Penalty for employer: fine up to Rs. 50,000 for first offense, up to Rs. 3 lakh for repeat offense.""",
        "category": ActCategory.LABOUR_LAW,
        "url": "https://www.indiacode.nic.in",
        "section": "Code on Wages 2019 — Minimum Wages and Payment",
    },
    {
        "title": "Property Registration — How to Register Property in India",
        "text": """Property registration is governed by the Registration Act 1908 and Transfer of Property Act 1882.

Mandatory registration: Any immovable property transaction above Rs. 100 in value MUST be registered. Unregistered sale deeds are not admissible as evidence of title transfer.

Steps to register property:
1. Prepare sale deed: Get a sale deed drafted by an advocate or licensed document writer. Include: buyer/seller details, property description, sale consideration, encumbrance status.
2. Pay stamp duty: Based on the state government's rate (typically 4-8% of property value). Pay online via the state registration portal or SBI/designated bank.
3. Book appointment: At the Sub-Registrar Office (SRO) of the area where the property is located. Many states allow online booking.
4. Present documents: Both buyer and seller must appear with original documents + 2 witnesses. Aadhaar and PAN mandatory.
5. Biometric verification: Aadhaar-based biometric verification at the SRO.
6. Registration: After verification, document is registered and a certified copy issued.

Documents needed: Sale deed (2 copies), encumbrance certificate, previous ownership documents, NOC from society (if apartment), payment challan for stamp duty.

Online search: Check encumbrances and ownership history via state revenue department portals (e.g., kaveri2.karnataka.gov.in for Karnataka, igrsup.gov.in for UP).""",
        "category": ActCategory.CIVIL_LAW,
        "url": "https://www.indiacode.nic.in",
        "section": "Property Registration — Registration Act 1908",
    },
    {
        "title": "Free Legal Aid — NALSA and Legal Services Authorities",
        "text": """Under the Legal Services Authorities Act 1987, free legal aid is a constitutional right (Article 39A).

Who is entitled to free legal aid:
- Women and children (regardless of income)
- Members of SC/ST communities
- Persons with disabilities
- Victims of trafficking, disasters, industrial disasters
- Persons in custody (under-trials)
- Persons whose annual income is below Rs. 3 lakh (for Supreme Court aid) or as specified by respective State Legal Services Authority

How to get free legal aid:
1. Visit the nearest District Legal Services Authority (DLSA) office (located at District Courts).
2. Apply online at https://nalsa.gov.in
3. Call Toll Free: 15100 (National Legal Services Authority helpline)
4. DLSA will assign a panel advocate free of cost.

Lok Adalat: Alternative dispute resolution for pre-litigation and pending court cases. Awards are binding on both parties and cannot be appealed. No court fee. Covers: Motor accident claims, bank recovery, matrimonial cases (not divorce), labour disputes, electricity disputes.
Schedule: Held every 2nd Saturday of each month at District Courts.""",
        "category": ActCategory.SOCIAL_WELFARE,
        "url": "https://nalsa.gov.in",
        "section": "Free Legal Aid — NALSA and Lok Adalat",
    },
    {
        "title": "Aadhaar — Services and Grievance Redressal",
        "text": """Aadhaar is governed by the Aadhaar (Targeted Delivery of Financial and Other Subsidies, Benefits and Services) Act 2016.

Key Aadhaar services:
1. Update Aadhaar: Visit https://myaadhaar.uidai.gov.in or nearest Aadhaar Seva Kendra. Update name, address, DOB, mobile, email.
2. Download e-Aadhaar: Free from UIDAI website. Password is first 4 letters of name (capital) + birth year.
3. Lock/Unlock Biometrics: Lock your biometrics to prevent misuse at https://uidai.gov.in or mAadhaar app.
4. Virtual ID (VID): 16-digit number to share instead of Aadhaar number, protecting privacy.

Grievance:
- Call UIDAI helpline: 1947 (toll-free)
- Email: help@uidai.gov.in
- File complaint at: https://uidai.gov.in/en/contact-support/grievance.html
- Aadhaar is NOT mandatory for: domestic air travel, school admission, bank account opening (alternative KYC accepted).

Supreme Court ruling (2018): Aadhaar is valid for government subsidies and benefits but cannot be mandated by private entities for services.""",
        "category": ActCategory.GENERAL,
        "url": "https://uidai.gov.in",
        "section": "Aadhaar Services and Rights",
    },
    {
        "title": "FIR Filing — Rights and Procedure",
        "text": """Filing a First Information Report (FIR) under the Code of Criminal Procedure (CrPC) / Bharatiya Nagarik Suraksha Sanhita (BNSS) 2023:

Key rights:
- Any person can file an FIR about a cognizable offense at any police station (not just the nearest one to the crime — Supreme Court ruling in Sakiri Vasu v. State of UP).
- Police CANNOT refuse to register an FIR for cognizable offenses (Section 154 CrPC / Section 173 BNSS). Refusal is a criminal offense for the police officer.
- You are entitled to a free copy of the FIR immediately after registration.

How to file FIR:
1. Go to the nearest police station.
2. Give oral or written complaint to the Station House Officer (SHO).
3. Complaint is written, read back to you, and signed by you.
4. You receive a copy with FIR number.

If police refuses to register FIR:
1. Write a complaint to the Superintendent of Police (SP) by registered post.
2. File a complaint directly to the Executive Magistrate.
3. File a private complaint to the Judicial Magistrate under Section 156(3) CrPC.
4. File a Zero FIR (registered at any station, transferred to correct jurisdiction later).

Online FIR: Many state police portals allow online FIR for certain offenses (e.g., cybercrime at https://cybercrime.gov.in).""",
        "category": ActCategory.CRIMINAL_LAW,
        "url": "https://www.mha.gov.in",
        "section": "FIR Filing — CrPC Section 154 / BNSS Section 173",
    },
    {
        "title": "Startup Registration — DPIIT Recognition and Benefits",
        "text": """Startup India — Registration and benefits under DPIIT (Department for Promotion of Industry and Internal Trade):

Eligibility for Startup Recognition:
- Company incorporated/registered in India: Private Limited, LLP, or Partnership Firm
- Up to 10 years from date of incorporation
- Annual turnover not exceeded Rs. 100 crore in any previous year
- Working towards innovation, development of products/services/processes

Benefits of DPIIT recognition:
1. Tax exemption: 3 years of income tax exemption (out of 10 years) under Section 80-IAC
2. Angel tax exemption: Share issuances to investors at premium not taxed (Section 56(2)(viib))
3. IPR fast-tracking: 80% rebate on patent filing fees; dedicated startup cell
4. Self-certification: Self-certify compliance with 9 labour and 3 environmental laws for 3-5 years
5. Govt procurement: Exempted from prior experience/turnover criteria for government tenders
6. Easy wind-up: Fast-track insolvency (90 days under IBC)

How to register:
1. Visit https://www.startupindia.gov.in
2. Register with your entity details + Incorporation Certificate
3. Upload business pitch/innovation document
4. DPIIT recognition typically granted within 2 working days (auto-approval system)""",
        "category": ActCategory.CORPORATE_LAW,
        "url": "https://www.startupindia.gov.in",
        "section": "Startup India — DPIIT Recognition Benefits",
    },
    {
        "title": "RERA — Real Estate Buyer Rights",
        "text": """Real Estate (Regulation and Development) Act 2016 — Buyer Rights:

Key rights under RERA:
1. Disclosure: Builder must register project with state RERA authority. All project details (approvals, layout, timeline, escrow account) must be publicly available on the RERA website.
2. Escrow: 70% of project funds must be kept in a dedicated escrow account, usable only for that project's construction and land cost.
3. Carpet area: Builder must quote price on carpet area basis (not super built-up area).
4. Possession date: Builder must honor the promised possession date. Delay = interest compensation to buyer.
5. Structural defect liability: Builder responsible for structural defects for 5 years after possession.
6. Title: Builder must ensure clear title; any defect = compensation to buyer.

How to file RERA complaint:
1. Visit your state's RERA portal (e.g., rera.mp.gov.in, maharerait.mahaonline.gov.in, up-rera.in).
2. Register as complainant.
3. File complaint against builder with project details and grievance.
4. RERA adjudicating officer resolves within 60 days.
5. Appeal to RERA Appellate Tribunal within 60 days of order.
6. Appeal to High Court within 60 days of Appellate Tribunal order.

Penalty on builder: Up to 10% of project cost for first offense; up to 3 years imprisonment for repeat offense.""",
        "category": ActCategory.REAL_ESTATE,
        "url": "https://rera.karnataka.gov.in",
        "section": "RERA 2016 — Buyer Rights and Complaint Procedure",
    },
]
