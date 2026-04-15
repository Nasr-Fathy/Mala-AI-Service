STATEMENT_STRUCTURING_PROMPT = """
You are a financial data extraction expert. Extract all line items from this {statement_type}.

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
                "table_id": "t1",
                "row_index": 2,
                "page": 5
            }},
            "confidence": 0.95,
            "order": 1
        }}
    ],
    "totals": {{
        "total_assets": {{
            "2024": 15000000,
            "2023": 14000000
        }}
    }},
    "extraction_notes": [],
    "confidence": 0.88
}}

Important rules:
1. Extract ALL line items, not just major categories
2. Preserve the exact hierarchy as shown in the document
3. Amounts should be raw numbers WITHOUT the value scale applied
4. Use null for missing values, not 0
5. parent_index references the index in this array (0-based)
6. order should preserve the document sequence
7. Include confidence score for each line item
8. DO NOT assign category - leave it out entirely

For hierarchy detection:
- Level 0: Main totals (Total Assets, Total Liabilities)
- Level 1: Category totals (Total Current Assets)
- Level 2: Individual items
- Level 3+: Sub-items

Return ONLY valid JSON. Do not include explanations.
"""


def get_statement_prompt(statement_type: str) -> str:
    """Get prompt formatted for a specific statement type."""
    return STATEMENT_STRUCTURING_PROMPT.format(statement_type=statement_type)
