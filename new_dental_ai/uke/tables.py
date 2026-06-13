"""歯科電子点数表のチェック用テーブル（点検テーブル）の読み込み。

診療報酬情報提供サービス（厚生労働省）が公開している歯科のチェック用
テーブルのうち、レセプト点検に使える 4 種を扱う:

- 算定回数限度テーブル（h-6）: レセプト単位に算定回数が限定されている診療行為
- 年齢制限テーブル（h-8）: 算定に当たって年齢制限がある診療行為
- 併算定背反テーブル（h-9）: 他の診療行為との併算定ができない診療行為
- 実日数関連テーブル（h-10）: 算定回数が診療実日数を超えることがない等の診療行為

ダウンロード:
    python -m new_dental_ai.uke.tables --download data/
"""

from __future__ import annotations

import csv
import glob
import os
from dataclasses import dataclass, field
from typing import Union

from .master import download as _download_zip

ENCODING = "cp932"

_BASE = "https://shinryohoshu.mhlw.go.jp/shinryohoshu/receDentalMenu/"

# テーブル名 → (ダウンロード URL, 展開後の CSV ファイル名パターン)
TABLES = {
    "算定回数限度": (_BASE + "hSanteiFile", "h-6_*.csv"),
    "年齢制限": (_BASE + "hNenreiFile", "h-8_*.csv"),
    "併算定背反": (_BASE + "hHeiSanteiFile", "h-9_*.csv"),
    "実日数関連": (_BASE + "hJitsuNissuFile", "h-10_*.csv"),
}


@dataclass(frozen=True)
class CountLimit:
    """算定回数限度テーブルの 1 件。"""

    code: str
    name: str
    unit: str  # 単位コード（131=1月につき、121=1日につき 等）
    limit: int  # 上限回数
    special: bool  # 特例条件あり（上限超過が直ちに誤りとは限らない）


@dataclass(frozen=True)
class AgeLimit:
    """年齢制限テーブルの 1 件。下限・上限は生値（"00"=制限なし、"BK"=未就学 等）。"""

    code: str
    name: str
    lower: str  # 下限年齢（この年齢以上が対象）
    upper: str  # 上限年齢（この年齢未満が対象）


@dataclass(frozen=True)
class DayRelation:
    """実日数関連テーブルの 1 件。"""

    code: str
    name: str
    relation: str  # 実日数との関係区分（"1"=算定回数が診療実日数以下）


@dataclass(frozen=True)
class Exclusion:
    """併算定背反テーブルの 1 組（自コードから見た相手）。"""

    code: str
    name: str
    partner_code: str
    partner_name: str
    kubun: str  # 背反区分


@dataclass
class CheckTables:
    """点検テーブル一式。"""

    count_limits: dict[str, CountLimit] = field(default_factory=dict)
    age_limits: dict[str, AgeLimit] = field(default_factory=dict)
    day_relations: dict[str, DayRelation] = field(default_factory=dict)
    exclusions: dict[str, list[Exclusion]] = field(default_factory=dict)

    @classmethod
    def load_dir(cls, directory: Union[str, os.PathLike]) -> "CheckTables":
        """ダウンロード済みディレクトリから存在するテーブルを読み込む。"""
        tables = cls()
        for name, (_, pattern) in TABLES.items():
            paths = sorted(glob.glob(os.path.join(directory, pattern)))
            if not paths:
                continue
            rows = _read_csv(paths[-1])
            if name == "算定回数限度":
                tables._load_count_limits(rows)
            elif name == "年齢制限":
                tables._load_age_limits(rows)
            elif name == "併算定背反":
                tables._load_exclusions(rows)
            elif name == "実日数関連":
                tables._load_day_relations(rows)
        return tables

    # 各 CSV とも先頭は 変更区分, 診療行為コード, 区分(5項目), 漢字名称, 省略漢字名称
    # で、その後にテーブル固有の項目、末尾に適用開始日・終了日等が続く。

    def _load_count_limits(self, rows: list[list[str]]) -> None:
        for r in rows:
            if len(r) < 12:
                continue
            self.count_limits[r[1]] = CountLimit(
                code=r[1], name=r[7], unit=r[9],
                limit=int(r[10]), special=r[11] == "1",
            )

    def _load_age_limits(self, rows: list[list[str]]) -> None:
        for r in rows:
            if len(r) < 11:
                continue
            self.age_limits[r[1]] = AgeLimit(
                code=r[1], name=r[7], lower=r[9], upper=r[10],
            )

    def _load_day_relations(self, rows: list[list[str]]) -> None:
        for r in rows:
            if len(r) < 10:
                continue
            self.day_relations[r[1]] = DayRelation(code=r[1], name=r[7], relation=r[9])

    def _load_exclusions(self, rows: list[list[str]]) -> None:
        # 自レコード(9項目)の後に (背反区分, コード, 区分×5, 名称, 省略名称) の
        # 9 項目 × 最大 10 組の相手が続く。
        for r in rows:
            if len(r) < 18:
                continue
            code, name = r[1], r[7]
            for start in range(9, min(len(r) - 8, 99), 9):
                partner_code = r[start + 1]
                if not partner_code or not partner_code.isdigit():
                    continue
                self.exclusions.setdefault(code, []).append(Exclusion(
                    code=code, name=name,
                    partner_code=partner_code, partner_name=r[start + 7],
                    kubun=r[start],
                ))


def _read_csv(path: str) -> list[list[str]]:
    with open(path, encoding=ENCODING, newline="") as f:
        return list(csv.reader(f))


def download_all(dest_dir: Union[str, os.PathLike]) -> dict[str, str]:
    """4 テーブルすべてをダウンロードし、{テーブル名: CSVパス} を返す。"""
    result = {}
    for name, (url, _) in TABLES.items():
        result[name] = _download_zip(dest_dir, url=url)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m new_dental_ai.uke.tables",
        description="歯科電子点数表チェック用テーブルのダウンロード",
    )
    parser.add_argument("--download", metavar="DIR", help="点検テーブルを DIR にダウンロードする")
    args = parser.parse_args(argv)
    if args.download:
        for name, path in download_all(args.download).items():
            print(f"{name}: {path}")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
