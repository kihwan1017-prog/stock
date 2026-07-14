from stock_platform.scheduler.registry import JobRegistry


def test_register_and_list_jobs() -> None:
    registry = JobRegistry()

    registry.register(
        name="sample",
        group="TEST",
        description="sample job",
        handler=lambda payload: payload,
    )

    job = registry.get("sample")

    assert job.name == "sample"
    assert job.group == "TEST"
    assert registry.list_jobs() == [job]
