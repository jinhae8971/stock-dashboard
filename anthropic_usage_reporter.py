"""
Anthropic Usage Reporter
========================
Drop-in module that reports token usage from anthropic.Messages.create()
to a central GitHub repo via repository_dispatch.

Usage (2 lines added to existing code):

    from anthropic_usage_reporter import report_usage
    # ... after each client.messages.create() call:
    report_usage(response, workflow_name="kospi-strategy")

Or use the wrapper context manager / decorator for automatic capture.

Required environment variables (set as GitHub Secrets):
    USAGE_DISPATCH_TOKEN : GitHub PAT with `repo` scope on dashboard repo
    USAGE_DISPATCH_REPO  : Default "jinhae8971/github-actions-dashboard"
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("anthropic_usage_reporter")

DASHBOARD_REPO = os.environ.get(
    "USAGE_DISPATCH_REPO", "jinhae8971/github-actions-dashboard"
)
DISPATCH_TOKEN = os.environ.get("USAGE_DISPATCH_TOKEN", "").strip()
GITHUB_REPO_ENV = os.environ.get("GITHUB_REPOSITORY", "")  # owner/repo on Actions
GITHUB_WORKFLOW_ENV = os.environ.get("GITHUB_WORKFLOW", "")
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "")

# Local pricing table (USD per million tokens). Update as needed.
# Reference: Anthropic pricing page; values are rough and only used for cost
# estimation — the source of truth is your Anthropic Console.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7":    {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
    "claude-opus-4-6":    {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
    "claude-sonnet-4-6":  {"input": 3.0,  "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4-5":  {"input": 3.0,  "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5":   {"input": 1.0,  "output": 5.0,  "cache_read": 0.10, "cache_write": 1.25},
    "claude-haiku-3-5":   {"input": 0.80, "output": 4.0,  "cache_read": 0.08, "cache_write": 1.0},
    # Generic fallbacks for unknown date-stamped variants
    "opus":   {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
    "sonnet": {"input": 3.0,  "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "haiku":  {"input": 1.0,  "output": 5.0,  "cache_read": 0.10, "cache_write": 1.25},
}


def _resolve_pricing(model: str) -> dict[str, float]:
    """Find pricing entry matching the model string."""
    if not model:
        return PRICING["sonnet"]
    # Strip date suffix (e.g. claude-sonnet-4-6-20250101 → claude-sonnet-4-6)
    base = model.lower()
    base = base.split("@")[0]  # drop anthropic-vertex suffix
    if base in PRICING:
        return PRICING[base]
    # Try without trailing date
    parts = base.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) >= 6:
        no_date = parts[0]
        if no_date in PRICING:
            return PRICING[no_date]
    # Fallback by family
    for family in ("opus", "sonnet", "haiku"):
        if family in base:
            return PRICING[family]
    return PRICING["sonnet"]


def _estimate_cost(model: str, usage: dict[str, int]) -> float:
    p = _resolve_pricing(model)
    cost = 0.0
    cost += usage.get("input_tokens", 0) / 1_000_000 * p["input"]
    cost += usage.get("output_tokens", 0) / 1_000_000 * p["output"]
    cost += usage.get("cache_read_input_tokens", 0) / 1_000_000 * p["cache_read"]
    cost += usage.get("cache_creation_input_tokens", 0) / 1_000_000 * p["cache_write"]
    return round(cost, 6)


def _extract_usage(response: Any) -> dict[str, int]:
    """Extract usage dict from anthropic.types.Message or raw dict."""
    if hasattr(response, "usage"):
        u = response.usage
        return {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }
    if isinstance(response, dict):
        u = response.get("usage", {}) or {}
        return {
            "input_tokens": int(u.get("input_tokens", 0) or 0),
            "output_tokens": int(u.get("output_tokens", 0) or 0),
            "cache_read_input_tokens": int(u.get("cache_read_input_tokens", 0) or 0),
            "cache_creation_input_tokens": int(u.get("cache_creation_input_tokens", 0) or 0),
        }
    return {"input_tokens": 0, "output_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def _extract_model(response: Any) -> str:
    if hasattr(response, "model"):
        return getattr(response, "model", "") or ""
    if isinstance(response, dict):
        return response.get("model", "") or ""
    return ""


def report_usage(
    response: Any = None,
    *,
    model: str | None = None,
    usage: dict[str, int] | None = None,
    workflow: str | None = None,
    repo: str | None = None,
    tag: str | None = None,
    silent: bool = True,
    max_retries: int = 2,
) -> bool:
    """
    Report a single API call's usage to the central dashboard.

    Args:
        response: anthropic.types.Message (preferred), or raw dict
        model: override model name
        usage: override usage dict
        workflow: friendly workflow identifier (e.g. "daily-kospi-strategy")
        repo: override repo name (defaults to GITHUB_REPOSITORY env)
        tag: optional sub-tag (e.g. "scanner", "decision", "executor")
        silent: if True, swallow all errors (default — don't break user code)
        max_retries: HTTP retry count
    Returns:
        True if dispatch accepted; False otherwise.
    """
    try:
        if response is not None:
            model = model or _extract_model(response)
            usage = usage or _extract_usage(response)

        if not usage or not model:
            if not silent:
                log.warning("report_usage: missing model/usage; skipped.")
            return False

        if not DISPATCH_TOKEN:
            if not silent:
                log.warning("USAGE_DISPATCH_TOKEN not set; skipping report.")
            return False

        owner_repo = repo or GITHUB_REPO_ENV or "unknown/unknown"
        repo_name = owner_repo.split("/")[-1] if "/" in owner_repo else owner_repo

        # NOTE: GitHub repository_dispatch limits client_payload to 10 properties.
        # We combine cache_read + cache_create into cache_tokens, and drop run_id
        # (not used by dashboard). This stays under the limit.
        payload = {
            "event_type": "anthropic-usage",
            "client_payload": {
                "ts": datetime.now(timezone.utc).isoformat(),
                "repo": repo_name,
                "workflow": workflow or GITHUB_WORKFLOW_ENV or "(unknown)",
                "tag": tag or "",
                "model": model,
                "input_tokens": int(usage.get("input_tokens", 0)),
                "output_tokens": int(usage.get("output_tokens", 0)),
                "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0)),
                "cache_create_tokens": int(usage.get("cache_creation_input_tokens", 0)),
                "estimated_usd": _estimate_cost(model, usage),
            },
        }

        url = f"https://api.github.com/repos/{DASHBOARD_REPO}/dispatches"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {DISPATCH_TOKEN}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        attempt = 0
        while attempt <= max_retries:
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status in (204, 200):
                        return True
                    if not silent:
                        log.warning("Dispatch HTTP %s: %s", resp.status, resp.read()[:200])
                    return False
            except urllib.error.HTTPError as e:
                if e.code in (502, 503, 504) and attempt < max_retries:
                    time.sleep(0.5 * (2 ** attempt))
                    attempt += 1
                    continue
                if not silent:
                    log.warning("Dispatch HTTPError %s: %s", e.code, e.read()[:200])
                return False
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(0.5 * (2 ** attempt))
                    attempt += 1
                    continue
                if not silent:
                    log.warning("Dispatch error: %s", e)
                return False
        return False

    except Exception as e:
        if not silent:
            log.exception("report_usage failed: %s", e)
        return False


# -----------------------------------------------------------------------------
# Convenience: monkey-patch anthropic client (opt-in)
# -----------------------------------------------------------------------------
def patch_anthropic_client(workflow: str | None = None) -> None:
    """
    Monkey-patch anthropic.Messages.create so EVERY call auto-reports.
    Call once at the top of your script:

        from anthropic_usage_reporter import patch_anthropic_client
        patch_anthropic_client(workflow="kospi-strategy")
    """
    try:
        import anthropic  # type: ignore
        from anthropic.resources.messages import Messages  # type: ignore

        if getattr(Messages, "_usage_patched", False):
            return

        orig_create = Messages.create

        def patched_create(self, *args, **kwargs):
            response = orig_create(self, *args, **kwargs)
            try:
                report_usage(response, workflow=workflow, silent=True)
            except Exception:
                pass
            return response

        Messages.create = patched_create  # type: ignore
        Messages._usage_patched = True  # type: ignore
        log.info("anthropic.Messages.create patched for usage reporting.")
    except ImportError:
        log.debug("anthropic package not installed; skip patching.")
    except Exception as e:
        log.warning("Failed to patch anthropic client: %s", e)


if __name__ == "__main__":
    # Self-test
    fake_response = {
        "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 1000, "output_tokens": 500,
                  "cache_read_input_tokens": 200, "cache_creation_input_tokens": 50},
    }
    print("Test report:", report_usage(fake_response, workflow="test", silent=False))
    print("Estimated USD:", _estimate_cost("claude-sonnet-4-6", {"input_tokens": 1000, "output_tokens": 500}))
