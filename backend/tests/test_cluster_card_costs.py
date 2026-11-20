import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.clusters import list_clusters
from app.models.cluster import Cluster
from app.models.cluster_cost import ClusterCost


@pytest.mark.asyncio
async def test_card_summaries_are_opt_in_and_scoped_to_listed_ibm_clusters(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'billing.db'}")
    try:
        async with engine.begin() as conn:
            for model in (Cluster, ClusterCost):
                await conn.run_sync(model.__table__.create)
        async with async_sessionmaker(engine)() as db:
            for name, provider in [('a', 'ibm'), ('b', 'ibm'), ('c', 'other'), ('d', 'ibm')]:
                db.add(Cluster(id=name, name=name, kubeconfig_path='test', provider=provider))
            await db.flush()
            for cluster, month, amount, error in [
                ('a', '2026-07', 53, None), ('a', '2026-08', 0, None),
                ('a', '2026-09', 9, 'incomplete'), ('a', '2026-10', None, None),
                ('b', '2026-08', None, None), ('c', '2026-10', 99, None),
                ('d', '2026-10', 23, None),
            ]:
                db.add(ClusterCost(cluster_id=cluster, billing_month=month, total_cost=amount,
                                   currency='EUR', error=error))
            await db.commit()
            assert (await list_clusters(db=db)).latest_costs is None
            page = await list_clusters(db=db, limit=3, include_latest_cost=True)
            assert page.total == 4
            assert list(page.latest_costs) == ['a']
            assert page.latest_costs['a'].model_dump() == {
                'billing_month': '2026-08', 'currency': 'EUR', 'total_cost': 0,
            }
    finally:
        await engine.dispose()
