from .models import CustomerAuthToken


def get_token_from_header(request):
    auth_header = request.headers.get("Authorization", "").strip()
    if not auth_header:
        return None
    if auth_header.lower().startswith("token "):
        return auth_header.split(" ", 1)[1].strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None


def get_authenticated_user(request):
    token = get_token_from_header(request)
    if not token:
        return None
    auth = CustomerAuthToken.objects.select_related("user").filter(token=token).first()
    if not auth:
        return None
    return auth.user
