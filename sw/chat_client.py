#!/usr/bin/env python3
"""chat_client.py — readline REPL / one-shot client for sw/serve.py.

stdlib only (http.client + readline): it runs in sw/.venv, in the system
python, or over an ssh tunnel from a laptop with nothing installed.

    ./.venv/bin/python chat_client.py                       # REPL
    ./.venv/bin/python chat_client.py --prompt "hello"      # one-shot
    ./.venv/bin/python chat_client.py --session alice --max-tokens 16

The server binds 127.0.0.1 only, so from another machine:

    ssh -N -L 8137:127.0.0.1:8137 snoke

REPL commands:  /reset  /health  /metrics  /sessions  /session NAME
                /ntok N  /raw  /help  /quit          (Ctrl-D also quits)

What it prints while a turn runs:
  queued 2 (eta ~21s)      you are behind other clients — the board is ONE
                           context and the server serves strictly FIFO
  prefill 7/12 139 ms      one launch per prompt token (lite body)
  <text>                   streamed detokenized deltas, live
  [12 tok in 2.0s | 5.98 tok/s | decode 156.2 ms/step | ctx 19/500 (4%)]
"""
import argparse
import http.client
import json
import os
import sys
import time

DEFAULT_PORT = 8137
CLEAR = "\r" + " " * 72 + "\r"


class ClientError(RuntimeError):
    pass


class Client(object):
    def __init__(self, host="127.0.0.1", port=DEFAULT_PORT, timeout=900.0):
        self.host, self.port, self.timeout = host, port, float(timeout)

    def _conn(self):
        return http.client.HTTPConnection(self.host, self.port,
                                          timeout=self.timeout)

    # ---------------------------------------------------- plain JSON
    def request(self, method, path, obj=None):
        c = self._conn()
        try:
            body = None if obj is None else json.dumps(obj).encode()
            hdrs = {"Accept": "application/json"}
            if body is not None:
                hdrs["Content-Type"] = "application/json"
            c.request(method, path, body=body, headers=hdrs)
            r = c.getresponse()
            raw = r.read()
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                data = {"error": raw.decode("utf-8", "replace")[:400]}
            return r.status, data
        except (OSError, http.client.HTTPException) as e:
            raise ClientError("cannot reach http://%s:%d — is serve.py "
                              "running?  (%s)" % (self.host, self.port, e))
        finally:
            c.close()

    def get(self, path):
        return self.request("GET", path)

    # ---------------------------------------------------- SSE
    def stream(self, prompt, session_id="default", max_tokens=None,
               on_event=None):
        """POST /v1/generate and yield (event_name, data) as they arrive."""
        body = {"prompt": prompt, "session_id": session_id}
        if max_tokens is not None:
            body["max_tokens"] = int(max_tokens)
        c = self._conn()
        try:
            c.request("POST", "/v1/generate", body=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json",
                               "Accept": "text/event-stream"})
            r = c.getresponse()
            if r.status != 200:
                raw = r.read().decode("utf-8", "replace")
                try:
                    msg = json.loads(raw).get("error", raw)
                except ValueError:
                    msg = raw.strip()
                raise ClientError("HTTP %d: %s" % (r.status, msg))
            name, data = None, []
            while True:
                line = r.readline()
                if not line:
                    break
                line = line.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith(":"):            # keepalive comment
                    continue
                if line == "":
                    if name is not None:
                        try:
                            obj = json.loads("\n".join(data)) if data else {}
                        except ValueError:
                            obj = {"raw": "\n".join(data)}
                        if on_event is not None:
                            on_event(name, obj)
                        yield name, obj
                    name, data = None, []
                    continue
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
        except (OSError, http.client.HTTPException) as e:
            raise ClientError("stream failed: %s" % e)
        finally:
            c.close()


# ======================================================================
def run_turn(cli, prompt, session, ntok, raw=False, out=sys.stdout):
    """One turn, printed live.  Returns the stats dict (or None on error).

    On a tty the queue/prefill progress rewrites one line with \\r; piped to
    a file (tests, evidence logs) it prints whole lines and reports prefill
    only on the first and last step, so a transcript stays readable.
    """
    tty = hasattr(out, "isatty") and out.isatty()
    clear = CLEAR if tty else ""
    nl = "" if tty else "\n"
    t0 = time.monotonic()
    stats = None
    printed_any = False
    for name, d in cli.stream(prompt, session, ntok):
        if raw:
            out.write("[%s] %s\n" % (name, json.dumps(d, sort_keys=True)))
            out.flush()
            if name == "stats":
                stats = d
            continue
        if name == "queue":
            eta = d.get("eta_s")
            out.write(clear + "  queued %s%s — the board is ONE context%s"
                      % (d.get("position"),
                         "" if eta is None else " (eta ~%.0fs)" % eta, nl))
            out.flush()
        elif name == "start":
            bits = []
            if d.get("reset"):
                bits.append("context reset")
            if d.get("replayed"):
                bits.append("replaying %d history tokens" % d["replayed"])
            bits.append("%d prompt tokens" % d.get("prompt_tokens", 0))
            bits.append("%d steps" % d.get("steps", 0))
            if d.get("mock"):
                bits.append("MOCK")
            out.write(clear + "  " + ", ".join(bits) + "\n")
            out.flush()
        elif name == "prefill":
            i, n = d.get("index", 0), d.get("total", 0)
            if tty or i in (1, n):
                out.write(clear + "  prefill %d/%d  %.0f ms/step (%s)%s"
                          % (i, n, d.get("device_ms", 0.0),
                             "lite" if d.get("lite") else "full", nl))
                out.flush()
        elif name == "token":
            if not printed_any:
                out.write(clear + ("" if tty else "  "))
                printed_any = True
            out.write(d.get("text", ""))
            out.flush()
        elif name == "stats":
            stats = d
            if not printed_any:
                out.write(clear)
            out.write("\n" + stats_line(d) + "\n")
            out.flush()
        elif name == "error":
            out.write(clear + "  *** %s (%s)\n"
                      % (d.get("error", "?"), d.get("type", "?")))
            out.flush()
            return None
    if stats is None and not raw:
        out.write("  *** stream ended without a stats event after %.1fs\n"
                  % (time.monotonic() - t0))
    return stats


