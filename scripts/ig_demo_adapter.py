"""IG CFD demo-only API client. Never accepts production endpoints or credentials."""
import os
import json
import urllib.request

DEMO_BASE = "https://demo-api.ig.com/gateway/deal"

class DemoOnlyError(RuntimeError):
    pass

def demo_config():
    if os.getenv("TRADELAB_LIVE_TRADING", "").lower() in ("true", "1", "yes"):
        raise DemoOnlyError("Live trading is prohibited in this adapter")
    key = os.getenv("IG_DEMO_API_KEY")
    token = os.getenv("IG_DEMO_CST")
    security = os.getenv("IG_DEMO_SECURITY_TOKEN")
    if not all((key, token, security)):
        raise DemoOnlyError("Missing IG demo credentials; no order sent")
    return {"X-IG-API-KEY": key, "CST": token,
            "X-SECURITY-TOKEN": security, "Content-Type": "application/json",
            "Accept": "application/json", "VERSION": "2"}

def demo_positions():
    headers = demo_config()
    request = urllib.request.Request(DEMO_BASE + "/positions", headers=headers)
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)

def validate_candidate(signal, *, risk_gbp, max_risk_gbp=25):
    """Gate before any later demo order integration; no order endpoint here."""
    if signal.get("mode") != "PAPER_ONLY":
        raise DemoOnlyError("Only paper signals are permitted")
    if signal.get("signal") not in ("BUY", "SELL"):
        raise DemoOnlyError("No trade signal")
    if not 0 < risk_gbp <= max_risk_gbp:
        raise DemoOnlyError("Risk limit exceeded")
    entry, stop, target = (float(signal[k]) for k in ("entry", "stop", "target"))
    if signal["signal"] == "BUY" and not (stop < entry < target):
        raise DemoOnlyError("Invalid long levels")
    if signal["signal"] == "SELL" and not (target < entry < stop):
        raise DemoOnlyError("Invalid short levels")
    if abs(target - entry) < 2 * abs(entry - stop):
        raise DemoOnlyError("Reward/risk below 2:1")
    return True
