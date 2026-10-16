#!/usr/bin/env python3
"""
Внедрение багов в синтетические карточки.

Читает чистые карточки из synthetic-data/cards/ и создаёт
версии с багами в synthetic-data/injected-bugs/.

Распределение багов (по process.md):
- Зона 1 (Реквизиты):        3 карточки
- Зона 2 (Сумма):            4 карточки
- Зона 3 (Период):           3 карточки
- Зона 4 (Приложения):       5 карточек
- Зона 5 (Подсудность):      4 карточки
- Зона 6 (Исковая давность): 3 карточки
- Зона 7 (ПДн третьих лиц):  3 карточки
- Комбинированные (2–3 бага): 10 карточек
- Чистые (без багов):        15 карточек
Итого: 50 карточек, 35 с багами, 15 чистых.

Использование:
    python3 scripts/inject_bugs.py
    python3 scripts/inject_bugs.py --seed 42
"""

import argparse
import copy
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, List


# ---------------------------------------------------------------- #
# Баги                                                              #
# ---------------------------------------------------------------- #

def bug_zone_1_wrong_inn(card: dict, rng: random.Random) -> dict:
    """Зона 1: неверный ИНН ответчика (битая контрольная сумма)."""
    card = copy.deepcopy(card)
    inn = card["respondent"]["inn"]
    # Меняем последнюю цифру → контрольная сумма ломается
    new_last = (int(inn[-1]) + 1) % 10
    card["respondent"]["inn"] = inn[:-1] + str(new_last)
    card["_injected_bug"] = "zone_1_wrong_inn"
    return card


def bug_zone_1_missing_ogrn(card: dict, rng: random.Random) -> dict:
    """Зона 1: отсутствует ОГРН кредитора."""
    card = copy.deepcopy(card)
    card["creditor"].pop("ogrn", None)
    card["_injected_bug"] = "zone_1_missing_ogrn"
    return card


def bug_zone_1_wrong_address(card: dict, rng: random.Random) -> dict:
    """Зона 1: адрес в документе не совпадает с карточкой."""
    card = copy.deepcopy(card)
    card["document"]["document_requisites"] = {
        "respondent": {
            "address": "г. Москва, ул. Тверская, д. 1, кв. 1",
        }
    }
    card["_injected_bug"] = "zone_1_wrong_address"
    return card


def bug_zone_2_overstated_amount(card: dict, rng: random.Random) -> dict:
    """Зона 2: сумма в документе завышена на 15%."""
    card = copy.deepcopy(card)
    # Расчётная сумма — из карточки (principal + interest + penalty).
    # Для бага — ставим заведомо завышенную (например, × 1.15).
    principal = card["contract"]["amount"]
    # Сумма "как будто" начислено без потолка
    inflated = round(principal * 1.15, 2)
    card["document"]["claim_amount"] = inflated
    card["_injected_bug"] = "zone_2_overstated_amount"
    return card


def bug_zone_2_rate_exceeded(card: dict, rng: random.Random) -> dict:
    """Зона 2: ставка выше 0.8% в день (нарушение 353-ФЗ)."""
    card = copy.deepcopy(card)
    card["contract"]["rate"] = 1.2  # 1.2% в день > 0.8%
    card["_injected_bug"] = "zone_2_rate_exceeded"
    return card


def bug_zone_3_period_gap(card: dict, rng: random.Random) -> dict:
    """Зона 3: пропуск в периоде (переход через месяц)."""
    card = copy.deepcopy(card)
    period_end = date.fromisoformat(card["period_end"])
    # Сдвигаем конец периода вперёд с пропуском
    new_end = period_end + timedelta(days=30)
    card["period_end"] = new_end.isoformat()
    card["_injected_bug"] = "zone_3_period_gap"
    return card


def bug_zone_3_period_future(card: dict, rng: random.Random) -> dict:
    """Зона 3: конец периода в будущем (позже даты подачи)."""
    card = copy.deepcopy(card)
    filing = date.fromisoformat(card["filing_date"])
    card["period_end"] = (filing + timedelta(days=60)).isoformat()
    card["_injected_bug"] = "zone_3_period_future"
    return card


