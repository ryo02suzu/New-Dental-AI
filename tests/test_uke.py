import datetime

import pytest

from new_dental_ai.uke import (
    UkeParseError,
    describe_receipt_type,
    parse_bytes,
    parse_file,
    parse_gyymm,
    parse_gyymmdd,
)


def ss_record(shikibetsu, futan, code, tensu, kaisu, days):
    """歯科診療行為レコード（SS）の1行を組み立てる。"""
    fields = ["SS", shikibetsu, futan, code, "", ""]
    fields += [""] * 70  # 加算コード／加算数量データ 1〜35
    fields += [str(tensu), str(kaisu)]
    santeibi = [""] * 31
    for day, count in days.items():
        santeibi[day - 1] = str(count)
    fields += santeibi
    return ",".join(fields).rstrip(",")


def build_uke(lines):
    """UKEファイルのバイト列（cp932 / CRLF / 末尾EOFコード）を組み立てる。"""
    return ("\r\n".join(lines) + "\r\n").encode("cp932") + b"\x1a"


SAMPLE_LINES = [
    "IR,1,13,3,1234567,,テスト歯科医院,50604,03-1234-5678,",
    # レセプト1: 医保単独・本人・入院外
    "RE,1,3112,50604,山田　太郎,1,3601015,,,5060401,,,,,,K001",
    "HO,06132013,はーと,1234567,2,580",
    "HS,,,110100,8830109",
    ss_record("11", "1", "301000110", 261, 1, {2: 1}),
    ss_record("12", "1", "301000370", 319, 2, {2: 1, 16: 1}),
    "CO,99,1,810000001,丁寧な歯清を実施",
    # レセプト2: 公費単独・入院外
    "RE,2,3212,50604,佐藤　花子,2,4050203,,,5060105,,,,,,K002",
    "KO,12131011,1234567,,3,580",
    "HS,,,210100,8830109",
    ss_record("11", "5", "301000110", 261, 1, {7: 1}),
    ss_record("12", "5", "301000370", 319, 2, {14: 1, 28: 1}),
    "GO,2,1160,99",
]


@pytest.fixture
def sample_uke():
    return parse_bytes(build_uke(SAMPLE_LINES))


class TestWareki:
    def test_parse_gyymm(self):
        assert parse_gyymm("50604") == (2024, 4)  # 令和6年4月
        assert parse_gyymm("42504") == (2013, 4)  # 平成25年4月
        assert parse_gyymm("") is None

    def test_parse_gyymmdd(self):
        assert parse_gyymmdd("3601015") == datetime.date(1985, 10, 15)  # 昭和60年
        assert parse_gyymmdd("5010501") == datetime.date(2019, 5, 1)  # 令和元年
        assert parse_gyymmdd("") is None

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_gyymm("123")
        with pytest.raises(ValueError):
            parse_gyymmdd("9010101")  # 年号区分コード9は未定義


class TestReceiptType:
    def test_iho_tandoku(self):
        assert (
            describe_receipt_type("3112")
            == "歯科・医保・国保・単独・本人/世帯主・入院外"
        )

    def test_kohi_tandoku(self):
        assert describe_receipt_type("3212") == "歯科・公費・単独・入院外"

    def test_kohi_heiyo(self):
        assert describe_receipt_type("3222") == "歯科・公費・2種の公費併用・入院外"

    def test_kouki(self):
        assert (
            describe_receipt_type("3318")
            == "歯科・後期高齢者・単独・高齢受給者一般・低所得者・入院外"
        )
        assert describe_receipt_type("3328").startswith("歯科・後期高齢者・１種の公費併用")

    def test_unknown_passthrough(self):
        assert describe_receipt_type("0000") == "0000"
        assert describe_receipt_type("31") == "31"


