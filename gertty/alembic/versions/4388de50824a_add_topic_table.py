"""add topic table

Revision ID: 4388de50824a
Revises: 254ac5fc3941
Create Date: 2015-10-31 19:06:38.538948

"""

# revision identifiers, used by Alembic.
revision = '4388de50824a'
down_revision = '254ac5fc3941'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('topic',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), index=True, nullable=False),
    sa.Column('sequence', sa.Integer(), index=True, unique=True, nullable=False),
    sa.PrimaryKeyConstraint('key')
    )

    op.create_table('project_topic',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('project_key', sa.Integer(), sa.ForeignKey('project.key'), index=True),
    sa.Column('topic_key', sa.Integer(), sa.ForeignKey('topic.key'), index=True),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('key'),
    sa.UniqueConstraint('topic_key', 'sequence', name='topic_key_sequence_const'),
    )

def downgrade():
    pass
