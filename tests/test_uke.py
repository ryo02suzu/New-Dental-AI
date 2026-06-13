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
