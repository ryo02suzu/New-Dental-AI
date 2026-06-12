# New-Dental-AI

歯科レセプト関連の AI ツール群。

## UKE パーサー (`new_dental_ai.uke`)

歯科レセプト電算処理システムの請求ファイル（RECEIPTC.UKE）を読み取り、
レセプト単位の構造化データに変換するパーサーです。
「オンライン又は光ディスク等による請求に係る記録条件仕様（歯科用）」に準拠しています。

### 対応レコード

| 識別 | レコード | 識別 | レコード |
|------|----------|------|----------|
| UK | 受付情報 | SS | 歯科診療行為 |
| IR | 医療機関情報 | SI | 医科診療行為 |
| RE | レセプト共通 | IY | 医薬品 |
| HO | 保険者 | TO | 特定器材 |
| KO | 公費 | CO | コメント |
| HS | 傷病名部位 | SJ | 症状詳記 |
| GO | 診療報酬請求書 | | |

### 機能

- Shift_JIS (cp932)・CRLF・EOF コード (0x1A) を含む UKE ファイルの読み取り
- 記録条件仕様の項目名による値アクセス（`record.get("合計点数")` など）
- 和暦 (GYYMM / GYYMMDD) → 西暦変換
- レセプト種別コード（別表6）の読み下し（例: `3112` → 歯科・医保・国保・単独・本人/世帯主・入院外）
- 整合性チェック（GO の総件数・総合計点数、診療行為の回数と算定日情報の突合）

### 使い方

```python
from new_dental_ai.uke import parse_file

uke = parse_file("RECEIPTC.UKE")
print(uke.institution_name, uke.billing_month)
for receipt in uke.receipts:
    print(receipt.patient_name, receipt.main_insurance_points)

for issue in uke.validate():
    print("NG:", issue)
```

CLI:

```sh
# サマリ表示
python -m new_dental_ai.uke RECEIPTC.UKE

# JSON 出力
python -m new_dental_ai.uke --json RECEIPTC.UKE
```

### テスト

```sh
pip install pytest
python -m pytest tests/
```
