"""
Формирование и валидация реквизитов.

Ключевое: валидация ИНН и ОГРН по контрольной сумме (алгоритм ФНС).
Это не regex — это настоящая проверка, которую использует налоговая.

ИНН: 10 цифр (юрлицо) или 12 цифр (физлицо/ИП).
ОГРН: 13 цифр (юрлицо), ОГРНИП: 15 цифр (ИП).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationResult:
    """Результат валидации реквизита."""
    is_valid: bool
    reason: Optional[str] = None


def validate_inn(inn: str) -> ValidationResult:
    """
    Валидация ИНН по контрольной сумме (алгоритм ФНС).

    ИНН юрлица: 10 цифр.
    ИНН физлица/ИП: 12 цифр.

    Returns:
        ValidationResult(is_valid=True) если ИНН корректен.
        ValidationResult(is_valid=False, reason=...) если нет.
    """
    if not inn:
        return ValidationResult(False, "ИНН пустой")

    if not inn.isdigit():
        return ValidationResult(False, "ИНН содержит нецифровые символы")

    if len(inn) == 10:
        return _validate_inn_10(inn)
    elif len(inn) == 12:
        return _validate_inn_12(inn)
    else:
        return ValidationResult(
            False,
            f"ИНН должен содержать 10 или 12 цифр, получено {len(inn)}"
        )


def _validate_inn_10(inn: str) -> ValidationResult:
    """Валидация 10-значного ИНН (юрлицо)."""
    coefficients = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    checksum = sum(int(inn[i]) * coefficients[i] for i in range(9))
    control = (checksum % 11) % 10

    if control != int(inn[9]):
        return ValidationResult(
            False,
            f"Неверная контрольная сумма: ожидалось {control}, получено {inn[9]}"
        )
    return ValidationResult(True)


def _validate_inn_12(inn: str) -> ValidationResult:
    """Валидация 12-значного ИНН (физлицо/ИП)."""
    # Первая контрольная цифра (11-я)
    coefficients_1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    checksum_1 = sum(int(inn[i]) * coefficients_1[i] for i in range(10))
    control_1 = (checksum_1 % 11) % 10

    if control_1 != int(inn[10]):
        return ValidationResult(
            False,
            f"Неверная первая контрольная сумма: ожидалось {control_1}, получено {inn[10]}"
        )

    # Вторая контрольная цифра (12-я)
    coefficients_2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    checksum_2 = sum(int(inn[i]) * coefficients_2[i] for i in range(11))
    control_2 = (checksum_2 % 11) % 10

    if control_2 != int(inn[11]):
        return ValidationResult(
            False,
            f"Неверная вторая контрольная сумма: ожидалось {control_2}, получено {inn[11]}"
        )
    return ValidationResult(True)


def validate_ogrn(ogrn: str) -> ValidationResult:
    """
    Валидация ОГРН по контрольной сумме.

    ОГРН юрлица: 13 цифр.
    ОГРНИП: 15 цифр.
    """
    if not ogrn:
        return ValidationResult(False, "ОГРН пустой")

    if not ogrn.isdigit():
        return ValidationResult(False, "ОГРН содержит нецифровые символы")

    if len(ogrn) == 13:
        return _validate_ogrn_13(ogrn)
    elif len(ogrn) == 15:
        return _validate_ogrn_15(ogrn)
    else:
        return ValidationResult(
            False,
            f"ОГРН должен содержать 13 или 15 цифр, получено {len(ogrn)}"
        )


def _validate_ogrn_13(ogrn: str) -> ValidationResult:
    """Валидация 13-значного ОГРН (юрлицо)."""
    # Контрольная цифра: (первые 12 цифр как число) % 11, последняя цифра остатка
    first_12 = int(ogrn[:12])
    control = (first_12 % 11) % 10

    if control != int(ogrn[12]):
        return ValidationResult(
            False,
            f"Неверная контрольная сумма ОГРН: ожидалось {control}, получено {ogrn[12]}"
        )
    return ValidationResult(True)


def _validate_ogrn_15(ogrn: str) -> ValidationResult:
    """Валидация 15-значного ОГРНИП."""
    first_14 = int(ogrn[:14])
    control = (first_14 % 13) % 10

    if control != int(ogrn[14]):
        return ValidationResult(
            False,
            f"Неверная контрольная сумма ОГРНИП: ожидалось {control}, получено {ogrn[14]}"
        )
    return ValidationResult(True)


def format_requisites(card: dict) -> dict:
    """
    Формирование реквизитов из карточки должника.

    Args:
        card: карточка должника (dict).

    Returns:
        dict с ключами:
        - respondent: реквизиты ответчика
        - creditor: реквизиты истца
        - validation: результаты валидации (list[dict])
    """
    validation_issues = []

    respondent = card.get("respondent", {})
    creditor = card.get("creditor", {})

    # Валидация ИНН ответчика
    if "inn" in respondent:
        result = validate_inn(respondent["inn"])
        if not result.is_valid:
            validation_issues.append({
                "party": "respondent",
                "field": "inn",
                "value": respondent["inn"],
                "reason": result.reason,
            })

    # Валидация ИНН истца
    if "inn" in creditor:
        result = validate_inn(creditor["inn"])
        if not result.is_valid:
            validation_issues.append({
                "party": "creditor",
                "field": "inn",
                "value": creditor["inn"],
                "reason": result.reason,
            })

    # Валидация ОГРН истца
    if "ogrn" in creditor:
        result = validate_ogrn(creditor["ogrn"])
        if not result.is_valid:
            validation_issues.append({
                "party": "creditor",
                "field": "ogrn",
                "value": creditor["ogrn"],
                "reason": result.reason,
            })

    return {
        "respondent": {
            "fio": respondent.get("fio"),
            "birth_date": respondent.get("birth_date"),
            "address": respondent.get("address"),
            "inn": respondent.get("inn"),
        },
        "creditor": {
            "name": creditor.get("name"),
            "inn": creditor.get("inn"),
            "ogrn": creditor.get("ogrn"),
        },
        "validation": validation_issues,
    }
