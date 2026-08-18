from django.http import JsonResponse


def health_check(request):
    """Simple liveness endpoint: confirms the API + DB connection are up."""
    from django.db import connection

    db_ok = True
    try:
        connection.ensure_connection()
    except Exception:
        db_ok = False

    return JsonResponse(
        {
            "status": "ok",
            "service": "prayer-app-backend",
            "database": "connected" if db_ok else "unreachable",
        }
    )
