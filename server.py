#!/usr/bin/env python3
"""
GCHSS School MCP Server — All 6 Sheets
Railway Deployment Ready
"""

import json
import os
import uvicorn
from mcp.server.fastmcp import FastMCP
import gspread
from google.oauth2.service_account import Credentials

# ── CONFIG ───────────────────────────────────────────────────────────────────
SPREADSHEET_ID = "1xq8qkIGeRSQJ1uk-pUXEbYdBvg-tmZzKzAv84TDTT0k"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEETS = {
    "students":    "Students",
    "teachers":    "Teachers",
    "attendance":  "Attendance",
    "assignments": "Assignments",
    "news":        "News",
    "settings":    "Settings",
    "gallery":     "Gallery",
}

# ── FASTMCP APP ───────────────────────────────────────────────────────────────
mcp = FastMCP("gchss-school")

# ── GOOGLE SHEETS HELPERS ─────────────────────────────────────────────────────
def get_spreadsheet():
    creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def get_sheet(sheet_key: str):
    spreadsheet = get_spreadsheet()
    sheet_name  = SHEETS.get(sheet_key.lower())
    if not sheet_name:
        raise ValueError(f"Unknown sheet '{sheet_key}'. Valid: {', '.join(SHEETS.keys())}")
    return spreadsheet.worksheet(sheet_name)

def sheet_to_records(sheet):
    data = sheet.get_all_values()
    if not data:
        return []
    headers = data[0]
    return [
        {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        for row in data[1:]
        if any(cell.strip() for cell in row)
    ]

# ── TOOLS ─────────────────────────────────────────────────────────────────────
@mcp.tool()
def list_sheets() -> str:
    """List all sheet tab names in the spreadsheet"""
    names = [ws.title for ws in get_spreadsheet().worksheets()]
    return json.dumps({"sheets": names})

@mcp.tool()
def get_sheet_data(sheet: str) -> str:
    """Get all records from a sheet: students, teachers, attendance, assignments, news, settings"""
    records = sheet_to_records(get_sheet(sheet))
    return json.dumps(records, indent=2)

@mcp.tool()
def search_records(sheet: str, query: str) -> str:
    """Search any sheet for records matching a query"""
    records = sheet_to_records(get_sheet(sheet))
    q       = query.lower()
    results = [r for r in records if any(q in str(v).lower() for v in r.values())]
    return json.dumps(results if results else f"No records found matching '{query}'.")

@mcp.tool()
def add_record(sheet: str, data: dict) -> str:
    """Add a new row to any sheet. data should be column name to value pairs."""
    s          = get_sheet(sheet)
    all_values = s.get_all_values()
    headers    = all_values[0] if all_values else []
    new_row    = [data.get(h, "") for h in headers]
    s.append_row(new_row)
    return f"Record added to {sheet} successfully!"

@mcp.tool()
def add_bulk_records(sheet: str, records: list) -> str:
    """Add multiple rows to any sheet at once. records should be a list of dicts with column name to value pairs."""
    s          = get_sheet(sheet)
    all_values = s.get_all_values()
    headers    = all_values[0] if all_values else []
    rows       = [[record.get(h, "") for h in headers] for record in records]
    s.append_rows(rows)
    return f"{len(rows)} records added to {sheet} successfully!"

@mcp.tool()
def update_record(sheet: str, key_column: str, key_value: str, field: str, value: str) -> str:
    """Update a field in a row. Find row by key_column=key_value, then update field to value."""
    s          = get_sheet(sheet)
    all_values = s.get_all_values()
    headers    = all_values[0]
    if key_column not in headers:
        return f"Column '{key_column}' not found. Available: {', '.join(headers)}"
    if field not in headers:
        return f"Column '{field}' not found. Available: {', '.join(headers)}"
    ki = headers.index(key_column)
    fi = headers.index(field) + 1
    for i, row in enumerate(all_values[1:], start=2):
        if len(row) > ki and str(row[ki]).strip() == key_value.strip():
            s.update_cell(i, fi, value)
            return f"Updated '{field}' = '{value}' where {key_column} = '{key_value}'"
    return f"No row found where {key_column} = '{key_value}'"

@mcp.tool()
def get_statistics(class_name: str = "") -> str:
    """Get pass/fail/absent stats. Optionally filter by class_name e.g. VI-A"""
    records = sheet_to_records(get_sheet("students"))
    if class_name:
        records = [r for r in records if str(r.get("Class","")).upper() == class_name.upper()]
    stats = {}
    for r in records:
        res = str(r.get("Result", "Unknown"))
        stats[res] = stats.get(res, 0) + 1
    return json.dumps({
        "scope":     f"Class {class_name}" if class_name else "All Classes",
        "total":     len(records),
        "breakdown": stats
    }, indent=2)

# ── RUN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app = mcp.sse_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        forwarded_allow_ips="*",
        proxy_headers=True
    )
