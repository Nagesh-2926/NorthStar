from backend.tests.conftest import login, register, create_enrollment, ingest_model_sources
from backend.app.llm.http_provider import JsonHttpProvider
from backend.app.llm.gemini_provider import GeminiProvider
from backend.app.llm.factory import build_provider
from backend.app.core.config import Settings
from backend.app.llm.service import StudyPlanService
from backend.app.schemas.llm import StudySupportContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_records_interventions_and_student_isolation(client):
    student_user = register(client, "records.student@example.com")
    coord_user = register(client, "records.coord@example.com", "coordinator", "test-coordinator-invite")
    student = login(client, student_user["email"])
    coordinator = login(client, coord_user["email"])
    profile = client.get("/api/students/me", headers=student).json()
    enrollment = create_enrollment(client, coordinator, profile["id"])
    schedule_path = f"/api/enrollments/{enrollment['id']}/assessment-schedule"
    schedule_write = client.put(schedule_path, headers=coordinator, json={"assessments":[
        {"assessment_key":"a1","scheduled_day":30,"weight":50.0}]})
    assert schedule_write.status_code == 200 and schedule_write.json()["assessment_count"] == 1
    schedule_read = client.get(schedule_path, headers=coordinator)
    assert schedule_read.status_code == 200 and schedule_read.json()[0]["assessment_key"] == "a1"
    assert client.get(schedule_path, headers=student).status_code == 403
    assert client.get("/api/enrollments/00000000-0000-0000-0000-000000000000/assessment-schedule",
                      headers=coordinator).status_code == 404
    score = client.post(f"/api/students/{profile['id']}/performance?enrollment_id={enrollment['id']}",
        headers=coordinator, json={"record_type":"module_score","score":82,
        "details":{"assessment":"early test"}})
    assert score.status_code == 201
    assert len(client.get(f"/api/students/{profile['id']}/performance", headers=student).json()) == 1
    invalid = client.post(f"/api/students/{profile['id']}/performance?enrollment_id={enrollment['id']}",
        headers=coordinator, json={"record_type":"module_score","score":101})
    assert invalid.status_code == 422
    malformed_assessment = client.post(
        f"/api/students/{profile['id']}/performance?enrollment_id={enrollment['id']}",
        headers=coordinator, json={"record_type":"assessment_score","score":82})
    assert malformed_assessment.status_code == 422
    assessment = client.post(f"/api/students/{profile['id']}/performance?enrollment_id={enrollment['id']}",
        headers=coordinator, json={"record_type":"assessment_score","score":82,
            "assessment_key":"a1","submitted_day":20})
    assert assessment.status_code == 201
    duplicate = client.post(f"/api/students/{profile['id']}/performance?enrollment_id={enrollment['id']}",
        headers=coordinator, json={"record_type":"assessment_score","score":90,
            "assessment_key":"a1","submitted_day":22})
    assert duplicate.status_code == 409
    engagement = client.post(f"/api/students/{profile['id']}/engagement?enrollment_id={enrollment['id']}",
        headers=coordinator, json={"week_index":0,"clicks":12,"active_days":2,
            "active_site_ids":[11],"activity_types":["forum"]})
    assert engagement.status_code == 201
    intervention = client.post("/api/interventions", headers=coordinator, json={
        "enrollment_id":enrollment["id"],"title":"Offer a check-in","notes":"Discuss course questions."})
    assert intervention.status_code == 201
    assert len(client.get("/api/interventions", headers=student).json()) == 1
    changed = client.put(f"/api/interventions/{intervention.json()['id']}", headers=coordinator,
        json={"status":"completed"})
    assert changed.status_code == 200 and changed.json()["status"] == "completed"
    assert client.get("/api/analytics/overview", headers=student).status_code == 403
    assert client.get("/api/analytics/overview", headers=coordinator).status_code == 200


def test_engagement_week_upsert_and_database_conflict_response(client, monkeypatch):
    student_user = register(client, "engagement-upsert.student@example.com")
    coordinator_user = register(client, "engagement-upsert.coord@example.com", "coordinator",
                                 "test-coordinator-invite")
    student = login(client, student_user["email"])
    coordinator = login(client, coordinator_user["email"])
    profile = client.get("/api/students/me", headers=student).json()
    enrollment = create_enrollment(client, coordinator, profile["id"])
    path = f"/api/students/{profile['id']}/engagement?enrollment_id={enrollment['id']}"
    empty_dimensions = {"active_site_ids": [], "activity_types": []}

    first = client.post(path, headers=coordinator,
        json={**empty_dimensions, "week_index": 0, "clicks": 12, "active_days": 2})
    repeated = client.post(path, headers=coordinator,
        json={**empty_dimensions, "week_index": 0, "clicks": 18, "active_days": 3})
    assert first.status_code == 201
    assert repeated.status_code == 201
    records = client.get(path, headers=student).json()
    assert len(records) == 1
    assert records[0]["clicks"] == 18
    assert records[0]["active_days"] == 3

    def raise_unique_conflict(_session):
        raise IntegrityError("INSERT engagement_records", {}, Exception("unique week conflict"))

    monkeypatch.setattr(Session, "commit", raise_unique_conflict)
    conflict = client.post(path, headers=coordinator,
        json={**empty_dimensions, "week_index": 1, "clicks": 7, "active_days": 1})
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Engagement record conflicts with an existing week"


