"""UKE ファイルのサマリ表示 CLI。

使い方:
    python -m new_dental_ai.uke RECEIPTC.UKE
    python -m new_dental_ai.uke --json RECEIPTC.UKE
    python -m new_dental_ai.uke --details --master data/h_YYYYMMDD.csv RECEIPTC.UKE
"""

from __future__ import annotations

import argparse
import json
import sys

from .master import DentalMaster
from .parser import parse_file

_CODE_FIELD = {
    "SS": "診療行為コード",
    "SI": "診療行為コード",
    "IY": "医薬品コード",
    "TO": "特定器材コード",
    "CO": "コメントコード",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m new_dental_ai.uke",
        description="歯科レセプト UKE ファイルのサマリを表示する",
    )
    parser.add_argument("path", help="UKE ファイルのパス（例: RECEIPTC.UKE）")
    parser.add_argument("--json", action="store_true", help="JSON で出力する")
    parser.add_argument("--details", action="store_true", help="診療行為の明細も表示する")
    parser.add_argument(
        "--master", metavar="CSV",
        help="歯科診療行為マスター（基本テーブル）CSV。コードを名称に解決する",
    )
    args = parser.parse_args(argv)

    uke = parse_file(args.path)
    master = DentalMaster.load(args.master) if args.master else None

    def resolve(record) -> str:
        code = record.get(_CODE_FIELD.get(record.record_type, "")) if record.record_type in _CODE_FIELD else ""
        if not code:
            return ""
        if master and record.record_type in ("SS", "SI"):
            return master.name(code) or code
        return code

    if args.json:
        data = uke.to_dict()
        if master:
            for receipt_dict, receipt in zip(data["レセプト"], uke.receipts):
                for detail_dict, record in zip(receipt_dict["診療行為レコード"], receipt.details):
                    if record.record_type in ("SS", "SI"):
                        name = master.name(record.get("診療行為コード"))
                        if name:
                            detail_dict["名称"] = name
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        billing = uke.billing_month
        print(f"医療機関: {uke.institution_name} ({uke.prefecture} {uke.institution_code})")
        if billing:
            print(f"請求年月: {billing[0]}年{billing[1]}月")
        print(f"レセプト件数: {len(uke.receipts)} / 総合計点数: {uke.total_points}")
        print()
        for receipt in uke.receipts:
            treatment = receipt.treatment_month
            month = f"{treatment[0]}年{treatment[1]}月" if treatment else "?"
            print(
                f"  [{receipt.receipt_number}] {receipt.patient_name} ({receipt.sex}) "
                f"診療 {month} 実日数 {receipt.actual_days or '-'} "
                f"点数 {receipt.main_insurance_points or '-'} "
                f"({receipt.receipt_type_description})"
            )
            if args.details:
                for record in receipt.details:
                    if record.record_type == "CO":
                        label = record.get("文字データ") or record.get("コメントコード")
                        tensu = kaisu = ""
                    else:
                        label = resolve(record)
                        tensu = record.get("点数")
                        kaisu = record.get("回数")
                    line = f"      {record.record_type} {label}"
                    if tensu:
                        line += f" {tensu}点"
                    if kaisu:
                        line += f" x{kaisu}"
                    print(line)

    issues = uke.validate()
    if issues:
        print("\n整合性チェック:", file=sys.stderr)
        for issue in issues:
            print(f"  NG {issue}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
