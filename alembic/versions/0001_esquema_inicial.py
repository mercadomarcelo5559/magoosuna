"""Esquema inicial de la Social Video API.

Crea las tablas: clients, api_keys, social_accounts, media_assets,
oauth_states, idempotency_records, post_groups, posts, post_attempts
y scheduled_posts.

Revision ID: 0001_initial
Revises: -
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '0001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('clients',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('oauth_states',
    sa.Column('state', sa.String(length=128), nullable=False),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('client_id', sa.String(length=36), nullable=False),
    sa.Column('redirect_uri', sa.Text(), nullable=False),
    sa.Column('return_url', sa.Text(), nullable=True),
    sa.Column('code_verifier_encrypted', sa.Text(), nullable=True),
    sa.Column('extra', sa.JSON(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_oauth_states_client_id'), 'oauth_states', ['client_id'], unique=False)
    op.create_index(op.f('ix_oauth_states_state'), 'oauth_states', ['state'], unique=True)
    op.create_table('api_keys',
    sa.Column('client_id', sa.String(length=36), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_keys_client_id'), 'api_keys', ['client_id'], unique=False)
    op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'], unique=True)
    op.create_table('idempotency_records',
    sa.Column('client_id', sa.String(length=36), nullable=False),
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('endpoint', sa.String(length=120), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=False),
    sa.Column('response_body', sa.JSON(), nullable=True),
    sa.Column('resource_id', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_id', 'key', name='uq_idempotency_client_key')
    )
    op.create_index(op.f('ix_idempotency_records_client_id'), 'idempotency_records', ['client_id'], unique=False)
    op.create_table('media_assets',
    sa.Column('client_id', sa.String(length=36), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
    sa.Column('storage_backend', sa.String(length=16), nullable=True),
    sa.Column('storage_key', sa.String(length=1024), nullable=True),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('asset_metadata', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_media_assets_client_id'), 'media_assets', ['client_id'], unique=False)
    op.create_index(op.f('ix_media_assets_expires_at'), 'media_assets', ['expires_at'], unique=False)
    op.create_index(op.f('ix_media_assets_status'), 'media_assets', ['status'], unique=False)
    op.create_table('social_accounts',
    sa.Column('client_id', sa.String(length=36), nullable=False),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('account_name', sa.String(length=255), nullable=False),
    sa.Column('external_account_id', sa.String(length=255), nullable=False),
    sa.Column('access_token_encrypted', sa.Text(), nullable=False),
    sa.Column('refresh_token_encrypted', sa.Text(), nullable=True),
    sa.Column('token_expiration', sa.DateTime(timezone=True), nullable=True),
    sa.Column('refresh_token_expiration', sa.DateTime(timezone=True), nullable=True),
    sa.Column('scopes', sa.JSON(), nullable=False),
    sa.Column('account_metadata', sa.JSON(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('disconnected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_refreshed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_id', 'platform', 'external_account_id', name='uq_social_account_identity')
    )
    op.create_index(op.f('ix_social_accounts_client_id'), 'social_accounts', ['client_id'], unique=False)
    op.create_index(op.f('ix_social_accounts_external_account_id'), 'social_accounts', ['external_account_id'], unique=False)
    op.create_index(op.f('ix_social_accounts_platform'), 'social_accounts', ['platform'], unique=False)
    op.create_table('post_groups',
    sa.Column('client_id', sa.String(length=36), nullable=False),
    sa.Column('media_asset_id', sa.String(length=36), nullable=False),
    sa.Column('caption', sa.Text(), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('idempotency_key', sa.String(length=255), nullable=True),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['media_asset_id'], ['media_assets.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_post_groups_client_id'), 'post_groups', ['client_id'], unique=False)
    op.create_index(op.f('ix_post_groups_idempotency_key'), 'post_groups', ['idempotency_key'], unique=False)
    op.create_table('posts',
    sa.Column('group_id', sa.String(length=36), nullable=False),
    sa.Column('client_id', sa.String(length=36), nullable=False),
    sa.Column('media_asset_id', sa.String(length=36), nullable=False),
    sa.Column('social_account_id', sa.String(length=36), nullable=False),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('caption', sa.Text(), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=False),
    sa.Column('platform_options', sa.JSON(), nullable=False),
    sa.Column('external_post_id', sa.String(length=255), nullable=True),
    sa.Column('external_url', sa.Text(), nullable=True),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('error_category', sa.String(length=32), nullable=True),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('provider_state', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['group_id'], ['post_groups.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['media_asset_id'], ['media_assets.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['social_account_id'], ['social_accounts.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_posts_client_created', 'posts', ['client_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_posts_client_id'), 'posts', ['client_id'], unique=False)
    op.create_index(op.f('ix_posts_external_post_id'), 'posts', ['external_post_id'], unique=False)
    op.create_index(op.f('ix_posts_group_id'), 'posts', ['group_id'], unique=False)
    op.create_index(op.f('ix_posts_next_retry_at'), 'posts', ['next_retry_at'], unique=False)
    op.create_index(op.f('ix_posts_platform'), 'posts', ['platform'], unique=False)
    op.create_index(op.f('ix_posts_social_account_id'), 'posts', ['social_account_id'], unique=False)
    op.create_index(op.f('ix_posts_status'), 'posts', ['status'], unique=False)
    op.create_index('ix_posts_status_scheduled', 'posts', ['status', 'scheduled_at'], unique=False)
    op.create_table('post_attempts',
    sa.Column('post_id', sa.String(length=36), nullable=False),
    sa.Column('attempt_number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('stage', sa.String(length=64), nullable=True),
    sa.Column('error_category', sa.String(length=32), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('post_id', 'attempt_number', name='uq_attempt_number')
    )
    op.create_index(op.f('ix_post_attempts_post_id'), 'post_attempts', ['post_id'], unique=False)
    op.create_table('scheduled_posts',
    sa.Column('post_id', sa.String(length=36), nullable=False),
    sa.Column('client_id', sa.String(length=36), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=120), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scheduled_posts_client_id'), 'scheduled_posts', ['client_id'], unique=False)
    op.create_index(op.f('ix_scheduled_posts_post_id'), 'scheduled_posts', ['post_id'], unique=False)
    op.create_index('ix_scheduled_run', 'scheduled_posts', ['status', 'run_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_scheduled_run', table_name='scheduled_posts')
    op.drop_index(op.f('ix_scheduled_posts_post_id'), table_name='scheduled_posts')
    op.drop_index(op.f('ix_scheduled_posts_client_id'), table_name='scheduled_posts')
    op.drop_table('scheduled_posts')
    op.drop_index(op.f('ix_post_attempts_post_id'), table_name='post_attempts')
    op.drop_table('post_attempts')
    op.drop_index('ix_posts_status_scheduled', table_name='posts')
    op.drop_index(op.f('ix_posts_status'), table_name='posts')
    op.drop_index(op.f('ix_posts_social_account_id'), table_name='posts')
    op.drop_index(op.f('ix_posts_platform'), table_name='posts')
    op.drop_index(op.f('ix_posts_next_retry_at'), table_name='posts')
    op.drop_index(op.f('ix_posts_group_id'), table_name='posts')
    op.drop_index(op.f('ix_posts_external_post_id'), table_name='posts')
    op.drop_index(op.f('ix_posts_client_id'), table_name='posts')
    op.drop_index('ix_posts_client_created', table_name='posts')
    op.drop_table('posts')
    op.drop_index(op.f('ix_post_groups_idempotency_key'), table_name='post_groups')
    op.drop_index(op.f('ix_post_groups_client_id'), table_name='post_groups')
    op.drop_table('post_groups')
    op.drop_index(op.f('ix_social_accounts_platform'), table_name='social_accounts')
    op.drop_index(op.f('ix_social_accounts_external_account_id'), table_name='social_accounts')
    op.drop_index(op.f('ix_social_accounts_client_id'), table_name='social_accounts')
    op.drop_table('social_accounts')
    op.drop_index(op.f('ix_media_assets_status'), table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_expires_at'), table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_client_id'), table_name='media_assets')
    op.drop_table('media_assets')
    op.drop_index(op.f('ix_idempotency_records_client_id'), table_name='idempotency_records')
    op.drop_table('idempotency_records')
    op.drop_index(op.f('ix_api_keys_key_hash'), table_name='api_keys')
    op.drop_index(op.f('ix_api_keys_client_id'), table_name='api_keys')
    op.drop_table('api_keys')
    op.drop_index(op.f('ix_oauth_states_state'), table_name='oauth_states')
    op.drop_index(op.f('ix_oauth_states_client_id'), table_name='oauth_states')
    op.drop_table('oauth_states')
    op.drop_table('clients')
