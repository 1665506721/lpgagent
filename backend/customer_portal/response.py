from rest_framework import status
from rest_framework.response import Response


def ok_response(data, status_code=status.HTTP_200_OK):
    return Response({"ok": True, "data": data, "error": None}, status=status_code)


def error_response(code, message, details=None, status_code=status.HTTP_400_BAD_REQUEST):
    if details is None:
        details = {}
    return Response(
        {"ok": False, "data": None, "error": {"code": code, "message": message, "details": details}},
        status=status_code,
    )
