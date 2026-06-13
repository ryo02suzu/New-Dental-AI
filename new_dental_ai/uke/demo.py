"""デモ・テスト用の合成 UKE ファイル生成器。

実在の診療行為コード・点数（令和8年度 歯科診療行為マスター）を使って、
本物に近い歯科レセプト UKE ファイルを生成する。個人情報は一切含まず、
患者名・生年月日はすべて架空の値。

既定では「新規開業医院でよくあるミス」を意図的に混入する:

- 成人への乳幼児加算（年齢制限違反）
- 同月内の初診料 2 回（算定回数限度超過）
- 歯科疾患管理料と歯科特定疾患療養管理料の併算定（併算定背反）
- 算定回数が診療実日数を超える記録（実日数関連）
- 傷病名の記録漏れ

使い方:
    python -m new_dental_ai.uke.demo -o RECEIPTC.UKE
    python -m new_dental_ai.uke.demo -o RECEIPTC.UKE --clean  # ミスなし
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

ENCODING = "cp932"

# 診療行為（コード, 診療識別, 名称, 点数）: 令和8年度 歯科診療行為マスターより
SHOSHIN = ("301000110", "11", "歯科初診料", 272)
NYUYOJI_KASAN_SHOSHIN = ("301000370", "11", "乳幼児加算（初診）", 40)
SAISHIN = ("301001610", "12", "歯科再診料", 59)
SHIKKAN_KANRI = ("302000110", "13", "歯科疾患管理料", 90)
BUNSHO_KASAN = ("302008470", "13", "文書提供加算（歯科疾患管理料）", 10)
JITCHI_SHIDO = ("302000610", "13", "歯科衛生実地指導料１", 80)
TOKUSHIKKAN_KANRI = ("302000710", "13", "歯科特定疾患療養管理料", 170)
SHISHU_KENSA = ("304000510", "31", "歯周基本検査（１０歯以上２０歯未満）", 110)
SHASHIN_SHINDAN = ("305000110", "31", "写真診断（全顎撮影）", 160)
SCALING = ("309004810", "41", "歯周基本治療（スケーリング（３分の１顎につき））", 72)
SHIMEN_SEISO = ("309011410", "41", "機械的歯面清掃処置（１口腔につき）", 72)

# 架空の氏名（姓, 姓カナ, 名候補は性別ごと）
_SURNAMES = [
    ("青木", "アオキ"), ("石田", "イシダ"), ("上野", "ウエノ"), ("遠藤", "エンドウ"),
    ("岡本", "オカモト"), ("加藤", "カトウ"), ("木村", "キムラ"), ("黒田", "クロダ"),
    ("小林", "コバヤシ"), ("斎藤", "サイトウ"), ("島田", "シマダ"), ("杉本", "スギモト"),
]
_GIVEN_M = [("健太", "ケンタ"), ("大輔", "ダイスケ"), ("翔", "ショウ"), ("悠真", "ユウマ")]
_GIVEN_F = [("美咲", "ミサキ"), ("陽菜", "ヒナ"), ("彩花", "アヤカ"), ("由美", "ユミ")]

# 架空の傷病名（未コード化傷病名コード 0000999 + 名称で記録する）
_DISEASES = ["う蝕症第２度", "う蝕症第３度", "歯肉炎", "慢性歯周炎", "象牙質知覚過敏症"]
_UNCODED = "0000999"


def _ss_line(code: str, tensu: int, days: dict[int, int], futan: str = "1",
             shikibetsu: str = "") -> str:
    fields = ["SS", shikibetsu, futan, code, "", ""]
    fields += [""] * 70  # 加算コード／加算数量データ 1〜35
    kaisu = sum(days.values())
    fields += [str(tensu), str(kaisu)]
    santeibi = [""] * 31
    for day, count in days.items():
        santeibi[day - 1] = str(count)
    fields += santeibi
    return ",".join(fields).rstrip(",")


@dataclass
class _ReceiptBuilder:
    number: int
    name: str
    kana: str
    sex: str  # "1"=男, "2"=女
    birth: str  # GYYMMDD
    month: str  # GYYMM
    karte: str
    insurer: str
    details: list[tuple[tuple[str, str, str, int], dict[int, int]]] = field(default_factory=list)
    diseases: list[tuple[str, int]] = field(default_factory=list)  # (傷病名, 開始日)
    actual_days_override: int | None = None

    def add(self, procedure: tuple[str, str, str, int], days: dict[int, int]) -> None:
        self.details.append((procedure, days))

    def add_disease(self, name: str, start_day: int) -> None:
        self.diseases.append((name, start_day))

    @property
    def total_points(self) -> int:
        return sum(p[3] * sum(days.values()) for p, days in self.details)

    @property
    def actual_days(self) -> int:
        if self.actual_days_override is not None:
            return self.actual_days_override
        return len({day for _, days in self.details for day in days})

    def lines(self) -> list[str]:
        first_day = min((d for _, days in self.details for d in days), default=1)
        start = f"{self.month}{first_day:02d}"
        lines = [
            f"RE,{self.number},3112,{self.month},{self.name},{self.sex},{self.birth},"
            f",,{start},,,,,,{self.karte},,,,,,,,,,{self.kana},",
            f"HO,{self.insurer},記号{self.number},{1000 + self.number},"
            f"{self.actual_days},{self.total_points}",
        ]
        for disease, day in self.diseases:
            lines.append(f"HS,{self.month}{day:02d},1,,{_UNCODED},,{disease}")
        for procedure, days in self.details:
            code, shikibetsu, _, tensu = procedure
            lines.append(_ss_line(code, tensu, days, shikibetsu=shikibetsu))
        return lines


def _make_patient(rng: random.Random, number: int, month: str, *,
                  child: bool = False) -> _ReceiptBuilder:
    surname, surname_kana = rng.choice(_SURNAMES)
    sex = rng.choice(["1", "2"])
    given, given_kana = rng.choice(_GIVEN_M if sex == "1" else _GIVEN_F)
    if child:
        # 令和2〜4年生まれ（3〜5歳程度）
        birth = f"5{rng.randint(2, 4):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
    else:
        # 昭和40年〜平成10年生まれの成人
        era, year = rng.choice([("3", rng.randint(40, 63)), ("4", rng.randint(1, 10))])
        birth = f"{era}{year:02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
    return _ReceiptBuilder(
        number=number,
        name=f"{surname}　{given}",
        kana=f"{surname_kana} {given_kana}",
        sex=sex,
        birth=birth,
        month=month,
        karte=f"K{number:04d}",
        insurer=f"0613{rng.randint(1000, 9999):04d}",
    )


def _typical_visit(rng: random.Random, builder: _ReceiptBuilder) -> None:
    """初診→再診の標準的な月をレセプトに記録する。"""
    day1 = rng.randint(1, 10)
    day2 = day1 + rng.randint(5, 14)
    builder.add_disease(rng.choice(_DISEASES), day1)
    builder.add(SHOSHIN, {day1: 1})
    builder.add(SHIKKAN_KANRI, {day1: 1})
    builder.add(BUNSHO_KASAN, {day1: 1})
    builder.add(SHASHIN_SHINDAN, {day1: 1})
    builder.add(SAISHIN, {day2: 1})
    builder.add(SHISHU_KENSA, {day2: 1})
    builder.add(SCALING, {day2: 1})


def generate(seed: int = 0, patients: int = 8, month: str = "50805",
             with_errors: bool = True) -> bytes:
    """合成 UKE ファイルのバイト列（cp932 / CRLF / EOF コード付き）を生成する。"""
    rng = random.Random(seed)
    builders: list[_ReceiptBuilder] = []

    for i in range(1, patients + 1):
        builder = _make_patient(rng, i, month, child=(i % 4 == 0))
        _typical_visit(rng, builder)
        builders.append(builder)

    if with_errors and builders:
        # ミス1: 成人レセプトに乳幼児加算 ＋ 同月2回目の初診料
        target = builders[0]
        first_day = min(d for _, days in target.details for d in days)
        target.add(NYUYOJI_KASAN_SHOSHIN, {first_day: 1})
        target.add(SHOSHIN, {min(first_day + 15, 28): 1})
        if len(builders) > 1:
            # ミス2: 歯科疾患管理料と歯科特定疾患療養管理料の併算定
            builders[1].add(TOKUSHIKKAN_KANRI, {min(
                d for _, days in builders[1].details for d in days): 1})
        if len(builders) > 2:
            # ミス3: 管理料の算定回数が診療実日数を超える（実日数の記録誤り）
            builder = builders[2]
            days = sorted({d for _, ds in builder.details for d in ds})
            builder.details = [
                (p, ds) for p, ds in builder.details if p is not SHIKKAN_KANRI
            ]
            builder.add(SHIKKAN_KANRI, {days[0]: 1, days[-1]: 1})
            builder.actual_days_override = 1
        if len(builders) > 3:
            # ミス4: 傷病名の記録漏れ
            builders[3].diseases.clear()

    lines = [
        "IR,1,13,3,9990001,,デモ歯科クリニック,"
        f"{_next_month(month)},03-0000-0000,",
    ]
    for builder in builders:
        lines.extend(builder.lines())
    total = sum(b.total_points for b in builders)
    lines.append(f"GO,{len(builders)},{total},99")
    return ("\r\n".join(lines) + "\r\n").encode(ENCODING) + b"\x1a"


def _next_month(gyymm: str) -> str:
    """診療年月の翌月（請求年月）を返す。"""
    era, year, month = gyymm[0], int(gyymm[1:3]), int(gyymm[3:5])
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return f"{era}{year:02d}{month:02d}"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m new_dental_ai.uke.demo",
        description="デモ用の合成 UKE ファイルを生成する",
    )
    parser.add_argument("-o", "--out", default="RECEIPTC.UKE", help="出力先（既定: RECEIPTC.UKE）")
    parser.add_argument("--patients", type=int, default=8, help="患者数（既定: 8）")
    parser.add_argument("--seed", type=int, default=0, help="乱数シード")
    parser.add_argument("--month", default="50805", help="診療年月 GYYMM（既定: 50805 = 令和8年5月）")
    parser.add_argument("--clean", action="store_true", help="ミスを混入しない")
    args = parser.parse_args(argv)

    data = generate(
        seed=args.seed, patients=args.patients,
        month=args.month, with_errors=not args.clean,
    )
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"{args.out} を生成しました（患者 {args.patients} 名、ミス混入: {'なし' if args.clean else 'あり'}）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
