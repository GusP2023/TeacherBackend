"""
Configuración de Feriados en Bolivia

Este módulo contiene la lista de feriados nacionales de Bolivia.
Se usa para NO generar clases automáticas en días feriados.

IMPORTANTE: Actualizar esta lista cada año con los feriados correspondientes.

Feriados fijos:
- 1 enero: Año Nuevo
- 22 enero: Estado Plurinacional de Bolivia
- 1 mayo: Día del Trabajo
- 6 agosto: Día de la Independencia
- 2 noviembre: Todos los Santos
- 25 diciembre: Navidad

Feriados variables (dependen del calendario lunar):
- Carnaval (lunes y martes, 47 días antes de Semana Santa)
- Viernes Santo (depende del calendario lunar)
- Corpus Christi (60 días después de Semana Santa)
"""

from datetime import date


# ============================================
# FERIADOS 2025
# ============================================

HOLIDAYS_2025 = [
    # Enero
    date(2025, 1, 1),   # Año Nuevo
    date(2025, 1, 22),  # Estado Plurinacional de Bolivia

    # Febrero - Carnaval (variable)
    date(2025, 2, 24),  # Lunes de Carnaval
    date(2025, 2, 25),  # Martes de Carnaval

    # Abril - Semana Santa (variable)
    date(2025, 4, 18),  # Viernes Santo

    # Mayo
    date(2025, 5, 1),   # Día del Trabajo

    # Junio - Corpus Christi (variable)
    date(2025, 6, 19),  # Corpus Christi
    date(2025, 6, 21),  # Año Nuevo Aymara (21 de junio)

    # Agosto
    date(2025, 8, 6),   # Día de la Independencia de Bolivia

    # Noviembre
    date(2025, 11, 2),  # Día de Todos los Santos

    # Diciembre
    date(2025, 12, 25), # Navidad
]


# ============================================
# FERIADOS 2026 (para continuidad)
# ============================================

HOLIDAYS_2026 = [
    # Enero
    date(2026, 1, 1),   # Año Nuevo
    date(2026, 1, 22),  # Estado Plurinacional de Bolivia

    # Febrero - Carnaval (variable - VERIFICAR FECHAS)
    date(2026, 2, 16),  # Lunes de Carnaval (aproximado)
    date(2026, 2, 17),  # Martes de Carnaval (aproximado)

    # Abril - Semana Santa (variable - VERIFICAR FECHAS)
    date(2026, 4, 3),   # Viernes Santo (aproximado)

    # Mayo
    date(2026, 5, 1),   # Día del Trabajo

    # Junio
    date(2026, 6, 21),  # Año Nuevo Aymara

    # Agosto
    date(2026, 8, 6),   # Día de la Independencia de Bolivia

    # Noviembre
    date(2026, 11, 2),  # Día de Todos los Santos

    # Diciembre
    date(2026, 12, 25), # Navidad
]


# ============================================
# LISTA COMBINADA DE TODOS LOS FERIADOS
# ============================================

ALL_HOLIDAYS = HOLIDAYS_2025 + HOLIDAYS_2026


# ============================================
# FUNCIONES HELPER
# ============================================

def is_holiday(check_date: date) -> bool:
    """
    Verifica si una fecha es feriado en Bolivia

    Args:
        check_date: Fecha a verificar

    Returns:
        True si es feriado, False si no

    Example:
        >>> from datetime import date
        >>> is_holiday(date(2025, 1, 1))
        True
        >>> is_holiday(date(2025, 1, 2))
        False
    """
    return check_date in ALL_HOLIDAYS


def get_holidays_in_range(start_date: date, end_date: date) -> list[date]:
    """
    Obtiene todos los feriados en un rango de fechas

    Args:
        start_date: Fecha de inicio (inclusiva)
        end_date: Fecha de fin (inclusiva)

    Returns:
        Lista de fechas que son feriados en el rango

    Example:
        >>> from datetime import date
        >>> get_holidays_in_range(date(2025, 1, 1), date(2025, 1, 31))
        [date(2025, 1, 1), date(2025, 1, 22)]
    """
    return [
        holiday
        for holiday in ALL_HOLIDAYS
        if start_date <= holiday <= end_date
    ]


def get_holidays_by_year(year: int) -> list[date]:
    """
    Obtiene todos los feriados de un año específico

    Args:
        year: Año a consultar

    Returns:
        Lista de fechas que son feriados en ese año

    Example:
        >>> get_holidays_by_year(2025)
        [date(2025, 1, 1), date(2025, 1, 22), ...]
    """
    return [
        holiday
        for holiday in ALL_HOLIDAYS
        if holiday.year == year
    ]
