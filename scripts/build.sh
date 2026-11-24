#!/usr/bin/env bash
set -euo pipefail
# trade_prices / land_prices などは area・quarter / タイル単位の増分取得で、
# 取得済みのデータと取得の状態を前回のバージョンの _source から引き継ぐ。
# build-fdl.sh は apply ブランチの最新のバージョンを fdl clone してから始まる
# 説明 (<model>.tabledoc.yml) の無いテーブル (取り込んだままの _source と stg) は Queria の一覧と検索に出さない
export FDL_UNDESCRIBED="${FDL_UNDESCRIBED:-hidden}"
exec "$(dirname "$0")/../shared/scripts/build-fdl.sh" "$@"
