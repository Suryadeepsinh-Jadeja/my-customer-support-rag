"""Bookings and confirmation requests

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06 22:57:53.111517

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('bookings',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('flight', 'hotel', 'car', 'excursion', name='booking_kind', native_enum=False, length=32), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('provider_ref', sa.String(length=64), nullable=True),
    sa.Column('status', sa.Enum('searching', 'price_check', 'awaiting_confirmation', 'booking', 'confirmed', 'modification_requested', 'modified', 'cancellation_requested', 'cancelled', 'failed', 'expired', name='booking_status', native_enum=False, length=32), nullable=False),
    sa.Column('travel_date', sa.Date(), nullable=True),
    sa.Column('total_amount', sa.Numeric(precision=12, scale=2, asdecimal=False), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_bookings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bookings'))
    )
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.create_index('ix_bookings_user_travel_date', ['user_id', 'travel_date'], unique=False)

    op.create_table('confirmation_requests',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('params', sa.JSON(), nullable=False),
    sa.Column('params_hash', sa.String(length=64), nullable=False),
    sa.Column('summary', sa.JSON(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'confirmed', 'declined', 'expired', name='confirmation_status', native_enum=False, length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_confirmation_requests_conversation_id_conversations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_confirmation_requests_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_confirmation_requests'))
    )
    with op.batch_alter_table('confirmation_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_confirmation_requests_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('confirmation_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_confirmation_requests_user_id'))

    op.drop_table('confirmation_requests')
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.drop_index('ix_bookings_user_travel_date')

    op.drop_table('bookings')
