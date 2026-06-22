from common.identity import clean_suggested_slug, normkey, slugify
from daemon import orchestrator
from daemon import web_discovery as wd
from mcp_server.discovery_server import _passes_keyword_filter


# --- identity resolution -------------------------------------------------------------

def test_normkey_collapses_namespaces_and_separators():
    assert normkey("google/gemini-2.5-flash-lite") == normkey("Gemini 2.5 Flash Lite")
    assert normkey("meta-llama/llama-3.3-70b-instruct") == normkey("Llama 3.3 70B Instruct")
    assert normkey("qwen/qwen3-max") == normkey("Qwen 3 Max") == normkey("qwen3max")


def test_normkey_distinguishes_real_differences():
    assert normkey("openai/gpt-4o") != normkey("openai/gpt-4")


def test_slugify_mirrors_openrouter_namespace():
    assert slugify("DeepSeek", "DeepSeek V3.2") == "deepseek/deepseek-v3.2"
    assert slugify("Moonshot AI", "Kimi K2") == "moonshot-ai/kimi-k2"


def test_clean_suggested_slug():
    assert clean_suggested_slug("Vendor/Model-X") == "vendor/model-x"
    assert clean_suggested_slug("not a slug") is None
    assert clean_suggested_slug("a/b/c") is None  # only vendor/model shape allowed
    assert clean_suggested_slug(None) is None


# --- the isolation invariant (web tools must not leak into the eval surfaces) ---------

def test_web_allowlist_has_web_tools_but_not_eval_tools():
    assert "WebSearch" in wd.DISC_ALLOW and "WebFetch" in wd.DISC_ALLOW
    assert "mcp__kelp_disc__record_discovered_model" in wd.DISC_ALLOW
    # the key-bearing eval tool must be UNREACHABLE from the web agent
    assert "measured_candidate_call" not in wd.DISC_ALLOW
    assert "mcp__kelp__" not in wd.DISC_ALLOW


def test_eval_surface_still_forbids_web():
    assert "WebSearch" in orchestrator.DENY_TOOLS and "WebFetch" in orchestrator.DENY_TOOLS
    assert "WebSearch" not in orchestrator.ALLOWED  # eval allowlist is kelp tools only


def test_build_web_cmd_flags():
    cmd = wd.build_web_cmd("PROMPT", "/tmp/cfg.json", model="claude-sonnet-4-6", max_turns=7)
    allow = cmd[cmd.index("--allowedTools") + 1]
    deny = cmd[cmd.index("--disallowedTools") + 1]
    assert "WebSearch" in allow and "measured_candidate_call" not in allow
    assert "WebSearch" not in deny and "Bash" in deny   # web allowed, shell denied
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == "/tmp/cfg.json"
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-4-6"
    assert cmd[cmd.index("--max-turns") + 1] == "7"


# --- relevance keyword backstop ------------------------------------------------------

def test_keyword_filter():
    assert _passes_keyword_filter("Llama 4 Scout", "MoE, 10M context, open weights") is True
    assert _passes_keyword_filter("BGE embedding model", None) is False
    assert _passes_keyword_filter("Some Reranker v2", None) is False
    assert _passes_keyword_filter("Whisper Large v4", None) is False


# --- summary parsing -----------------------------------------------------------------

def test_parse_summary():
    assert wd._parse_summary('{"recorded":2,"skipped_known":1,"notes":"ok"}')["recorded"] == 2
    assert wd._parse_summary('```json\n{"recorded":0}\n```')["recorded"] == 0
    assert wd._parse_summary("garbage") == {}
    assert wd._parse_summary(None) == {}
