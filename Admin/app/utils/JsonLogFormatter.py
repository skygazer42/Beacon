import json
import logging
from datetime import datetime, timezone


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        """处理`format`。"""
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Best-effort: include OpenTelemetry trace context if available.
        #
        # This enables log -> trace correlation in industrial deployments without
        # making tracing a hard dependency for logging.
        try:
            from opentelemetry import trace  # type: ignore
        except ImportError:
            trace = None

        if trace is not None:
            try:
                span = trace.get_current_span()
                ctx = span.get_span_context() if span else None
                if ctx and getattr(ctx, "is_valid", False):
                    try:
                        payload["trace_id"] = format(int(ctx.trace_id), "032x")
                        payload["span_id"] = format(int(ctx.span_id), "016x")
                    except Exception:
                        payload.pop("trace_id", None)
                        payload.pop("span_id", None)
            except Exception:
                payload.pop("trace_id", None)
                payload.pop("span_id", None)

        try:
            payload["module"] = record.module
            payload["func"] = record.funcName
            payload["line"] = record.lineno
        except Exception:
            payload.pop("module", None)
            payload.pop("func", None)
            payload.pop("line", None)

        if record.exc_info:
            try:
                payload["exc_info"] = self.formatException(record.exc_info)
            except Exception:
                payload["exc_info"] = "exception"

        return json.dumps(payload, ensure_ascii=False, default=str)
