# backend/

Python 3.12 + FastAPI. **Not scaffolded yet.**

First step in the build window:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi "uvicorn[standard]" pydantic-settings pymongo httpx
```
The planned module layout is in `../docs/architecture.md` §3. Local env goes in the repo-root `.env` (git-ignored).
