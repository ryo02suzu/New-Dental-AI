"""公式チェック用テーブルに基づくレセプト点検エンジン。

歯科電子点数表のチェック用テーブル（tables.py）を使って、UKE ファイルの
各レセプトから返戻リスクのある記録を検出する。

検出の重大度:
- NG: テーブル上明確に condition を満たさない（返戻リスク大）
- 要確認: 特例条件がある、月内の誕生日で判定が変わり得る等、人の確認が必要
"""

from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass

from .models import Receipt, UkeFile
from .tables import CheckTables

NG = "NG"
REVIEW = "要確認"

# 点検対象の診療行為系レコード
_PROCEDURE_TYPES = ("SS", "SI")


@dataclass(frozen=True)
class Finding:
    """点検で見つかった指摘 1 件。"""

    receipt_number: int | None
    patient_name: str
    severity: str  # NG / 要確認
    rule: str  # 算定回数限度 / 年齢制限 / 併算定背反 / 実日数
    message: str

    def __str__(self) -> str:
        return (
            f"[{self.receipt_number}] {self.patient_name}: "
            f"{self.severity} [{self.rule}] {self.message}"
        )


def check_uke(uke: UkeFile, tables: CheckTables) -> list[Finding]:
    """UKE ファイル全体を点検し、指摘のリストを返す。"""
    findings: list[Finding] = []
    for receipt in uke.receipts:
        findings.extend(check_receipt(receipt, tables))
    return findings


def check_receipt(receipt: Receipt, tables: CheckTables) -> list[Finding]:
    findings: list[Finding] = []

    # コードごとの月内合計回数と日別回数を集計する
    totals: dict[str, int] = {}
    day_counts: dict[str, dict[int, int]] = {}
    for record in receipt.details:
        if record.record_type not in _PROCEDURE_TYPES:
            continue
        code = record.get("診療行為コード")
        if not code:
            continue
        santeibi = record.santeibi()
        kaisu = record.get_int("回数") or sum(santeibi.values()) or 1
        totals[code] = totals.get(code, 0) + kaisu
        days = day_counts.setdefault(code, {})
        for day, count in santeibi.items():
            days[day] = days.get(day, 0) + count

    def add(severity: str, rule: str, message: str) -> None:
        findings.append(Finding(
            receipt_number=receipt.receipt_number,
            patient_name=receipt.patient_name,
            severity=severity, rule=rule, message=message,
        ))

    _check_count_limits(totals, day_counts, tables, add)
    _check_age_limits(receipt, totals, tables, add)
    _check_day_relations(receipt, totals, tables, add)
    _check_exclusions(totals, tables, add)
    return findings


# ---------------------------------------------------------------------------
# 算定回数限度
# ---------------------------------------------------------------------------

def _check_count_limits(totals, day_counts, tables: CheckTables, add) -> None:
    for code, total in totals.items():
        cl = tables.count_limits.get(code)
        if cl is None:
            continue
        if cl.unit == "131":  # 1月（レセプト）につき
            if total > cl.limit:
                add(
                    REVIEW if cl.special else NG, "算定回数限度",
                    f"{cl.name}: 月{total}回 算定（上限 月{cl.limit}回"
                    + ("、特例条件あり）" if cl.special else "）"),
                )
        elif cl.unit == "121":  # 1日につき
            for day, count in sorted(day_counts.get(code, {}).items()):
                if count > cl.limit:
                    add(
                        REVIEW if cl.special else NG, "算定回数限度",
                        f"{cl.name}: {day}日に{count}回 算定（上限 1日{cl.limit}回）",
                    )
        # その他の単位（週・入院中等）は月内レセプトだけでは判定できないため対象外


# ---------------------------------------------------------------------------
# 年齢制限
# ---------------------------------------------------------------------------

def _age_at(birth: datetime.date, on: datetime.date) -> int:
    years = on.year - birth.year
    if (on.month, on.day) < (birth.month, birth.day):
        years -= 1
    return years


def _preschool_cutoff(birth: datetime.date) -> datetime.date:
    """未就学（6歳に達した日以後の最初の3月31日）の最終日を返す。"""
    sixth = birth.replace(year=birth.year + 6, day=min(birth.day, 28) if birth.month == 2 else birth.day)
    year = sixth.year if sixth <= datetime.date(sixth.year, 3, 31) else sixth.year + 1
    return datetime.date(year, 3, 31)


def _age_ok(limit, birth: datetime.date, on: datetime.date) -> bool:
    age = _age_at(birth, on)
    if limit.lower.isdigit() and int(limit.lower) > 0 and age < int(limit.lower):
        return False
    if limit.upper.isdigit() and int(limit.upper) > 0 and age >= int(limit.upper):
        return False
    if limit.upper == "BK" and on > _preschool_cutoff(birth):
        return False
    return True


def _describe_age_limit(limit) -> str:
    parts = []
    if limit.lower.isdigit() and int(limit.lower) > 0:
        parts.append(f"{int(limit.lower)}歳以上")
    if limit.upper.isdigit() and int(limit.upper) > 0:
        parts.append(f"{int(limit.upper)}歳未満")
    if limit.upper == "BK":
        parts.append("未就学")
    return "・".join(parts) or "制限あり"


def _check_age_limits(receipt: Receipt, totals, tables: CheckTables, add) -> None:
    birth = receipt.birth_date
    treatment = receipt.treatment_month
    if birth is None or treatment is None:
        return
    year, month = treatment
    month_start = datetime.date(year, month, 1)
    month_end = datetime.date(year, month, calendar.monthrange(year, month)[1])
    for code in totals:
        limit = tables.age_limits.get(code)
        if limit is None:
            continue
        # "AA"（生後28日）等、月単位では判定できない表記は対象外
        if not (limit.lower.isdigit() or limit.lower == "00"):
            continue
        if not (limit.upper.isdigit() or limit.upper in ("00", "BK")):
            continue
        ok_start = _age_ok(limit, birth, month_start)
        ok_end = _age_ok(limit, birth, month_end)
        if ok_start and ok_end:
            continue
        age = _age_at(birth, month_start)
        message = (
            f"{limit.name}: 患者は{age}歳"
            f"（対象: {_describe_age_limit(limit)}、生年月日 {birth.isoformat()}）"
        )
        # 月の途中の誕生日で判定が変わる場合は要確認にとどめる
        add(NG if not (ok_start or ok_end) else REVIEW, "年齢制限", message)


# ---------------------------------------------------------------------------
# 実日数関連
# ---------------------------------------------------------------------------

def _check_day_relations(receipt: Receipt, totals, tables: CheckTables, add) -> None:
    actual_days = receipt.actual_days
    if not actual_days:
        return
    for code, total in totals.items():
        relation = tables.day_relations.get(code)
        if relation is None or relation.relation != "1":
            continue
        if total > actual_days:
            add(
                REVIEW, "実日数",
                f"{relation.name}: 月{total}回 算定が診療実日数 {actual_days}日 を超えています",
            )


# ---------------------------------------------------------------------------
# 併算定背反
# ---------------------------------------------------------------------------

def _check_exclusions(totals, tables: CheckTables, add) -> None:
    present = set(totals)
    reported: set[frozenset[str]] = set()
    for code in present:
        for exclusion in tables.exclusions.get(code, ()):
            if exclusion.partner_code not in present:
                continue
            pair = frozenset((code, exclusion.partner_code))
            if pair in reported:
                continue
            reported.add(pair)
            add(
                REVIEW, "併算定背反",
                f"{exclusion.name} と {exclusion.partner_name} が"
                f"同一レセプトに記録されています（背反区分 {exclusion.kubun}）",
            )
