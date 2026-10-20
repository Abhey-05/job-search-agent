from app.dedup import compute_dedup_hash, compute_job_id
from app.models import JobPosting


def _posting(**overrides):
    base = dict(
        source="sample_board_a", external_id="a-1", url="http://x/1",
        title="Senior Backend Engineer", company="Acme Analytics",
        location="Remote", description="desc", posted_at="2026-01-01",
    )
    base.update(overrides)
    return JobPosting(**base)


def test_job_id_stable_per_source_and_external_id():
    p1 = _posting()
    p2 = _posting()
    assert compute_job_id(p1) == compute_job_id(p2)


def test_job_id_differs_across_sources():
    p1 = _posting(source="sample_board_a")
    p2 = _posting(source="sample_board_b")
    assert compute_job_id(p1) != compute_job_id(p2)


def test_dedup_hash_matches_across_sources_for_same_role():
    p1 = _posting(source="sample_board_a", external_id="a-1")
    p2 = _posting(source="sample_board_b", external_id="b-1")
    assert compute_dedup_hash(p1) == compute_dedup_hash(p2)


def test_dedup_hash_differs_for_different_company():
    p1 = _posting(company="Acme Analytics")
    p2 = _posting(company="Northwind Logistics")
    assert compute_dedup_hash(p1) != compute_dedup_hash(p2)


def test_dedup_hash_is_case_and_punctuation_insensitive():
    p1 = _posting(title="Senior Backend Engineer", company="Acme Analytics")
    p2 = _posting(title="senior backend engineer!!", company="ACME, Analytics")
    assert compute_dedup_hash(p1) == compute_dedup_hash(p2)
