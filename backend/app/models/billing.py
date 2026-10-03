"""Tenant reads and narrow atomic Paddle capabilities; never an owner connection."""

from datetime import datetime

from psycopg.errors import InsufficientPrivilege
from psycopg.types.json import Jsonb

from app.models.database import Database, WorkspaceIdentity, WritePermissionRequiredError


class BillingRepository:
    def __init__(self, database: Database):
        self.database = database

    def create_intent(
        self, identity: WorkspaceIdentity, token_hash: str, price_id: str, ttl_seconds: int,
    ) -> datetime:
        try:
            with self.database.workspace_transaction(identity, write=True) as connection:
                return connection.execute(
                    "SELECT public.create_billing_checkout_intent(%s,%s,%s) AS expires_at",
                    (token_hash, price_id, ttl_seconds),
                ).fetchone()["expires_at"]
        except InsufficientPrivilege:
            raise WritePermissionRequiredError from None

    def subscriptions(self, identity: WorkspaceIdentity) -> list[dict]:
        with self.database.workspace_transaction(identity) as connection:
            return connection.execute(
                """SELECT subscription_id,customer_id,environment,bound_price_id,price_id,product_id,
                    quantity,status,trial_starts_at,trial_ends_at,current_period_starts_at,
                    current_period_ends_at,next_billed_at,scheduled_action,scheduled_effective_at,
                    last_occurred_at,last_occurred_at AS occurred_at,watermark_conflict
                    FROM public.billing_subscriptions WHERE workspace_id=%s
                    ORDER BY last_occurred_at DESC,subscription_id""",
                (identity.workspace_id,),
            ).fetchall()

    def apply_event(self, snapshot: dict) -> str:
        # This method is called only after the webhook signature and schema checks.
        serialized = {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in snapshot.items()
        }
        with self.database.connection(timeout=2) as connection, connection.transaction():
            connection.execute("SET LOCAL statement_timeout='2s'")
            connection.execute("SET LOCAL lock_timeout='1s'")
            return connection.execute(
                "SELECT public.apply_paddle_billing_event(%s) AS outcome", (Jsonb(serialized),),
            ).fetchone()["outcome"]
