"""Golden tests against the Cloudera dbt-spark-cde-example seeds (Apache-2.0, see fixtures NOTICE)."""

import hashlib
from pathlib import Path

import pytest

pytest.importorskip("multipart")

from fastapi.testclient import TestClient  # noqa: E402

from cutover.web import create_app  # noqa: E402
from cutover.web.profiling import profile_csv  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "cloudera_covid"

# (rows, column name -> inferred type)
EXPECTED = {
    "raw_covid__cases.csv": (510, {
        "date_rep": "date", "day": "integer", "month": "integer", "year": "integer",
        "cases": "integer", "deaths": "integer", "geo_id": "text"}),
    "ref__country_codes.csv": (255, {
        "country": "text", "alpha_2code": "text", "alpha_3code": "text", "numeric_code": "integer",
        "latitude_avg": "decimal", "longitude_avg": "decimal"}),
    "ref__populations.csv": (266, {"country_code": "text", "population": "integer"}),
    "raw_covid__vaccines.csv": (3740, {
        "year_week_iso": "date", "reporting_country": "text", "num_doses_recv": "integer",
        "num_doses_exported": "integer", "first_dose": "integer", "first_dose_refused": "integer",
        "second_dose": "integer", "unknown_dose": "integer", "target_group": "text", "vaccine": "text"}),
}


# These two files contain only the dates 01/01/2022 and 02/01/2022: they read as 1 and 2 January or as
# 1 January and 1 February. The profiler cannot know, and says so; every other seed is clean.
AMBIGUOUS_DATES = {"raw_covid__cases.csv", "raw_covid__vaccines.csv"}


@pytest.mark.parametrize("name", EXPECTED)
def test_seed_profiles_match_known_shape_and_raise_only_the_known_flags(name):
    rows, types = EXPECTED[name]
    profile = profile_csv(FIXTURES / name)
    assert profile.rows == rows
    assert {c["name"]: c["type"] for c in profile.columns} == types
    assert [f.kind for f in profile.flags] == (["ambiguous_dates"] if name in AMBIGUOUS_DATES else [])
    if name in AMBIGUOUS_DATES:
        date = next(c for c in profile.columns if c["type"] == "date")
        assert date["date_format"] == "dd/MM/yyyy" and date["date_ambiguous"] and (date["min"], date["max"]) == ("2022-01-01", "2022-01-02")
    assert profile.duplicate_rows == 0 and profile.empty_cells == 0


@pytest.mark.parametrize("name", EXPECTED)
def test_profile_hash_matches_independent_computation(name):
    expected = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
    assert profile_csv(FIXTURES / name).sha256 == expected


def test_corrupted_cases_file_raises_the_expected_flags(tmp_path):
    lines = (FIXTURES / "raw_covid__cases.csv").read_text(encoding="utf-8").splitlines()
    header, body = lines[0].replace("geo_id", "geo id"), lines[1:]
    body.append(body[0])  # exact duplicate row
    body.append("02/01/2022,02")  # truncated row
    body[1] = "01/01/2022,01,01,2022,n/a,13,AL"  # non-numeric in an integer column
    broken = tmp_path / "cases.csv"
    broken.write_text("\n".join([header, *body]) + "\n", encoding="utf-8")

    profile = profile_csv(broken)
    kinds = {f.kind: f for f in profile.flags}
    assert kinds["column_names"].items == ["'geo id'"]
    assert kinds["duplicate_rows"].items
    assert kinds["mixed_types"].items == ["cases"]
    assert kinds["malformed_rows"].items == [f"linha {len(body) + 1}"]
    assert profile.rows == 510 + 1  # 510 original rows + 1 duplicate; truncated row excluded


def test_upload_of_cloudera_seed_end_to_end(tmp_path):
    client = TestClient(create_app(tmp_path), follow_redirects=False)
    client.post("/signup", data={"email": "qa@example.com", "password": "correct-horse-1"})
    data = (FIXTURES / "ref__populations.csv").read_bytes()
    response = client.post("/app/datasets", files={"file": ("ref__populations.csv", data)},
                           data={"target": "microsoft_fabric"})
    page = client.get(response.headers["location"]).text
    assert hashlib.sha256(data).hexdigest() in page
    assert "Nenhum alerta" in page and "ref__populations.csv" in page
