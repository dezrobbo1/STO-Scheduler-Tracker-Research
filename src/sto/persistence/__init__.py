"""PostgreSQL persistence: hand-written SQL over psycopg, no ORM.

Nothing in here is imported by ``sto.core``. The tables are defined by the
migrations under ``infra/migrations``; this package only reads and writes them.
"""
