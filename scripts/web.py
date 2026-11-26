"""Local web UI and JSON API for the search index.

Usage:
  pip install fastapi uvicorn
  python scripts/web.py index/search.db            # then open http://localhost:8000

Endpoints:
  GET /                         the search page
  GET /api/search?q=...&state=OH&level=county&n=10
  GET /api/dataset/{id}         full details (same as the MCP get_dataset tool)
"""
import json, os, sys
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DB_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'index', 'search.db')
sys.argv = [sys.argv[0], DB_PATH]  # mcp_server reads the db path from argv
import mcp_server as M  # reuse the same search and detail logic as the agent tools
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title='Civic Data Explorer', version='0.1')
PAGE = open(os.path.join(HERE, '..', 'web', 'index.html'), encoding='utf-8').read()


@app.get('/', response_class=HTMLResponse)
def page():
    return PAGE


@app.get('/api/search')
def api_search(q: str, state: str | None = None, level: str | None = None,
               year_from: int | None = None, year_to: int | None = None, n: int = Query(10, ge=1, le=30)):
    return JSONResponse(json.loads(M.search_datasets(q, state, level, year_from, year_to, n)))


@app.get('/api/dataset/{id:path}')
def api_dataset(id: str):
    return JSONResponse(json.loads(M.get_dataset(id)))


if __name__ == '__main__':
    import uvicorn
    print('Loading models (first search may take a few seconds)...', flush=True)
    M.model()
    print('Open http://localhost:8000', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8000, log_level='warning')
