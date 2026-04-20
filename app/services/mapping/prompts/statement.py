STATEMENT_STRUCTURING_PROMPT = """
You are a financial data extraction expert. Extract all line items from this {statement_type}.

Use the provided `statement_title` to disambiguate when multiple tables share a page.

Using ONLY the tables provided (which are already filtered to this statement), extract:

1. **Line Items**
   - Name in English and Arabic (if available)
   - Numerical values for each period column
   - Hierarchy level (indentation)
   - Parent-child relationships
   - Whether it's a total/subtotal row
   - Note reference number (if any)

2. **Source Tracking**
   - Which table the value came from (table_id)
   - Which row in that table (row_index, 0-based)
   - Original page number

3. **Totals and Subtotals**
   - Identify rows that are totals or subtotals
   - These typically have bold formatting indicators or "Total" in the name

DO NOT assign categories. Leave category empty or omit it entirely.
Categories will be assigned by the backend system.

Return a JSON object with this exact structure:
{{
    "statement_type": "BALANCE_SHEET",
    "line_items": [
        {{
            "name_en": "Cash and cash equivalents",
            "name_ar": "النقد وما يعادله",
            "values": [
                {{
                    "fiscal_year": 2024,
                    "amount": 1500000,
                    "column_index": 0
                }},
                {{
                    "fiscal_year": 2023,
                    "amount": 1200000,
                    "column_index": 1
                }}
            ],
            "level": 1,
            "parent_index": null,
            "is_total": false,
            "is_subtotal": false,
            "note_number": "5",
            "source": {{
                "table_id": "p1_t1",
                "row_index": 2,
                "page": 5
            }},
            "confidence": 0.95,
            "order": 1
        }}
    ],
    "extraction_notes": [],
    "confidence": 0.88
}}

Important rules:
1. Extract ALL line items, not just major categories
2. Preserve the exact hierarchy as shown in the document
3. Amounts should be raw numbers at the same scale shown in the table cells. Do NOT multiply or divide by the provided `value_scale`.
4. Use null for missing values, not 0
5. parent_index references the index in this array (0-based)
6. order should preserve the document sequence
7. Include confidence score for each line item
8. DO NOT assign category - leave it out entirely
9. CRITICAL: The 'column_index' in the output MUST exactly match the 'index' provided in the input 'columns' mapping for that specific fiscal year. Do not default to 0.
10. `name_en` must always be a non-empty string.
11. If only Arabic text exists in the source, translate it into English for `name_en`.
12. Never return `name_en` as null.
13. CRITICAL: Do NOT wrap the output in a "statements" array or any other parent key. The response must be a single JSON object starting exactly with the "statement_type" key.
14. CRITICAL: Do NOT add any extra undocumented fields (such as "statement_info") to the output JSON. Stick strictly to the provided example structure.
15. CRITICAL: The 'table_id' in the 'source' object MUST exactly match the input table_id (e.g., "p1_t1"). Do NOT modify it or add/remove prefixes.

For hierarchy detection:
- Level 0: Main totals (Total Assets, Total Liabilities)
- Level 1: Category totals (Total Current Assets)
- Level 2: Individual items
- Level 3+: Sub-items

CRITICAL RULES FOR COLUMNS AND FISCAL YEARS (FALLBACK MECHANISM):
- If the input 'columns' array is provided and not empty, the 'column_index' MUST exactly match the provided index for that fiscal year.
- IF the 'columns' array is EMPTY [], OR if the statement is 'CHANGES_IN_EQUITY' where columns represent financial components (e.g., Share Capital, Retained Earnings) instead of distinct years:
  1. Deduce the primary 'fiscal_year' from the page text, statement title, or row text (e.g., 2024, 2025). If absolutely no year can be deduced, default to the year mentioned in the column headers or use the current reporting year. 
  2. The 'fiscal_year' MUST be an integer between 1900 and 2100.
  3. Assign this same 'fiscal_year' to ALL numerical values extracted for that line item.
  4. Assign 'column_index' sequentially (0, 1, 2, 3...) to represent the order of the numerical data columns exactly as they appear in the source table from right-to-left or left-to-right.
  5. NEVER leave 'fiscal_year' or 'column_index' as null. Always apply this fallback logic to satisfy the required schema.
Return ONLY valid JSON. Do not include markdown formatting like ```json or explanations.
"""

def get_statement_prompt(statement_type: str) -> str:
    """Get prompt formatted for a specific statement type."""
    return STATEMENT_STRUCTURING_PROMPT.format(statement_type=statement_type)
