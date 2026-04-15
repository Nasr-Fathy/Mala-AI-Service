NOTES_EXTRACTION_PROMPT = """
You are a financial document analyst. Extract all notes and disclosures from this document.

Using the OCR text and tables from the notes section, extract:

1. **Note Structure**
   - Note number (e.g., "1", "2.1", "3a")
   - Title in English and Arabic
   - Brief description/summary

2. **Note Content**
   - Key disclosures and explanations
   - Accounting policies described
   - Significant judgments mentioned

3. **Embedded Tables**
   - Tables within each note
   - Link tables to their note number

4. **Related Line Items**
   - Which line items reference this note
   - The note_number field from line items

Return a JSON object with this exact structure:
{
    "notes": [
        {
            "note_number": "1",
            "title_en": "General Information",
            "title_ar": "معلومات عامة",
            "description": "Brief summary of the note content",
            "content_type": "TEXT",
            "has_table": false,
            "table_ids": [],
            "page": 11,
            "related_line_items": [],
            "key_disclosures": [
                "Company was established in 2010",
                "Registered in Riyadh, Saudi Arabia"
            ]
        }
    ],
    "accounting_policies": [
        {
            "policy_name": "Revenue Recognition",
            "note_reference": "2.2",
            "summary": "Revenue recognized when control transfers"
        }
    ],
    "contingencies": [
        {
            "type": "Legal",
            "note_reference": "25",
            "description": "Pending litigation matters",
            "amount": 500000,
            "likelihood": "Possible"
        }
    ],
    "related_parties": {
        "note_reference": "28",
        "transactions_disclosed": true,
        "parties_identified": ["Parent Company", "Sister Company"]
    },
    "confidence": 0.85
}

Content types:
- TEXT: Primarily narrative content
- TABLE: Contains significant tabular data
- MIXED: Both narrative and tables

Important:
- Extract note numbers exactly as shown (1, 2, 2.1, 3a, etc.)
- Include sub-notes when notes have hierarchical structure
- Link tables to notes using table_ids from OCR data
- Identify key accounting policies for common areas
- Note any contingencies or commitments mentioned

Return ONLY valid JSON. Do not include explanations.
"""
