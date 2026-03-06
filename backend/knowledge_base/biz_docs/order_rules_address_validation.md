title: Order Rules - Address Validation
tags: order, rules, validation
policy_type: ORDER
content:
- Minimum order is one cylinder per request.
- Maximum standard order is four cylinders.
- Address must pass service area validation.
- Duplicate orders within 30 minutes are flagged.
- Large orders require manual approval.
- Customer contact must be verified for bulk orders.
exceptions:
- VIP customers may exceed limits with approval.
- Emergency orders can bypass limits.
- Corporate contracts use custom limits.
source: Internal Ops Policy v1
