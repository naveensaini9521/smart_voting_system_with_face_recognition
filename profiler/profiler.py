import cProfile
import pstats
from smart_app.backend.run import app

def profile_dashboard():
    with app.test_client() as client:
        client.get("/api/dashboard")

def profile_login():
    with app.test_client() as client:
        client.post(
            "/api/auth/login",
            json={
                "voter_id": "564046DD",
                "password": "Naveen@123"
            }
        )

profile_func = profile_login
# profile_func = profile_dashboard

profiler = cProfile.Profile()

profiler.enable()
profile_func()
profiler.disable()

stats = pstats.Stats(profiler)
stats.sort_stats("cumulative")
stats.print_stats(50)