class TestParser:
    def test_institution(self, sample_uke):
        assert sample_uke.institution_name == "テスト歯科医院"
        assert sample_uke.institution_code == "1234567"
        assert sample_uke.prefecture == "東京"
        assert sample_uke.billing_month == (2024, 4)

    def test_receipts(self, sample_uke):
        assert len(sample_uke.receipts) == 2
        r1, r2 = sample_uke.receipts
        assert r1.receipt_number == 1
        assert r1.patient_name == "山田　太郎"
        assert r1.sex == "男"
        assert r1.birth_date == datetime.date(1985, 10, 15)
        assert r1.treatment_month == (2024, 4)
        assert r1.actual_days == 2
        assert r1.main_insurance_points == 580
        assert r2.sex == "女"
        assert r2.main_insurance_points == 580  # 公費単独はKOレコードから

    def test_records_grouping(self, sample_uke):
        r1 = sample_uke.receipts[0]
        assert len(r1.hos) == 1
        assert len(r1.kos) == 0
        assert len(r1.hss) == 1
        assert [d.record_type for d in r1.details] == ["SS", "SS", "CO"]
        r2 = sample_uke.receipts[1]
        assert len(r2.hos) == 0
        assert len(r2.kos) == 1

    def test_field_access_by_name(self, sample_uke):
        ho = sample_uke.receipts[0].hos[0]
        assert ho.get("保険者番号") == "06132013"
        assert ho.get("合計点数") == "580"
        assert ho.get("減額金額") == ""  # 末尾省略は空文字列
        with pytest.raises(KeyError):
            ho.get("存在しない項目")

    def test_santeibi(self, sample_uke):
        ss = sample_uke.receipts[0].details[1]
        assert ss.get("点数") == "319"
        assert ss.santeibi() == {2: 1, 16: 1}

    def test_total_and_validation(self, sample_uke):
        assert sample_uke.total_points == 1160
        assert sample_uke.go.get("総件数") == "2"
        assert sample_uke.validate() == []

    def test_to_dict(self, sample_uke):
        d = sample_uke.to_dict()
        assert d["医療機関名称"] == "テスト歯科医院"
        assert d["レセプト件数"] == 2
        assert d["レセプト"][0]["レセプト種別名"] == "歯科・医保・国保・単独・本人/世帯主・入院外"

    def test_parse_file(self, tmp_path, sample_uke):
        path = tmp_path / "RECEIPTC.UKE"
        path.write_bytes(build_uke(SAMPLE_LINES))
        uke = parse_file(path)
        assert uke.to_dict() == sample_uke.to_dict()


class TestValidation:
    def test_go_count_mismatch(self):
        lines = list(SAMPLE_LINES)
        lines[-1] = "GO,3,1160,99"
        issues = parse_bytes(build_uke(lines)).validate()
        assert any("総件数" in i for i in issues)

    def test_go_points_mismatch(self):
        lines = list(SAMPLE_LINES)
        lines[-1] = "GO,2,9999,99"
        issues = parse_bytes(build_uke(lines)).validate()
        assert any("総合計点数" in i for i in issues)

    def test_santeibi_kaisu_mismatch(self):
        lines = list(SAMPLE_LINES)
        lines[4] = ss_record("11", "1", "301000110", 261, 3, {2: 1})  # 回数3だが算定日合計1
        issues = parse_bytes(build_uke(lines)).validate()
        assert any("算定日情報" in i for i in issues)

    def test_missing_go(self):
        issues = parse_bytes(build_uke(SAMPLE_LINES[:-1])).validate()
        assert any("GO" in i for i in issues)

    def test_record_before_re(self):
        with pytest.raises(UkeParseError):
            parse_bytes(build_uke(["IR,1,13,3,1234567,,テスト,50604,,", "HO,06132013,a,1,2,580"]))


# 歯科診療行為マスター（基本テーブル）の抜粋（公開データ）
MASTER_ROWS = [
    "0,H,301000110,A,000,00,001,00000,歯科初診料,初診,3,272.00",
    "0,H,301000210,A,000,00,002,00000,地域歯科診療支援病院歯科初診料,病初診,3,296.00",
    "0,H,301000370,A,000,00,004,CA001,乳幼児加算（初診）,乳（初診）,3,40.00",
]


@pytest.fixture
def master_csv(tmp_path):
    path = tmp_path / "h_master.csv"
    path.write_bytes(("\r\n".join(MASTER_ROWS) + "\r\n").encode("cp932"))
    return path


