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
   - Use original_page_number from the OCR data when available. Otherwise use page_number/page.

3. **Column Structure**
   - Identify fiscal periods ONLY when the table columns themselves represent time periods (e.g. 2025, 2024, Q1, Q2, etc.).
   - Typically this applies to statements such as Balance Sheet, Income Statement, and Cash Flow Statement.
   - Do NOT infer fiscal periods from non-period columns such as "البيان", "رأس المال", "إحتياطي نظامي", "ارباح مبقاه", "المجموع".
   - If a statement (especially CHANGES_IN_EQUITY) is presented as separate full tables for different years rather than year-columns inside one table, then set "columns" to an empty array [] for that statement.
   - Never force a year-to-column mapping unless the year is explicitly represented as a column header.

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
- Use original_page_number values from the tables/pages data when available
- Include all table_ids that appear within each statement's pages
- If a statement spans multiple pages, capture the full range
- If a page contains multiple tables for the same statement, include all of them
- For CHANGES_IN_EQUITY, be especially careful: fiscal years may be split by separate tables instead of columns
- If fiscal periods are not represented as actual columns, return "columns": []
- List any segmentation issues or ambiguities in the "issues" array

Return ONLY valid JSON. Do not include explanations.
"""