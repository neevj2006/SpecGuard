import os

from alembic import context
from sqlalchemy import create_engine

from services.api.schema import metadata

url = os.environ.get("SPECGUARD_DATABASE_URL", context.config.get_main_option("sqlalchemy.url"))
if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
