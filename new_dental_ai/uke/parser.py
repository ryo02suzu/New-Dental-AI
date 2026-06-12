"""UKE ファイルのパーサー。"""

from __future__ import annotations

import os
from typing import Union

from .models import Receipt, UkeFile, UkeRecord

# UKE ファイルの文字コードは Shift_JIS。Windows 系レセコンの出力を考慮し
# cp932（Shift_JIS の MS 拡張）でデコードする。
ENCODING = "cp932"

_EOF_BYTE = b"\x1a"


class UkeParseError(ValueError):
    def __init__(self, message: str, line_number: int | None = None):
        if line_number is not None:
            message = f"{line_number}行目: {message}"
        super().__init__(message)
        self.line_number = line_number


def parse_bytes(data: bytes) -> UkeFile:
    """UKE ファイルのバイト列を解析する。"""
    text = data.rstrip(_EOF_BYTE + b"\r\n \t").decode(ENCODING)
    records = [
        UkeRecord(fields=line.split(","), line_number=i)
        for i, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1)
        if line.strip()
    ]
    return _assemble(records)


def parse_file(path: Union[str, os.PathLike]) -> UkeFile:
    """UKE ファイル（RECEIPTC.UKE 等）を読み込み解析する。"""
    with open(path, "rb") as f:
        return parse_bytes(f.read())


def _assemble(records: list[UkeRecord]) -> UkeFile:
    """レコード列をレセプト単位にまとめる。"""
    uke = UkeFile()
    current: Receipt | None = None

    for record in records:
        record_type = record.record_type
        if record_type == "UK":
            uke.uk = record
        elif record_type == "IR":
            if uke.ir is not None:
                raise UkeParseError("IR レコードが重複しています", record.line_number)
            uke.ir = record
        elif record_type == "RE":
            current = Receipt(re=record)
            uke.receipts.append(current)
        elif record_type == "GO":
            uke.go = record
            current = None
        elif record_type in ("HO", "KO", "HS", "SS", "SI", "IY", "TO", "CO", "SJ"):
            if current is None:
                raise UkeParseError(
                    f"{record.record_name}（{record_type}）が RE レコードより前に出現しました",
                    record.line_number,
                )
            if record_type == "HO":
                current.hos.append(record)
            elif record_type == "KO":
                current.kos.append(record)
            elif record_type == "HS":
                current.hss.append(record)
            elif record_type == "SJ":
                current.sjs.append(record)
            else:
                current.details.append(record)
        else:
            uke.unknown_records.append(record)

    return uke