class TestMaster:
    def test_load_and_lookup(self, master_csv):
        from decimal import Decimal

        from new_dental_ai.uke import DentalMaster

        master = DentalMaster.load(master_csv)
        assert len(master) == 3
        assert master.name("301000110") == "歯科初診料"
        entry = master.lookup("301000110")
        assert entry.kubun == "A000"
        assert entry.short_name == "初診"
        assert entry.points == Decimal("272.00")
        assert master.name("999999999") is None
        assert "301000370" in master


# 点検テーブルの抜粋（公開データに基づく。302000110 の特例条件のみテスト用に 0）
SANTEI_ROWS = [  # h-6 算定回数限度: 単位, 上限回数, 特例条件
    "0,301000110,A,000,00,001,00000,歯科初診料,初診,131,1,1,20260601,99999999,0",
    "0,301000370,A,000,00,004,CA001,乳幼児加算（初診）,乳（初診）,131,1,1,20260601,99999999,0",
    "0,302000110,B,000,04,000,00000,歯科疾患管理料,歯科疾患管理料,131,1,0,20260601,99999999,0",
]
NENREI_ROWS = [  # h-8 年齢制限: 下限, 上限
    "0,301000370,A,000,00,004,CA001,乳幼児加算（初診）,乳（初診）,00,06,20260601,99999999,0",
]
JITSUNISSU_ROWS = [  # h-10 実日数関連: 関係区分
    "0,302000110,B,000,04,000,00000,歯科疾患管理料,歯科疾患管理料,1,0,20260601,99999999,0",
]


def heisantei_row(code_a, name_a, code_b, name_b):
    """h-9 併算定背反の1行（相手は最大10組・各9項目）を組み立てる。"""
    row = ["0", code_a, "B", "000", "00", "000", "00000", name_a, name_a]
    row += ["0", code_b, "B", "000", "00", "000", "00000", name_b, name_b]
    row += [""] * (9 * 9)  # 残り9組分
    row += ["20260601", "99999999", "0", "0", "0"]
    return ",".join(row)


@pytest.fixture
def tables_dir(tmp_path):
    files = {
        "h-6_20260601.csv": SANTEI_ROWS,
        "h-8_20260601.csv": NENREI_ROWS,
        "h-9_20260601.csv": [
            heisantei_row("302000110", "歯科疾患管理料", "302000710", "歯科特定疾患療養管理料"),
        ],
        "h-10_20260601.csv": JITSUNISSU_ROWS,
    }
    d = tmp_path / "tables"
    d.mkdir()
    for name, rows in files.items():
        (d / name).write_bytes(("\r\n".join(rows) + "\r\n").encode("cp932"))
    return d


