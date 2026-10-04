import datetime
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-02-570bfbc4645a"

def seed_data():
    db = firestore.Client(project=PROJECT_ID)
    runs_ref = db.collection("run_logs")
    
    sample_runs = [
        {
            "id": "run_001",
            "date": "2026-09-28",
            "distance_km": 5.0,
            "duration_minutes": 27,
            "average_pace": "5:24 min/km",
            "performance_score": 88,
            "pre_run_mood": "Stressed from work",
            "post_run_mood": "Refreshed & Energized",
            "energy_level": 7,
            "skip_reason": None,
            "notes": "Evening run around the neighborhood park. Felt much clearer afterwards.",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        },
        {
            "id": "run_002",
            "date": "2026-09-30",
            "distance_km": 8.5,
            "duration_minutes": 46,
            "average_pace": "5:25 min/km",
            "performance_score": 92,
            "pre_run_mood": "Motivated",
            "post_run_mood": "Strong & Accomplished",
            "energy_level": 9,
            "skip_reason": None,
            "notes": "Tempo run along the waterfront. Maintained steady breathing.",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        },
        {
            "id": "run_003",
            "date": "2026-10-02",
            "distance_km": 0.0,
            "duration_minutes": 0,
            "average_pace": "N/A",
            "performance_score": 40,
            "pre_run_mood": "Exhausted after long meeting",
            "post_run_mood": "Guilty for skipping",
            "energy_level": 3,
            "skip_reason": "Late night work deadline & rain",
            "notes": "Skipped scheduled 5K. Need to plan shorter indoor alternative when busy.",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        },
        {
            "id": "run_004",
            "date": "2026-10-03",
            "distance_km": 3.2,
            "duration_minutes": 16,
            "average_pace": "5:00 min/km",
            "performance_score": 85,
            "pre_run_mood": "Short on time, low motivation",
            "post_run_mood": "Glad I moved!",
            "energy_level": 6,
            "skip_reason": None,
            "notes": "Quick 15-minute intervals before dinner to break up sedentary day.",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
    ]
    
    for run in sample_runs:
        doc_id = run["id"]
        runs_ref.document(doc_id).set(run)
        print(f"Seeded document: {doc_id}")

    print("Firestore seed completed successfully!")

if __name__ == "__main__":
    seed_data()
