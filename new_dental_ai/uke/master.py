"""歯科診療行為マスター（基本テーブル）の読み込みと名称解決。

診療報酬情報提供サービス（厚生労働省）が公開している
「歯科診療行為マスター 基本テーブル」CSV を読み込み、
診療行為コード（9桁）から名称・点数を引けるようにする。

ダウンロード:
    python -m new_dental_ai.uke.master --download data/
"""

from __future__ import annotations

import csv
import io
import os
import urllib.request
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from typing import Union

# 診療報酬情報提供サービスの歯科診療行為マスター（基本テーブル）全件ダウンロード URL
DOWNLOAD_URL = "https://shinryohoshu.mhlw.go.jp/shinryohoshu/receDentalMenu/hFile"

ENCODING = "cp932"


@dataclass(frozen=True)
class MasterEntry:
    """歯科診療行為マスターの 1 件。"""

    code: str  # 診療行為コード（9桁）
    name: str  # 漢字名称（例: 歯科初診料）
    short_name: str  # 省略漢字名称（例: 初診）
    kubun: str  # 点数表区分番号（例: A000）
    point_type: str  # 点数識別
    points: Decimal | None  # 新又は現点数


class DentalMaster:
    """診療行為コード → マスター情報の辞書。"""

    def __init__(self, entries: dict[str, MasterEntry]):
        self._entries = entries

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, code: str) -> bool:
        return code in self._entries

    def lookup(self, code: str) -> MasterEntry | None:
        return self._entries.get(code)

    def name(self, code: str) -> str | None:
        entry = self._entries.get(code)
        return entry.name if entry else None

    @classmethod
    def load(cls, path: Union[str, os.PathLike]) -> "DentalMaster":
        """基本テーブル CSV（cp932）を読み込む。"""
        entries: dict[str, MasterEntry] = {}
        with open(path, encoding=ENCODING, newline="") as f:
            for row in csv.reader(f):
                entry = _parse_row(row)
                if entry:
                    entries[entry.code] = entry
        return cls(entries)


def _parse_row(row: list[str]) -> MasterEntry | None:
    # 列構成: 変更区分, レコード識別("H"), 診療行為コード,
    #         区分（章 + 区分番号 + 枝番…）, 漢字名称, 省略漢字名称,
    #         点数識別, 新又は現点数, ...
    if len(row) < 12 or row[1] != "H":
        return None
    code = row[2].strip()
    if len(code) != 9 or not code.isdigit():
        return None
    try:
        points: Decimal | None = Decimal(row[11])
    except ArithmeticError:
        points = None
    return MasterEntry(
        code=code,
        name=row[8].strip(),
        short_name=row[9].strip(),
        kubun=f"{row[3]}{row[4]}".strip(),
        point_type=row[10].strip(),
        points=points,
    )


def download(dest_dir: Union[str, os.PathLike], url: str = DOWNLOAD_URL) -> str:
    """マスター zip をダウンロード・展開し、CSV のパスを返す。"""
    os.makedirs(dest_dir, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise RuntimeError("zip 内に CSV が見つかりません")
        zf.extract(csv_names[0], dest_dir)
    return os.path.join(dest_dir, csv_names[0])


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m new_dental_ai.uke.master",
        description="歯科診療行為マスターのダウンロード",
    )
    parser.add_argument("--download", metavar="DIR", help="マスターを DIR にダウンロードする")
    args = parser.parse_args(argv)
    if args.download:
        path = download(args.download)
        master = DentalMaster.load(path)
        print(f"{path} ({len(master)}件)")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
