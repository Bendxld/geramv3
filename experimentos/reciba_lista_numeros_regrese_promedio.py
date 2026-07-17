#!/usr/bin/env python3
"""
Script para calcular el promedio de una lista de números.

Los números se deben pasar como argumentos de línea de comandos.
Ejemplo: python3 promedio.py 10 20 30 40 50
"""

import sys


def calculate_average(numbers_list: list[float]) -> float:
    """
    Calcula el promedio de una lista de números flotantes.

    Args:
        numbers_list: Una lista de números (flotantes o enteros).

    Returns:
        El promedio de los números en la lista.

    Raises:
        ValueError: Si la lista de entrada está vacía.
    """
    if not numbers_list:
        raise ValueError("La lista de números no puede estar vacía para calcular el promedio.")
    return sum(numbers_list) / len(numbers_list)


def main():
    """
    Función principal del script.
    Procesa los argumentos de línea de comandos, calcula el promedio y lo imprime.
    """
    if len(sys.argv) < 2:
        print("Uso: python3 promedio.py <numero1> <numero2> ...")
        print("Ejemplo: python3 promedio.py 10 20 30 40 50")
        sys.exit(1)

    input_numbers = []
    for arg in sys.argv[1:]:
        try:
            num = float(arg)
            input_numbers.append(num)
        except ValueError:
            print(f"Advertencia: '{arg}' no es un número válido y será ignorado.", file=sys.stderr)

    if not input_numbers:
        print("Error: No se proporcionaron números válidos para calcular el promedio.", file=sys.stderr)
        sys.exit(1)

    try:
        average = calculate_average(input_numbers)
        print(f"La lista de números procesada es: {input_numbers}")
        print(f"El promedio es: {average}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Permite salir limpiamente con Ctrl+C
        sys.exit(0)