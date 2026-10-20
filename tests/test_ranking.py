import sqlite3

from app.ranking import rank_job


def _row(**overrides):
    base = dict(
        title="Senior Backend Engineer", description="Python and SQL, distributed systems",
        company="Acme Analytics", location="Remote", posted_at="2026-01-01",
    )
    base.update(overrides)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cols = ", ".join(base.keys())
    placeholders = ", ".join("?" for _ in base)
    conn.execute(f"CREATE TABLE t ({', '.join(f'{k} TEXT' for k in base)})")
    conn.execute(f"INSERT INTO t ({cols}) VALUES ({placeholders})", list(base.values()))
    return conn.execute("SELECT * FROM t").fetchone()


PREFS = {
    "target_roles": ["Backend Engineer"],
    "target_companies": ["Acme Analytics"],
    "locations": ["Remote"],
    "remote_ok": True,
    "keywords_boost": ["python", "distributed systems"],
    "keywords_exclude": ["unpaid"],
}


def test_strong_match_scores_higher_than_weak_match():
    strong = _row(title="Senior Backend Engineer", company="Acme Analytics", location="Remote")
    weak = _row(title="Graphic Designer", company="Some Other Co", location="Antarctica")
    score_strong, _ = rank_job(strong, PREFS)
    score_weak, _ = rank_job(weak, PREFS)
    assert score_strong > score_weak


def test_excluded_keyword_forces_zero_score():
    row = _row(description="This role is unpaid but great experience")
    score, explanation = rank_job(row, PREFS)
    assert score == 0.0
    assert any("EXCLUDED" in line for line in explanation)


def test_recency_affects_score():
    recent = _row(posted_at="2026-10-19")
    old = _row(posted_at="2020-01-01")
    score_recent, _ = rank_job(recent, PREFS)
    score_old, _ = rank_job(old, PREFS)
    assert score_recent >= score_old
