"""Records what every Claude call costs (data/claude_usage.jsonl), using the token counts Anthropic
returns with each reply. Adds no API calls. A logging problem never affects the run."""
import datetime as dt
import json
from pathlib import Path

USAGE_PATH = Path(__file__).parent.parent / "data" / "claude_usage.jsonl"
PRICE_IN, PRICE_OUT = 1.00, 5.00  # US dollars per million tokens, Claude Haiku 4.5


def record(message, purpose, model):
    try:
        u = message.usage
        tokens_in = (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        tokens_out = u.output_tokens or 0
        entry = {"time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "purpose": purpose, "model": model,
                 "in": tokens_in, "out": tokens_out, "usd": round((tokens_in * PRICE_IN + tokens_out * PRICE_OUT) / 1e6, 6)}
        with USAGE_PATH.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
