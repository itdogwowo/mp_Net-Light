# /action/file_actions.py
from lib.schema_loader import cmd_str_to_int

CMD_FILE_BEGIN = cmd_str_to_int("0x2001")
CMD_FILE_CHUNK = cmd_str_to_int("0x2002")
CMD_FILE_END   = cmd_str_to_int("0x2003")

def register(app):
    def on_begin(ctx, args):
        ok = app.file_rx.begin(args)
        print("FILE_BEGIN:", "OK" if ok else ("FAIL " + str(app.file_rx.last_error)))

    def on_chunk(ctx, args):
        ok = app.file_rx.chunk(args)
        if not ok:
            print("FILE_CHUNK FAIL:", app.file_rx.last_error)

    def on_end(ctx, args):
        ok = app.file_rx.end(args)
        print("FILE_END:", "OK" if ok else ("FAIL " + str(app.file_rx.last_error)))

    app.disp.on(CMD_FILE_BEGIN, on_begin)
    app.disp.on(CMD_FILE_CHUNK, on_chunk)
    app.disp.on(CMD_FILE_END, on_end)