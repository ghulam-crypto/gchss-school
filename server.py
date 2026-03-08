#!/usr/bin/env python3
"""
GCHSS School MCP Server — All 6 Sheets
Railway Deployment Ready
"""

import json
import os
import asyncio
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

    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.middleware.cors import CORSMiddleware
    from mcp.server.sse import SseServerTransport

    sse_transport = SseServerTransport("/messages/")

    # Track initialization state
    _initialized = False

    async def handle_sse(request: Request):
        global _initialized
        # FIX: wait for MCP server to fully initialize before first connection
        if not _initialized:
            await asyncio.sleep(3)
            _initialized = True
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], streams[1],
                mcp._mcp_server.create_initialization_options()
            )

    # ── Health check ──────────────────────────────────────────────────────────
    async def health(request: Request):
        return JSONResponse({
            "status": "ok",
            "service": "gchss-school MCP",
            "port": port,
            "sheets": list(SHEETS.keys())
        })

    # ── NEW: REST API endpoints for the live dashboard ────────────────────────

    async def api_students(request: Request):
        """Returns all students as JSON — used by the live marks dashboard."""
        try:
            records = sheet_to_records(get_sheet("students"))
            return JSONResponse(records)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def api_teachers(request: Request):
        """Returns all teachers as JSON — used by the live marks dashboard."""
        try:
            records = sheet_to_records(get_sheet("teachers"))
            return JSONResponse(records)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def api_stats(request: Request):
        """Returns summary stats as JSON — used by the live marks dashboard."""
        try:
            students = sheet_to_records(get_sheet("students"))
            subjects = [
                "English","Mathematics","Social Studies","Sindhi","Islamiat",
                "G.Science","Urdu","Arabic","Physics","Biology","Chemistry","Computer"
            ]
            # Build class-level stats
            classes = {}
            for s in students:
                cls = s.get("Class", "").strip()
                if not cls:
                    continue
                if cls not in classes:
                    classes[cls] = {"total": 0, "hasResult": 0, "hasMarks": 0, "subjects": {sub: 0 for sub in subjects}}
                classes[cls]["total"] += 1
                if s.get("Result", "").strip():
                    classes[cls]["hasResult"] += 1
                has_any_mark = any(
                    str(s.get(sub, "")).strip() not in ("", "0")
                    for sub in subjects
                )
                if has_any_mark:
                    classes[cls]["hasMarks"] += 1
                for sub in subjects:
                    val = str(s.get(sub, "")).strip()
                    if val and val != "0":
                        classes[cls]["subjects"][sub] += 1

            total    = len(students)
            has_marks = sum(1 for cls in classes.values() for _ in range(cls["hasMarks"]))
            has_result = sum(cls["hasResult"] for cls in classes.values())

            return JSONResponse({
                "total":     total,
                "hasMarks":  sum(c["hasMarks"]  for c in classes.values()),
                "hasResult": sum(c["hasResult"] for c in classes.values()),
                "pending":   total - sum(c["hasMarks"] for c in classes.values()),
                "classes":   classes,
                "generatedAt": "live"
            })
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Starlette app with all routes ─────────────────────────────────────────
    starlette_app = Starlette(routes=[
        Route("/",              endpoint=health),           # Railway health check
        Route("/health",        endpoint=health),           # Extra health endpoint
        Route("/sse",           endpoint=handle_sse),       # MCP SSE endpoint
        Mount("/messages",      app=sse_transport.handle_post_message),
        # ── NEW REST API routes ──
        Route("/api/students",  endpoint=api_students),     # Live student data
        Route("/api/teachers",  endpoint=api_teachers),     # Live teacher data
        Route("/api/stats",     endpoint=api_stats),        # Live summary stats
    ])

    starlette_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    print(f"✅ GCHSS MCP Server starting on port {port}")
    print(f"📊 REST API endpoints: /api/students | /api/teachers | /api/stats")
    uvicorn.run(
        starlette_app,
        host="0.0.0.0",
        port=port,
        forwarded_allow_ips="*",
        proxy_headers=True,
    )
