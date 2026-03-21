import time
from lib.proto import Proto
from lib.schema_codec import SchemaCodec


_state = {
    "active": False,
    "run_id": 0,
    "start_ms": 0,
    "last_report_ms": 0,
    "report_interval_ms": 1000,
    "total_bytes": 0,
    "total_chunks": 0,
    "last_seq": 0,
}


def _ticks_ms():
    return time.ticks_ms()


def _elapsed_ms(now_ms, start_ms):
    return time.ticks_diff(now_ms, start_ms)


def _send_report(ctx, final=False):
    if "send" not in ctx:
        return
    app = ctx.get("app")
    if not app:
        return

    now = _ticks_ms()
    elapsed = _elapsed_ms(now, _state["start_ms"]) if _state["active"] else 0

    cmd_def = app.store.get(0x1804)
    payload = SchemaCodec.encode(
        cmd_def,
        {
            "run_id": int(_state["run_id"]),
            "elapsed_ms": int(elapsed),
            "total_bytes": int(_state["total_bytes"]) & 0xFFFFFFFF,
            "total_chunks": int(_state["total_chunks"]) & 0xFFFFFFFF,
            "last_seq": int(_state["last_seq"]) & 0xFFFFFFFF,
        },
    )
    ctx["send"](Proto.pack(0x1804, payload))

    if final:
        _state["last_report_ms"] = now


def on_net_bench_start(ctx, args):
    run_id = int(args.get("run_id", 0))
    interval = int(args.get("report_interval_ms", 1000))

    _state["active"] = True
    _state["run_id"] = run_id
    _state["start_ms"] = _ticks_ms()
    _state["last_report_ms"] = _state["start_ms"]
    _state["report_interval_ms"] = interval if interval > 0 else 1000
    _state["total_bytes"] = 0
    _state["total_chunks"] = 0
    _state["last_seq"] = 0

    _send_report(ctx)


def on_net_bench_chunk(ctx, args):
    if not _state["active"]:
        return
    if int(args.get("run_id", 0)) != int(_state["run_id"]):
        return

    data = args.get("data")
    ln = len(data) if data else 0

    _state["total_bytes"] += ln
    _state["total_chunks"] += 1
    _state["last_seq"] = int(args.get("seq", _state["last_seq"]))

    now = _ticks_ms()
    if _elapsed_ms(now, _state["last_report_ms"]) >= _state["report_interval_ms"]:
        _state["last_report_ms"] = now
        _send_report(ctx)


def on_net_bench_stop(ctx, args):
    if not _state["active"]:
        return
    if int(args.get("run_id", 0)) != int(_state["run_id"]):
        return

    _send_report(ctx, final=True)
    _state["active"] = False


def register(app):
    app.disp.on(0x1801, on_net_bench_start)
    app.disp.on(0x1802, on_net_bench_chunk)
    app.disp.on(0x1803, on_net_bench_stop)
