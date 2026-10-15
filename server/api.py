import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .domain import DomainError, Engine
from .distributed import DistributedEngine


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Start(Input):
    label: str = Field(min_length=1, max_length=40)


class Item(Input):
    sku: str = Field(min_length=1, max_length=64)
    quantity: Annotated[StrictInt, Field(ge=1, le=6)]


class Order(Input):
    request_id: str = Field(min_length=8, max_length=80)
    items: list[Item] = Field(min_length=1, max_length=6)


class Gateway(Input):
    gateway_id: str = Field(min_length=8, max_length=80)


class NodeConnection(Input):
    node_id: str = Field(min_length=1, max_length=80)
    instance_id: str = Field(min_length=8, max_length=80)


class NodeEvent(NodeConnection):
    event: "DeviceEvent"


class MockAction(NodeConnection):
    command_id: str
    action: Literal["EXECUTE", "STOPPED", "ARM_CLEAR", "EXITED"]


class DeviceEvent(Input):
    event_id: str = Field(min_length=8, max_length=100)
    run_id: str
    command_id: str
    task_id: str
    session_id: str
    device_id: str
    mode: Literal["mock"]
    observed_at: float = Field(allow_inf_nan=False)
    kind: Literal["ACCEPTED", "SUCCEEDED", "FAILED", "STOPPED", "ARM_CLEAR", "EXITED"]
    data: dict = Field(default_factory=dict)


class Basket(Input):
    session_id: str
    task_id: str
    basket_id: str = Field(min_length=1, max_length=80)


class Steps(Input):
    count: Annotated[StrictInt, Field(ge=1, le=100)] = 1


class Fault(Input):
    device_id: str
    kind: Literal["PICK_FAIL", "DISCONNECT"]


class Device(Input):
    device_id: str


