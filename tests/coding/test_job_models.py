"""job_models extraction — types must move out of job_tracker without behavior change."""
from __future__ import annotations


def test_job_models_module_exports_data_classes() -> None:
    from breadmind.coding import job_models
    assert hasattr(job_models, "JobStatus")
    assert hasattr(job_models, "PhaseStatus")
    assert hasattr(job_models, "PhaseInfo")
    assert hasattr(job_models, "JobInfo")
    # Sanity: enum values unchanged
    assert job_models.JobStatus.RUNNING.value == "running"
    assert job_models.PhaseStatus.COMPLETED.value == "completed"


def test_job_tracker_reexports_data_classes_for_backcompat() -> None:
    """Existing imports `from breadmind.coding.job_tracker import JobInfo` must still work."""
    from breadmind.coding.job_tracker import JobInfo, JobStatus, PhaseInfo, PhaseStatus
    from breadmind.coding import job_models
    assert JobInfo is job_models.JobInfo
    assert JobStatus is job_models.JobStatus
    assert PhaseInfo is job_models.PhaseInfo
    assert PhaseStatus is job_models.PhaseStatus


def test_jobinfo_to_dict_unchanged() -> None:
    from breadmind.coding.job_models import JobInfo, JobStatus
    j = JobInfo(
        job_id="x", project="p", agent="a", prompt="hi",
        status=JobStatus.PENDING, started_at=1000.0, user="u", channel="c",
    )
    d = j.to_dict()
    assert d["job_id"] == "x"
    assert d["user"] == "u"
    assert d["channel"] == "c"
    assert d["status"] == "pending"
