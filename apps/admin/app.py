"""Admin Streamlit app — the localhost control surface (phase 3/POC).

This is the human-in-the-loop surface: approve/skip discovered models, enqueue benchmarks,
enter provider keys, trigger a catalog sync, and monitor runs/logs. It REPLACES Teams inbound
(which needs premium Power Automate); Teams stays the outbound notification channel.

Security: bind to loopback only — physical access is the auth, and this app writes keys +
enqueues spend. Run:
    uv run streamlit run apps/admin/app.py --server.address 127.0.0.1
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # make the project importable under `streamlit run`

import pandas as pd
import streamlit as st

from common import keys as keystore
from common import repo
from common.config import settings
from common.db import connect

USECASES_DIR = ROOT / "usecases"

st.set_page_config(page_title="Kelp Admin", layout="wide")
st.title("Kelp — Admin Console")
st.caption("Localhost control surface · physical access = auth · writes keys and enqueues spend.")
if st.button("🔄 Refresh", help="Re-read live state — the app doesn't auto-poll while a run is in progress"):
    st.rerun()


def _disk_use_cases() -> list[str]:
    if not USECASES_DIR.exists():
        return []
    return sorted(
        d.name for d in USECASES_DIR.iterdir()
        if d.is_dir() and (d / f"{d.name}.md").exists()
    )


def _daemon_health() -> str:
    """Pings the OPTIONAL Teams-inbound HTTP server (only run when wiring Teams inbound)."""
    url = f"http://{settings.http_host}:{settings.http_port}/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return "🟢 up" if r.status == 200 else f"🟠 http {r.status}"
    except Exception:
        return "🔴 off"


def _worker_status() -> str:
    """The thing that actually runs benchmarks — alive if it beat within ~3 poll intervals."""
    with connect() as c:
        hb = repo.get_heartbeat(c, "worker")
    if not hb:
        return "⚪ never run"
    age = (datetime.now(timezone.utc) - hb["last_beat"]).total_seconds()
    if age <= 3 * settings.worker_poll_seconds:
        return f"🟢 {(hb['detail'] or {}).get('current', 'idle')}"
    return f"🔴 stale {int(age)}s"


# --- Overview bar --------------------------------------------------------------------
with connect() as c:
    cands = repo.list_candidates(c)
    benches = repo.get_recent_benchmarks(c, limit=200)
    catalog = repo.get_catalog_status(c)

status_counts: dict[str, int] = {}
for cand in cands:
    status_counts[cand["status"]] = status_counts.get(cand["status"], 0) + 1
running = [b for b in benches if b["status"] == "running"]

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Worker", _worker_status())
c2.metric("HTTP (Teams inbound)", _daemon_health())
c3.metric("Catalog models", catalog["n"] if catalog else 0)
c4.metric("Queued", status_counts.get("queued", 0))
c5.metric("Discovered", status_counts.get("discovered", 0))
c6.metric("Running now", len(running))

tab_queue, tab_keys, tab_disc, tab_bench, tab_base, tab_logs = st.tabs(
    ["Queue", "Keys", "Discovery", "Benchmarks", "Baselines", "Logs"]
)

# --- Queue / candidates --------------------------------------------------------------
with tab_queue:
    st.subheader("Candidate queue (the human gate)")
    if cands:
        st.dataframe(
            pd.DataFrame([
                {"slug": x["slug"], "status": x["status"], "source": x["source"],
                 "decided_by": x["decided_by"], "created": x["created_at"]}
                for x in cands
            ]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No candidates yet. Discovered models and manual requests show up here.")

    st.markdown("**Decide on discovered / pending models**")
    actionable = [x for x in cands if x["status"] in ("discovered", "pending", "deferred")]
    if not actionable:
        st.caption("Nothing awaiting a decision.")
    for x in actionable:
        col_a, col_b, col_c = st.columns([3, 1, 1])
        col_a.write(f"`{x['slug']}`  ·  *{x['status']}*  ·  {x['source']}")
        if col_b.button("Benchmark", key=f"bench_{x['slug']}"):
            with connect() as c:
                repo.set_candidate_status(c, x["slug"], "queued", decided_by="admin")
            st.success(f"Queued {x['slug']}")
            st.rerun()
        if col_c.button("Skip", key=f"skip_{x['slug']}"):
            with connect() as c:
                repo.set_candidate_status(c, x["slug"], "rejected", decided_by="admin")
            st.rerun()

    st.divider()
    st.markdown("**Manually enqueue a model**")
    with st.form("enqueue"):
        slug = st.text_input("Model slug (OpenRouter style, e.g. moonshotai/kimi-k2)")
        submitted = st.form_submit_button("Enqueue")
        if submitted:
            if slug.strip():
                with connect() as c:
                    repo.upsert_candidate(c, slug=slug.strip(), source="admin",
                                          status="queued", decided_by="admin")
                st.success(f"Enqueued {slug.strip()}")
                st.rerun()
            else:
                st.warning("Enter a slug.")

    st.divider()
    st.markdown("**Cancel a queued model**")
    queued = [x for x in cands if x["status"] == "queued"]
    for x in queued:
        col_a, col_b = st.columns([4, 1])
        col_a.write(f"`{x['slug']}`  ·  {x['source']}")
        if col_b.button("Cancel", key=f"cancel_{x['slug']}"):
            with connect() as c:
                repo.set_candidate_status(c, x["slug"], "rejected", decided_by="admin")
            st.rerun()

# --- Keys ----------------------------------------------------------------------------
with tab_keys:
    st.subheader("Provider keys")
    st.caption("Keys are stored in keys.json (mode 600, gitignored). Values are never shown.")
    providers = keystore.list_providers()
    if providers:
        st.dataframe(pd.DataFrame(providers), use_container_width=True, hide_index=True)
    else:
        st.info("No provider keys stored yet.")

    with st.form("addkey"):
        st.markdown("**Add / update a key**")
        prov = st.text_input("Provider (e.g. gemini, openai)")
        keyval = st.text_input("API key", type="password")
        model = st.text_input("Default model id (optional)")
        if st.form_submit_button("Save key"):
            if prov.strip() and keyval.strip():
                keystore.set_key(prov.strip(), keyval.strip(), model=model.strip() or None)
                st.success(f"Stored key for {prov.strip()} (value never logged).")
                st.rerun()
            else:
                st.warning("Provider and key are both required.")

    if providers:
        st.markdown("**Revoke**")
        for p in providers:
            col_a, col_b = st.columns([4, 1])
            col_a.write(f"`{p['provider']}`")
            if col_b.button("Revoke", key=f"revoke_{p['provider']}"):
                keystore.revoke(p["provider"])
                st.rerun()

# --- Discovery / catalog -------------------------------------------------------------
with tab_disc:
    st.subheader("OpenRouter catalog")
    if catalog and catalog["n"]:
        st.write(f"**{catalog['n']}** models · last sync `{catalog['last_sync']}`")
    else:
        st.info("Catalog empty — run a sync.")
    post_cards = st.checkbox("Post discovery cards to Teams on this sync", value=False)
    if st.button("Run discovery sync now"):
        from daemon.discovery import sync_openrouter
        with st.spinner("Syncing OpenRouter /models…"):
            try:
                res = sync_openrouter(post_cards=post_cards)
                st.success(f"Synced {res['synced']} · new in catalog {res['new_in_catalog']} · "
                           f"discoveries {len(res['discoveries'])} · "
                           f"retired alerts {len(res['retired_alerted'])}")
                if res["discoveries"]:
                    st.write("New candidates:", res["discoveries"])
            except Exception as exc:
                st.error(f"Sync failed: {type(exc).__name__}: {exc}")
        st.rerun()

    st.markdown("**Recently discovered (awaiting a decision)**")
    discovered = [x for x in cands if x["status"] == "discovered"]
    if discovered:
        st.dataframe(
            pd.DataFrame([{"slug": x["slug"], "source": x["source"]} for x in discovered]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("None.")

    st.divider()
    st.subheader("Web discovery (claude -p research)")
    st.caption("Scans AI news/blogs, HuggingFace, Reddit, X for new models. Uses Max quota.")
    wpost = st.checkbox("Post a Teams summary on this run", value=False, key="web_post")
    wtarget = st.number_input("Max new models this run", 1, 50,
                              value=settings.web_discovery_target, key="web_target")
    if st.button("Run web discovery now"):
        from daemon.web_discovery import run_web_discovery
        with st.spinner("Researching the web for new models… (this spends Max quota)"):
            try:
                res = run_web_discovery(target=int(wtarget), post_cards=wpost)
                st.success(f"Recorded {len(res['new_slugs'])} new model(s): {res['new_slugs']}")
                if res["is_error"]:
                    st.warning("Agent reported an error — see the Logs tab.")
            except Exception as exc:
                st.error(f"Web discovery failed: {type(exc).__name__}: {exc}")
        st.rerun()

    with connect() as c:
        intel = repo.list_discovered_models(c)
    if intel:
        st.dataframe(
            pd.DataFrame([
                {"slug": d["slug"], "status": d["status"], "name": d["canonical_name"],
                 "provider": d["provider"], "est_cost": d["est_cost"],
                 "attributes": d["attributes"], "maybe_dup_of": d["possible_duplicate_of"]}
                for d in intel
            ]),
            use_container_width=True, hide_index=True,
        )
        st.markdown("**Decide on web-discovered models**")
        for d in [x for x in intel if x["status"] in ("discovered", "pending")]:
            ca, cb, cc = st.columns([3, 1, 1])
            ca.write(f"`{d['slug']}` — {d['canonical_name']} ({d['provider'] or '?'})")
            if cb.button("Benchmark", key=f"webbench_{d['slug']}"):
                with connect() as c:
                    repo.set_candidate_status(c, d["slug"], "queued", decided_by="admin")
                st.rerun()
            if cc.button("Skip", key=f"webskip_{d['slug']}"):
                with connect() as c:
                    repo.set_candidate_status(c, d["slug"], "rejected", decided_by="admin")
                st.rerun()
    else:
        st.caption("No web-discovered models yet.")

# --- Benchmarks monitor + drill-down -------------------------------------------------
with tab_bench:
    st.subheader("Benchmarks")
    if benches:
        st.dataframe(
            pd.DataFrame([
                {"id": b["benchmark_id"], "slug": b["slug"], "use_case": b["use_case"],
                 "status": b["status"], "baseline": b["is_baseline"], "drift": b["is_drift"],
                 "reps": b["n_reps"], "started": b["started_at"], "finished": b["finished_at"]}
                for b in benches
            ]),
            use_container_width=True, hide_index=True,
        )
        ids = [b["benchmark_id"] for b in benches]
        chosen = st.selectbox("Drill into benchmark", ids)
        if chosen:
            with connect() as c:
                runs = repo.get_runs(c, chosen)
                scores = repo.get_scores(c, chosen)
            st.markdown("**Runs**")
            st.dataframe(pd.DataFrame(runs), use_container_width=True, hide_index=True)
            st.markdown("**Aggregated scores (mean / min / max across reps)**")
            if scores:
                st.dataframe(pd.DataFrame(scores), use_container_width=True, hide_index=True)
            else:
                st.caption("No aggregated scores (run may be incomplete).")
            if runs:
                run_ids = [r["run_id"] for r in runs]
                rid = st.selectbox("Per-input detail for run", run_ids)
                with connect() as c:
                    results = repo.get_results(c, rid)
                    item_scores = repo.get_item_scores(c, rid)
                col_l, col_r = st.columns(2)
                with col_l:
                    st.caption("results (output + latency/tokens/cost)")
                    st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
                with col_r:
                    st.caption("item_scores (per-input, with judge rationale)")
                    st.dataframe(pd.DataFrame(item_scores), use_container_width=True, hide_index=True)
    else:
        st.info("No benchmarks yet.")

# --- Baselines -----------------------------------------------------------------------
with tab_base:
    st.subheader("Baselines & per-use-case config")
    use_cases = _disk_use_cases()
    if not use_cases:
        st.info("No use cases found on disk.")
    for uc in use_cases:
        with st.expander(uc, expanded=False):
            with connect() as c:
                band = repo.get_baseline(c, uc)
                cfg = repo.get_use_case_config(c, uc)
            st.caption("Current baseline band (per metric):")
            if band:
                st.dataframe(
                    pd.DataFrame([{"metric": m, **{k: v for k, v in d.items() if k != "metric"}}
                                  for m, d in band.items()]),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("No baseline established yet.")
            with st.form(f"cfg_{uc}"):
                bm = st.text_input("Baseline model slug",
                                   value=(cfg or {}).get("baseline_model") or "")
                reps = st.number_input("Default reps", min_value=1, max_value=10,
                                       value=int((cfg or {}).get("n_reps") or settings.n_reps_default))
                temp = st.text_input("Temperature (optional)",
                                     value=str((cfg or {}).get("temperature") or ""))
                if st.form_submit_button("Save config"):
                    t = float(temp) if temp.strip() else None
                    with connect() as c:
                        repo.set_use_case_config(c, use_case=uc, baseline_model=bm.strip() or None,
                                                 n_reps=int(reps), temperature=t)
                    st.success(f"Saved config for {uc}")
                    st.rerun()

# --- Logs ----------------------------------------------------------------------------
with tab_logs:
    st.subheader("Recent run logs / alerts")
    with connect() as c:
        logs = repo.get_recent_logs(c, limit=200)
    if logs:
        st.dataframe(
            pd.DataFrame([
                {"ts": l["ts"], "level": l["level"], "event": l["event"],
                 "bench": l["benchmark_id"], "run": l["run_id"],
                 "detail": json.dumps(l["detail"]) if l["detail"] else ""}
                for l in logs
            ]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("No logs yet.")
