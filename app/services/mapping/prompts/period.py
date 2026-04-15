PERIOD_DETECTION_PROMPT = """
You are a financial document analyst. Identify and segment the financial statements in this document.

Using the OCR text and tables provided, identify:

1. **Statement Types Present**
   - Balance Sheet (Statement of Financial Position / قائمة المركز المالي)
   - Income Statement (Statement of Profit or Loss / قائمة الدخل)
   - Cash Flow Statement (Statement of Cash Flows / قائمة التدفقات النقدية)
   - Statement of Changes in Equity (قائمة التغيرات في حقوق الملكية)
   - Notes to Financial Statements (الإيضاحات)

2. **Page Ranges**
   - Start and end page for each statement
   - Use original_page_number from the OCR data

3. **Column Structure**
   - Which fiscal periods are in which columns
   - Typically: current year, previous year (comparative)

4. **Table Associations**
   - Which table_ids belong to which statement

Return a JSON object with this exact structure:
{
    "statements": [
        {
            "statement_type": "BALANCE_SHEET",
            "title_en": "Statement of Financial Position",
            "title_ar": "قائمة المركز المالي",
            "start_page": 5,
            "end_page": 6,
            "table_ids": ["t1", "t2"],
            "columns": [
                {
                    "index": 0,
                    "fiscal_year": 2024,
                    "period_type": "ANNUAL",
                    "header_text": "31 December 2024"
                },
                {
                    "index": 1,
                    "fiscal_year": 2023,
                    "period_type": "ANNUAL",
                    "header_text": "31 December 2023"
                }
            ]
        }
    ],
    "notes_section": {
        "start_page": 11,
        "end_page": 45,
        "table_ids": ["t7", "t8", "t9"]
    },
    "segmentation_confidence": 0.90,
    "issues": []
}

Statement types must be one of:
- BALANCE_SHEET
- INCOME_STATEMENT
- CASH_FLOW
- CHANGES_IN_EQUITY
- COMPREHENSIVE_INCOME
- NOTES

Important:
- Use original_page_number values from the tables/pages data
- Include all table_ids that appear within each statement's pages
- If a statement spans multiple pages, capture the full range
- List any segmentation issues or ambiguities in the "issues" array

Return ONLY valid JSON. Do not include explanations.
"""