def test_llm_failure_and_unsafe_content_use_supportive_fallback():
    context = StudySupportContext(priority_band="review_for_support", active_weeks=1,
        assessment_count=0, recent_performance=[41.0])
    class Failed:
        def generate(self, *_args):
            raise TimeoutError("provider offline")
    class Unsafe:
        def generate(self, *_args):
            return '{"title":"Plan","actions":["Study now"],"motivational_message":"You will fail."}'
    class UnsafeGoal:
        def generate(self, *_args):
            return ('{"title":"Plan","priorities":["You will fail."],"actions":["Study now"],'
                    '"schedule":[],"goals":["Study"],"motivational_message":"You have support."}')
    for provider in (Failed(), Unsafe(), UnsafeGoal()):
        content, used = StudyPlanService(provider).create(context)
        assert used is False
        assert "fail" not in content.motivational_message.lower()
        assert content.actions


def test_provider_adapter_uses_generic_json_http_contract(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"content":"{\"title\":\"Plan\"}"}

    class Client:
        def __init__(self, timeout):
            captured["timeout"] = timeout
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def post(self, endpoint, headers, json):
            captured.update(endpoint=endpoint, headers=headers, json=json)
            return Response()

    monkeypatch.setattr("backend.app.llm.http_provider.httpx.Client", Client)
    provider = JsonHttpProvider("https://llm.example/api", "server-only-key", timeout=9)
    assert provider.generate("system", "prompt") == '{"title":"Plan"}'
    assert captured["timeout"] == 9
    assert captured["endpoint"] == "https://llm.example/api"
    assert captured["headers"]["Authorization"] == "Bearer server-only-key"
    assert captured["json"] == {"system_prompt":"system", "user_prompt":"prompt",
        "response_format":"json"}


def test_gemini_adapter_uses_server_key_structured_json_and_parses_candidate(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"title":"Plan"}'}]}}]}

    def post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("backend.app.llm.gemini_provider.httpx.post", post)
    provider = GeminiProvider("server-only-key", "gemini-3.8-flash", timeout=7)
    assert provider.generate("support-only system", "pseudonymous context") == '{"title":"Plan"}'
    assert captured["url"].endswith("/gemini-3.8-flash:generateContent")
    assert captured["headers"] == {"x-goog-api-key": "server-only-key"}
    assert captured["timeout"] == 7
    assert captured["json"]["systemInstruction"]["parts"][0]["text"] == "support-only system"
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_provider_without_key_uses_fallback():
    settings = Settings(_env_file=None, database_url="sqlite://",
        jwt_secret_key="test-only-signing-key-64-bytes-minimum-not-production",
        llm_provider="gemini", gemini_api_key=None)
    assert build_provider(settings) is None


def test_study_plan_uses_persisted_prediction_and_local_fallback(client):
    student_user = register(client, "plan.student@example.com")
    coordinator_user = register(client, "plan.coord@example.com", "coordinator", "test-coordinator-invite")
    student = login(client, student_user["email"])
    coordinator = login(client, coordinator_user["email"])
    profile = client.get("/api/students/me", headers=student).json()
    enrollment = create_enrollment(client, coordinator, profile["id"])
    ingest_model_sources(client, coordinator, profile["id"], enrollment["id"])
    prediction = client.post(f"/api/predictions/{profile['id']}", headers=coordinator,
        json={"enrollment_id": enrollment["id"]})
    assert prediction.status_code == 201
    overview = client.get("/api/analytics/overview", headers=coordinator)
    assert overview.status_code == 200 and overview.json()["predictions"] == 1
    analytics = overview.json()
    assert analytics["recorded_score_count"] == 3
    assert analytics["mean_recorded_score"] == 81.0
    assert analytics["performance_distribution"]["80-100"] == 2
    assert analytics["performance_distribution"]["60-79"] == 1
    assert analytics["outcome_forecast_distribution"]["not_generated"] == 1
    assert client.get("/api/analytics/risk-trends?days=14", headers=coordinator).status_code == 200
    assert client.get("/api/analytics/engagement", headers=coordinator).status_code == 200
    result = client.post(f"/api/students/{profile['id']}/study-plan", headers=student,
        json={"enrollment_id":enrollment["id"]})
    assert result.status_code == 201, result.text
    assert result.json()["generated_by_llm"] is False
    assert result.json()["motivational_message"]["source"] == "fallback"
    plan = result.json()["study_plan"]
    assert plan["content"]["priorities"]
    assert plan["content"]["schedule"]
    assert plan["content"]["goals"]
    assert plan["content"]["completed_goal_indices"] == []


