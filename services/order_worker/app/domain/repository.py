"""订单写入仓储。"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.models import Order


def create_order_idempotent(
    session: Session,
    *,
    request_id: str,
    user_id: str,
    sku_id: str,
    created_at,
) -> bool:
    """幂等创建订单，返回是否新插入。"""

    order = Order(
        request_id=request_id,
        user_id=user_id,
        sku_id=sku_id,
        status="CREATED",
        created_at=created_at,
    )
    session.add(order)
    try:
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False
