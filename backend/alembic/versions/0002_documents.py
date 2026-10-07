"""Documents, extracted pages and fields, processing job queue

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 17:08:57.456242

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('documents',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('queued', 'processing', 'extracted', 'failed', 'rejected', name='document_status', native_enum=False, length=32), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('document_type', sa.Enum('passport', 'visa', 'flight_ticket', 'boarding_pass', 'hotel_booking', 'car_booking', 'insurance', 'itinerary', 'identity_document', 'other', name='document_type', native_enum=False, length=32), nullable=True),
    sa.Column('type_confidence', sa.Float(), nullable=True),
    sa.Column('analysis_method', sa.String(length=16), nullable=True),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('ocr_used', sa.Boolean(), nullable=False),
    sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('text_extracted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fields_extracted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_documents_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_documents_storage_key')),
    sa.UniqueConstraint('user_id', 'sha256', name='uq_documents_user_sha256')
    )
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_documents_status'), ['status'], unique=False)
        batch_op.create_index('ix_documents_user_created', ['user_id', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_documents_user_id'), ['user_id'], unique=False)

    op.create_table('document_pages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('ocr', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_document_pages_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_pages'))
    )
    with op.batch_alter_table('document_pages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_pages_document_id'), ['document_id'], unique=False)

    op.create_table('extracted_entities',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('entity_type', sa.String(length=32), nullable=False),
    sa.Column('field', sa.String(length=64), nullable=False),
    sa.Column('value', sa.String(length=1000), nullable=False),
    sa.Column('group_index', sa.Integer(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('method', sa.String(length=16), nullable=False),
    sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_extracted_entities_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_extracted_entities_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_extracted_entities'))
    )
    with op.batch_alter_table('extracted_entities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_extracted_entities_document_id'), ['document_id'], unique=False)
        batch_op.create_index('ix_extracted_entities_user_field', ['user_id', 'field'], unique=False)

    op.create_table('processing_jobs',
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('queued', 'running', 'succeeded', 'failed', name='job_status', native_enum=False, length=32), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('run_after', sa.DateTime(timezone=True), nullable=False),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.String(length=200), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_processing_jobs_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_processing_jobs'))
    )
    with op.batch_alter_table('processing_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_processing_jobs_document_id'), ['document_id'], unique=False)
        batch_op.create_index('ix_processing_jobs_pick', ['status', 'run_after'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('processing_jobs', schema=None) as batch_op:
        batch_op.drop_index('ix_processing_jobs_pick')
        batch_op.drop_index(batch_op.f('ix_processing_jobs_document_id'))

    op.drop_table('processing_jobs')
    with op.batch_alter_table('extracted_entities', schema=None) as batch_op:
        batch_op.drop_index('ix_extracted_entities_user_field')
        batch_op.drop_index(batch_op.f('ix_extracted_entities_document_id'))

    op.drop_table('extracted_entities')
    with op.batch_alter_table('document_pages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_pages_document_id'))

    op.drop_table('document_pages')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documents_user_id'))
        batch_op.drop_index('ix_documents_user_created')
        batch_op.drop_index(batch_op.f('ix_documents_status'))

    op.drop_table('documents')