def create_app(engine=None, admin_token=None, gateway_token=None, node_tokens=None):
    injected = engine is not None
    admin_token = admin_token or os.getenv("SHOP_ADMIN_TOKEN", "")
    gateway_token = gateway_token or os.getenv("SHOP_GATEWAY_TOKEN", "")
    database = os.getenv("SHOP_DB", "runtime/shopping.db")
    import json
    node_tokens = node_tokens if node_tokens is not None else json.loads(os.getenv("SHOP_NODE_TOKENS", "{}"))
    distributed = isinstance(engine, DistributedEngine) or (engine is None and os.getenv("SHOP_GATEWAY_MODE") == "distributed")
    security = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app):
        if len(admin_token) < 16:
            raise RuntimeError("SHOP_ADMIN_TOKEN(16자 이상)이 필요합니다")
        if distributed:
            from .distributed import profiles
            values = [admin_token, *node_tokens.values()]
            if (set(node_tokens) != set(profiles()) or any(not isinstance(v, str) or len(v) < 16 for v in values)
                    or len(values) != len(set(values))):
                raise RuntimeError("중개 A/B/C 각각에 서로 다른 16자 이상 토큰이 필요합니다")
        elif min(len(admin_token), len(gateway_token)) < 16 or admin_token == gateway_token:
            raise RuntimeError("서로 다른 SHOP_ADMIN_TOKEN / SHOP_GATEWAY_TOKEN(16자 이상)이 필요합니다. scripts/setup_ubuntu.sh를 사용하세요.")
        lockfile = None
        if not injected:
            # Protect the single scheduler, including against a second server process.
            import fcntl  # Ubuntu target; native Windows execution is outside this delivery.
            Path(database).parent.mkdir(parents=True, exist_ok=True)
            lockfile = open(database + ".lock.pid", "a+")
            try:
                fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lockfile.close()
                raise RuntimeError("다른 작업 제어 서버가 이 DB를 사용 중입니다. workers=1로 실행하세요.")
        app.state.engine = engine if injected else (DistributedEngine(database) if distributed else Engine(database))

        async def monitor():
            while True:
                await asyncio.sleep(1)
                app.state.engine.watchdog()

        monitor_task = asyncio.create_task(monitor())
        try:
            yield
        finally:
            monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await monitor_task
            if not injected:
                app.state.engine.store.close()
            if lockfile:
                lockfile.close()

    app = FastAPI(title="쇼핑키프로 작업 제어 · MOCK", version="0.1.0", lifespan=lifespan)

    def control(request: Request):
        return request.app.state.engine

    def token_value(credentials: HTTPAuthorizationCredentials | None):
        if credentials is None:
            raise HTTPException(401, "인증이 필요합니다")
        return credentials.credentials

    def admin(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if not hmac.compare_digest(token_value(credentials), admin_token):
            raise HTTPException(401, "관리자 인증 실패")

    def gateway(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if distributed:
            raise HTTPException(409, "분산 실행에서는 중개별 /api/nodes 경로를 사용하세요")
        if not hmac.compare_digest(token_value(credentials), gateway_token):
            raise HTTPException(401, "장비 연결 인증 실패")

    def node_auth(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if not distributed:
            raise HTTPException(409, "분산 중개 서버가 아닙니다")
        token = token_value(credentials)
        for node_id, expected in node_tokens.items():
            if hmac.compare_digest(token, expected):
                return node_id
        raise HTTPException(401, "중개 인증 실패")

    def owned(body, principal):
        if body.node_id != principal:
            raise HTTPException(403, "인증된 중개와 요청 중개가 다릅니다")

    def customer(credentials: HTTPAuthorizationCredentials | None = Depends(security), e=Depends(control)):
        return e.authenticate_customer(token_value(credentials))

    @app.exception_handler(DomainError)
    async def domain_error(_request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "mock", "gateway_mode": "distributed" if distributed else "single",
                "preview_id": os.getenv("SHOP_PREVIEW_ID"),
                "physical_hardware_verified": False}

    @app.get("/api/products")
    def products(e=Depends(control)):
        snapshot = e.snapshot()
        return {"items": snapshot["products"], "capacity": snapshot["capacity"], "mode": "mock"}

    @app.post("/api/sessions", status_code=201)
    def start(body: Start, e=Depends(control)):
        return e.create_session(body.label)

    @app.get("/api/customer/state")
    def customer_state(sid=Depends(customer), e=Depends(control)):
        return e.snapshot(sid)

    @app.post("/api/customer/orders", status_code=201)
    def order(body: Order, sid=Depends(customer), e=Depends(control)):
        return e.submit_order(sid, [item.model_dump() for item in body.items], body.request_id)

    @app.post("/api/customer/checkout")
    def checkout(sid=Depends(customer), e=Depends(control)):
        return e.checkout(sid)

    @app.get("/api/admin/state", dependencies=[Depends(admin)])
    def admin_state(e=Depends(control)):
        return e.snapshot()

    @app.get("/api/admin/logs", dependencies=[Depends(admin)])
    def logs(e=Depends(control)):
        return {"items": e.logs()}

    @app.post("/api/admin/basket-ready", dependencies=[Depends(admin)])
    def basket(body: Basket, e=Depends(control)):
        e.basket_ready(body.session_id, body.task_id, body.basket_id)
        return {"recorded": True}

    @app.post("/api/admin/mock/steps", dependencies=[Depends(admin)])
    def steps(body: Steps, e=Depends(control)):
        return e.mock_steps(body.count)

    @app.post("/api/admin/mock/fault", dependencies=[Depends(admin)])
    def fault(body: Fault, e=Depends(control)):
        e.inject_failure(body.device_id, body.kind)
        return {"recorded": True}

    @app.post("/api/admin/mock/new-run", dependencies=[Depends(admin)])
    def new_run(e=Depends(control)):
        return e.reset_mock()

    @app.post("/api/gateway/heartbeat", dependencies=[Depends(gateway)])
    def heartbeat(body: Gateway, e=Depends(control)):
        return e.heartbeat(body.gateway_id)

    @app.post("/api/gateway/commands/claim", dependencies=[Depends(gateway)])
    def claim(body: Gateway, e=Depends(control)):
        return {"command": e.claim(body.gateway_id)}

    @app.post("/api/gateway/events", dependencies=[Depends(gateway)])
    def event(body: DeviceEvent, e=Depends(control)):
        return e.event(body.model_dump())

    @app.get("/api/gateway/mock/state", dependencies=[Depends(gateway)])
    def gateway_state(e=Depends(control)):
        return e.snapshot()

    @app.post("/api/gateway/mock/permit", dependencies=[Depends(gateway)])
    def permit(e=Depends(control)):
        return {"allowed": e.take_permit()}

    @app.post("/api/gateway/mock/failure", dependencies=[Depends(gateway)])
    def failure(body: Device, e=Depends(control)):
        return {"fail": e.consume_failure(body.device_id)}

    @app.post("/api/nodes/heartbeat")
    def node_heartbeat(body: NodeConnection, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        return e.node_heartbeat(body.node_id, body.instance_id)

    @app.post("/api/nodes/commands/claim")
    def node_claim(body: NodeConnection, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        return {"command": e.node_claim(body.node_id, body.instance_id)}

    @app.post("/api/nodes/work")
    def node_work(body: NodeConnection, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        return e.node_work(body.node_id, body.instance_id)

    @app.post("/api/nodes/events")
    def node_event(body: NodeEvent, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        return e.node_event(body.node_id, body.instance_id, body.event.model_dump())

    @app.post("/api/nodes/mock/action")
    def node_mock_action(body: MockAction, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        return e.mock_action(body.node_id, body.instance_id, body.command_id, body.action)

    @app.post("/api/nodes/mock/permit")
    def node_permit(body: NodeConnection, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        e.node_work(body.node_id, body.instance_id)
        return {"allowed": e.take_permit()}

    dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "API 경로를 찾을 수 없습니다")
        if not (dist / "index.html").is_file():
            return JSONResponse({"message": "웹 빌드가 필요합니다. scripts/setup_ubuntu.sh 실행 후 서버를 시작하세요.",
                                 "api_docs": "/docs"})
        return FileResponse(dist / "index.html")

    return app
