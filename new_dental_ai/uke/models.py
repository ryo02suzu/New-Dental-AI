"""UKE ファイルのデータモデル。"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Iterator

from . import spec


# ---------------------------------------------------------------------------
# 和暦変換
# ---------------------------------------------------------------------------

def wareki_to_year(era_code: str, year: int) -> int:
    """年号区分コードと和暦年から西暦年を返す。"""
    try:
        _, first_year = spec.ERAS[era_code]
    except KeyError:
        raise ValueError(f"不明な年号区分コード: {era_code!r}")
    return first_year + year - 1


def parse_gyymm(value: str) -> tuple[int, int] | None:
    """"GYYMM" 形式（例: 50604 = 令和6年4月）を (西暦年, 月) に変換する。"""
    if not value:
        return None
    if len(value) != 5 or not value.isdigit():
        raise ValueError(f"GYYMM 形式ではありません: {value!r}")
    year = wareki_to_year(value[0], int(value[1:3]))
    return year, int(value[3:5])


def parse_gyymmdd(value: str) -> datetime.date | None:
    """"GYYMMDD" 形式（例: 4010203 = 平成1年2月3日）を date に変換する。"""
    if not value:
        return None
    if len(value) != 7 or not value.isdigit():
        raise ValueError(f"GYYMMDD 形式ではありません: {value!r}")
    year = wareki_to_year(value[0], int(value[1:3]))
    return datetime.date(year, int(value[3:5]), int(value[5:7]))


# ---------------------------------------------------------------------------
# レコード
# ---------------------------------------------------------------------------

@dataclass
class UkeRecord:
    """UKE ファイルの 1 行（1 レコード）。

    fields はコンマ区切りを分割した生の値（先頭はレコード識別情報）。
    末尾の省略項目は空文字列として扱う。
    """

    fields: list[str]
    line_number: int = 0

    @property
    def record_type(self) -> str:
        return self.fields[0] if self.fields else ""

    @property
    def record_name(self) -> str:
        return spec.RECORD_NAMES.get(self.record_type, "不明レコード")

    def get(self, name: str) -> str:
        """記録条件仕様の項目名で値を取得する。省略された項目は空文字列。"""
        names = spec.FIELD_NAMES.get(self.record_type)
        if names is None:
            raise KeyError(f"未定義のレコード種別: {self.record_type!r}")
        try:
            index = names.index(name)
        except ValueError:
            raise KeyError(f"{self.record_type} レコードに項目 {name!r} はありません")
        if index < len(self.fields):
            return self.fields[index]
        return ""

    def get_int(self, name: str, default: int | None = None) -> int | None:
        value = self.get(name)
        return int(value) if value else default

    def santeibi(self) -> dict[int, int]:
        """算定日情報を {日: 回数} で返す（SS/SI/IY/TO レコード用）。"""
        result: dict[int, int] = {}
        for day in range(1, 32):
            value = self.get(f"算定日_{day}日")
            if value:
                result[day] = int(value)
        return result

    def to_dict(self) -> dict[str, str]:
        """空でない項目を {項目名: 値} で返す。"""
        names = spec.FIELD_NAMES.get(self.record_type)
        if names is None:
            return {f"項目{i}": v for i, v in enumerate(self.fields) if v}
        result: dict[str, str] = {}
        for i, value in enumerate(self.fields):
            if not value:
                continue
            name = names[i] if i < len(names) else f"項目{i}"
            result[name] = value
        return result


# ---------------------------------------------------------------------------
# レセプト種別（別表６）のデコード
# ---------------------------------------------------------------------------

_SHUBETSU_HOKEN = {
    "1": "医保・国保",
    "2": "公費",
    "3": "後期高齢者",
    "4": "退職者",
}

_SHUBETSU_HEIYO = {
    "1": "単独",
    "2": "１種の公費併用",
    "3": "２種の公費併用",
    "4": "３種の公費併用",
    "5": "４種の公費併用",
}

_SHUBETSU_PATIENT = {
    "1": ("本人/世帯主", "入院"),
    "2": ("本人/世帯主", "入院外"),
    "3": ("未就学者", "入院"),
    "4": ("未就学者", "入院外"),
    "5": ("家族/その他", "入院"),
    "6": ("家族/その他", "入院外"),
    "7": ("高齢受給者一般・低所得者", "入院"),
    "8": ("高齢受給者一般・低所得者", "入院外"),
    "9": ("高齢受給者７割", "入院"),
    "0": ("高齢受給者７割", "入院外"),
}


def describe_receipt_type(code: str) -> str:
    """レセプト種別コード（4桁）を読み下し文字列にする。

    例: "3112" → "歯科・医保・国保単独・本人/世帯主・入院外"
    不明な形式の場合はコードをそのまま返す。
    """
    if len(code) != 4:
        return code
    table = spec.POINT_TABLES.get(code[0], f"点数表{code[0]}")
    hoken = _SHUBETSU_HOKEN.get(code[1])
    if hoken is None:
        return code
    parts = [table, hoken]
    if code[1] in ("1", "3", "4"):  # 医保・国保 / 後期高齢者 / 退職者は併用区分あり
        heiyo = _SHUBETSU_HEIYO.get(code[2])
        if heiyo:
            parts.append(heiyo)
    elif code[1] == "2":  # 公費: 3桁目は単独(1)または併用する公費の数(2〜4)
        parts.append("単独" if code[2] == "1" else f"{code[2]}種の公費併用")
    patient = _SHUBETSU_PATIENT.get(code[3])
    if code[1] == "2":
        # 公費は患者区分なし、末尾は入院/入院外のみ
        parts.append("入院" if code[3] == "1" else "入院外")
    elif patient:
        parts.extend(patient)
    return "・".join(parts)


# ---------------------------------------------------------------------------
# レセプト（RE レコード単位のまとまり）
# ---------------------------------------------------------------------------

@dataclass
class Receipt:
    """1 件のレセプト。RE レコードとそれに続く各レコードのまとまり。"""

    re: UkeRecord
    hos: list[UkeRecord] = field(default_factory=list)  # 保険者レコード
    kos: list[UkeRecord] = field(default_factory=list)  # 公費レコード
    hss: list[UkeRecord] = field(default_factory=list)  # 傷病名部位レコード
    details: list[UkeRecord] = field(default_factory=list)  # SS/SI/IY/TO/CO（記録順）
    sjs: list[UkeRecord] = field(default_factory=list)  # 症状詳記レコード

    @property
    def receipt_number(self) -> int | None:
        return self.re.get_int("レセプト番号")

    @property
    def receipt_type(self) -> str:
        return self.re.get("レセプト種別")

    @property
    def receipt_type_description(self) -> str:
        return describe_receipt_type(self.receipt_type)

    @property
    def patient_name(self) -> str:
        return self.re.get("氏名")

    @property
    def patient_kana(self) -> str:
        return self.re.get("カタカナ氏名")

    @property
    def sex(self) -> str:
        return spec.SEX.get(self.re.get("男女区分"), "")

    @property
    def birth_date(self) -> datetime.date | None:
        return parse_gyymmdd(self.re.get("生年月日"))

    @property
    def treatment_month(self) -> tuple[int, int] | None:
        """診療年月 (西暦年, 月)。"""
        return parse_gyymm(self.re.get("診療年月"))

    @property
    def main_insurance_points(self) -> int | None:
        """主保険に係る合計点数。

        保険者レコードがあればその合計点数、なければ最初の公費レコードの
        合計点数（GO レコードの総合計点数の合算規則に対応）。
        """
        if self.hos:
            return self.hos[0].get_int("合計点数")
        if self.kos:
            return self.kos[0].get_int("合計点数")
        return None

    @property
    def actual_days(self) -> int | None:
        """主保険の診療実日数。"""
        if self.hos:
            return self.hos[0].get_int("診療実日数")
        if self.kos:
            return self.kos[0].get_int("診療実日数")
        return None

    def all_records(self) -> Iterator[UkeRecord]:
        yield self.re
        yield from self.hos
        yield from self.kos
        yield from self.hss
        yield from self.details
        yield from self.sjs

    def to_dict(self) -> dict[str, Any]:
        treatment = self.treatment_month
        birth = self.birth_date
        return {
            "レセプト番号": self.receipt_number,
            "レセプト種別": self.receipt_type,
            "レセプト種別名": self.receipt_type_description,
            "診療年月": f"{treatment[0]:04d}-{treatment[1]:02d}" if treatment else None,
            "氏名": self.patient_name,
            "カタカナ氏名": self.patient_kana or None,
            "男女": self.sex,
            "生年月日": birth.isoformat() if birth else None,
            "診療実日数": self.actual_days,
            "合計点数": self.main_insurance_points,
            "保険者レコード": [r.to_dict() for r in self.hos],
            "公費レコード": [r.to_dict() for r in self.kos],
            "傷病名部位レコード": [r.to_dict() for r in self.hss],
            "診療行為レコード": [r.to_dict() for r in self.details],
            "症状詳記レコード": [r.to_dict() for r in self.sjs],
        }


# ---------------------------------------------------------------------------
# UKE ファイル全体
# ---------------------------------------------------------------------------

@dataclass
class UkeFile:
    """UKE ファイル 1 件分（1 ボリューム）の解析結果。"""

    uk: UkeRecord | None = None  # 受付情報レコード（オンライン請求時のみ）
    ir: UkeRecord | None = None  # 医療機関情報レコード
    receipts: list[Receipt] = field(default_factory=list)
    go: UkeRecord | None = None  # 診療報酬請求書レコード
    unknown_records: list[UkeRecord] = field(default_factory=list)

    @property
    def institution_name(self) -> str:
        return self.ir.get("医療機関名称") if self.ir else ""

    @property
    def institution_code(self) -> str:
        return self.ir.get("医療機関コード") if self.ir else ""

    @property
    def prefecture(self) -> str:
        if not self.ir:
            return ""
        return spec.PREFECTURES.get(self.ir.get("都道府県"), "")

    @property
    def billing_month(self) -> tuple[int, int] | None:
        """請求年月 (西暦年, 月)。"""
        return parse_gyymm(self.ir.get("請求年月")) if self.ir else None

    @property
    def total_points(self) -> int:
        """全レセプトの主保険合計点数の総和。"""
        return sum(r.main_insurance_points or 0 for r in self.receipts)

    def validate(self) -> list[str]:
        """ファイル内の整合性を検査し、問題点のリストを返す。"""
        issues: list[str] = []
        if self.ir is None:
            issues.append("IR（医療機関情報）レコードがありません")
        if self.go is None:
            issues.append("GO（診療報酬請求書）レコードがありません")
        else:
            total_count = self.go.get_int("総件数")
            if total_count is not None and total_count != len(self.receipts):
                issues.append(
                    f"GO の総件数 {total_count} がレセプト数 {len(self.receipts)} と一致しません"
                )
            total_points = self.go.get_int("総合計点数")
            if total_points is not None and total_points != self.total_points:
                issues.append(
                    f"GO の総合計点数 {total_points} が各レセプトの合算 {self.total_points} と一致しません"
                )
        for receipt in self.receipts:
            number = receipt.receipt_number
            for record in receipt.details:
                if record.record_type not in ("SS", "SI", "IY", "TO"):
                    continue
                kaisu = record.get_int("回数")
                santeibi = record.santeibi()
                if kaisu is not None and santeibi and sum(santeibi.values()) != kaisu:
                    issues.append(
                        f"レセプト{number} {record.record_name}"
                        f"（{record.line_number}行目）: 回数 {kaisu} と"
                        f"算定日情報の合計 {sum(santeibi.values())} が一致しません"
                    )
        return issues

    def to_dict(self) -> dict[str, Any]:
        billing = self.billing_month
        return {
            "医療機関コード": self.institution_code,
            "医療機関名称": self.institution_name,
            "都道府県": self.prefecture,
            "請求年月": f"{billing[0]:04d}-{billing[1]:02d}" if billing else None,
            "レセプト件数": len(self.receipts),
            "総合計点数": self.total_points,
            "レセプト": [r.to_dict() for r in self.receipts],
        }
