from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cutover.governance.bridge import load_dispatch_tiers
from cutover.web import auth
from cutover.web.db import Database
from cutover.web.profiling import ProfileError, profile_csv

HERE = Path(__file__).parent
BENCHMARK = HERE / "benchmarks" / "profile.json"
COOKIE = "cutover_session"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
TARGETS = {"microsoft_fabric": "Microsoft Fabric", "databricks": "Databricks"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def create_app(data_dir: Path | None = None) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("CUTOVER_DATA_DIR", "./cutover-data")).resolve()
    secure_cookie = os.environ.get("CUTOVER_COOKIE_SECURE", "0") == "1"
    db = Database(data_dir / "cutover.db")
    throttle = auth.LoginThrottle()
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["br_int"] = lambda n: f"{n:,}".replace(",", ".")
    templates.env.filters["br_dec"] = lambda n, digits=1: f"{n:.{digits}f}".replace(".", ",")

    def load_benchmark() -> dict[str, Any] | None:
        try:
            return json.loads(BENCHMARK.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # no measurements, no proof section: never show numbers that were not measured

    app = FastAPI(title="Cutover", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def render(request: Request, name: str, status: int = 200, **context: Any) -> Response:
        context.setdefault("user", current_user(request))
        return templates.TemplateResponse(request, name, context, status_code=status)

    def current_user(request: Request) -> sqlite3.Row | None:
        token = request.cookies.get(COOKIE)
        if not token:
            return None
        with db.connect() as conn:
            row = conn.execute(
                "SELECT u.id, u.email, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ?",
                (auth.hash_token(token),),
            ).fetchone()
        return row if row and auth.session_is_valid(row["expires_at"]) else None

    def same_origin(request: Request) -> bool:
        origin = request.headers.get("origin") or request.headers.get("referer")
        return origin is None or urlparse(origin).netloc == request.headers.get("host")

    def start_session(user_id: int) -> RedirectResponse:
        token, token_hash, expires = auth.new_session_token()
        with db.connect() as conn:
            conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?,?,?)",
                         (token_hash, user_id, expires))
        response = RedirectResponse("/app", status_code=303)
        response.set_cookie(COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True,
                            samesite="lax", secure=secure_cookie)
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        if request.method == "POST" and not same_origin(request):
            return Response("Origem não permitida.", status_code=403)
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    # ---- public ----------------------------------------------------------------

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(HERE / "static" / "favicon.ico", media_type="image/x-icon")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def landing(request: Request) -> Response:
        tiers = load_dispatch_tiers()
        return render(request, "landing.html", tiers=tiers,
                      max_cap=max(t["input_token_cap"] for t in tiers), bench=load_benchmark())

    @app.get("/login")
    def login_form(request: Request) -> Response:
        if current_user(request):
            return RedirectResponse("/app", status_code=303)
        return render(request, "login.html", mode="login", error=None)

    @app.post("/login")
    def login(request: Request, email: str = Form(...), password: str = Form(...)) -> Response:
        email = email.strip().lower()
        key = f"{request.client.host if request.client else '-'}|{email}"
        if throttle.blocked(key):
            return render(request, "login.html", 429, mode="login",
                          error="Muitas tentativas. Aguarde alguns minutos.")
        with db.connect() as conn:
            row = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        # Verify against a dummy hash when the user is unknown so timing does not reveal accounts.
        stored = row["password_hash"] if row else auth.hash_password("x")
        if not (auth.verify_password(password, stored) and row):
            throttle.record_failure(key)
            return render(request, "login.html", 401, mode="login", error="E-mail ou senha inválidos.")
        throttle.reset(key)
        return start_session(row["id"])

    @app.get("/signup")
    def signup_form(request: Request) -> Response:
        if current_user(request):
            return RedirectResponse("/app", status_code=303)
        return render(request, "login.html", mode="signup", error=None)

    @app.post("/signup")
    def signup(request: Request, email: str = Form(...), password: str = Form(...)) -> Response:
        email = email.strip().lower()
        error = None
        if not EMAIL.match(email):
            error = "Informe um e-mail válido."
        elif len(password) < auth.MIN_PASSWORD_LENGTH:
            error = f"A senha precisa ter ao menos {auth.MIN_PASSWORD_LENGTH} caracteres."
        if error:
            return render(request, "login.html", 400, mode="signup", error=error)
        try:
            with db.connect() as conn:
                cursor = conn.execute("INSERT INTO users(email, password_hash) VALUES (?,?)",
                                      (email, auth.hash_password(password)))
                user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return render(request, "login.html", 409, mode="signup", error="Este e-mail já está cadastrado.")
        assert user_id is not None
        return start_session(user_id)

    @app.post("/logout")
    def logout(request: Request) -> Response:
        token = request.cookies.get(COOKIE)
        if token:
            with db.connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (auth.hash_token(token),))
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(COOKIE)
        return response

    # ---- authenticated ---------------------------------------------------------

    @app.get("/app")
    def dashboard(request: Request) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, filename, target, size_bytes, created_at, profile_json FROM datasets "
                "WHERE user_id = ? ORDER BY id DESC", (user["id"],)).fetchall()
        datasets = []
        for row in rows:
            profile = json.loads(row["profile_json"])
            datasets.append({**dict(row), "rows": profile["rows"], "flags": len(profile["flags"])})
        return render(request, "dashboard.html", datasets=datasets, targets=TARGETS, error=None,
                      max_mb=MAX_UPLOAD_BYTES // (1024 * 1024))

    @app.post("/app/datasets")
    async def upload(request: Request, file: UploadFile = File(...), target: str = Form(...)) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)

        def fail(message: str, status: int = 400) -> Response:
            with db.connect() as conn:
                rows = conn.execute(
                    "SELECT id, filename, target, size_bytes, created_at, profile_json FROM datasets "
                    "WHERE user_id = ? ORDER BY id DESC", (user["id"],)).fetchall()
            datasets = [{**dict(r), "rows": json.loads(r["profile_json"])["rows"],
                         "flags": len(json.loads(r["profile_json"])["flags"])} for r in rows]
            return render(request, "dashboard.html", status, datasets=datasets, targets=TARGETS,
                          error=message, max_mb=MAX_UPLOAD_BYTES // (1024 * 1024))

        filename = Path(file.filename or "dataset.csv").name
        if target not in TARGETS:
            return fail("Escolha um destino válido.")
        if not filename.lower().endswith(".csv"):
            return fail("Nesta versão, apenas arquivos .csv são aceitos.")

        folder = data_dir / "uploads" / str(user["id"])
        folder.mkdir(parents=True, exist_ok=True)
        stored = folder / f"{uuid.uuid4().hex}.csv"
        size = 0
        with stored.open("wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    break
                out.write(chunk)
        if size > MAX_UPLOAD_BYTES:
            stored.unlink(missing_ok=True)
            return fail(f"O arquivo excede {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", 413)
        try:
            profile = profile_csv(stored)
        except ProfileError as exc:
            stored.unlink(missing_ok=True)
            return fail(str(exc))
        with db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO datasets(user_id, filename, stored_path, target, size_bytes, profile_json) "
                "VALUES (?,?,?,?,?,?)",
                (user["id"], filename, str(stored), target, size, json.dumps(profile.to_dict())))
        return RedirectResponse(f"/app/datasets/{cursor.lastrowid}", status_code=303)

    @app.get("/app/datasets/{dataset_id}")
    def dataset(request: Request, dataset_id: int) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id = ? AND user_id = ?",
                               (dataset_id, user["id"])).fetchone()
        if not row:
            return render(request, "notfound.html", 404)
        profile = json.loads(row["profile_json"])
        return render(request, "dataset.html", dataset=dict(row), profile=profile,
                      target_label=TARGETS.get(row["target"], row["target"]))

    return app
