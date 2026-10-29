"""STOPA artifact extraktoři — AXIOM-style extrakce z datových souborů.

První vlna: SQLite databáze (browser history, chaty…). Každý extraktor je
oddělený modul se schema matchery; IO jen v `extract_sqlite_artifacts`.
"""