def test_study_plan_progress_and_grounded_assistant_are_student_owned(client):
    student_a_user = register(client, "assistant.a@example.com")
    student_b_user = register(client, "assistant.b@example.com")
    coordinator_user = register(client, "assistant.coord@example.com", "coordinator",
                                 "test-coordinator-invite")
    student_a = login(client, student_a_user["email"])
    student_b = login(client, student_b_user["email"])
    coordinator = login(client, coordinator_user["email"])
    profile_a = client.get("/api/students/me", headers=student_a).json()
    profile_b = client.get("/api/students/me", headers=student_b).json()
    enrollment_a = create_enrollment(client, coordinator, profile_a["id"])
    enrollment_b = create_enrollment(client, coordinator, profile_b["id"])
    ingest_model_sources(client, coordinator, profile_a["id"], enrollment_a["id"])
    score_b = client.post(
        f"/api/students/{profile_b['id']}/performance?enrollment_id={enrollment_b['id']}",
        headers=coordinator,
        json={"record_type": "module_score", "score": 13},
    )
    assert score_b.status_code == 201
    prediction = client.post(f"/api/predictions/{profile_a['id']}", headers=coordinator,
        json={"enrollment_id": enrollment_a["id"]})
    assert prediction.status_code == 201

    plan_result = client.post(f"/api/students/{profile_a['id']}/study-plan",
        headers=student_a, json={"enrollment_id": enrollment_a["id"]})
    assert plan_result.status_code == 201, plan_result.text
    plan = plan_result.json()["study_plan"]
    assert len(plan["content"]["goals"]) >= 1
    first_goal = client.put(
        f"/api/students/{profile_a['id']}/study-plan/{plan['id']}/progress",
        headers=student_a,
        json={"completed_goal_indices": [0]},
    )
    assert first_goal.status_code == 200, first_goal.text
    assert first_goal.json()["content"]["completed_goal_indices"] == [0]

    forbidden_progress = client.put(
        f"/api/students/{profile_a['id']}/study-plan/{plan['id']}/progress",
        headers=student_b,
        json={"completed_goal_indices": [0]},
    )
    assert forbidden_progress.status_code == 404
    invalid_goal = client.put(
        f"/api/students/{profile_a['id']}/study-plan/{plan['id']}/progress",
        headers=student_a,
        json={"completed_goal_indices": [999]},
    )
    assert invalid_goal.status_code == 422

    intervention = client.post("/api/interventions", headers=coordinator, json={
        "enrollment_id": enrollment_a["id"],
        "title": "PRIVATE_INTERVENTION_TITLE_SENTINEL",
        "notes": "PRIVATE_INTERVENTION_NOTE_SENTINEL",
    })
    assert intervention.status_code == 201, intervention.text

    captured = {}

    class Grounded:
        def generate(self, system_prompt, user_prompt):
            captured.update(system_prompt=system_prompt, user_prompt=user_prompt)
            return '{"answer":"Your recorded early assessment scores include 82 and 62."}'

    client.app.state.study_plan_service = StudyPlanService(Grounded())
    answer = client.post("/api/students/me/support-assistant", headers=student_a,
        json={"enrollment_id": enrollment_a["id"], "question": "What scores are recorded?"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["source"] == "llm"
    assert "82 and 62" in answer.json()["answer"]
    assert "supplied student's stored records" in captured["system_prompt"].lower()
    assert '"score":82' in captured["user_prompt"]
    assert '"score":13' not in captured["user_prompt"]
    assert "PRIVATE_INTERVENTION_TITLE_SENTINEL" not in captured["user_prompt"]
    assert "PRIVATE_INTERVENTION_NOTE_SENTINEL" not in captured["user_prompt"]
    assert profile_b["id"] not in captured["user_prompt"]

    cross_student_question = client.post("/api/students/me/support-assistant",
        headers=student_b,
        json={"enrollment_id": enrollment_a["id"], "question": "What scores are recorded?"})
    assert cross_student_question.status_code == 404
    coordinator_question = client.post("/api/students/me/support-assistant",
        headers=coordinator,
        json={"enrollment_id": enrollment_a["id"], "question": "What scores are recorded?"})
    assert coordinator_question.status_code == 403


def test_student_assistant_reports_unavailable_when_no_provider_is_configured(client):
    student_user = register(client, "assistant.offline@example.com")
    coordinator_user = register(client, "assistant.offline.coord@example.com",
                                 "coordinator", "test-coordinator-invite")
    student = login(client, student_user["email"])
    coordinator = login(client, coordinator_user["email"])
    profile = client.get("/api/students/me", headers=student).json()
    enrollment = create_enrollment(client, coordinator, profile["id"])
    ingest_model_sources(client, coordinator, profile["id"], enrollment["id"])
    prediction = client.post(f"/api/predictions/{profile['id']}", headers=coordinator,
        json={"enrollment_id": enrollment["id"]})
    assert prediction.status_code == 201

    response = client.post("/api/students/me/support-assistant",
        headers=student,
        json={"enrollment_id": enrollment["id"], "question": "What should I work on?"})

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]
