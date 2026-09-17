"""RLS cross-tenant isolation — the ADR-005 required-proof suite (Postgres).

Proves isolation two ways: through the API (as the runtime role, GUC set per
request) and directly at the DB (a raw tillflow_pos connection), so the guarantee
holds even if application code forgot to filter. Assertions check *absence* of
rows, never a raised error.
"""

from tests.conftest import new_key, onboard, sale_payload

A = dict(name="A", phone="254700000001", shortcode="111111", att_phone="254711111111")
B = dict(name="B", phone="254700000002", shortcode="222222", att_phone="254722222222")


async def test_migration_enabled_and_forced_rls(admin_conn, _pg):
    rows = await admin_conn.fetch(
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relnamespace='pos'::regnamespace AND relkind='r' "
        "AND relname <> 'alembic_version' ORDER BY relname"  # bookkeeping, not tenant data
    )
    assert rows, "no pos tables found — migration didn't run"
    for r in rows:
        assert r["relrowsecurity"] and r["relforcerowsecurity"], f"{r['relname']} not forced"


async def test_other_tenant_cannot_read_sale_via_api(pg_client):
    a = await onboard(pg_client, **A)
    b = await onboard(pg_client, **B)
    created = await pg_client.post(
        "/sales", headers={**a["headers"], "Idempotency-Key": new_key()}, json=sale_payload(a)
    )
    sale_id = created.json()["id"]

    assert (await pg_client.get(f"/sales/{sale_id}", headers=a["headers"])).status_code == 200
    assert (await pg_client.get(f"/sales/{sale_id}", headers=b["headers"])).status_code == 404


async def test_list_scoped_to_tenant_via_api(pg_client):
    a = await onboard(pg_client, **A)
    b = await onboard(pg_client, **B)
    for _ in range(3):
        await pg_client.post(
            "/sales", headers={**a["headers"], "Idempotency-Key": new_key()}, json=sale_payload(a)
        )
    await pg_client.post(
        "/sales", headers={**b["headers"], "Idempotency-Key": new_key()}, json=sale_payload(b)
    )
    assert len((await pg_client.get("/sales", headers=a["headers"])).json()) == 3
    assert len((await pg_client.get("/sales", headers=b["headers"])).json()) == 1


async def test_rls_enforced_at_db_level(pg_client, runtime_conn):
    """Independent of app code: a raw tillflow_pos connection is filtered by RLS."""
    a = await onboard(pg_client, **A)
    b = await onboard(pg_client, **B)

    # tenant B context cannot see tenant A's tenant row...
    await runtime_conn.execute("SELECT set_config('app.current_tenant_id', $1, false)", b["id"])
    assert await runtime_conn.fetchval(
        "SELECT count(*) FROM pos.tenants WHERE id = $1", a["id"]
    ) == 0
    # ...but can see its own.
    assert await runtime_conn.fetchval(
        "SELECT count(*) FROM pos.tenants WHERE id = $1", b["id"]
    ) == 1


async def test_unset_guc_yields_zero_rows_not_error(pg_client, runtime_conn):
    await onboard(pg_client, **A)
    # Fresh connection, GUC never set -> current_setting(...,true) is NULL -> 0 rows.
    assert await runtime_conn.fetchval("SELECT count(*) FROM pos.tenants") == 0


async def test_with_check_blocks_cross_tenant_insert(pg_client, runtime_conn):
    import asyncpg

    a = await onboard(pg_client, **A)
    b = await onboard(pg_client, **B)
    # In tenant A's context, try to write a row tagged as tenant B -> policy blocks.
    await runtime_conn.execute("SELECT set_config('app.current_tenant_id', $1, false)", a["id"])
    import uuid as _uuid

    try:
        await runtime_conn.execute(
            "INSERT INTO pos.tills (id, tenant_id, name, shortcode) VALUES ($1,$2,'x','999')",
            _uuid.uuid4(), _uuid.UUID(b["id"]),
        )
        raised = False
    except asyncpg.InsufficientPrivilegeError:
        raised = True
    assert raised, "RLS WITH CHECK should have blocked the cross-tenant insert"
