"""不動産情報ライブラリ API 取得 + dbt build パイプライン。

queria の DuckLake カタログ(QUERIA_* 環境変数で注入)へ API 取得データを書き込み、
dbt で変換する。R2 への公開は queria sync の push が担う。
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, timedelta
from itertools import product

import duckdb
import pyarrow as pa
import requests
from dbt.cli.main import dbtRunner
from queria import Secret
from reinfolib import ReinfolibClient
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

type Year = int
type Quarter = int
type YearQuarter = tuple[Year, Quarter]

TABLE = "reinfolib._source.trade_prices"
PRICE_CLASSIFICATION = "01"
START: YearQuarter = (2005, 3)

# -- タイル走査の共通設定 --
# 走査タイルは、日本列島を包含する少数の大矩形 (lon_min, lat_min, lon_max, lat_max)
# から指定ズームのタイルへ展開した和集合。各矩形は四隅がすべて海上にあり陸地を完全に
# 含むため、端の取りこぼしが原理的に起きない。海上の空タイルは取得時に skip する。
JAPAN_BBOXES: list[tuple[float, float, float, float]] = [
    (128.0, 30.0, 142.5, 41.6),  # 本州・四国・九州
    (139.0, 41.0, 146.2, 45.7),  # 北海道
    (122.8, 24.0, 131.6, 29.6),  # 南西諸島 (奄美〜沖縄〜先島)
    (130.9, 25.4, 131.5, 26.1),  # 大東諸島
    (141.9, 26.4, 142.4, 27.3),  # 小笠原諸島
]

# -- XCT001: 鑑定評価書情報 --
APPRAISAL_TABLE = "reinfolib._source.appraisal_reports"
# 用途区分。年・都道府県・用途区分の 3 つが必須で、組み合わせに該当が無いと 404 が返る
APPRAISAL_DIVISIONS = ["00", "03", "05", "07", "09", "10", "13", "20"]
# API が返すのは最新年から 5 年分
APPRAISAL_YEARS = 5
# 鑑定評価書はその年の地価公示と一緒に公表されたあと書き換わらないので、取得済みの
# 組み合わせは 30 日空けてから取り直す。公表が都道府県ごとにずれた年に取りこぼした分も
# ここで拾い直す。全 1880 組み合わせの一巡はおよそ 4 分で、予算を切るほどではない
APPRAISAL_REFRESH_INTERVAL_DAYS = 30
APPRAISAL_STATE_TABLE = "reinfolib._source.appraisal_fetch_state"
# 鑑定評価書は 109 項目あり、項目名は年・用途区分をまたいで固定。ここでは JSON 文字列
# のまま保持して raw スキーマを 4 カラムにし、構造化は stg 層の json_extract に委ねる
APPRAISAL_SCHEMA = pa.schema(
    [
        ("properties", pa.string()),
        ("_year", pa.int32()),
        ("_area_code", pa.string()),
        ("_division", pa.string()),
    ]
)

# -- XPT002: 地価公示・地価調査ポイント --
LAND_TABLE = "reinfolib._source.land_prices"
LAND_TILES_TABLE = "reinfolib._source.land_price_tiles"
LAND_SCAN_PROGRESS = "reinfolib._source.land_scan_progress"
LAND_TILE_STATE = "reinfolib._source.land_tile_state"
LAND_TILE_Z = 13
LAND_START_YEAR = 1995

# 1 回のビルドで地価タイルの取得に使う時間の上限。全 4685 タイルを一巡すると
# 5 時間かかる (実測 6分45秒/100タイル) 一方、一時認証情報は最長 1 時間しか
# 持たない。区切って毎日少しずつ回し、どのビルドも必ず publish まで到達させる。
LAND_BUDGET_SECONDS = 30 * 60

# -- XKT001: 都市計画決定GISデータ (都市計画区域・区域区分) --
URBAN_TABLE = "reinfolib._source.urban_planning_areas"
URBAN_TILE_STATE = "reinfolib._source.urban_planning_tile_state"
URBAN_TILE_Z = 11

# 年度単位でしか更新されないデータなので、取得済みタイルは 30 日空けてから
# 取り直す。全 10170 タイルの一巡はおよそ 20 分 (空タイルが 87% で 0.09 秒、
# 区域のあるタイルが 0.29 秒) で、1 ビルド 15 分の予算だと 2 ビルドで一周する。
# 取得日はビルド単位でそろうので、初回のバックフィルのあとは 30 日ごとに
# 2 ビルドを使って回り直し、その間のビルドは空振りする。
URBAN_REFRESH_INTERVAL_DAYS = 30
URBAN_BUDGET_SECONDS = 15 * 60

#: XKT001 の properties は仕様で固定されているので、JSON 文字列ではなく列で持つ。
URBAN_PROPERTIES: list[tuple[str, pa.DataType]] = [
    ("prefecture", pa.string()),
    ("city_code", pa.string()),
    ("city_name", pa.string()),
    ("kubun_id", pa.int32()),
    ("area_classification_ja", pa.string()),
    ("decision_date", pa.string()),
    ("decision_classification", pa.string()),
    ("decision_maker", pa.string()),
    ("notice_number", pa.string()),
    ("notice_number_s", pa.string()),
    ("first_decision_date", pa.string()),
]
URBAN_SCHEMA = pa.schema(
    URBAN_PROPERTIES
    + [
        ("geometry", pa.string()),
        ("_z", pa.int32()),
        ("_x", pa.int32()),
        ("_y", pa.int32()),
    ]
)


@contextmanager
def _ducklake_connect() -> Generator[tuple[duckdb.DuckDBPyConnection, Secret]]:
    """Open a fresh DuckDB session with the queria-managed DuckLake attached.

    Uses the ``QUERIA_*`` environment variables injected by ``queria run``: the local
    SQLite live catalog (``QUERIA_CATALOG_PATH``) and the data location
    (``QUERIA_DATA_URL``, R2 for S3 targets). The catalog is created on first
    attach when it does not exist yet.
    """
    catalog_path = os.environ["QUERIA_CATALOG_PATH"]
    data_url = os.environ["QUERIA_DATA_URL"]
    is_s3 = data_url.startswith("s3://")
    # ビルドが公開ストレージを読むときの名乗り。queria run が queria-build として
    # 渡す。profiles.yml の config_options と同じ値を、こちらのセッションにも通す。
    # 取り込みは dbt ではなくこの接続で行い、増分取得が公開済みの parquet を読むので、
    # ここが抜けると読み取りの大半が匿名のまま出ていき、data.queria.io の利用統計に
    # 自分のビルドが利用者として混ざる。接続を開くときにしか決められないので config= で渡す
    conn = duckdb.connect(
        ":memory:",
        config={"custom_user_agent": os.environ.get("QUERIA_USER_AGENT", "")},
    )
    try:
        conn.execute("INSTALL ducklake; LOAD ducklake;")
        conn.execute("INSTALL sqlite; LOAD sqlite;")
        if is_s3:
            conn.execute("INSTALL httpfs; LOAD httpfs;")
            # credential_chain はこの拡張にある
            conn.execute("INSTALL aws; LOAD aws;")
        secret = Secret(conn)
        secret.install()
        conn.execute(
            f"ATTACH 'ducklake:{catalog_path}' AS reinfolib "
            f"(DATA_PATH '{data_url}', OVERRIDE_DATA_PATH true, "
            f"DATA_INLINING_ROW_LIMIT 0, META_TYPE 'sqlite', "
            f"META_JOURNAL_MODE 'WAL', BUSY_TIMEOUT 5000)"
        )
        yield conn, secret
    finally:
        conn.close()


def main() -> None:
    target = os.environ.get("DBT_TARGET", sys.argv[1] if len(sys.argv) > 1 else "default")

    api_key = os.environ["REINFOLIB_API_KEY"]
    areas = [f"{a:02d}" for a in range(1, 48)]
    all_quarters = _generate_quarters(START)
    logger.info("start: %d areas × %d quarters", len(areas), len(all_quarters))

    with _ducklake_connect() as (conn, secret), ReinfolibClient(api_key) as client:
        conn.execute("CREATE SCHEMA IF NOT EXISTS reinfolib._source")
        ingest_trade_prices(conn, client, secret, areas=areas, quarters=all_quarters)

        appraisal_latest = _latest_appraisal_year(client)
        appraisal_years = list(
            range(appraisal_latest - APPRAISAL_YEARS + 1, appraisal_latest + 1)
        )
        ingest_appraisal_reports(
            conn, client, secret, areas=areas, years=appraisal_years
        )

        land_latest = _latest_land_year(client)
        discover_land_price_tiles(conn, client, secret, year=land_latest)

    # フェーズ0 で長時間保持した接続を一度閉じ、フェーズ1 は新しい接続で開始する
    # (DuckLake バックエンドの idle 接続が枯渇するのを避ける)
    land_years = list(range(LAND_START_YEAR, land_latest + 1))
    with _ducklake_connect() as (conn, secret), ReinfolibClient(api_key) as client:
        tiles = _known_land_tiles(conn)
        ingest_land_prices(conn, client, secret, tiles=tiles, years=land_years)

    with _ducklake_connect() as (conn, secret), _urban_planning_session(api_key) as sess:
        ingest_urban_planning_areas(
            conn, sess, secret, tiles=_scan_tiles(URBAN_TILE_Z)
        )

    dbt = dbtRunner()
    for cmd in (
        ["deps"],
        ["run", "--target", target],
        ["docs", "generate", "--target", target],
    ):
        result = dbt.invoke(cmd)
        if not result.success:
            raise SystemExit(f"dbt {' '.join(cmd)} failed")

    # 公開の直前なので、ここでの失敗でビルドを落とさない。カバレッジはログに
    # 出すための診断で、公開を止める判断には使っていない
    try:
        with _ducklake_connect() as (conn, _):
            _verify_land_coverage(conn)
    except duckdb.Error as exc:
        logger.warning("land coverage: 検証できなかった: %s", exc)


def ingest_trade_prices(
    conn: duckdb.DuckDBPyConnection,
    client: ReinfolibClient,
    secret: Secret,
    *,
    areas: list[str],
    quarters: list[YearQuarter],
) -> None:
    """XIT001: 取引価格・成約価格を取得。"""
    current = quarters[-1]
    completed = _completed_pairs(conn)
    total = len(areas) * len(quarters)
    logger.info("completed: %d / %d pairs", len(completed), total)

    fetched = 0
    for area, (year, quarter) in product(areas, quarters):
        if (area, year, quarter) in completed and (year, quarter) != current:
            continue

        rows = client.get_real_estate_prices(
            year=year,
            quarter=quarter,
            area=area,
            price_classification=PRICE_CLASSIFICATION,
        )
        if not rows:
            logger.info("XIT001 area=%s %dQ%d: empty", area, year, quarter)
            continue
        fetched += 1

        for row in rows:
            row["_area_code"] = area
            row["_year"] = year
            row["_quarter"] = quarter

        conn.register("_batch", pa.Table.from_pylist(rows))
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE} AS SELECT * FROM _batch WITH NO DATA"
        )
        conn.execute("BEGIN")
        conn.execute(
            f"DELETE FROM {TABLE} WHERE _area_code = ? AND _year = ? AND _quarter = ?",
            [area, year, quarter],
        )
        conn.execute(f"INSERT INTO {TABLE} SELECT * FROM _batch")
        conn.execute("COMMIT")
        conn.unregister("_batch")
        secret.refresh_if_due()

        logger.info("XIT001 area=%s %dQ%d: %d rows", area, year, quarter, len(rows))

    logger.info("ingest done: %d partitions fetched", fetched)


def _completed_pairs(
    conn: duckdb.DuckDBPyConnection,
) -> set[tuple[str, int, int]]:
    try:
        return {
            (row[0], row[1], row[2])
            for row in conn.execute(
                f"SELECT DISTINCT _area_code, _year, _quarter FROM {TABLE}"
            ).fetchall()
        }
    except duckdb.CatalogException:
        return set()


def _latest_appraisal_year(client: ReinfolibClient) -> int:
    """当年の鑑定評価書が公開済みかを代表の組み合わせで確認し、最新の有効年を返す。"""
    current = date.today().year
    for year in (current, current - 1):
        if client.get_appraisal_reports(year=year, area="13", division="05"):
            return year
    return current - 1


def ingest_appraisal_reports(
    conn: duckdb.DuckDBPyConnection,
    client: ReinfolibClient,
    secret: Secret,
    *,
    areas: list[str],
    years: list[int],
) -> None:
    """XCT001: 地価公示の標準地ごとの鑑定評価書を取得する。

    タイル指定ではなく、年 × 都道府県 × 用途区分の総当たりで取る。取得日を状態表に
    持ち、APPRAISAL_REFRESH_INTERVAL_DAYS より新しい組み合わせは飛ばす。該当が無く
    404 が返った組み合わせも記録するので、空振りをビルドのたびに撃ち直さない。
    """
    _ensure_appraisal_table(conn)
    state = _load_appraisal_state(conn)
    cutoff = date.today() - timedelta(days=APPRAISAL_REFRESH_INTERVAL_DAYS)
    combinations = [
        (year, area, division)
        for year, area, division in product(years, areas, APPRAISAL_DIVISIONS)
        if state.get((year, area, division), date.min) <= cutoff
    ]
    total = len(years) * len(areas) * len(APPRAISAL_DIVISIONS)
    logger.info(
        "appraisal: %d/%d 組み合わせを取得 (%d日以内に取得済みは飛ばす)",
        len(combinations),
        total,
        APPRAISAL_REFRESH_INTERVAL_DAYS,
    )

    today = date.today()
    fetched = 0
    for done, (year, area, division) in enumerate(combinations):
        rows = client.get_appraisal_reports(year=year, area=area, division=division)
        state[(year, area, division)] = today
        if (done + 1) % 100 == 0:
            _save_appraisal_state(conn, state)
            secret.refresh_if_due()
        if not rows:
            continue
        fetched += 1

        batch = [
            {
                "properties": json.dumps(row, ensure_ascii=False),
                "_year": year,
                "_area_code": area,
                "_division": division,
            }
            for row in rows
        ]
        conn.register("_batch", pa.Table.from_pylist(batch, schema=APPRAISAL_SCHEMA))
        conn.execute("BEGIN")
        conn.execute(
            f"DELETE FROM {APPRAISAL_TABLE} "
            "WHERE _year = ? AND _area_code = ? AND _division = ?",
            [year, area, division],
        )
        conn.execute(f"INSERT INTO {APPRAISAL_TABLE} SELECT * FROM _batch")
        conn.execute("COMMIT")
        conn.unregister("_batch")
        secret.refresh_if_due()

        logger.info(
            "XCT001 %d area=%s division=%s: %d rows", year, area, division, len(rows)
        )

    _save_appraisal_state(conn, state)
    logger.info("appraisal ingest done: %d combinations fetched", fetched)


def _ensure_appraisal_table(conn: duckdb.DuckDBPyConnection) -> None:
    """列が固定なので、1 件も取れなかったビルドでも表だけは先に作っておく。

    表が無いままだと raw_appraisal_reports の作成でカタログエラーになり、
    dbt run ごと落ちて他のテーブルの公開まで止まる。
    """
    conn.register("_appraisal_empty", APPRAISAL_SCHEMA.empty_table())
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {APPRAISAL_TABLE} AS SELECT * FROM _appraisal_empty"
    )
    conn.unregister("_appraisal_empty")


#: 取得状況の表の列。fetched_on は最後に取りに行った日で、行が無ければ未取得。
#: 404 が返った組み合わせもここには残るので、空振りを毎ビルド撃ち直さずに済む。
_APPRAISAL_STATE_SCHEMA = pa.schema(
    [
        ("year", pa.int32()),
        ("area_code", pa.string()),
        ("division", pa.string()),
        ("fetched_on", pa.date32()),
    ]
)


def _load_appraisal_state(
    conn: duckdb.DuckDBPyConnection,
) -> dict[tuple[int, str, str], date]:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {APPRAISAL_STATE_TABLE} "
        "(year INTEGER, area_code VARCHAR, division VARCHAR, fetched_on DATE)"
    )
    rows = conn.execute(
        f"SELECT year, area_code, division, fetched_on FROM {APPRAISAL_STATE_TABLE}"
    ).fetchall()
    return {(r[0], r[1], r[2]): r[3] for r in rows}


def _save_appraisal_state(
    conn: duckdb.DuckDBPyConnection,
    state: dict[tuple[int, str, str], date],
) -> None:
    """状態表を丸ごと書き直す。2000 行に満たないので毎回書き直しても安い。"""
    rows = [
        {"year": year, "area_code": area, "division": division, "fetched_on": on}
        for (year, area, division), on in sorted(state.items())
    ]
    conn.register("_state", pa.Table.from_pylist(rows, schema=_APPRAISAL_STATE_SCHEMA))
    conn.execute("BEGIN")
    conn.execute(f"DELETE FROM {APPRAISAL_STATE_TABLE}")
    conn.execute(f"INSERT INTO {APPRAISAL_STATE_TABLE} SELECT * FROM _state")
    conn.execute("COMMIT")
    conn.unregister("_state")


def _generate_quarters(
    start: YearQuarter,
    end: YearQuarter | None = None,
) -> list[YearQuarter]:
    if end is None:
        today = date.today()
        end = (today.year, (today.month - 1) // 3 + 1)
    return [
        (y, q)
        for y in range(start[0], end[0] + 1)
        for q in range(1, 5)
        if start <= (y, q) <= end
    ]


def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    """経緯度を XYZ タイル座標へ変換する。"""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def _scan_tiles(z: int) -> list[tuple[int, int]]:
    """JAPAN_BBOXES を z タイルへ展開した和集合 (昇順)。

    環境変数 SCAN_BBOX_OVERRIDE="lon0,lat0,lon1,lat1" で走査範囲を上書きできる
    (検証用に範囲を狭める)。
    """
    override = os.environ.get("SCAN_BBOX_OVERRIDE")
    if override:
        nums = [float(v) for v in override.split(",")]
        boxes = [(nums[0], nums[1], nums[2], nums[3])]
    else:
        boxes = JAPAN_BBOXES
    tiles: set[tuple[int, int]] = set()
    for lon0, lat0, lon1, lat1 in boxes:
        x0, y0 = _lonlat_to_tile(lon0, lat1, z)  # 北西
        x1, y1 = _lonlat_to_tile(lon1, lat0, z)  # 南東
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                tiles.add((x, y))
    return sorted(tiles)


def _fetch_land_features(
    client: ReinfolibClient, *, z: int, x: int, y: int, year: int
) -> list[dict]:
    """XPT002 を GeoJSON で取得し features を返す。"""
    resp = client.get_land_prices_point(z=z, x=x, y=y, year=year)
    return resp.get("features", []) if isinstance(resp, dict) else []


def _latest_land_year(client: ReinfolibClient) -> int:
    """当年の地価公示が公開済みかを代表タイルで確認し、最新の有効年を返す。"""
    px, py = _lonlat_to_tile(139.767, 35.681, LAND_TILE_Z)  # 東京駅周辺
    current = date.today().year
    for year in (current, current - 1):
        if _fetch_land_features(client, z=LAND_TILE_Z, x=px, y=py, year=year):
            return year
    return current - 1


def discover_land_price_tiles(
    conn: duckdb.DuckDBPyConnection,
    client: ReinfolibClient,
    secret: Secret,
    *,
    year: int,
) -> list[tuple[int, int]]:
    """フェーズ0: 陸地タイルを走査し、地点が存在するタイルを記録・返す。

    走査進捗と発見タイルを 1000 タイルごとに永続化し、中断後は続きから再開する。
    一度完了した有効タイルは再利用する (過去年バックフィルや再ビルドを軽くする)。
    SCAN_BBOX_OVERRIDE 指定時 (検証用) は永続化せずメモリで完結する。
    """
    scan = _scan_tiles(LAND_TILE_Z)

    if os.environ.get("SCAN_BBOX_OVERRIDE"):
        found = [
            (x, y)
            for x, y in scan
            if _fetch_land_features(client, z=LAND_TILE_Z, x=x, y=y, year=year)
        ]
        logger.info(
            "land tiles (override): %d/%d tiles have points", len(found), len(scan)
        )
        return found

    _ensure_tile_tables(conn)
    scanned, total = _scan_progress(conn)
    if total != len(scan):
        # 走査範囲が変わった or 初回 → やり直し
        _reset_scan(conn)
        scanned = 0
    if scanned >= len(scan):
        known = _known_land_tiles(conn)
        logger.info("land tiles: reuse %d known tiles (scan complete)", len(known))
        return known

    logger.info(
        "land tiles: scanning %d candidate tiles from %d (year=%d)",
        len(scan),
        scanned,
        year,
    )
    batch: list[tuple[int, int]] = []
    for i in range(scanned, len(scan)):
        x, y = scan[i]
        if _fetch_land_features(client, z=LAND_TILE_Z, x=x, y=y, year=year):
            batch.append((x, y))
        if (i + 1) % 1000 == 0:
            _checkpoint_tiles(conn, batch, i + 1, len(scan))
            batch = []
            secret.refresh_if_due()
            n = conn.execute(f"SELECT count(*) FROM {LAND_TILES_TABLE}").fetchone()[0]
            logger.info("  scanned %d/%d, found %d", i + 1, len(scan), n)
    _checkpoint_tiles(conn, batch, len(scan), len(scan))

    known = _known_land_tiles(conn)
    logger.info("land tiles: %d tiles have points", len(known))
    return known


def _ensure_tile_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {LAND_TILES_TABLE} (z INTEGER, x INTEGER, y INTEGER)"
    )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {LAND_SCAN_PROGRESS} (scanned BIGINT, total BIGINT)"
    )


def _scan_progress(conn: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    try:
        row = conn.execute(
            f"SELECT scanned, total FROM {LAND_SCAN_PROGRESS} LIMIT 1"
        ).fetchone()
    except duckdb.CatalogException:
        return 0, 0
    return (int(row[0]), int(row[1])) if row else (0, 0)


def _reset_scan(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(f"DELETE FROM {LAND_TILES_TABLE}")
    conn.execute(f"DELETE FROM {LAND_SCAN_PROGRESS}")


def _checkpoint_tiles(
    conn: duckdb.DuckDBPyConnection,
    found: list[tuple[int, int]],
    scanned: int,
    total: int,
) -> None:
    """発見タイルの追記と走査進捗の更新をまとめて永続化する。"""
    conn.execute("BEGIN")
    if found:
        rows = [{"z": LAND_TILE_Z, "x": x, "y": y} for x, y in found]
        conn.register("_tiles", pa.Table.from_pylist(rows))
        conn.execute(f"INSERT INTO {LAND_TILES_TABLE} SELECT * FROM _tiles")
        conn.unregister("_tiles")
    conn.execute(f"DELETE FROM {LAND_SCAN_PROGRESS}")
    conn.execute(f"INSERT INTO {LAND_SCAN_PROGRESS} VALUES (?, ?)", [scanned, total])
    conn.execute("COMMIT")


def _known_land_tiles(conn: duckdb.DuckDBPyConnection) -> list[tuple[int, int]]:
    try:
        return [
            (r[0], r[1])
            for r in conn.execute(
                f"SELECT x, y FROM {LAND_TILES_TABLE} ORDER BY x, y"
            ).fetchall()
        ]
    except duckdb.CatalogException:
        return []


def ingest_land_prices(
    conn: duckdb.DuckDBPyConnection,
    client: ReinfolibClient,
    secret: Secret,
    *,
    tiles: list[tuple[int, int]],
    years: list[int],
) -> None:
    """フェーズ1: 有効タイルごとに対象年をまとめて取得する。

    タイル単位で対象年を取得し 1 トランザクションで書き込むことで、DuckLake
    バックエンドへのトランザクション数を抑える (接続枯渇対策)。取得済みかどうかで
    取得年を切り替える差分更新:
    - 未取得タイル: 全年 (初回バックフィル)
    - 取得済みタイル: 最新年のみ再取得 → 毎年の地価公示(3月)・地価調査(9月)の
      新規公表を取り込む。再取得が古いタイルから順に回す

    1 回のビルドは LAND_BUDGET_SECONDS で打ち切る。全タイルを一巡すると一時
    認証情報の寿命を大きく超えるので、続きは次のビルドが引き継ぐ。どこまで
    進んだかは land_tile_state が持つ。
    """
    if not tiles:
        logger.warning("land prices: no tiles to ingest")
        return

    latest = years[-1]
    state = _load_tile_state(conn, LAND_TILE_STATE) or _seed_tile_state(conn)
    pending = [t for t in tiles if t not in state]
    # 再取得は最終取得日の古い順。未取得タイルを先に片付けてから回す
    refreshable = sorted(
        (t for t in tiles if t in state), key=lambda t: state[t] or date.min
    )
    queue = pending + refreshable
    logger.info(
        "land prices: %d/%d tiles 取得済み (未取得=全年, 既存=最新年%d を"
        "古い順に再取得, 予算%d分)",
        len(state),
        len(tiles),
        latest,
        LAND_BUDGET_SECONDS // 60,
    )

    today = date.today()
    deadline = time.monotonic() + LAND_BUDGET_SECONDS
    written = 0
    for done, (x, y) in enumerate(queue):
        if time.monotonic() >= deadline:
            logger.info(
                "land prices: 予算に達したので %d タイルで打ち切り (残り %d)",
                done,
                len(queue) - done,
            )
            break
        tile_years = [latest] if (x, y) in state else years
        rows: list[dict] = []
        for year in tile_years:
            for f in _fetch_land_features(client, z=LAND_TILE_Z, x=x, y=y, year=year):
                rows.append(_feature_to_row(f, x, y, year))
        _write_tile_rows(conn, x, y, tile_years, rows)
        state[(x, y)] = today
        written += len(rows)
        if (done + 1) % 100 == 0:
            _save_tile_state(conn, LAND_TILE_STATE, state)
            secret.refresh_if_due()
            logger.info("  tiles %d/%d, rows %d", done + 1, len(queue), written)
    _save_tile_state(conn, LAND_TILE_STATE, state)

    stale = sum(1 for d in state.values() if d != today)
    logger.info(
        "land prices ingest done: %d rows written, 未再取得の残り %d タイル",
        written,
        stale,
    )


def _feature_to_row(f: dict, x: int, y: int, year: int) -> dict:
    """GeoJSON feature を _source.land_prices の行 dict に変換する。

    properties はキー構成が地点ごとに変動するため、JSON 文字列のまま保持して
    raw スキーマを固定 8 カラムにする。構造化は stg 層の json_extract に委ねる。
    """
    props = dict(f.get("properties", {}))
    props.pop("_id", None)
    props.pop("_index", None)
    geom = f.get("geometry") or {}
    coords = geom.get("coordinates") or [None, None]
    return {
        "properties": json.dumps(props, ensure_ascii=False),
        "longitude": coords[0],
        "latitude": coords[1],
        "geometry": json.dumps(geom, ensure_ascii=False),
        "_z": LAND_TILE_Z,
        "_x": x,
        "_y": y,
        "_year": year,
    }


def _write_tile_rows(
    conn: duckdb.DuckDBPyConnection,
    x: int,
    y: int,
    years: list[int],
    rows: list[dict],
) -> None:
    """1 タイル分の行を 1 トランザクションで書き込む (対象年を入れ替え)。"""
    if not rows:
        return
    conn.register("_batch", pa.Table.from_pylist(rows))
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {LAND_TABLE} AS SELECT * FROM _batch WITH NO DATA"
    )
    conn.execute("BEGIN")
    if len(years) == 1:
        conn.execute(
            f"DELETE FROM {LAND_TABLE} WHERE _x = ? AND _y = ? AND _year = ?",
            [x, y, years[0]],
        )
    else:
        conn.execute(f"DELETE FROM {LAND_TABLE} WHERE _x = ? AND _y = ?", [x, y])
    conn.execute(f"INSERT INTO {LAND_TABLE} SELECT * FROM _batch")
    conn.execute("COMMIT")
    conn.unregister("_batch")


#: タイル状態表の列。x, y はタイル座標、refreshed_on は最後に取り直した日
#: (NULL = まだ一度も再取得していない)。
_TILE_STATE_SCHEMA = pa.schema(
    [("x", pa.int32()), ("y", pa.int32()), ("refreshed_on", pa.date32())]
)


def _load_tile_state(
    conn: duckdb.DuckDBPyConnection, table: str
) -> dict[tuple[int, int], date | None]:
    """タイルごとの取得状況を読む。

    本体 (land_prices) を見て取得済みを判定すると、DuckLake のデータファイルと
    削除ファイルを HTTP 越しに全部開くことになり、それだけで 25 分近くかかる。
    判定に要るのはタイル座標だけなので、数千行の表に切り出して持つ。
    """
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table} (x INTEGER, y INTEGER, refreshed_on DATE)"
    )
    rows = conn.execute(f"SELECT x, y, refreshed_on FROM {table}").fetchall()
    return {(r[0], r[1]): r[2] for r in rows}


def _seed_tile_state(
    conn: duckdb.DuckDBPyConnection,
) -> dict[tuple[int, int], date | None]:
    """状態表が空のときだけ、本体から取得済みタイルを写し取る。

    この表を持つ前に取り込んだ分を引き継ぐための一度きりの経路。本体の全件
    走査になるが、走るのは最初の 1 回だけで、以降は状態表だけを読む。
    """
    try:
        found = conn.execute(f"SELECT DISTINCT _x, _y FROM {LAND_TABLE}").fetchall()
    except duckdb.CatalogException:
        return {}
    state: dict[tuple[int, int], date | None] = {(r[0], r[1]): None for r in found}
    if state:
        logger.info("land tile state: 本体から %d タイルを引き継ぎ", len(state))
        _save_tile_state(conn, LAND_TILE_STATE, state)
    return state


def _save_tile_state(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    state: dict[tuple[int, int], date | None],
) -> None:
    """状態表を丸ごと書き直す。

    追記にするとチェックポイントごとにデータファイルが増え、次のビルドの
    読み出しがそのぶん遅くなる。数千行なので毎回書き直しても安く、読む側は
    常に 1 ファイルで済む。
    """
    rows = [
        {"x": x, "y": y, "refreshed_on": on} for (x, y), on in sorted(state.items())
    ]
    conn.register("_state", pa.Table.from_pylist(rows, schema=_TILE_STATE_SCHEMA))
    conn.execute("BEGIN")
    conn.execute(f"DELETE FROM {table}")
    conn.execute(f"INSERT INTO {table} SELECT * FROM _state")
    conn.execute("COMMIT")
    conn.unregister("_state")


@contextmanager
def _urban_planning_session(api_key: str) -> Generator[requests.Session]:
    """XKT001 用の HTTP セッション。

    reinfolib-client はまだ XKT001 を持たないので、ここだけ直接叩く。
    リトライの設定はクライアントに合わせてある。
    """
    session = requests.Session()
    session.headers["Ocp-Apim-Subscription-Key"] = api_key
    retry = Retry(
        total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    try:
        yield session
    finally:
        session.close()


def _fetch_urban_features(
    session: requests.Session, *, z: int, x: int, y: int
) -> list[dict]:
    """XKT001 を GeoJSON で取得し features を返す。

    API キーはヘッダで送る。requests がリダイレクト時に落とすのは Authorization
    などの既知のヘッダだけで、独自ヘッダは別ホストへも再送されてしまうため、
    リダイレクトは追わずに異常として扱う。
    """
    resp = session.get(
        "https://www.reinfolib.mlit.go.jp/ex-api/external/XKT001",
        params={"response_format": "geojson", "z": str(z), "x": str(x), "y": str(y)},
        timeout=60,
        allow_redirects=False,
    )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    body = resp.json()
    return body.get("features", []) if isinstance(body, dict) else []


def ingest_urban_planning_areas(
    conn: duckdb.DuckDBPyConnection,
    session: requests.Session,
    secret: Secret,
    *,
    tiles: list[tuple[int, int]],
) -> None:
    """XKT001: 都市計画区域・区域区分をタイル単位で取得する。

    地価ポイントと違い年の軸が無く、1 タイル 1 リクエストで済む。未取得の
    タイルを先に片付け、そのあとは最終取得日が URBAN_REFRESH_INTERVAL_DAYS
    より古いものを古い順に取り直す。1 回のビルドは URBAN_BUDGET_SECONDS で
    打ち切り、続きは次のビルドが引き継ぐ。

    区域ポリゴンはタイルの境界で切られて返るため、断片のまま書き込み、
    元の区域に戻すのは mart 層の ST_Union_Agg に任せる。
    """
    _ensure_urban_table(conn)
    state = _load_tile_state(conn, URBAN_TILE_STATE)
    today = date.today()
    cutoff = today - timedelta(days=URBAN_REFRESH_INTERVAL_DAYS)
    pending = [t for t in tiles if t not in state]
    refreshable = sorted(
        (t for t in tiles if state.get(t) is not None and state[t] <= cutoff),
        key=lambda t: state[t],
    )
    queue = pending + refreshable
    logger.info(
        "urban planning: %d/%d タイル取得済み (未取得=%d, %d日以上前=%d, 予算%d分)",
        len(state),
        len(tiles),
        len(pending),
        URBAN_REFRESH_INTERVAL_DAYS,
        len(refreshable),
        URBAN_BUDGET_SECONDS // 60,
    )

    deadline = time.monotonic() + URBAN_BUDGET_SECONDS
    written = 0
    for done, (x, y) in enumerate(queue):
        if time.monotonic() >= deadline:
            logger.info(
                "urban planning: 予算に達したので %d タイルで打ち切り (残り %d)",
                done,
                len(queue) - done,
            )
            break
        rows = [
            _urban_feature_to_row(f, x, y)
            for f in _fetch_urban_features(session, z=URBAN_TILE_Z, x=x, y=y)
        ]
        _write_urban_tile_rows(conn, x, y, rows)
        state[(x, y)] = today
        written += len(rows)
        if (done + 1) % 200 == 0:
            _save_tile_state(conn, URBAN_TILE_STATE, state)
            secret.refresh_if_due()
            logger.info("  tiles %d/%d, rows %d", done + 1, len(queue), written)
    _save_tile_state(conn, URBAN_TILE_STATE, state)

    logger.info(
        "urban planning ingest done: %d rows written, 未処理の残り %d タイル",
        written,
        len([t for t in tiles if t not in state]),
    )


def _ensure_urban_table(conn: duckdb.DuckDBPyConnection) -> None:
    """列が固定なので、空のタイルしか無いビルドでも表だけは先に作っておく。"""
    conn.register("_urban_empty", URBAN_SCHEMA.empty_table())
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {URBAN_TABLE} AS SELECT * FROM _urban_empty"
    )
    conn.unregister("_urban_empty")


def _urban_feature_to_row(f: dict, x: int, y: int) -> dict:
    """GeoJSON feature を _source.urban_planning_areas の行 dict に変換する。

    _id / _index は配信側の検索インデックスの都合で、再構築のたびに変わる。
    区域を識別するのに使えないので落とす。
    """
    props = f.get("properties", {})
    row = {name: props.get(name) for name, _ in URBAN_PROPERTIES}
    row["geometry"] = json.dumps(f.get("geometry") or {}, ensure_ascii=False)
    row["_z"] = URBAN_TILE_Z
    row["_x"] = x
    row["_y"] = y
    return row


def _write_urban_tile_rows(
    conn: duckdb.DuckDBPyConnection, x: int, y: int, rows: list[dict]
) -> None:
    """1 タイル分の行を入れ替える。

    区域が消えたタイルを空のまま残せるよう、行が無くても削除だけは実行する。
    """
    conn.execute("BEGIN")
    conn.execute(f"DELETE FROM {URBAN_TABLE} WHERE _x = ? AND _y = ?", [x, y])
    if rows:
        conn.register("_batch", pa.Table.from_pylist(rows, schema=URBAN_SCHEMA))
        conn.execute(f"INSERT INTO {URBAN_TABLE} SELECT * FROM _batch")
    conn.execute("COMMIT")
    if rows:
        conn.unregister("_batch")


def _verify_land_coverage(conn: duckdb.DuckDBPyConnection) -> None:
    """公開テーブルのカバレッジを検証しログ出力する (取りこぼしの安全網)。

    47都道府県の欠落と総地点数で走査範囲の取りこぼしを検出する。_source は
    都道府県コードを JSON 文字列の中に持つので、そちらを見ると全行の JSON を
    ダウンロードすることになる。列に展開済みの mart を見る。
    """
    prefs = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT prefecture_code FROM reinfolib.main.mart_land_prices"
        ).fetchall()
    }
    missing = {f"{i:02d}" for i in range(1, 48)} - prefs
    if missing:
        logger.warning("land coverage: 地価データが無い都道府県: %s", sorted(missing))
    else:
        logger.info("land coverage: 47都道府県すべてに地価データあり")

    total = conn.execute(
        "SELECT count(*) FROM reinfolib.main.mart_land_prices"
    ).fetchone()[0]
    logger.info("land coverage: 総地点数(全年) %d", total)


if __name__ == "__main__":
    main()
