
from alembic import op
import sqlalchemy as sa

revision = '001_initial_tables'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('users',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(20), server_default='hr'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    op.create_table('slides',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200)),
        sa.Column('content', sa.Text),
        sa.Column('extra_data', sa.JSON),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('priority', sa.Integer, server_default='0'),
        sa.Column('views', sa.Integer, server_default='0'),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('is_auto_generated', sa.Boolean, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )
    op.create_table('screens',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('code', sa.String(3), unique=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('is_connected', sa.Boolean, server_default='false'),
        sa.Column('is_online', sa.Boolean, server_default='false'),
        sa.Column('last_active', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )

def downgrade():
    op.drop_table('screens')
    op.drop_table('slides')
    op.drop_table('users')
