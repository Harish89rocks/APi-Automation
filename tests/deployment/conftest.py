import os


def pytest_report_header(config):
    url = os.getenv("DEPLOYED_API_URL")
    if not url:
        return "deployment target: not configured (DEPLOYED_API_URL unset)"
    host = url.split("@")[-1]  # never print userinfo if someone embedded it
    return (
        f"deployment target: {host} "
        f"(env={os.getenv('DEPLOYED_API_ENV', 'unspecified')}, "
        f"writes={'on' if os.getenv('DEPLOYED_API_ALLOW_WRITES') else 'off'})"
    )
