"""
Contract-aligned application usecases.

CLI commands should call functions from here instead of legacy services.
"""

# Import modules to make them available at package level
# Note: Import order matters - plan_add must come before plan_show,
# and plan_show must come before plan_delete and plan_update
# because they have dependencies: plan_show -> plan_add, plan_delete -> (plan_add, plan_show)
from . import asset_attention  # noqa: I001
from . import asset_update  # noqa: I001
from . import channel_add  # noqa: I001
from . import channel_update  # noqa: I001
from . import channel_validate  # noqa: I001
from . import plan_add  # noqa: I001
from . import plan_list  # noqa: I001
from . import plan_show  # noqa: I001  # Depends on plan_add
from . import plan_delete  # noqa: I001  # Depends on plan_add and plan_show
from . import plan_update  # noqa: I001  # Depends on plan_add and plan_show
from . import channel_manager_launch  # noqa: I001