def bug_zone_4_missing_appendix(card: dict, rng: random.Random) -> dict:
    """Зона 4: отсутствует расчёт задолженности."""
    card = copy.deepcopy(card)
    appendices = card["document"].get("appendices", [])
    card["document"]["appendices"] = [
        a for a in appendices if "расчёт" not in a.lower()
    ]
    card["_injected_bug"] = "zone_4_missing_appendix"
    return card


def bug_zone_4_no_payment_order(card: dict, rng: random.Random) -> dict:
    """Зона 4: отсутствует документ об уплате госпошлины."""
    card = copy.deepcopy(card)
    appendices = card["document"].get("appendices", [])
    card["document"]["appendices"] = [
        a for a in appendices if "пошлин" not in a.lower()
    ]
    card["_injected_bug"] = "zone_4_no_payment_order"
    return card


def bug_zone_5_wrong_jurisdiction(card: dict, rng: random.Random) -> dict:
    """Зона 5: суд не соответствует месту жительства должника."""
    card = copy.deepcopy(card)
    # Ставим суд из другого региона (Москва)
    card["document"]["court"] = "Судебный участок № 100 Центрального района г. Москвы"
    card["_injected_bug"] = "zone_5_wrong_jurisdiction"
    return card


def bug_zone_6_expired_limitation(card: dict, rng: random.Random) -> dict:
    """Зона 6: срок исковой давности пропущен (сдвигаем договор на 4 года назад)."""
    card = copy.deepcopy(card)
    contract_end = date.fromisoformat(card["contract"]["end_date"])
    old_end = contract_end - timedelta(days=4 * 365)
    card["contract"]["end_date"] = old_end.isoformat()
    card["period_start"] = (old_end + timedelta(days=1)).isoformat()
    card["_injected_bug"] = "zone_6_expired_limitation"
    return card


def bug_zone_7_relative_no_consent(card: dict, rng: random.Random) -> dict:
    """Зона 7: упомянут родственник без связи со спором."""
    card = copy.deepcopy(card)
    card["third_parties"] = [
        {
            "name": "Сидоров Пётр Иванович",
            "role": "родственник",
            "disclosed_fields": ["fio"],
            "is_party": False,
        }
    ]
    card["_injected_bug"] = "zone_7_relative_no_consent"
    return card


def bug_zone_7_excessive_fields(card: dict, rng: random.Random) -> dict:
    """Зона 7: поручитель, но избыточно раскрыты ПДн (адрес, телефон)."""
    card = copy.deepcopy(card)
    card["third_parties"] = [
        {
            "name": "Иванова Мария Петровна",
            "role": "поручитель",
            "disclosed_fields": ["fio", "address", "phone", "workplace"],
            "is_party": True,
        }
    ]
    card["_injected_bug"] = "zone_7_excessive_fields"
    return card


# ---------------------------------------------------------------- #
# Реестр багов                                                      #
# ---------------------------------------------------------------- #

ZONE_BUGS = {
    1: [
        ("wrong_inn", bug_zone_1_wrong_inn),
        ("missing_ogrn", bug_zone_1_missing_ogrn),
        ("wrong_address", bug_zone_1_wrong_address),
    ],
    2: [
        ("overstated_amount", bug_zone_2_overstated_amount),
        ("rate_exceeded", bug_zone_2_rate_exceeded),
    ],
    3: [
        ("period_gap", bug_zone_3_period_gap),
        ("period_future", bug_zone_3_period_future),
    ],
    4: [
        ("missing_appendix", bug_zone_4_missing_appendix),
        ("no_payment_order", bug_zone_4_no_payment_order),
    ],
    5: [
        ("wrong_jurisdiction", bug_zone_5_wrong_jurisdiction),
    ],
    6: [
        ("expired_limitation", bug_zone_6_expired_limitation),
    ],
    7: [
        ("relative_no_consent", bug_zone_7_relative_no_consent),
        ("excessive_fields", bug_zone_7_excessive_fields),
    ],
}


