"""Ogni strumento di DeepSeek deve rispondere senza sollevare eccezioni e
restare serializzabile in JSON, anche con gli store vuoti (task #324)."""
import json

from app import main


def test_deepseek_tools_all_callable_and_serializable():
    tools = main._deepseek_tools()
    assert tools, "no tools"
    for name, (spec, fn) in tools.items():
        assert isinstance(spec, dict) and spec.get("name") == name
        if name == "segnala_bug":
            continue                      # writes on the board: not a read
        required = spec.get("parameters", {}).get("required") or []
        result = fn(**{k: "X" for k in required})
        json.dumps(result, default=str)