class TestChecker:
    def make_uke(self, ss_lines, birth="3601015", actual_days=2):
        lines = [
            "IR,1,13,3,1234567,,テスト歯科医院,50604,03-1234-5678,",
            f"RE,1,3112,50604,山田　太郎,1,{birth},,,5060401,,,,,,K001",
            f"HO,06132013,はーと,1234567,{actual_days},580",
            "HS,5060401,1,,0000999,,う蝕症第２度",
            *ss_lines,
            "GO,1,580,99",
        ]
        return parse_bytes(build_uke(lines))

    def check(self, uke, tables_dir):
        from new_dental_ai.uke import CheckTables, check_uke

        return check_uke(uke, CheckTables.load_dir(tables_dir))

    def test_age_limit_adult_with_infant_addition(self, tables_dir):
        # 昭和60年生まれ（成人）に乳幼児加算 → NG
        uke = self.make_uke([ss_record("12", "1", "301000370", 319, 1, {2: 1})])
        findings = self.check(uke, tables_dir)
        assert len(findings) == 1
        f = findings[0]
        assert (f.severity, f.rule) == ("NG", "年齢制限")
        assert "乳幼児加算（初診）" in f.message and "38歳" in f.message

    def test_age_limit_child_ok(self, tables_dir):
        # 令和元年5月1日生まれ（4歳）なら指摘なし
        uke = self.make_uke(
            [ss_record("12", "1", "301000370", 319, 1, {2: 1})], birth="5010501"
        )
        assert self.check(uke, tables_dir) == []

    def test_count_limit(self, tables_dir):
        # 初診料 月2回: 上限1回・特例条件あり → 要確認
        uke = self.make_uke([ss_record("11", "1", "301000110", 261, 2, {2: 1, 16: 1})])
        findings = self.check(uke, tables_dir)
        assert [(f.severity, f.rule) for f in findings] == [("要確認", "算定回数限度")]
        assert "月2回" in findings[0].message

    def test_count_limit_ng_and_day_relation(self, tables_dir):
        # 歯科疾患管理料 月2回（上限1回・特例なし）→ NG、実日数1日超え → 要確認
        uke = self.make_uke(
            [ss_record("13", "1", "302000110", 100, 2, {2: 1, 16: 1})], actual_days=1
        )
        findings = self.check(uke, tables_dir)
        assert ("NG", "算定回数限度") in [(f.severity, f.rule) for f in findings]
        assert ("要確認", "実日数") in [(f.severity, f.rule) for f in findings]

    def test_exclusion(self, tables_dir):
        # 歯科疾患管理料と歯科特定疾患療養管理料の併算定 → 要確認（1件のみ報告）
        uke = self.make_uke([
            ss_record("13", "1", "302000110", 100, 1, {2: 1}),
            ss_record("13", "1", "302000710", 170, 1, {2: 1}),
        ])
        findings = [f for f in self.check(uke, tables_dir) if f.rule == "併算定背反"]
        assert len(findings) == 1
        assert "歯科特定疾患療養管理料" in findings[0].message

    def test_missing_disease(self, tables_dir):
        # 傷病名（HSレコード）のないレセプト → NG
        lines = [
            "IR,1,13,3,1234567,,テスト歯科医院,50604,03-1234-5678,",
            "RE,1,3112,50604,山田　太郎,1,3601015,,,5060401,,,,,,K001",
            "HO,06132013,はーと,1234567,1,261",
            ss_record("11", "1", "301000110", 261, 1, {2: 1}),
            "GO,1,261,99",
        ]
        findings = self.check(parse_bytes(build_uke(lines)), tables_dir)
        assert ("NG", "傷病名") in [(f.severity, f.rule) for f in findings]

    def test_demo_generator(self, tables_dir):
        # デモ生成器: 正規のUKEとして読め、混入したミスが検出される
        from new_dental_ai.uke.demo import generate

        uke = parse_bytes(generate(seed=1))
        assert uke.validate() == []
        assert generate(seed=1) == generate(seed=1)
        rules = {f.rule for f in self.check(uke, tables_dir)}
        assert {"年齢制限", "算定回数限度", "併算定背反", "実日数", "傷病名"} <= rules
        # ミスなし生成では指摘ゼロ（点検テーブル対象の指摘がない）
        clean = parse_bytes(generate(seed=1, with_errors=False))
        assert clean.validate() == []
        assert self.check(clean, tables_dir) == []

    def test_cli_check(self, tmp_path, capsys, tables_dir):
        from new_dental_ai.uke.__main__ import main

        path = tmp_path / "RECEIPTC.UKE"
        path.write_bytes(build_uke(SAMPLE_LINES))
        code = main(["--check", str(tables_dir), str(path)])
        out = capsys.readouterr().out
        assert "点検結果" in out and "年齢制限" in out
        assert code == 1  # NG（成人への乳幼児加算）を含む


class TestCli:
    def test_summary(self, tmp_path, capsys):
        from new_dental_ai.uke.__main__ import main

        path = tmp_path / "RECEIPTC.UKE"
        path.write_bytes(build_uke(SAMPLE_LINES))
        assert main([str(path)]) == 0
        out = capsys.readouterr().out
        assert "テスト歯科医院" in out
        assert "山田　太郎" in out

    def test_details_with_master(self, tmp_path, capsys, master_csv):
        from new_dental_ai.uke.__main__ import main

        path = tmp_path / "RECEIPTC.UKE"
        path.write_bytes(build_uke(SAMPLE_LINES))
        assert main(["--details", "--master", str(master_csv), str(path)]) == 0
        out = capsys.readouterr().out
        assert "歯科初診料" in out  # 301000110 が名称解決される

    def test_json(self, tmp_path, capsys):
        import json

        from new_dental_ai.uke.__main__ import main

        path = tmp_path / "RECEIPTC.UKE"
        path.write_bytes(build_uke(SAMPLE_LINES))
        assert main(["--json", str(path)]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["レセプト件数"] == 2
