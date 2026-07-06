from app.models import Briefing, Task, User


async def test_models_create(session_factory):
    async with session_factory() as session:
        user = User(email="a@test.com", hashed_password="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        task = Task(user_id=user.id, title="테스트 할일")
        session.add(task)
        await session.commit()
        await session.refresh(task)

        assert task.priority == "mid"
        assert task.status == "todo"
        assert task.created_at is not None

        briefing = Briefing(
            user_id=user.id, kind="daily",
            content={"summary": "s", "suggestions": [], "urgent_count": 0},
            tasks_fingerprint="abc",
        )
        session.add(briefing)
        await session.commit()
        await session.refresh(briefing)
        assert briefing.content["summary"] == "s"
