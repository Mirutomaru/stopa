"""STOPA CLI — moduly příkazů podle doménových rodin (P1-4 rozklad monolitu cli.py).

Každý modul obsahuje implementace ``cmd_*`` pro svou skupinu subpříkazů;
facade ``stopa.cli`` je re-exportuje a registruje jejich parsery v ``build_parser``.
"""