# ---------------------------------------------------------------- #
# Внедрение багов по карточкам                                      #
# ---------------------------------------------------------------- #

def apply_single_bug(card: dict, zone: int, rng: random.Random) -> dict:
    """Применить один баг указанной зоны к карточке."""
    bugs = ZONE_BUGS[zone]
    _, func = rng.choice(bugs)
    return func(card, rng)


def apply_combined_bug(card: dict, zones: List[int], rng: random.Random) -> dict:
    """Применить несколько багов из разных зон."""
    result = copy.deepcopy(card)
    for zone in zones:
        result = apply_single_bug(result, zone, rng)
    # Перезаписываем метку — комбинированный баг
    result["_injected_bug"] = f"combined_{'_'.join(str(z) for z in zones)}"
    return result


def main():
    parser = argparse.ArgumentParser(description="Внедрение багов в карточки")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--input", type=str, default="synthetic-data/cards")
    parser.add_argument("--output", type=str, default="synthetic-data/injected-bugs")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    cards = sorted(input_dir.glob("*.json"))
    if len(cards) < 50:
        print(f"⚠ Найдено {len(cards)} карточек. Ожидалось 50.")
        print(f"  Сначала запустите: python3 scripts/generate_synthetic.py")
        return

    # Первые 15 — чистые (копируем как есть)
    clean_cards = cards[:15]
    for card_path in clean_cards:
        with card_path.open("r", encoding="utf-8") as f:
            card = json.load(f)
        card["_injected_bug"] = None
        output_file = output_dir / card_path.name
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)

    print(f"✓ 15 чистых карточек → {output_dir}/")

    # Баги: зоны 1–7
    single_bug_distribution = [
        (1, 3),  # Зона 1 — 3 карточки
        (2, 4),  # Зона 2 — 4 карточки
        (3, 3),  # Зона 3 — 3 карточки
        (4, 5),  # Зона 4 — 5 карточек
        (5, 4),  # Зона 5 — 4 карточки
        (6, 3),  # Зона 6 — 3 карточки
        (7, 3),  # Зона 7 — 3 карточки
    ]

    buggy_cards = cards[15:15 + 25]  # 25 карточек под одиночные баги
    cursor = 0

    for zone, count in single_bug_distribution:
        for _ in range(count):
            if cursor >= len(buggy_cards):
                break
            with buggy_cards[cursor].open("r", encoding="utf-8") as f:
                card = json.load(f)
            bugged = apply_single_bug(card, zone, rng)
            output_file = output_dir / buggy_cards[cursor].name
            with output_file.open("w", encoding="utf-8") as f:
                json.dump(bugged, f, ensure_ascii=False, indent=2)
            cursor += 1

    print(f"✓ 25 карточек с одиночными багами → {output_dir}/")

    # Комбинированные баги: 10 карточек
    combined_cards = cards[40:50]
    combined_patterns = [
        [2, 4, 5],  # тройной — для демо
        [1, 4],
        [3, 6],
        [2, 5],
        [4, 7],
        [1, 5],
        [2, 3],
        [6, 7],
        [1, 2, 6],
        [3, 4, 5],
    ]

    for card_path, zones in zip(combined_cards, combined_patterns):
        with card_path.open("r", encoding="utf-8") as f:
            card = json.load(f)
        bugged = apply_combined_bug(card, zones, rng)
        output_file = output_dir / card_path.name
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(bugged, f, ensure_ascii=False, indent=2)

    print(f"✓ 10 карточек с комбинированными багами → {output_dir}/")
    print(f"\nИтого: 50 карточек (15 чистых, 25 с одиночными, 10 с комбинированными)")
    print(f"Демо-карточка с тройным багом: case-00041.json (зоны 2, 4, 5)")


if __name__ == "__main__":
    main()
