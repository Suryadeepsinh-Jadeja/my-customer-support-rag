"""Document and knowledge-base chunks with embeddings (pgvector), documents.indexed_at

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06 17:26:05.314687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.models.rag import Embedding


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('knowledge_documents',
    sa.Column('source', sa.String(length=300), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('last_updated', sa.String(length=32), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_documents')),
    sa.UniqueConstraint('source', name=op.f('uq_knowledge_documents_source'))
    )
    op.create_table('knowledge_chunks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('knowledge_document_id', sa.Uuid(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('section', sa.String(length=300), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('embedding', Embedding(), nullable=True),
    sa.ForeignKeyConstraint(['knowledge_document_id'], ['knowledge_documents.id'], name=op.f('fk_knowledge_chunks_knowledge_document_id_knowledge_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_chunks'))
    )
    with op.batch_alter_table('knowledge_chunks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_knowledge_chunks_knowledge_document_id'), ['knowledge_document_id'], unique=False)

    op.create_table('document_chunks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('embedding', Embedding(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_document_chunks_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_document_chunks_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_chunks'))
    )
    with op.batch_alter_table('document_chunks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_chunks_document_id'), ['document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_chunks_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True))


    if op.get_bind().dialect.name == "postgresql":
        for table in ("document_chunks", "knowledge_chunks"):
            op.execute(f"CREATE INDEX ix_{table}_embedding ON {table} "
                       "USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_column('indexed_at')

    with op.batch_alter_table('document_chunks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_chunks_user_id'))
        batch_op.drop_index(batch_op.f('ix_document_chunks_document_id'))

    op.drop_table('document_chunks')
    with op.batch_alter_table('knowledge_chunks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_knowledge_chunks_knowledge_document_id'))

    op.drop_table('knowledge_chunks')
    op.drop_table('knowledge_documents')
