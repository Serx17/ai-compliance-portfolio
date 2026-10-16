#!/usr/bin/env python3
"""
Генератор синтетических карточек должников.

Создаёт 50 карточек с реалистичными данными:
- ФИО, дата рождения, адрес
- ИНН/ОГРН (с корректными контрольными суммами)
- Договор займа (номер, дата, сумма, ставка, срок)
- Период задолженности
- Реквизиты кредитора

Все данные — СИНТЕТИЧЕСКИЕ. Никаких реальных ПДн.

Использование:
    python3 scripts/generate_synthetic.py
    python3 scripts/generate_synthetic.py --count 50 --seed 42
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import List


# ---------------------------------------------------------------- #
# Генераторы реквизитов с корректными контрольными суммами         #
# ---------------------------------------------------------------- #

def generate_inn_legal(seed_random: random.Random) -> str:
    """
    Генерация ИНН юрлица (10 цифр) с корректной контрольной суммой.

    Алгоритм ФНС: коэффициенты [2,4,10,3,5,9,4,6,8].
    """
    base = [seed_random.randint(0, 9) for _ in range(9)]
    coefficients = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    checksum = sum(base[i] * coefficients[i] for i in range(9))
    control = (checksum % 11) % 10
    return "".join(str(d) for d in base) + str(control)


def generate_inn_person(seed_random: random.Random) -> str:
    """
    Генерация ИНН физлица (12 цифр) с корректными контрольными суммами.
    """
    base = [seed_random.randint(0, 9) for _ in range(10)]

    coef_1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    checksum_1 = sum(base[i] * coef_1[i] for i in range(10))
    control_1 = (checksum_1 % 11) % 10

    base_11 = base + [control_1]
    coef_2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    checksum_2 = sum(base_11[i] * coef_2[i] for i in range(11))
    control_2 = (checksum_2 % 11) % 10

    return "".join(str(d) for d in base) + str(control_1) + str(control_2)


def generate_ogrn(seed_random: random.Random) -> str:
    """
    Генерация ОГРН юрлица (13 цифр) с корректной контрольной суммой.
    """
    base = [seed_random.randint(0, 9) for _ in range(12)]
    first_12 = int("".join(str(d) for d in base))
    control = (first_12 % 11) % 10
    return "".join(str(d) for d in base) + str(control)


# ---------------------------------------------------------------- #
# Справочники                                                       #
# ---------------------------------------------------------------- #

LAST_NAMES_M = ["Иванов", "Петров", "Сидоров", "Кузнецов", "Смирнов",
                "Волков", "Морозов", "Новиков", "Фёдоров", "Егоров"]
LAST_NAMES_F = ["Иванова", "Петрова", "Сидорова", "Кузнецова", "Смирнова",
                "Волкова", "Морозова", "Новикова", "Фёдорова", "Егорова"]
FIRST_NAMES_M = ["Иван", "Пётр", "Сергей", "Алексей", "Дмитрий",
                 "Андрей", "Николай", "Михаил", "Владимир", "Олег"]
FIRST_NAMES_F = ["Мария", "Анна", "Елена", "Ольга", "Татьяна",
                 "Наталья", "Ирина", "Светлана", "Екатерина", "Юлия"]
PATRONYMICS_M = ["Иванович", "Петрович", "Сергеевич", "Алексеевич", "Дмитриевич",
                 "Андреевич", "Николаевич", "Михайлович", "Владимирович", "Олегович"]
PATRONYMICS_F = ["Ивановна", "Петровна", "Сергеевна", "Алексеевна", "Дмитриевна",
                 "Андреевна", "Николаевна", "Михайловна", "Владимировна", "Олеговна"]

REGIONS = [
    ("г. Самара", "Кировский район", "63"),
    ("г. Москва", "Центральный район", "77"),
    ("г. Санкт-Петербург", "Невский район", "78"),
    ("г. Казань", "Вахитовский район", "16"),
    ("г. Новосибирск", "Ленинский район", "54"),
    ("г. Екатеринбург", "Верх-Исетский район", "66"),
]

STREETS = ["ул. Ленина", "ул. Мира", "ул. Советская", "ул. Победы",
           "пр. Кирова", "ул. Гагарина", "ул. Пушкина"]

CREDITORS = [
    "ООО МФО «Быстрые деньги»",
    "ООО МКК «Финанс-Групп»",
    "ООО МФО «Кредит-Экспресс»",
    "ООО МКК «Национальный займ»",
]

COURT_TEMPLATES = {
    "63": "Судебный участок № {n} Кировского района г. Самары",
    "77": "Судебный участок № {n} Центрального района г. Москвы",
    "78": "Судебный участок № {n} Невского района г. Санкт-Петербурга",
    "16": "Судебный участок № {n} Вахитовского района г. Казани",
    "54": "Судебный участок № {n} Ленинского района г. Новосибирска",
    "66": "Судебный участок № {n} Верх-Исетского района г. Екатеринбурга",
}


# ---------------------------------------------------------------- #
# Генератор одной карточки                                          #
# ---------------------------------------------------------------- #

def generate_card(case_idx: int, seed_random: random.Random) -> dict:
    """Генерация одной карточки должника."""

    # Пол
    gender = seed_random.choice(["M", "F"])

    if gender == "M":
        fio = f"{seed_random.choice(LAST_NAMES_M)} {seed_random.choice(FIRST_NAMES_M)} {seed_random.choice(PATRONYMICS_M)}"
        inn = generate_inn_person(seed_random)
    else:
        fio = f"{seed_random.choice(LAST_NAMES_F)} {seed_random.choice(FIRST_NAMES_F)} {seed_random.choice(PATRONYMICS_F)}"
        inn = generate_inn_person(seed_random)

    # Дата рождения (25–55 лет)
    birth_year = 1970 + seed_random.randint(0, 30)
    birth_date = date(birth_year, seed_random.randint(1, 12), seed_random.randint(1, 28))

    # Адрес
    region_city, region_district, region_code = seed_random.choice(REGIONS)
    address = (
        f"{region_city}, {region_district}, "
        f"{seed_random.choice(STREETS)}, "
        f"д. {seed_random.randint(1, 100)}, "
        f"кв. {seed_random.randint(1, 200)}"
    )

    # Кредитор
    creditor_name = seed_random.choice(CREDITORS)
    creditor_inn = generate_inn_legal(seed_random)
    creditor_ogrn = generate_ogrn(seed_random)

    # Договор
    contract_year = 2023 + seed_random.randint(0, 1)
    contract_month = seed_random.randint(1, 12)
    contract_day = seed_random.randint(1, 28)
    contract_date = date(contract_year, contract_month, contract_day)
    contract_end = contract_date + timedelta(days=seed_random.choice([15, 21, 30, 45]))

    principal = seed_random.choice([10000, 15000, 20000, 30000, 50000, 75000])

    # Период задолженности: с даты окончания + 1 до "сегодня" минус N
    period_start = contract_end + timedelta(days=1)
    period_end = period_start + timedelta(days=seed_random.choice([30, 60, 90, 120, 180]))

    # Дата подачи: через 10–30 дней после конца периода
    filing_date = period_end + timedelta(days=seed_random.randint(10, 30))

    # Суд (совпадает с регионом должника — корректный случай)
    court = COURT_TEMPLATES[region_code].format(n=seed_random.randint(20, 200))

    return {
        "case_id": f"case-{case_idx:05d}",
        "respondent": {
            "fio": fio,
            "birth_date": birth_date.isoformat(),
            "address": address,
            "inn": inn,
        },
        "creditor": {
            "name": creditor_name,
            "inn": creditor_inn,
            "ogrn": creditor_ogrn,
        },
        "contract": {
            "number": f"МФО-{contract_year}-{seed_random.randint(10000, 99999)}",
            "date": contract_date.isoformat(),
            "amount": float(principal),
            "rate": 0.8,
            "end_date": contract_end.isoformat(),
        },
        "payments": [],
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "filing_date": filing_date.isoformat(),
        "document": {
            "court": court,
            "claim_amount": None,  # заполнится в inject_bugs
            "appendices": [
                "договор займа",
                "расчёт задолженности",
                "документ об уплате государственной пошлины",
            ],
            "text": "",
        },
        "third_parties": [],
        "region_code": region_code,
    }


# ---------------------------------------------------------------- #
# Main                                                              #
# ---------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Генератор синтетических карточек")
    parser.add_argument("--count", type=int, default=50, help="Количество карточек")
    parser.add_argument("--seed", type=int, default=42, help="Seed для воспроизводимости")
    parser.add_argument(
        "--output",
        type=str,
        default="synthetic-data/cards",
        help="Директория для сохранения карточек",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Генерация {args.count} карточек (seed={args.seed})...")

    for idx in range(1, args.count + 1):
        card = generate_card(idx, rng)
        output_file = output_dir / f"{card['case_id']}.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)

    print(f"✓ Сгенерировано {args.count} карточек в {output_dir}/")
    print(f"  Пример: {output_dir}/case-00001.json")


if __name__ == "__main__":
    main()
