from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urlparse

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cutover.governance.bridge import load_dispatch_tiers
from cutover.web import auth
from cutover.web.db import Database
from cutover.plugins.mapping import DELTA_TYPES, correct_mapping
from cutover.codegen import CodegenError, Params, build_bundle, default_params
from cutover.codegen.generate import TARGETS as CODEGEN_TARGETS
from cutover.codegen.generate import zip_bundle
from cutover.web import runs as run_store
from cutover.web.profiling import PROFILE_VERSION, ProfileError, profile_csv
from cutover.web.report import build_context, column_note, consolidated_analysis, dataset_analysis, landing_finding, load as load_measured
from cutover.web.live import SESSION_BUDGET_USD, run_mapping_stream

HERE = Path(__file__).parent
BENCHMARK = HERE / "benchmarks" / "profile.json"
COOKIE = "cutover_session"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
TARGETS = {"microsoft_fabric": "Microsoft Fabric", "databricks": "Databricks"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def create_app(
    data_dir: Path | None = None,
    provider_factory: Callable[[], Any] | None = None,
    pricing: Any | None = None,
) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("CUTOVER_DATA_DIR", "./cutover-data")).resolve()
    secure_cookie = os.environ.get("CUTOVER_COOKIE_SECURE", "0") == "1"
    db = Database(data_dir / "cutover.db")
    live_max_runs = int(os.environ.get("CUTOVER_LIVE_MAX_RUNS_PER_DAY", "10"))

    def live_ready() -> bool:
        return provider_factory is not None or bool(os.environ.get("DEEPSEEK_API_KEY"))

    def make_provider() -> tuple[Any, Any]:
        from cutover.providers.deepseek import DeepSeekPricing, DeepSeekProvider

        price = pricing or DeepSeekPricing.from_env()
        return (provider_factory() if provider_factory else DeepSeekProvider(pricing=price)), price
    throttle = auth.LoginThrottle()
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["br_int"] = lambda n: f"{n:,}".replace(",", ".")
    def asset(path: str) -> str:
        """Static URL with a content-version suffix, so a deploy never leaves a stale CSS or JS behind."""
        file = HERE / "static" / path
        try:
            version = f"{int(file.stat().st_mtime):x}"
        except OSError:
            version = "0"
        return f"/static/{path}?v={version}"

    templates.env.globals["asset"] = asset
    templates.env.filters["br_usd"] = lambda n, d=6: f"{n:.{d}f}".replace(".", ",")
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

    def list_datasets(user_id: int) -> list[dict[str, Any]]:
        """The user's datasets with row/alert counts and the state of their mapping (pending, approved, rejected)."""
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, filename, target, size_bytes, created_at, profile_json, "
                "(SELECT decision FROM mapping_runs m WHERE m.dataset_id = datasets.id AND m.status = 'completed' "
                " ORDER BY (m.decision = 'approved') DESC, m.id DESC LIMIT 1) AS mapping "
                "FROM datasets WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
        result = []
        for row in rows:
            profile = json.loads(row["profile_json"])
            result.append({**dict(row), "rows": profile["rows"], "flags": len(profile["flags"])})
        return result

    def baselines_for(dataset_id: int, user_id: int) -> list[dict[str, Any]]:
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM manual_baselines WHERE dataset_id = ? AND user_id = ? ORDER BY id DESC",
                                (dataset_id, user_id)).fetchall()
        return [dict(r) for r in rows]

    @app.post("/app/datasets/{dataset_id}/baseline")
    async def add_baseline(request: Request, dataset_id: int, seconds: int = Form(...), method: str = Form("manual"),
                           note: str = Form("")) -> Response:
        """Record how long the analyst took to do this assessment by hand. Self-reported, and labelled as such."""
        user = current_user(request)
        if not user:
            return JSONResponse({"ok": False, "message": "Faça login."}, status_code=401)
        with db.connect() as conn:
            owns = conn.execute("SELECT 1 FROM datasets WHERE id = ? AND user_id = ?", (dataset_id, user["id"])).fetchone()
        if not owns:
            return JSONResponse({"ok": False, "message": "Dataset não encontrado."}, status_code=404)
        if not 30 <= seconds <= 24 * 3600:
            return JSONResponse({"ok": False, "message": "Informe entre 30 segundos e 24 horas."}, status_code=400)
        with db.connect() as conn:
            conn.execute("INSERT INTO manual_baselines(dataset_id, user_id, seconds, method, note) VALUES (?,?,?,?,?)",
                         (dataset_id, user["id"], seconds, "stopwatch" if method == "stopwatch" else "manual", note[:300]))
        return JSONResponse({"ok": True, "message": "Baseline registrado."})

    @app.get("/app/report")
    def consolidated_report(request: Request) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM datasets WHERE user_id = ? ORDER BY id", (user["id"],)).fetchall()
        items = [{
            "dataset": dict(r), "profile": json.loads(r["profile_json"]),
            "run": run_store.best_run(db, dataset_id=r["id"], user_id=user["id"]),
            "runs": run_store.list_runs(db, dataset_id=r["id"], user_id=user["id"]),
            "baselines": baselines_for(r["id"], user["id"]),
        } for r in rows]
        return templates.TemplateResponse(request, "consolidated_report.html", {
            "items": items, "c": consolidated_analysis(items) if items else None, "user": user, "targets": TARGETS,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        })

    # ---- migration code generation (generates only; never executes) -------------------------

    def migration_context(request: Request, dataset_id: int) -> tuple[Any, ...] | Response:
        """Resolve dataset, approved run and parameters. Returns a Response when the request must stop early."""
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id = ? AND user_id = ?", (dataset_id, user["id"])).fetchone()
        if not row:
            return render(request, "notfound.html", 404)
        run = run_store.best_run(db, dataset_id=dataset_id, user_id=user["id"])
        target = request.query_params.get("target", row["target"])
        if target not in CODEGEN_TARGETS:
            target = row["target"]
        base = default_params(row["filename"], target)
        q = request.query_params
        params = Params(
            table=q.get("table", base.table).strip(), schema=q.get("schema", base.schema).strip(),
            catalog=(q.get("catalog", base.catalog or "").strip() or None) if target == "databricks" else None,
            source_path=q.get("source_path", base.source_path).strip(), drop_duplicates=q.get("drop_duplicates") == "1")
        return user, row, run, target, params

    # ---- correcting a suggested mapping (no model call, no cost) -----------------------------

    def owned_run(request: Request, dataset_id: int, run_id: int) -> tuple[Any, ...] | Response:
        user = current_user(request)
        if not user:
            return JSONResponse({"ok": False, "message": "Faça login."}, status_code=401)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id = ? AND user_id = ?", (dataset_id, user["id"])).fetchone()
        run = run_store.load_run(db, dataset_id=dataset_id, user_id=user["id"], run_id=run_id) if row else None
        if not row or run is None or run["status"] != "completed":
            return JSONResponse({"ok": False, "message": "Execução não encontrada."}, status_code=404)
        return user, row, run, json.loads(row["profile_json"])["columns"]

    @app.get("/app/datasets/{dataset_id}/mapping/runs/{run_id}/fixes")
    def mapping_fixes(request: Request, dataset_id: int, run_id: int) -> Response:
        ctx = owned_run(request, dataset_id, run_id)
        if isinstance(ctx, Response):
            return ctx
        _, _, run, columns = ctx
        corrected, changes = correct_mapping(columns, run["mappings"])
        return JSONResponse({"ok": True, "changes": changes, "corrected": corrected})

    @app.post("/app/datasets/{dataset_id}/mapping/runs/{run_id}/fix")
    async def mapping_fix(request: Request, dataset_id: int, run_id: int) -> Response:
        ctx = owned_run(request, dataset_id, run_id)
        if isinstance(ctx, Response):
            return ctx
        user, _, run, columns = ctx
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"ok": False, "message": "Corpo inválido."}, status_code=400)
        if body.get("mode") == "auto":
            new_mappings, changes = correct_mapping(columns, run["mappings"])
            source = "regras determinísticas"
            if not changes:
                return JSONResponse({"ok": False, "message": "Nenhuma correção automática se aplica."}, status_code=409)
        elif body.get("mode") == "manual" and isinstance(body.get("entries"), dict):
            known = {c["name"] for c in columns}
            new_mappings, changes = dict(run["mappings"]), []
            for column, entry in body["entries"].items():
                if column not in known or not isinstance(entry, dict):
                    return JSONResponse({"ok": False, "message": f"Coluna desconhecida: {column!r}."}, status_code=400)
                target, kind = str(entry.get("target", "")).strip()[:128], str(entry.get("type", "")).strip()[:32]
                current = new_mappings.get(column)
                before: dict[str, Any] = current if isinstance(current, dict) else {}
                for field, old, new in (("destino", before.get("target"), target), ("tipo", before.get("type"), kind)):
                    if old != new:
                        changes.append({"column": column, "field": field, "from": old, "to": new, "reason": "Edição manual."})
                new_mappings[column] = {"target": target, "type": kind}
            source = "edição manual"
            if not changes:
                return JSONResponse({"ok": False, "message": "Nada foi alterado."}, status_code=409)
        else:
            return JSONResponse({"ok": False, "message": "Modo inválido."}, status_code=400)
        ok, message, result = run_store.revise(db, run_id=run_id, dataset_id=dataset_id, user_id=user["id"], who=user["email"],
                                               profile_columns=columns, new_mappings=new_mappings, changes=changes, source=source)
        if not ok or result is None:
            return JSONResponse({"ok": False, "message": message}, status_code=409)
        return JSONResponse({"ok": True, "decision": "pending", **result})

    @app.get("/app/datasets/{dataset_id}/mapping/runs/{run_id}/edit")
    def mapping_edit_page(request: Request, dataset_id: int, run_id: int) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id = ? AND user_id = ?", (dataset_id, user["id"])).fetchone()
        run = run_store.load_run(db, dataset_id=dataset_id, user_id=user["id"], run_id=run_id) if row else None
        if not row or run is None or run["status"] != "completed":
            return render(request, "notfound.html", 404)
        columns = json.loads(row["profile_json"])["columns"]
        return render(request, "mapping_edit.html", dataset=dict(row), run=run, columns=columns, delta_types=DELTA_TYPES,
                      notes={c["name"]: column_note(c) for c in columns})

    @app.get("/app/datasets/{dataset_id}/migration")
    def migration_page(request: Request, dataset_id: int) -> Response:
        ctx = migration_context(request, dataset_id)
        if isinstance(ctx, Response):
            return ctx
        user, row, run, target, params = ctx
        profile = json.loads(row["profile_json"])
        files: dict[str, str] = {}
        error = None
        approved = bool(run and run["decision"] == "approved")
        if approved:
            try:
                files = build_bundle(target=target, dataset=dict(row), profile=profile, run=run, params=params)
            except CodegenError as exc:
                error = str(exc)
        query = urlencode({"target": target, "table": params.table, "schema": params.schema, "catalog": params.catalog or "",
                           "source_path": params.source_path, "drop_duplicates": "1" if params.drop_duplicates else "0"})
        return render(request, "migration.html", 400 if error else 200, dataset=dict(row), run=run, approved=approved,
                      target=target, params=params, files=files, error=error, query=query, profile=profile,
                      targets=TARGETS, target_label=TARGETS.get(target, target))

    @app.get("/app/datasets/{dataset_id}/migration/download")
    def migration_download(request: Request, dataset_id: int) -> Response:
        ctx = migration_context(request, dataset_id)
        if isinstance(ctx, Response):
            return ctx
        user, row, run, target, params = ctx
        if not run or run["decision"] != "approved":
            return Response("Aprove o mapeamento antes de gerar código.", status_code=409)
        try:
            files = build_bundle(target=target, dataset=dict(row), profile=json.loads(row["profile_json"]), run=run, params=params)
        except CodegenError as exc:
            return Response(str(exc), status_code=400)
        payload = zip_bundle(files)
        import hashlib

        with db.connect() as conn:
            conn.execute("INSERT INTO migration_bundles(dataset_id, user_id, run_id, target, params_json, bundle_sha256) VALUES (?,?,?,?,?,?)",
                         (dataset_id, user["id"], run["id"], target, json.dumps({"table": params.table, "schema": params.schema,
                          "catalog": params.catalog, "source_path": params.source_path, "drop_duplicates": params.drop_duplicates}),
                          hashlib.sha256(payload).hexdigest()))
        name = f"migracao-{params.table}-{target}.zip"
        return Response(payload, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/relatorio")
    def report(request: Request) -> Response:
        return render(request, "report.html", **build_context())

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(HERE / "static" / "favicon.ico", media_type="image/x-icon")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def landing(request: Request) -> Response:
        tiers = load_dispatch_tiers()
        llm = load_measured("llm")
        return render(request, "landing.html", tiers=tiers, max_cap=max(t["input_token_cap"] for t in tiers),
                      bench=load_benchmark(), llm=llm, finding=landing_finding(llm),
                      checks_n=max((r.get("checks_total", 0) for r in llm["runs"]), default=0) if llm else 0)

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
        datasets = list_datasets(user["id"])
        return render(request, "dashboard.html", datasets=datasets, targets=TARGETS, error=None,
                      max_mb=MAX_UPLOAD_BYTES // (1024 * 1024), max_bytes=MAX_UPLOAD_BYTES)

    @app.post("/app/datasets")
    async def upload(request: Request, file: UploadFile = File(...), target: str = Form(...)) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)

        def fail(message: str, status: int = 400) -> Response:
            datasets = list_datasets(user["id"])
            return render(request, "dashboard.html", status, datasets=datasets, targets=TARGETS,
                          error=message, max_mb=MAX_UPLOAD_BYTES // (1024 * 1024), max_bytes=MAX_UPLOAD_BYTES)

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
            # CPU-bound: run it off the event loop, or one large upload freezes the app for every user.
            profile = await asyncio.to_thread(profile_csv, stored)
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
                      run=run_store.best_run(db, dataset_id=dataset_id, user_id=user["id"]),
                      baselines=baselines_for(dataset_id, user["id"]),
                      target_label=TARGETS.get(row["target"], row["target"]))

    # ---- live governed run -----------------------------------------------------

    def runs_today(user_id: int) -> int:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM live_runs WHERE user_id = ? AND created_at >= datetime('now', '-1 day')",
                (user_id,)).fetchone()
        return int(row["n"])

    @app.get("/app/datasets/{dataset_id}/mapping")
    def mapping_page(request: Request, dataset_id: int) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        with db.connect() as conn:
            row = conn.execute("SELECT id, filename, target FROM datasets WHERE id = ? AND user_id = ?",
                               (dataset_id, user["id"])).fetchone()
        if not row:
            return render(request, "notfound.html", 404)
        return render(request, "mapping.html", dataset=dict(row), target_label=TARGETS.get(row["target"]),
                      ready=live_ready(), runs_left=max(0, live_max_runs - runs_today(user["id"])),
                      history=run_store.list_runs(db, dataset_id=dataset_id, user_id=user["id"]),
                      model=os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"), budget=SESSION_BUDGET_USD)

    @app.post("/app/datasets/{dataset_id}/mapping/run")
    async def mapping_run(request: Request, dataset_id: int) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id = ? AND user_id = ?",
                               (dataset_id, user["id"])).fetchone()
        if not row:
            return Response("Dataset não encontrado.", status_code=404)
        if not live_ready():
            return Response("Chave da DeepSeek não configurada.", status_code=503)
        if runs_today(user["id"]) >= live_max_runs:
            return Response("Limite diário de execuções atingido.", status_code=429)
        with db.connect() as conn:
            conn.execute("INSERT INTO live_runs(user_id, dataset_id) VALUES (?, ?)", (user["id"], dataset_id))

        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        collected: list[dict[str, Any]] = []
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

        def emit(event: dict[str, Any]) -> None:
            if event["type"] == "done":  # persist first so the screen can offer approval and the report
                run_id = run_store.save_run(db, user_id=user["id"], dataset_id=dataset_id, model=model, events=collected)
                events.put({"type": "saved", "run_id": run_id, "t_ms": event.get("t_ms", 0)})
            elif event["type"] != "provider.delta":
                collected.append(event)
            events.put(event)

        def worker() -> None:
            try:
                provider, price = make_provider()
                run_mapping_stream(
                    profile=json.loads(row["profile_json"]), target=row["target"], dataset_id=dataset_id,
                    db_path=data_dir / "ledger.db", provider=provider, pricing=price, model=model, emit=emit)
            except Exception as exc:  # setup failures (missing prices, bad key) still reach the screen
                emit({"type": "error", "message": f"{type(exc).__name__}: {exc}", "t_ms": 0})
                emit({"type": "done", "t_ms": 0})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        async def stream() -> Any:
            while (event := await asyncio.to_thread(events.get)) is not None:
                yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/app/datasets/{dataset_id}/mapping/runs/{run_id}/decision")
    async def mapping_decision(request: Request, dataset_id: int, run_id: int, decision: str = Form(...),
                               note: str = Form("")) -> Response:
        user = current_user(request)
        if not user:
            return JSONResponse({"ok": False, "message": "Faça login."}, status_code=401)
        if decision not in {"approved", "rejected"}:
            return JSONResponse({"ok": False, "message": "Decisão inválida."}, status_code=400)
        ok, message = run_store.decide(db, run_id=run_id, user_id=user["id"], dataset_id=dataset_id,
                                       decision=decision, note=note, who=user["email"])
        return JSONResponse({"ok": ok, "message": message, "decision": decision if ok else None},
                            status_code=200 if ok else 409)

    @app.get("/app/datasets/{dataset_id}/mapping/runs/{run_id}/download")
    def mapping_download(request: Request, dataset_id: int, run_id: int) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        run = run_store.load_run(db, dataset_id=dataset_id, user_id=user["id"], run_id=run_id)
        if run is None or run["status"] != "completed":
            return Response("Execução não encontrada.", status_code=404)
        return Response(run_store.mapping_csv(run), media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="mapeamento-{dataset_id}-{run_id}-{run["decision"]}.csv"'})

    @app.get("/app/datasets/{dataset_id}/report")
    def dataset_report(request: Request, dataset_id: int) -> Response:
        user = current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id = ? AND user_id = ?",
                               (dataset_id, user["id"])).fetchone()
        if not row:
            return render(request, "notfound.html", 404)
        profile = json.loads(row["profile_json"])
        if profile.get("profile_version", 1) < PROFILE_VERSION and Path(row["stored_path"]).exists():
            try:  # datasets profiled by an older version get the richer profile, from the file that was stored
                fresh = profile_csv(Path(row["stored_path"])).to_dict()
                if fresh["sha256"] == profile["sha256"]:
                    profile = fresh
                    with db.connect() as conn:
                        conn.execute("UPDATE datasets SET profile_json = ? WHERE id = ?", (json.dumps(fresh), dataset_id))
            except ProfileError:
                pass
        run = run_store.best_run(db, dataset_id=dataset_id, user_id=user["id"])
        history = run_store.list_runs(db, dataset_id=dataset_id, user_id=user["id"])
        return templates.TemplateResponse(request, "dataset_report.html", {
            "dataset": dict(row), "profile": profile, "run": run, "history": history,
            "analysis": dataset_analysis(profile, run, history, baselines_for(dataset_id, user["id"])),
            "target_label": TARGETS.get(row["target"], row["target"]), "user": user,
            "runs_total": len(history),
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        })

    return app
