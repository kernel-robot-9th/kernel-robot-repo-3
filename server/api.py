import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .domain import DomainError, Engine
from .distributed import DistributedEngine
from .video import VIDEO_PATH, FIELD_VIDEO_PATH, VideoRegistry
from .device_tests import Bench


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
    mode: Literal['mock', 'hardware'] = 'mock'
    role: Literal['control', 'test'] = 'control'


class NodeHeartbeat(NodeConnection):
    motion: dict = Field(default_factory=dict)


class FieldObservation(Input):
    observation: str = Field(min_length=1, max_length=40)
    operator: str = Field(default='현장 운영자', min_length=1, max_length=80, pattern=r'\S')


class FieldRouteSelection(Input):
    version: Literal[3,4]


class TestRequest(Input):
    node_id: Literal['gateway-a', 'gateway-b', 'gateway-c']
    kind: Literal['PING', 'INSPECT', 'PICK', 'HANDOFF', 'NAVIGATE']
    request_id: str = Field(min_length=8, max_length=80)
    parameters: dict = Field(default_factory=dict)
    prepared: bool = False
    simulate_failure: bool = False


class TestPoll(NodeConnection):
    profile: dict = Field(default_factory=dict)
    available: bool = False


class TestEvent(NodeConnection):
    job_id: str
    event_id: str = Field(min_length=8, max_length=100)
    kind: Literal['ACCEPTED', 'STARTED', 'STOP_ACK', 'PROGRESS', 'FINISHED', 'ERROR']
    data: dict = Field(default_factory=dict)


class TestReview(Input):
    operator: str = Field(min_length=1, max_length=80, pattern=r'\S')
    success: bool = False
    stopped: bool = False
    process_closed: bool = False
    note: str = Field(min_length=1, max_length=500, pattern=r'\S')


class TestObservation(Input):
    operator: str = Field(min_length=1, max_length=80, pattern=r'\S')
    facts: dict[str, bool]


class TestRelease(Input):
    operator: str = Field(min_length=1, max_length=80, pattern=r'\S')
    restored: bool = False


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
    mode: Literal["mock", "hardware"]
    observed_at: float = Field(allow_inf_nan=False)
    kind: Literal["ACCEPTED", "SUCCEEDED", "FAILED", "STOPPED", "ARM_CLEAR", "EXITED", "TRANSFER_READY"]
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


class NewRun(Input):
    acknowledge_unresolved: bool = False


class VideoFault(Input):
    kind: Literal['none', 'freeze', 'offline']


