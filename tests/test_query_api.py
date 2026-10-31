import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.server.apis.query_api import QueryApi
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Base, PublishPos, Works, Upload


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'q.db'}")
    Base.metadata.create_all(engine)
    DatabaseManager.engine = engine
    DatabaseManager.SessionLocal = sessionmaker(bind=engine)

    with DatabaseManager.get_db_session() as s:
        s.add_all([
            PublishPos(authorId="u1", website="pixiv", state="inQueue", addTime="2026-03-26T00:25:59"),
            PublishPos(authorId="u2", website="pixiv", state="stopped", addTime="2026-03-26T00:37:25"),
            PublishPos(authorId="u3", website="danbooru", state="inQueue", addTime="2026-04-01T10:00:00"),
            Works(workNumber="w1", website="pixiv", state="inQueue", downloadPriority=0,
                  title="标题甲", upTime="2026-03-01T10:00:00"),
            Works(workNumber="w2", website="pixiv", state="done", downloadPriority=5,
                  title="标题乙", upTime="2026-02-15T09:00:00", downloadDate="2026-03-20T12:00:00",
                  downloadInfo='{"quality":"original"}', otherInfo='{"siteState":"连载中"}'),
            Works(workNumber="w3", website="pixiv", state="failed", title="标题丙"),
            Works(workNumber="w4", website="danbooru", state="inQueue", title="dan work"),
            Works(workNumber="w5", website="pixiv", state=None, title="旧数据"),
            Upload(website="pixiv", authorId="u1", workNumber="w1"),
            Upload(website="pixiv", authorId="u1", workNumber="w2"),
            Upload(website="pixiv", authorId="u2", workNumber="w3"),
        ])

    app = Flask(__name__)
    app.register_blueprint(QueryApi().blueprint)
    yield app.test_client()

    DatabaseManager.engine = None
    DatabaseManager.SessionLocal = None
    engine.dispose()


def _numbers(data):
    return [i["workNumber"] for i in data["items"]]


def test_works_no_filter(client):
    data = client.get("/api/query/works").get_json()
    assert data["success"] and data["total"] == 5


def test_works_filter_website_and_states(client):
    data = client.get("/api/query/works?website=danbooru").get_json()
    assert _numbers(data) == ["w4"]

    data = client.get("/api/query/works?state=done,failed").get_json()
    assert set(_numbers(data)) == {"w2", "w3"}


def test_works_state_none_matches_legacy_null(client):
    data = client.get("/api/query/works?state=none").get_json()
    assert _numbers(data) == ["w5"]


def test_works_filter_by_author_via_upload(client):
    data = client.get("/api/query/works?author=u1").get_json()
    assert set(_numbers(data)) == {"w1", "w2"}

    data = client.get("/api/query/works?author=u1&website=pixiv&state=inQueue").get_json()
    assert _numbers(data) == ["w1"]


def test_works_date_range_on_download_date(client):
    data = client.get("/api/query/works?date_field=downloadDate&date_from=2026-03-01&date_to=2026-03-31").get_json()
    assert _numbers(data) == ["w2"]


def test_works_keyword_matches_title_and_number(client):
    data = client.get("/api/query/works?keyword=标题乙").get_json()
    assert _numbers(data) == ["w2"]
    data = client.get("/api/query/works?keyword=w4").get_json()
    assert _numbers(data) == ["w4"]


def test_works_sort_and_pagination(client):
    data = client.get("/api/query/works?sort=downloadPriority&order=desc&limit=2&offset=0").get_json()
    assert data["total"] == 5 and len(data["items"]) == 2
    assert data["items"][0]["downloadPriority"] == 5  # 优先级最高的在前

    data = client.get("/api/query/works?sort=downloadPriority&order=desc&limit=2&offset=2").get_json()
    assert len(data["items"]) == 2


def test_works_parsed_json_fields(client):
    data = client.get("/api/query/works?keyword=w2").get_json()
    item = data["items"][0]
    assert item["downloadInfo"] == {"quality": "original"}
    assert item["siteState"] == "连载中"


def test_works_rejects_unknown_sort_field(client):
    resp = client.get("/api/query/works?sort=1;drop")
    assert resp.status_code == 400


def test_positions_filters_and_work_counts(client):
    data = client.get("/api/query/positions").get_json()
    assert data["total"] == 3
    by_id = {i["authorId"]: i for i in data["items"]}
    assert by_id["u1"]["workCount"] == 2
    assert by_id["u2"]["workCount"] == 1
    assert by_id["u3"]["workCount"] == 0

    data = client.get("/api/query/positions?state=stopped").get_json()
    assert [i["authorId"] for i in data["items"]] == ["u2"]

    data = client.get("/api/query/positions?website=danbooru").get_json()
    assert [i["authorId"] for i in data["items"]] == ["u3"]

    data = client.get("/api/query/positions?keyword=u1").get_json()
    assert [i["authorId"] for i in data["items"]] == ["u1"]


def test_positions_date_range(client):
    data = client.get("/api/query/positions?date_from=2026-04-01&date_to=2026-04-30").get_json()
    assert [i["authorId"] for i in data["items"]] == ["u3"]


def test_stats_groups_by_website_and_state(client):
    data = client.get("/api/query/stats").get_json()
    assert data["works"]["pixiv"] == {"inQueue": 1, "done": 1, "failed": 1, "none": 1}
    assert data["works"]["danbooru"] == {"inQueue": 1}
    assert data["positions"]["pixiv"] == {"inQueue": 1, "stopped": 1}
    assert data["positions"]["danbooru"] == {"inQueue": 1}
