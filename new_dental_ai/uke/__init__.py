"""歯科レセプト電算処理システム UKE ファイルの読み取り・解析。

使い方::

    from new_dental_ai.uke import parse_file

    uke = parse_file("RECEIPTC.UKE")
    print(uke.institution_name, uke.billing_month)
    for receipt in uke.receipts:
        print(receipt.patient_name, receipt.main_insurance_points)
"""

from .master import DentalMaster, MasterEntry
from .models import (
    Receipt,
    UkeFile,
    UkeRecord,
    describe_receipt_type,
    parse_gyymm,
    parse_gyymmdd,
    wareki_to_year,
)
from .parser import UkeParseError, parse_bytes, parse_file

__all__ = [
    "DentalMaster",
    "MasterEntry",
    "Receipt",
    "UkeFile",
    "UkeRecord",
    "UkeParseError",
    "describe_receipt_type",
    "parse_bytes",
    "parse_file",
    "parse_gyymm",
    "parse_gyymmdd",
    "wareki_to_year",
]
