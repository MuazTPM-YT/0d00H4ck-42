from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


# business dates follow mill time, not the server's timezone
def mill_today() -> date:
    return datetime.now(IST).date()
