"""`python -m app` (from api/, venv active): the development server, reloading on every change -- the same as
`uvicorn app.main:app --reload --port 8000`. api/.env is read by the package itself (dev_env.py), so it needs no
--env-file. PORT (in the shell or .env) picks another port. Deployments don't use this: the images start uvicorn
from docker-entrypoint.sh."""
import os
from pathlib import Path

import uvicorn

if __name__ == "__main__":
    api_dir = Path(__file__).resolve().parent.parent
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
        reload_dirs=[str(api_dir / "app")],
        app_dir=str(api_dir),
    )