def stats_line(d):
    fill = d.get("context_fill")
    return ("  [%d tok in %.2fs | %s tok/s | prefill %s x %s ms | decode %s x "
            "%s ms | device %s ms (%s of wall) | ctx %s/%s (%s) | stop %s%s]"
            % (d.get("tokens", 0), d.get("wall_s", 0.0),
               d.get("tok_per_s"), d.get("prefill_steps"),
               d.get("prefill_ms_mean"), d.get("decode_steps"),
               d.get("decode_ms_mean"), d.get("device_ms_total"),
               ("%.0f%%" % (100 * d["device_frac"]))
               if d.get("device_frac") is not None else "?",
               d.get("context_used"), d.get("context_max"),
               ("%.0f%%" % (100 * fill)) if fill is not None else "?",
               d.get("stop"), " | MOCK" if d.get("mock") else ""))


def show(title, code, data, out=sys.stdout):
    out.write("  %s (HTTP %d)\n%s\n"
              % (title, code, json.dumps(data, indent=1, sort_keys=True)))
    out.flush()


def repl(cli, args):
    try:
        import readline                                        # noqa: F401
        hist = os.path.expanduser("~/.fable5_chat_history")
        try:
            readline.read_history_file(hist)
        except OSError:
            pass
    except ImportError:                                        # pragma: no cover
        hist = None
    code, h = cli.get("/v1/health")
    print("connected to http://%s:%d — %s%s"
          % (cli.host, cli.port, h.get("status", "?"),
             " [MOCK BACKEND]" if h.get("mock") else ""))
    if h.get("backend", {}).get("version"):
        print("  board VERSION %s  MAGIC %s  CALIB %s"
              % (h["backend"].get("version"), h["backend"].get("magic"),
                 h["backend"].get("calib")))
    session, ntok, raw = args.session, args.max_tokens, args.raw
    print("  session %r, max_tokens %s.  /help for commands." % (session, ntok))
    while True:
        try:
            line = input("\n%s> " % session).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/quit", "/q", "/exit"):
            break
        if line == "/help":
            print("  /reset            drop this session's history\n"
                  "  /session NAME     switch session (resets + replays)\n"
                  "  /ntok N           max_tokens for the next turns\n"
                  "  /health /metrics /sessions   server introspection\n"
                  "  /raw              toggle raw SSE event dump\n"
                  "  /quit")
            continue
        if line == "/reset":
            show("reset", *cli.request("POST", "/v1/reset",
                                       {"session_id": session}))
            continue
        if line == "/health":
            show("health", *cli.get("/v1/health"))
            continue
        if line == "/metrics":
            show("metrics", *cli.get("/v1/metrics"))
            continue
        if line == "/sessions":
            show("sessions", *cli.get("/v1/sessions"))
            continue
        if line == "/raw":
            raw = not raw
            print("  raw events %s" % ("on" if raw else "off"))
            continue
        if line.startswith("/session"):
            p = line.split()
            if len(p) != 2:
                print("  usage: /session NAME")
            else:
                session = p[1]
                print("  session %r (the next turn resets the board context "
                      "and replays this session's history)" % session)
            continue
        if line.startswith("/ntok"):
            p = line.split()
            try:
                ntok = int(p[1])
                print("  max_tokens = %d" % ntok)
            except (IndexError, ValueError):
                print("  usage: /ntok N")
            continue
        if line.startswith("/"):
            print("  unknown command %r (/help)" % line)
            continue
        try:
            run_turn(cli, line, session, ntok, raw=raw)
        except ClientError as e:
            print("  *** %s" % e)
    if hist:
        try:
            import readline
            readline.write_history_file(hist)
        except (OSError, ImportError):                          # pragma: no cover
            pass


def main():
    ap = argparse.ArgumentParser(
        description="readline/SSE client for sw/serve.py (stdlib only).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--session", default="default")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="default: whatever the server's default is")
    ap.add_argument("--prompt", action="append", default=[],
                    help="one-shot turn (repeatable); no REPL")
    ap.add_argument("--reset", action="store_true",
                    help="POST /v1/reset for --session first")
    ap.add_argument("--health", action="store_true", help="GET /v1/health")
    ap.add_argument("--metrics", action="store_true", help="GET /v1/metrics")
    ap.add_argument("--raw", action="store_true",
                    help="dump every SSE event verbatim")
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()

    cli = Client(args.host, args.port, args.timeout)
    try:
        if args.health:
            show("health", *cli.get("/v1/health"))
        if args.metrics:
            show("metrics", *cli.get("/v1/metrics"))
        if args.reset:
            show("reset", *cli.request("POST", "/v1/reset",
                                       {"session_id": args.session}))
        if args.prompt:
            rc = 0
            for p in args.prompt:
                print("\n%s> %s" % (args.session, p))
                st = run_turn(cli, p, args.session, args.max_tokens,
                              raw=args.raw)
                if st is None:
                    rc = 1
            raise SystemExit(rc)
        if args.health or args.metrics or args.reset:
            return
        repl(cli, args)
    except ClientError as e:
        print("*** %s" % e)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
