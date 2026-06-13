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
- 歯科診療行為マスター（基本テーブル）による名称解決（例: `301000110` → 歯科初診料）

## レセプト点検エンジン (`new_dental_ai.uke.checker`)

歯科電子点数表のチェック用テーブル（厚生労働省 診療報酬情報提供サービスの公開データ）に
基づいて、返戻リスクのある記録を提出前に検出します。

| 点検 | 使用テーブル | 検出例 |
|------|--------------|--------|
| 算定回数限度 | 算定回数限度テーブル | 歯科初診料が月 2 回記録されている |
| 年齢制限 | 年齢制限テーブル | 38 歳の患者に乳幼児加算が付いている |
| 併算定背反 | 併算定背反テーブル | 歯科疾患管理料と歯科特定疾患療養管理料の同時記録 |
| 実日数 | 実日数関連テーブル | 算定回数が診療実日数を超えている |

重大度は 2 段階: `NG`（テーブル上明確な逸脱）と `要確認`（特例条件あり・
月内の誕生日で判定が変わり得る等、人の確認が必要なもの）。

出力例:

```
点検結果: 2件の指摘
  [1] 山田　太郎: NG [年齢制限] 乳幼児加算（初診）: 患者は38歳（対象: 6歳未満、生年月日 1985-10-15）
  [1] 山田　太郎: 要確認 [算定回数限度] 乳幼児加算（初診）: 月2回 算定（上限 月1回、特例条件あり）
```

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

# 診療行為マスターをダウンロード（診療報酬情報提供サービスの公開データ）
python -m new_dental_ai.uke.master --download data/

# 明細表示（マスターで名称解決）
python -m new_dental_ai.uke --details --master data/h_YYYYMMDD.csv RECEIPTC.UKE

# 点検テーブル（算定回数限度・年齢制限・併算定背反・実日数関連）をダウンロード
python -m new_dental_ai.uke.tables --download data/

# レセプト点検（NG があれば終了コード 1）
python -m new_dental_ai.uke --check data/ RECEIPTC.UKE
```

### テスト

```sh
pip install pytest
python -m pytest tests/
```
