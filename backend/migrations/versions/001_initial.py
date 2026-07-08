"""Initial migration

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.create_table(
        'accounts',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='account'),
        sa.Column('account_type', sa.String(20), nullable=False, default='standard'),
        sa.Column('country', sa.String(2), nullable=False),
        sa.Column('email', sa.String(254), nullable=True),
        sa.Column('business_type', sa.String(20), nullable=True),
        sa.Column('business_profile', postgresql.JSONB, nullable=True),
        sa.Column('company', postgresql.JSONB, nullable=True),
        sa.Column('individual', postgresql.JSONB, nullable=True),
        sa.Column('capabilities', postgresql.JSONB, nullable=True),
        sa.Column('requirements', postgresql.JSONB, nullable=True),
        sa.Column('settings', postgresql.JSONB, nullable=True),
        sa.Column('tos_acceptance', postgresql.JSONB, nullable=True),
        sa.Column('charges_enabled', sa.Boolean, nullable=False, default=False),
        sa.Column('payouts_enabled', sa.Boolean, nullable=False, default=False),
        sa.Column('details_submitted', sa.Boolean, nullable=False, default=False),
        sa.Column('default_currency', sa.String(3), nullable=False, default='USD'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_accounts_type', 'accounts', ['account_type'])
    op.create_index('ix_accounts_country', 'accounts', ['country'])

    op.create_table(
        'customers',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='customer'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('email', sa.String(254), nullable=True),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('address_line1', sa.String(100), nullable=True),
        sa.Column('address_line2', sa.String(100), nullable=True),
        sa.Column('address_city', sa.String(50), nullable=True),
        sa.Column('address_state', sa.String(50), nullable=True),
        sa.Column('address_postal_code', sa.String(20), nullable=True),
        sa.Column('address_country', sa.String(2), nullable=True),
        sa.Column('balance', sa.BigInteger, nullable=False, default=0),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('default_source', sa.String(50), nullable=True),
        sa.Column('default_payment_method', sa.String(50), nullable=True),
        sa.Column('invoice_prefix', sa.String(20), nullable=True),
        sa.Column('tax_exempt', sa.String(20), nullable=False, default='none'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_customers_email_account', 'customers', ['email', 'account_id'])
    op.create_index('ix_customers_created_at', 'customers', ['created_at'])

    op.create_table(
        'payment_intents',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='payment_intent'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('customer_id', sa.String(50), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('amount_capturable', sa.BigInteger, nullable=False, default=0),
        sa.Column('amount_received', sa.BigInteger, nullable=False, default=0),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('client_secret', sa.String(100), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, default='requires_payment_method'),
        sa.Column('capture_method', sa.String(20), nullable=False, default='automatic'),
        sa.Column('confirmation_method', sa.String(20), nullable=False, default='automatic'),
        sa.Column('payment_method_types', postgresql.ARRAY(sa.String), nullable=False, default=['card']),
        sa.Column('payment_method', sa.String(50), nullable=True),
        sa.Column('latest_charge', sa.String(50), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('receipt_email', sa.String(254), nullable=True),
        sa.Column('statement_descriptor', sa.String(22), nullable=True),
        sa.Column('setup_future_usage', sa.String(50), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_payment_intents_status', 'payment_intents', ['status'])
    op.create_index('ix_payment_intents_customer_created', 'payment_intents', ['customer_id', 'created_at'])

    op.create_table(
        'charges',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='charge'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('customer_id', sa.String(50), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payment_intent_id', sa.String(50), sa.ForeignKey('payment_intents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('amount_captured', sa.BigInteger, nullable=False, default=0),
        sa.Column('amount_refunded', sa.BigInteger, nullable=False, default=0),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('paid', sa.Boolean, nullable=False, default=False),
        sa.Column('captured', sa.Boolean, nullable=False, default=False),
        sa.Column('refunded', sa.Boolean, nullable=False, default=False),
        sa.Column('disputed', sa.Boolean, nullable=False, default=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('receipt_email', sa.String(254), nullable=True),
        sa.Column('receipt_number', sa.String(20), nullable=True),
        sa.Column('statement_descriptor', sa.String(22), nullable=True),
        sa.Column('payment_method', sa.String(50), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_charges_status', 'charges', ['status'])
    op.create_index('ix_charges_payment_intent', 'charges', ['payment_intent_id'])

    op.create_table(
        'refunds',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='refund'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('charge_id', sa.String(50), sa.ForeignKey('charges.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('reason', sa.String(50), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_refunds_charge', 'refunds', ['charge_id'])
    op.create_index('ix_refunds_status', 'refunds', ['status'])

    op.create_table(
        'products',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='product'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(250), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('active', sa.Boolean, nullable=False, default=True),
        sa.Column('type', sa.String(20), nullable=False, default='service'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_products_active', 'products', ['active'])

    op.create_table(
        'prices',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='price'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('product_id', sa.String(50), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('unit_amount', sa.BigInteger, nullable=True),
        sa.Column('active', sa.Boolean, nullable=False, default=True),
        sa.Column('type', sa.String(20), nullable=False, default='recurring'),
        sa.Column('recurring_interval', sa.String(10), nullable=True),
        sa.Column('recurring_interval_count', sa.Integer, nullable=False, default=1),
        sa.Column('tax_behavior', sa.String(20), nullable=False, default='unspecified'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_prices_product', 'prices', ['product_id'])

    op.create_table(
        'subscriptions',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='subscription'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('customer_id', sa.String(50), sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='incomplete'),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('items', postgresql.JSONB, nullable=True),
        sa.Column('billing_cycle_anchor', sa.BigInteger, nullable=False),
        sa.Column('current_period_start', sa.BigInteger, nullable=False),
        sa.Column('current_period_end', sa.BigInteger, nullable=False),
        sa.Column('cancel_at_period_end', sa.Boolean, nullable=False, default=False),
        sa.Column('canceled_at', sa.BigInteger, nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_subscriptions_customer_status', 'subscriptions', ['customer_id', 'status'])

    op.create_table(
        'invoices',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='invoice'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('customer_id', sa.String(50), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('subscription_id', sa.String(50), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='draft'),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('amount_due', sa.BigInteger, nullable=False),
        sa.Column('amount_paid', sa.BigInteger, nullable=False, default=0),
        sa.Column('amount_remaining', sa.BigInteger, nullable=False),
        sa.Column('total', sa.BigInteger, nullable=False),
        sa.Column('paid', sa.Boolean, nullable=False, default=False),
        sa.Column('collection_method', sa.String(30), nullable=False, default='charge_automatically'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_invoices_customer_status', 'invoices', ['customer_id', 'status'])

    op.create_table(
        'checkout_sessions',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='checkout.session'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('customer_id', sa.String(50), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('mode', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='open'),
        sa.Column('success_url', sa.String(500), nullable=True),
        sa.Column('cancel_url', sa.String(500), nullable=True),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('client_secret', sa.String(100), nullable=True),
        sa.Column('line_items', postgresql.JSONB, nullable=True),
        sa.Column('payment_method_types', postgresql.ARRAY(sa.String), nullable=False, default=['card']),
        sa.Column('amount_total', sa.BigInteger, nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('expires_at', sa.BigInteger, nullable=False),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_checkout_sessions_status', 'checkout_sessions', ['status'])

    op.create_table(
        'payment_methods',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='payment_method'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('customer_id', sa.String(50), sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=True),
        sa.Column('type', sa.String(30), nullable=False),
        sa.Column('card', postgresql.JSONB, nullable=True),
        sa.Column('billing_details', postgresql.JSONB, nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_payment_methods_customer_type', 'payment_methods', ['customer_id', 'type'])

    op.create_table(
        'events',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='event'),
        sa.Column('account_id', sa.String(50), nullable=True),
        sa.Column('type', sa.String(100), nullable=False),
        sa.Column('data', postgresql.JSONB, nullable=False),
        sa.Column('api_version', sa.String(20), nullable=False),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_events_type_created', 'events', ['type', 'created_at'])

    op.create_table(
        'webhook_endpoints',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='webhook_endpoint'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=True),
        sa.Column('url', sa.String(500), nullable=False),
        sa.Column('secret', sa.String(100), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='enabled'),
        sa.Column('enabled_events', postgresql.ARRAY(sa.String), nullable=False),
        sa.Column('api_version', sa.String(20), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_webhook_endpoints_account', 'webhook_endpoints', ['account_id'])

    op.create_table(
        'event_deliveries',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('event_id', sa.String(50), sa.ForeignKey('events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('webhook_endpoint_id', sa.String(50), sa.ForeignKey('webhook_endpoints.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', sa.String(50), nullable=True),
        sa.Column('webhook_url', sa.String(500), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('attempt_number', sa.Integer, nullable=False, default=1),
        sa.Column('response_status_code', sa.Integer, nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_event_deliveries_status', 'event_deliveries', ['status'])
    op.create_index('ix_event_deliveries_next_retry', 'event_deliveries', ['next_retry_at'])

    op.create_table(
        'api_keys',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=True),
        sa.Column('key_hash', sa.String(128), nullable=False, unique=True),
        sa.Column('key_prefix', sa.String(20), nullable=False),
        sa.Column('type', sa.String(20), nullable=False, default='secret'),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_api_keys_account', 'api_keys', ['account_id'])

    op.create_table(
        'balance_transactions',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(20), nullable=False, default='balance_transaction'),
        sa.Column('account_id', sa.String(50), nullable=True),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('net', sa.BigInteger, nullable=False),
        sa.Column('fee', sa.BigInteger, nullable=False, default=0),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('source', sa.String(50), nullable=True),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('available_on', sa.BigInteger, nullable=False),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_balance_transactions_type', 'balance_transactions', ['type'])
    op.create_index('ix_balance_transactions_source', 'balance_transactions', ['source'])

    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.String(100), primary_key=True),
        sa.Column('account_id', sa.String(50), nullable=True),
        sa.Column('request_path', sa.String(500), nullable=False),
        sa.Column('request_method', sa.String(10), nullable=False),
        sa.Column('request_params_hash', sa.String(128), nullable=False),
        sa.Column('request_raw_params', postgresql.JSONB, nullable=True),
        sa.Column('response_status_code', sa.Integer, nullable=True),
        sa.Column('response_body', sa.Text, nullable=True),
        sa.Column('response_headers', postgresql.JSONB, nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_idempotency_keys_expires', 'idempotency_keys', ['expires_at'])

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('account_id', sa.String(50), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=False),
        sa.Column('resource_id', sa.String(50), nullable=False),
        sa.Column('actor_id', sa.String(50), nullable=True),
        sa.Column('actor_type', sa.String(30), nullable=False, default='user'),
        sa.Column('actor_ip_address', sa.String(50), nullable=True),
        sa.Column('actor_user_agent', sa.String(500), nullable=True),
        sa.Column('changes', postgresql.JSONB, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='success'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_audit_logs_account_created', 'audit_logs', ['account_id', 'created_at'])
    op.create_index('ix_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'])

    op.create_table(
        'ledger_accounts',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='ledger.account'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('account_type', sa.String(30), nullable=False),
        sa.Column('balance', sa.BigInteger, nullable=False, default=0),
        sa.Column('posted_balance', sa.BigInteger, nullable=False, default=0),
        sa.Column('pending_balance', sa.BigInteger, nullable=False, default=0),
        sa.Column('status', sa.String(20), nullable=False, default='open'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_ledger_accounts_account_id', 'ledger_accounts', ['account_id'])
    op.create_index('ix_ledger_accounts_currency', 'ledger_accounts', ['currency'])

    op.create_table(
        'journal_entries',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='ledger.journal_entry'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('transaction_id', sa.String(50), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reversal_for', sa.String(50), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_journal_entries_account_id', 'journal_entries', ['account_id'])
    op.create_index('ix_journal_entries_status', 'journal_entries', ['status'])
    op.create_index('ix_journal_entries_effective_at', 'journal_entries', ['effective_at'])

    op.create_table(
        'ledger_entries',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='ledger.entry'),
        sa.Column('journal_entry_id', sa.String(50), sa.ForeignKey('journal_entries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ledger_account_id', sa.String(50), sa.ForeignKey('ledger_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('balance_after', sa.BigInteger, nullable=False),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ledger_entries_journal_entry', 'ledger_entries', ['journal_entry_id'])
    op.create_index('ix_ledger_entries_ledger_account', 'ledger_entries', ['ledger_account_id'])

    op.create_table(
        'issuing_cardholders',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='issuing.cardholder'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(20), nullable=False, default='individual'),
        sa.Column('status', sa.String(20), nullable=False, default='active'),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('email', sa.String(254), nullable=True),
        sa.Column('phone_number', sa.String(20), nullable=True),
        sa.Column('address_line1', sa.String(100), nullable=False),
        sa.Column('address_line2', sa.String(100), nullable=True),
        sa.Column('address_city', sa.String(50), nullable=False),
        sa.Column('address_state', sa.String(50), nullable=True),
        sa.Column('address_postal_code', sa.String(20), nullable=False),
        sa.Column('address_country', sa.String(2), nullable=False),
        sa.Column('spending_controls', postgresql.JSONB, nullable=True),
        sa.Column('company', postgresql.JSONB, nullable=True),
        sa.Column('individual', postgresql.JSONB, nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_issuing_cardholders_account', 'issuing_cardholders', ['account_id'])
    op.create_index('ix_issuing_cardholders_status', 'issuing_cardholders', ['status'])

    op.create_table(
        'issuing_cards',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='issuing.card'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cardholder_id', sa.String(50), sa.ForeignKey('issuing_cardholders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(20), nullable=False, default='virtual'),
        sa.Column('status', sa.String(20), nullable=False, default='inactive'),
        sa.Column('currency', sa.String(3), nullable=False, default='USD'),
        sa.Column('brand', sa.String(20), nullable=False),
        sa.Column('last4', sa.String(4), nullable=False),
        sa.Column('exp_month', sa.Integer, nullable=False),
        sa.Column('exp_year', sa.Integer, nullable=False),
        sa.Column('spending_controls', postgresql.JSONB, nullable=True),
        sa.Column('replacement_for', sa.String(50), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_issuing_cards_account', 'issuing_cards', ['account_id'])
    op.create_index('ix_issuing_cards_cardholder', 'issuing_cards', ['cardholder_id'])
    op.create_index('ix_issuing_cards_status', 'issuing_cards', ['status'])

    op.create_table(
        'issuing_authorizations',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='issuing.authorization'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('card_id', sa.String(50), sa.ForeignKey('issuing_cards.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('merchant_data', postgresql.JSONB, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('approved', sa.Boolean, nullable=False, default=False),
        sa.Column('wallet_provider', sa.String(30), nullable=True),
        sa.Column('authorization_method', sa.String(30), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_issuing_authorizations_account', 'issuing_authorizations', ['account_id'])
    op.create_index('ix_issuing_authorizations_card', 'issuing_authorizations', ['card_id'])
    op.create_index('ix_issuing_authorizations_status', 'issuing_authorizations', ['status'])

    op.create_table(
        'treasury_financial_accounts',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='treasury.financial_account'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_type', sa.String(20), nullable=False, default='checking'),
        sa.Column('currency', sa.String(3), nullable=False, default='USD'),
        sa.Column('status', sa.String(20), nullable=False, default='open'),
        sa.Column('available_balance', sa.BigInteger, nullable=False, default=0),
        sa.Column('pending_balance', sa.BigInteger, nullable=False, default=0),
        sa.Column('reserved_balance', sa.BigInteger, nullable=False, default=0),
        sa.Column('features', postgresql.JSONB, nullable=True),
        sa.Column('routing_numbers', postgresql.JSONB, nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_treasury_financial_accounts_account', 'treasury_financial_accounts', ['account_id'])
    op.create_index('ix_treasury_financial_accounts_status', 'treasury_financial_accounts', ['status'])

    op.create_table(
        'treasury_transfers',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='treasury.transfer'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('financial_account_id', sa.String(50), sa.ForeignKey('treasury_financial_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('transfer_type', sa.String(30), nullable=False),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('network', sa.String(20), nullable=True),
        sa.Column('originating_account', sa.String(50), nullable=True),
        sa.Column('destination_account', sa.String(50), nullable=True),
        sa.Column('expected_arrival_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_treasury_transfers_account', 'treasury_transfers', ['account_id'])
    op.create_index('ix_treasury_transfers_financial_account', 'treasury_transfers', ['financial_account_id'])
    op.create_index('ix_treasury_transfers_status', 'treasury_transfers', ['status'])

    op.create_table(
        'capital_offers',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='capital.offering'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, default='USD'),
        sa.Column('withhold_rate', sa.Numeric(5, 4), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='offered'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_capital_offers_account', 'capital_offers', ['account_id'])
    op.create_index('ix_capital_offers_status', 'capital_offers', ['status'])

    op.create_table(
        'capital_financings',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='capital.financing'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('offer_id', sa.String(50), sa.ForeignKey('capital_offers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, default='USD'),
        sa.Column('amount_disbursed', sa.BigInteger, nullable=False, default=0),
        sa.Column('amount_repaid', sa.BigInteger, nullable=False, default=0),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('disbursement_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_capital_financings_account', 'capital_financings', ['account_id'])
    op.create_index('ix_capital_financings_offer', 'capital_financings', ['offer_id'])
    op.create_index('ix_capital_financings_status', 'capital_financings', ['status'])

    op.create_table(
        'crypto_addresses',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='crypto.address'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cryptocurrency', sa.String(10), nullable=False),
        sa.Column('address', sa.String(200), nullable=False),
        sa.Column('derivation_path', sa.String(100), nullable=True),
        sa.Column('derivation_index', sa.Integer, nullable=True),
        sa.Column('public_key', sa.String(200), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='active'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_crypto_addresses_account', 'crypto_addresses', ['account_id'])
    op.create_index('ix_crypto_addresses_cryptocurrency', 'crypto_addresses', ['cryptocurrency'])
    op.create_index('ix_crypto_addresses_address', 'crypto_addresses', ['address'])

    op.create_table(
        'crypto_payments',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='crypto.payment'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('payment_intent_id', sa.String(50), sa.ForeignKey('payment_intents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('address_id', sa.String(50), sa.ForeignKey('crypto_addresses.id', ondelete='SET NULL'), nullable=True),
        sa.Column('cryptocurrency', sa.String(10), nullable=False),
        sa.Column('amount_crypto', sa.Numeric(30, 18), nullable=False),
        sa.Column('amount_fiat', sa.BigInteger, nullable=False),
        sa.Column('exchange_rate', sa.Numeric(20, 8), nullable=False),
        sa.Column('settlement_currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, default='pending'),
        sa.Column('transaction_hash', sa.String(200), nullable=True),
        sa.Column('confirmation_blocks', sa.Integer, nullable=False, default=0),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_crypto_payments_account', 'crypto_payments', ['account_id'])
    op.create_index('ix_crypto_payments_status', 'crypto_payments', ['status'])
    op.create_index('ix_crypto_payments_transaction_hash', 'crypto_payments', ['transaction_hash'])

    op.create_table(
        'climate_orders',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='climate.order'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.String(50), nullable=False),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, default='USD'),
        sa.Column('metric_tons', sa.Numeric(12, 6), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('certificate_url', sa.String(500), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_climate_orders_account', 'climate_orders', ['account_id'])
    op.create_index('ix_climate_orders_status', 'climate_orders', ['status'])

    op.create_table(
        'climate_credits',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='climate.credit'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_id', sa.String(50), sa.ForeignKey('climate_orders.id', ondelete='SET NULL'), nullable=True),
        sa.Column('serial_number', sa.String(100), nullable=False, unique=True),
        sa.Column('vintage_year', sa.Integer, nullable=False),
        sa.Column('verification_standard', sa.String(30), nullable=False),
        sa.Column('metric_tons', sa.Numeric(12, 6), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('retirement_beneficiary', sa.String(200), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_climate_credits_account', 'climate_credits', ['account_id'])
    op.create_index('ix_climate_credits_order', 'climate_credits', ['order_id'])
    op.create_index('ix_climate_credits_status', 'climate_credits', ['status'])

    op.create_table(
        'verification_sessions',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='identity.verification_session'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('client_ip', sa.String(50), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('redacted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_verification_sessions_account', 'verification_sessions', ['account_id'])
    op.create_index('ix_verification_sessions_status', 'verification_sessions', ['status'])

    op.create_table(
        'document_verifications',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='identity.document_verification'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_id', sa.String(50), sa.ForeignKey('verification_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_type', sa.String(30), nullable=False),
        sa.Column('country', sa.String(2), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('extracted_data', postgresql.JSONB, nullable=True),
        sa.Column('verification_result', postgresql.JSONB, nullable=True),
        sa.Column('ocr_confidence', sa.Numeric(5, 4), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_document_verifications_account', 'document_verifications', ['account_id'])
    op.create_index('ix_document_verifications_session', 'document_verifications', ['session_id'])
    op.create_index('ix_document_verifications_status', 'document_verifications', ['status'])

    op.create_table(
        'recognition_schedules',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='revenue.schedule'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('transaction_id', sa.String(50), nullable=True),
        sa.Column('total_amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('recognized_amount', sa.BigInteger, nullable=False, default=0),
        sa.Column('deferred_amount', sa.BigInteger, nullable=False, default=0),
        sa.Column('start_date', sa.Date, nullable=False),
        sa.Column('end_date', sa.Date, nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('recognition_method', sa.String(20), nullable=False),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_recognition_schedules_account', 'recognition_schedules', ['account_id'])
    op.create_index('ix_recognition_schedules_status', 'recognition_schedules', ['status'])

    op.create_table(
        'recognition_periods',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='revenue.period'),
        sa.Column('schedule_id', sa.String(50), sa.ForeignKey('recognition_schedules.id', ondelete='CASCADE'), nullable=False),
        sa.Column('period_start', sa.Date, nullable=False),
        sa.Column('period_end', sa.Date, nullable=False),
        sa.Column('amount_to_recognize', sa.BigInteger, nullable=False),
        sa.Column('recognized_amount', sa.BigInteger, nullable=False, default=0),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('journal_entry_id', sa.String(50), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_recognition_periods_schedule', 'recognition_periods', ['schedule_id'])
    op.create_index('ix_recognition_periods_status', 'recognition_periods', ['status'])

    op.create_table(
        'terminal_locations',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='terminal.location'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('address_line1', sa.String(100), nullable=False),
        sa.Column('address_line2', sa.String(100), nullable=True),
        sa.Column('address_city', sa.String(50), nullable=False),
        sa.Column('address_state', sa.String(50), nullable=True),
        sa.Column('address_postal_code', sa.String(20), nullable=False),
        sa.Column('address_country', sa.String(2), nullable=False),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_terminal_locations_account', 'terminal_locations', ['account_id'])

    op.create_table(
        'terminal_readers',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='terminal.reader'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('location_id', sa.String(50), sa.ForeignKey('terminal_locations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('device_type', sa.String(50), nullable=False),
        sa.Column('device_sw_version', sa.String(30), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='offline'),
        sa.Column('label', sa.String(100), nullable=True),
        sa.Column('serial_number', sa.String(50), nullable=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_terminal_readers_account', 'terminal_readers', ['account_id'])
    op.create_index('ix_terminal_readers_location', 'terminal_readers', ['location_id'])
    op.create_index('ix_terminal_readers_status', 'terminal_readers', ['status'])

    op.create_table(
        'terminal_payments',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='terminal.payment'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reader_id', sa.String(50), sa.ForeignKey('terminal_readers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payment_intent_id', sa.String(50), sa.ForeignKey('payment_intents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('capture_method', sa.String(20), nullable=False, default='manual'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_terminal_payments_account', 'terminal_payments', ['account_id'])
    op.create_index('ix_terminal_payments_reader', 'terminal_payments', ['reader_id'])
    op.create_index('ix_terminal_payments_status', 'terminal_payments', ['status'])

    op.create_table(
        'payment_links',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='payment_link'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('url', sa.String(200), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('active', sa.Boolean, nullable=False, default=True),
        sa.Column('payment_intent_data', postgresql.JSONB, nullable=True),
        sa.Column('line_items', postgresql.JSONB, nullable=True),
        sa.Column('after_completion', postgresql.JSONB, nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_payment_links_account', 'payment_links', ['account_id'])
    op.create_index('ix_payment_links_active', 'payment_links', ['active'])

    op.create_table(
        'payment_link_payments',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='payment_link.payment'),
        sa.Column('payment_link_id', sa.String(50), sa.ForeignKey('payment_links.id', ondelete='CASCADE'), nullable=False),
        sa.Column('payment_intent_id', sa.String(50), sa.ForeignKey('payment_intents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('customer_id', sa.String(50), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('amount', sa.BigInteger, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_payment_link_payments_link', 'payment_link_payments', ['payment_link_id'])
    op.create_index('ix_payment_link_payments_status', 'payment_link_payments', ['status'])

    op.create_table(
        'radar_value_lists',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='radar.value_list'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('list_type', sa.String(30), nullable=False),
        sa.Column('alias', sa.String(100), nullable=True),
        sa.Column('items_count', sa.Integer, nullable=False, default=0),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_radar_value_lists_account', 'radar_value_lists', ['account_id'])
    op.create_index('ix_radar_value_lists_type', 'radar_value_lists', ['list_type'])

    op.create_table(
        'radar_rules',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='radar.rule'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('rule_type', sa.String(20), nullable=False),
        sa.Column('conditions', postgresql.JSONB, nullable=True),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('priority', sa.Integer, nullable=False, default=0),
        sa.Column('enabled', sa.Boolean, nullable=False, default=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_radar_rules_account', 'radar_rules', ['account_id'])
    op.create_index('ix_radar_rules_type', 'radar_rules', ['rule_type'])
    op.create_index('ix_radar_rules_enabled', 'radar_rules', ['enabled'])

    op.create_table(
        'radar_reviews',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='radar.review'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('payment_intent_id', sa.String(50), sa.ForeignKey('payment_intents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='open'),
        sa.Column('risk_score', sa.Integer, nullable=True),
        sa.Column('risk_factors', postgresql.JSONB, nullable=True),
        sa.Column('assigned_to', sa.String(50), nullable=True),
        sa.Column('decision_reason', sa.String(500), nullable=True),
        sa.Column('decision_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_radar_reviews_account', 'radar_reviews', ['account_id'])
    op.create_index('ix_radar_reviews_status', 'radar_reviews', ['status'])

    op.create_table(
        'radar_sessions',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='radar.session'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('payment_intent_id', sa.String(50), sa.ForeignKey('payment_intents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('risk_score', sa.Integer, nullable=False, default=0),
        sa.Column('risk_level', sa.String(20), nullable=False, default='normal'),
        sa.Column('risk_factors', postgresql.JSONB, nullable=True),
        sa.Column('charge_probability', sa.Numeric(5, 4), nullable=True),
        sa.Column('fraud_outcome', sa.String(20), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_radar_sessions_account', 'radar_sessions', ['account_id'])
    op.create_index('ix_radar_sessions_payment_intent', 'radar_sessions', ['payment_intent_id'])

    op.create_table(
        'financial_connections',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='financial_connections.account'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('institution_name', sa.String(100), nullable=True),
        sa.Column('institution_id', sa.String(50), nullable=True),
        sa.Column('account_type', sa.String(30), nullable=True),
        sa.Column('account_subtype', sa.String(30), nullable=True),
        sa.Column('balance_available', sa.BigInteger, nullable=True),
        sa.Column('balance_current', sa.BigInteger, nullable=True),
        sa.Column('balance_currency', sa.String(3), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='active'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_financial_connections_account', 'financial_connections', ['account_id'])
    op.create_index('ix_financial_connections_status', 'financial_connections', ['status'])

    op.create_table(
        'linked_accounts',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='financial_connections.linked_account'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('financial_connection_id', sa.String(50), sa.ForeignKey('financial_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('customer_id', sa.String(50), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='active'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_linked_accounts_account', 'linked_accounts', ['account_id'])
    op.create_index('ix_linked_accounts_financial_connection', 'linked_accounts', ['financial_connection_id'])

    op.create_table(
        'confirmation_tokens',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='confirmation_token'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('payment_intent_id', sa.String(50), sa.ForeignKey('payment_intents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('token', sa.String(100), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_confirmation_tokens_account', 'confirmation_tokens', ['account_id'])
    op.create_index('ix_confirmation_tokens_token', 'confirmation_tokens', ['token'])
    op.create_index('ix_confirmation_tokens_status', 'confirmation_tokens', ['status'])

    op.create_table(
        'confirmation_challenges',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='confirmation.challenge'),
        sa.Column('confirmation_token_id', sa.String(50), sa.ForeignKey('confirmation_tokens.id', ondelete='CASCADE'), nullable=False),
        sa.Column('challenge_type', sa.String(30), nullable=False),
        sa.Column('challenge_data', postgresql.JSONB, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('attempts', sa.Integer, nullable=False, default=0),
        sa.Column('max_attempts', sa.Integer, nullable=False, default=3),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_confirmation_challenges_token', 'confirmation_challenges', ['confirmation_token_id'])
    op.create_index('ix_confirmation_challenges_status', 'confirmation_challenges', ['status'])

    op.create_table(
        'meters',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='billing.meter'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('display_name', sa.String(100), nullable=True),
        sa.Column('event_name', sa.String(100), nullable=False),
        sa.Column('aggregation_method', sa.String(30), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='active'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_meters_account', 'meters', ['account_id'])
    op.create_index('ix_meters_event_name', 'meters', ['event_name'])
    op.create_index('ix_meters_status', 'meters', ['status'])

    op.create_table(
        'meter_events',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='billing.meter_event'),
        sa.Column('meter_id', sa.String(50), sa.ForeignKey('meters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('customer_id', sa.String(50), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_name', sa.String(100), nullable=False),
        sa.Column('value', sa.Numeric(20, 6), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_meter_events_meter', 'meter_events', ['meter_id'])
    op.create_index('ix_meter_events_account', 'meter_events', ['account_id'])
    op.create_index('ix_meter_events_customer', 'meter_events', ['customer_id'])
    op.create_index('ix_meter_events_timestamp', 'meter_events', ['timestamp'])

    op.create_table(
        'usage_records',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='billing.usage_record'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('subscription_item_id', sa.String(50), nullable=False),
        sa.Column('quantity', sa.BigInteger, nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_usage_records_account', 'usage_records', ['account_id'])
    op.create_index('ix_usage_records_subscription_item', 'usage_records', ['subscription_item_id'])

    op.create_table(
        'report_schedules',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='reporting.schedule'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('report_type', sa.String(50), nullable=False),
        sa.Column('interval', sa.String(20), nullable=False),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='active'),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_report_schedules_account', 'report_schedules', ['account_id'])
    op.create_index('ix_report_schedules_type', 'report_schedules', ['report_type'])
    op.create_index('ix_report_schedules_next_run', 'report_schedules', ['next_run_at'])

    op.create_table(
        'reports',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('object', sa.String(30), nullable=False, default='reporting.report'),
        sa.Column('account_id', sa.String(50), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('schedule_id', sa.String(50), sa.ForeignKey('report_schedules.id', ondelete='SET NULL'), nullable=True),
        sa.Column('report_type', sa.String(50), nullable=False),
        sa.Column('parameters', postgresql.JSONB, nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('result_url', sa.String(500), nullable=True),
        sa.Column('result_size', sa.BigInteger, nullable=True),
        sa.Column('livemode', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_reports_account', 'reports', ['account_id'])
    op.create_index('ix_reports_type', 'reports', ['report_type'])
    op.create_index('ix_reports_status', 'reports', ['status'])


def downgrade() -> None:
    op.drop_table('reports')
    op.drop_table('report_schedules')
    op.drop_table('usage_records')
    op.drop_table('meter_events')
    op.drop_table('meters')
    op.drop_table('confirmation_challenges')
    op.drop_table('confirmation_tokens')
    op.drop_table('linked_accounts')
    op.drop_table('financial_connections')
    op.drop_table('radar_sessions')
    op.drop_table('radar_reviews')
    op.drop_table('radar_rules')
    op.drop_table('radar_value_lists')
    op.drop_table('payment_link_payments')
    op.drop_table('payment_links')
    op.drop_table('terminal_payments')
    op.drop_table('terminal_readers')
    op.drop_table('terminal_locations')
    op.drop_table('recognition_periods')
    op.drop_table('recognition_schedules')
    op.drop_table('document_verifications')
    op.drop_table('verification_sessions')
    op.drop_table('climate_credits')
    op.drop_table('climate_orders')
    op.drop_table('crypto_payments')
    op.drop_table('crypto_addresses')
    op.drop_table('capital_financings')
    op.drop_table('capital_offers')
    op.drop_table('treasury_transfers')
    op.drop_table('treasury_financial_accounts')
    op.drop_table('issuing_authorizations')
    op.drop_table('issuing_cards')
    op.drop_table('issuing_cardholders')
    op.drop_table('ledger_entries')
    op.drop_table('journal_entries')
    op.drop_table('ledger_accounts')
    op.drop_table('audit_logs')
    op.drop_table('idempotency_keys')
    op.drop_table('balance_transactions')
    op.drop_table('api_keys')
    op.drop_table('event_deliveries')
    op.drop_table('webhook_endpoints')
    op.drop_table('events')
    op.drop_table('payment_methods')
    op.drop_table('checkout_sessions')
    op.drop_table('invoices')
    op.drop_table('subscriptions')
    op.drop_table('prices')
    op.drop_table('products')
    op.drop_table('refunds')
    op.drop_table('charges')
    op.drop_table('payment_intents')
    op.drop_table('customers')
    op.drop_table('accounts')
    op.execute("DROP EXTENSION IF EXISTS \"uuid-ossp\"")
