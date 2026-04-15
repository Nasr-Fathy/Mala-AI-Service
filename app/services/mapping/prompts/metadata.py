METADATA_EXTRACTION_PROMPT = """
You are a financial document analyst. Extract metadata from this financial statement document.

Analyze the OCR text and tables provided to identify:

1. **Company Information**
   - Company name (in both English and Arabic if available)
   - Legal form (e.g., LLC, JSC, Limited Company)
   - Commercial registration number (if visible)

2. **Fiscal Period Information**
   - Fiscal year(s) covered in the document
   - Period end date(s)
   - Whether this is annual, semi-annual, or quarterly

3. **Currency and Scale**
   - Currency used (SAR, USD, EUR, etc.)
   - Value scale (units=1, thousands=1000, millions=1000000)
   - Look for phrases like "in thousands", "بالآلاف", "in millions"

4. **Audit Information**
   - Is this audited or unaudited?
   - Auditor name (if present)
   - Audit opinion type (Unqualified, Qualified, etc.)
   - Audit date

Return a JSON object with this exact structure:
{
    "company": {
        "name_en": "Company Name in English",
        "name_ar": "اسم الشركة بالعربية",
        "legal_form": "LLC",
        "registration_number": "1010123456"
    },
    "fiscal_periods": [
        {
            "fiscal_year": 2024,
            "period_type": "ANNUAL",
            "period_number": 1,
            "end_date": "2024-12-31",
            "is_comparative": false
        },
        {
            "fiscal_year": 2023,
            "period_type": "ANNUAL",
            "period_number": 1,
            "end_date": "2023-12-31",
            "is_comparative": true
        }
    ],
    "currency": {
        "code": "SAR",
        "symbol": "ر.س",
        "name_en": "Saudi Riyal",
        "name_ar": "ريال سعودي"
    },
    "value_scale": {
        "multiplier": 1000,
        "description_en": "In thousands",
        "description_ar": "بالآلاف"
    },
    "audit": {
        "is_audited": true,
        "auditor_name": "Ernst & Young",
        "opinion_type": "Unqualified",
        "audit_date": "2025-02-15"
    },
    "document_info": {
        "title_en": "Annual Financial Statements",
        "title_ar": "القوائم المالية السنوية",
        "detected_language": "ar-en"
    },
    "confidence": {
        "overall": 0.85,
        "company_name": 0.95,
        "fiscal_year": 0.90,
        "currency": 0.85,
        "audit_info": 0.75
    }
}

Important:
- fiscal_year should be an integer (e.g., 2024, not "2024")
- period_type should be: ANNUAL, QUARTERLY, SEMI_ANNUAL, MONTHLY
- is_comparative marks periods that are shown for comparison
- If information is not found, use null
- Set confidence scores between 0 and 1 based on clarity of extraction
- For Hijri dates, convert to Gregorian when possible

Return ONLY valid JSON. Do not include explanations.
"""