def create_app(engine=None, admin_token=None, gateway_token=None, node_tokens=None, video=None):
    injected = engine is not None
    admin_token = admin_token or os.getenv("SHOP_ADMIN_TOKEN", "")
    gateway_token = gateway_token or os.getenv("SHOP_GATEWAY_TOKEN", "")
    database = os.getenv("SHOP_DB", "runtime/shopping.db")
    import json
    node_tokens = node_tokens if node_tokens is not None else json.loads(os.getenv("SHOP_NODE_TOKENS", "{}"))
    distributed = isinstance(engine, DistributedEngine) or (engine is None and os.getenv("SHOP_GATEWAY_MODE") == "distributed")
    security = HTTPBearer(auto_error=False)
    configured_mode = engine.mode if injected else os.getenv('SHOP_DEVICE_MODE', 'mock')
    video = video or VideoRegistry(os.getenv('SHOP_VIDEO_CONFIG', str(FIELD_VIDEO_PATH if configured_mode == 'hardware' else VIDEO_PATH)))
    if configured_mode == 'hardware' and any(f['transport'] == 'mock' for f in video.feeds.values()):
        raise RuntimeError('실물 연결 모드에서는 가상 영상 설정을 사용할 수 없습니다')

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
        mode = os.getenv('SHOP_DEVICE_MODE', 'mock')
        if not injected and mode == 'hardware' and not distributed:
            raise RuntimeError('실물 연결은 분산 중계 모드에서만 지원합니다')
        readiness_path = os.getenv('SHOP_HARDWARE_READINESS')
        readiness = json.loads(Path(readiness_path).read_text(encoding='utf-8')) if readiness_path else None
        test_only = os.getenv('SHOP_TEST_ONLY') == '1'
        from .reference import ReferenceEngine
        reference = os.getenv('SHOP_MOTION_BACKEND') == 'reference_v4'
        if not injected and reference and (not distributed or mode != 'mock'):
            raise RuntimeError('reference_v4는 분산 MOCK 전용입니다. 실물 모드에 사용할 수 없습니다')
        engine_type = ReferenceEngine if reference else DistributedEngine
        app.state.engine = engine if injected else (engine_type(database, mode=mode, readiness=readiness, test_only=test_only)
                                                    if distributed else Engine(database, mode=mode, readiness=readiness, test_only=test_only))

        async def monitor():
            while True:
                await asyncio.sleep(1)
                if isinstance(app.state.engine, ReferenceEngine):
                    app.state.engine.watchdog()
                Bench(app.state.engine).watchdog()

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

    app = FastAPI(title="카트리나 작업 제어", version="0.1.0", lifespan=lifespan)

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
    def health(e=Depends(control)):
        return {"status": "ok", "mode": e.mode, "gateway_mode": "distributed" if distributed else "single",
                "test_only": e.test_only,
                "motion_backend": 'external_adapter' if e.mode == 'hardware' else ('reference_v4' if 'road' in e.state else 'logical'),
                "setup_only": e.mode == 'hardware' and e.test_only,
                "preview_id": os.getenv("SHOP_PREVIEW_ID"),
                "physical_hardware_verified": False}

    @app.get("/api/products")
    def products(e=Depends(control)):
        snapshot = e.snapshot()
        return {"items": snapshot["products"], "capacity": snapshot["capacity"], "cart_capacity": snapshot['cart_capacity'], "mode": e.mode,
                "accepting_sessions": not e.test_only}

    @app.post("/api/sessions", status_code=201)
    def start(body: Start, e=Depends(control)):
        if e.test_only:
            raise HTTPException(409, '현장 설정·장비 시험 중입니다. 주문 운영 전환 후 쇼핑을 시작하세요')
        return e.create_session(body.label)

    @app.get("/api/customer/state")
    def customer_state(sid=Depends(customer), e=Depends(control)):
        return e.snapshot(sid)

    @app.post("/api/customer/orders", status_code=201)
    def order(body: Order, sid=Depends(customer), e=Depends(control)):
        return e.submit_order(sid, [item.model_dump() for item in body.items], body.request_id)

    @app.post("/api/customer/orders/{order_id}/cancel")
    def cancel(order_id: str, sid=Depends(customer), e=Depends(control)):
        return e.cancel_order(sid, order_id)

    @app.post("/api/customer/checkout")
    def checkout(sid=Depends(customer), e=Depends(control)):
        return e.checkout(sid)

    @app.get("/api/admin/state", dependencies=[Depends(admin)])
    def admin_state(e=Depends(control)):
        return e.snapshot()

    @app.get('/api/admin/field/camera-position', dependencies=[Depends(admin)])
    def camera_position():
        from robot_gateway.hardware.camera_navigation import observation
        from robot_gateway.hardware.wait_parking import camera_view
        return camera_view(observation())

    @app.get('/api/admin/field/routes', dependencies=[Depends(admin)])
    def field_routes(e=Depends(control)):
        from robots.pinky import catalog, compact
        def preview(module):
            paths=module.bundle()[1]
            return {name:[p for segment in segments if segment['direction'] for p in segment['poses']][::20]
                    for name,segments in paths.items()}
        deployed={}
        from robot_gateway.hardware.station_remote import configuration
        try:
            deployed={robot:json.loads(Path(file).read_text()).get('route_modes')==[3,4]
                      for robot,file in configuration()['profiles'].items()}
        except FileNotFoundError:
            pass
        return {'selected':e.state.get('field_route_version',4), 'effective':'next_session', 'deployed':deployed,
                'options':[{'version':3,'name':'기본 순환 경로','routes':preview(catalog)},
                           {'version':4,'name':'작업대 간 단축 경로','routes':preview(compact)}],
                'active':[{'robot_id':s['robot_id'],'route_version':s.get('route_version',4)}
                          for s in e.state['sessions'].values() if s['state'] not in ('COMPLETED','ERROR')]}

    @app.post('/api/admin/field/routes', dependencies=[Depends(admin)])
    def select_field_route(body: FieldRouteSelection, e=Depends(control)):
        if not isinstance(e, DistributedEngine):
            raise HTTPException(409,'분산 관제에서 경로를 선택합니다')
        return e.select_field_route(body.version)

    @app.get("/api/admin/logs", dependencies=[Depends(admin)])
    def logs(e=Depends(control)):
        return {"items": e.logs()}

    @app.post('/api/admin/field/commands/{command_id}/observe', dependencies=[Depends(admin)])
    def field_observe(command_id: str, body: FieldObservation, e=Depends(control)):
        if not isinstance(e, DistributedEngine):
            raise HTTPException(409, '분산 중계 연결이 필요합니다')
        return e.field_observe(command_id, body.observation, body.operator)

    @app.post('/api/admin/field/robots/{robot_id}/stop', dependencies=[Depends(admin)])
    def field_stop(robot_id: str, e=Depends(control)):
        if not isinstance(e, DistributedEngine):
            raise HTTPException(409, '분산 중계 연결이 필요합니다')
        return e.field_stop(robot_id)

    @app.get('/api/admin/device-tests', dependencies=[Depends(admin)])
    def tests(e=Depends(control)):
        return Bench(e).snapshot()

    @app.get('/api/admin/motion-map', dependencies=[Depends(admin)])
    def motion_map():
        from robots.pinky.catalog import public_map
        return public_map()

    @app.post('/api/admin/device-tests', dependencies=[Depends(admin)])
    def test_create(body: TestRequest, e=Depends(control)):
        return Bench(e).create(body.node_id, body.kind, body.parameters, body.request_id, body.prepared, body.simulate_failure)

    @app.post('/api/admin/device-tests/{jid}/stop', dependencies=[Depends(admin)])
    def test_stop(jid: str, e=Depends(control)):
        return Bench(e).stop(jid)

    @app.post('/api/admin/device-tests/{jid}/observe', dependencies=[Depends(admin)])
    def test_observe(jid: str, body: TestObservation, e=Depends(control)):
        return Bench(e).observe(jid, body.operator, body.facts)

    @app.post('/api/admin/device-tests/{jid}/review', dependencies=[Depends(admin)])
    def test_review(jid: str, body: TestReview, e=Depends(control)):
        return Bench(e).review(jid, **body.model_dump())

    @app.post('/api/admin/device-tests/{jid}/release', dependencies=[Depends(admin)])
    def test_release(jid: str, body: TestRelease, e=Depends(control)):
        return Bench(e).release(jid, body.operator, body.restored)

    @app.post('/api/nodes/device-tests/poll')
    def test_poll(body: TestPoll, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        if body.mode != e.mode:
            raise HTTPException(409, '시험 실행 모드 불일치')
        return Bench(e).poll(principal, body.instance_id, body.profile, body.available)

    @app.post('/api/nodes/device-tests/events')
    def test_event(body: TestEvent, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        if body.mode != e.mode:
            raise HTTPException(409, '시험 결과 모드 불일치')
        return Bench(e).event(principal, body.instance_id, body.job_id, body.event_id, body.kind, body.data)

    def reference_engine(e):
        if 'road' not in e.state:
            raise HTTPException(409, 'v4 주문 통합 실행이 아닙니다')
        return e

    @app.get('/api/admin/road', dependencies=[Depends(admin)])
    def road(e=Depends(control)):
        return reference_engine(e).motion_snapshot()

    @app.get('/api/admin/road/map', dependencies=[Depends(admin)])
    def road_map(e=Depends(control)):
        reference_engine(e)
        from robots.pinky.compact import public_map
        return public_map()

    @app.post('/api/admin/road/stop', dependencies=[Depends(admin)])
    def road_stop(e=Depends(control)):
        return reference_engine(e).motion_stop()

    @app.post('/api/admin/road/failure', dependencies=[Depends(admin)])
    def road_failure(e=Depends(control)):
        return reference_engine(e).motion_failure()

    @app.post('/api/nodes/motion/poll')
    def road_poll(body: TestPoll, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        if body.mode != e.mode: raise HTTPException(409, '이동 실행 모드 불일치')
        return reference_engine(e).motion_poll(principal, body.instance_id, body.profile, body.available)

    @app.post('/api/nodes/motion/events')
    def road_event(body: TestEvent, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        if body.mode != e.mode: raise HTTPException(409, '이동 결과 모드 불일치')
        return reference_engine(e).motion_event(principal, body.instance_id, body.job_id, body.event_id, body.kind, body.data)

    @app.get('/api/admin/video', dependencies=[Depends(admin)])
    def video_list():
        return {'items': video.describe()}

    @app.get('/api/admin/video/{feed_id}/frame', dependencies=[Depends(admin)])
    def video_frame(feed_id: str):
        content, media_type, headers = video.frame(feed_id)
        return Response(content, media_type=media_type, headers=headers)

    @app.post('/api/admin/video/{feed_id}/mock-fault', dependencies=[Depends(admin)])
    def video_fault(feed_id: str, body: VideoFault):
        video.fault(feed_id, body.kind)
        return {'recorded': True}

    async def read_frame(request):
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > video.max_bytes:
                raise HTTPException(413, '프레임은 512KiB 이하여야 합니다')
            chunks.append(chunk)
        return b''.join(chunks)

    @app.post('/api/nodes/video/{feed_id}/frame')
    async def node_video(feed_id: str, request: Request, instance_id: str, sequence: int,
                         principal=Depends(node_auth), e=Depends(control)):
        e.node_work(principal, instance_id)
        content = await read_frame(request)
        e.node_work(principal, instance_id)
        video.publish(feed_id, principal, instance_id, sequence, content)
        return {'received': True}

    @app.post('/api/admin/video/{feed_id}/frame', dependencies=[Depends(admin)])
    async def central_video(feed_id: str, request: Request, instance_id: str, sequence: int):
        from .video import OWNERS
        if feed_id not in OWNERS:
            raise HTTPException(404, '영상 채널을 찾을 수 없습니다')
        video.publish(feed_id, OWNERS[feed_id], instance_id, sequence, await read_frame(request))
        return {'received': True}

    @app.post('/api/video/overview/frame')
    async def overview_video(request: Request, instance_id: str, sequence: int,
                             credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        expected = os.getenv('SHOP_OVERVIEW_TOKEN', '')
        if len(expected) < 16 or not hmac.compare_digest(token_value(credentials), expected):
            raise HTTPException(401, '전경 영상 게시 인증 실패')
        video.publish('overview', 'central', instance_id, sequence, await read_frame(request))
        return {'received': True}

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
    def new_run(body: NewRun, e=Depends(control)):
        return e.reset_mock(body.acknowledge_unresolved)

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
    def node_heartbeat(body: NodeHeartbeat, principal=Depends(node_auth), e=Depends(control)):
        owned(body, principal)
        if body.mode != e.mode:
            raise HTTPException(409, '중계와 중앙의 장비 모드가 다릅니다')
        result = e.node_heartbeat(body.node_id, body.instance_id, body.role)
        if body.motion:
            e.report_motion(body.node_id, body.instance_id, body.motion)
        return result

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
