import pytest
from breadmind.core.team_builder import TeamBuilder, TeamPlan, RoleAssessment
from breadmind.core.swarm import SwarmManager
from breadmind.core.performance import PerformanceTracker
from breadmind.core.skill_store import SkillStore


class TestRoleAssessment:
    def test_create(self):
        a = RoleAssessment(role="k8s_expert", relevance_score=0.9, success_rate=0.85, recommendation="use")
        assert a.recommendation == "use"


class TestTeamPlan:
    def test_create(self):
        plan = TeamPlan(goal="Check cluster health", selected_roles=["k8s_expert"],
            created_roles=[], skill_injections={}, reasoning="K8s expert is relevant")
        assert len(plan.selected_roles) == 1


class TestTeamBuilder:
    def _make_builder(self, llm_response=""):
        async def mock_handler(msg, user="", channel=""):
            return llm_response
        manager = SwarmManager()
        tracker = PerformanceTracker()
        skill_store = SkillStore()
        return TeamBuilder(swarm_manager=manager, tracker=tracker,
            skill_store=skill_store, message_handler=mock_handler)

    @pytest.mark.asyncio
    async def test_build_team_selects_existing_roles(self):
        llm_response = "ASSESS|k8s_expert|0.9|use\nASSESS|proxmox_expert|0.2|skip\nASSESS|general|0.5|use\nCREATE_NONE"
        builder = self._make_builder(llm_response)
        plan = await builder.build_team("Check Kubernetes pod health")
        assert "k8s_expert" in plan.selected_roles
        assert "proxmox_expert" not in plan.selected_roles

    @pytest.mark.asyncio
    async def test_build_team_creates_new_role(self):
        llm_response = ("ASSESS|k8s_expert|0.3|skip\nASSESS|general|0.4|skip\n"
            "CREATE|database_expert|Database and SQL optimization specialist|"
            "You are a database expert. Analyze query performance, index usage, and connection pools.|database,sql,query")
        builder = self._make_builder(llm_response)
        plan = await builder.build_team("Optimize database performance")
        assert "database_expert" in plan.created_roles
        roles = builder._swarm_manager.get_available_roles()
        role_names = [r["role"] for r in roles]
        assert "database_expert" in role_names

    @pytest.mark.asyncio
    async def test_max_3_created_roles(self):
        llm_response = ("ASSESS|general|0.1|skip\n"
            "CREATE|role1|d1|p1|k1\nCREATE|role2|d2|p2|k2\n"
            "CREATE|role3|d3|p3|k3\nCREATE|role4|d4|p4|k4\n")
        builder = self._make_builder(llm_response)
        plan = await builder.build_team("Complex multi-domain task")
        assert len(plan.created_roles) <= 3

    @pytest.mark.asyncio
    async def test_cooldown_returns_cached_plan(self):
        llm_response = "ASSESS|k8s_expert|0.9|use\nCREATE_NONE"
        builder = self._make_builder(llm_response)
        plan1 = await builder.build_team("Check pods")
        plan2 = await builder.build_team("Check pods")
        assert plan1.selected_roles == plan2.selected_roles

    @pytest.mark.asyncio
    async def test_skill_injections(self):
        llm_response = "ASSESS|k8s_expert|0.9|use\nCREATE_NONE"
        builder = self._make_builder(llm_response)
        await builder._skill_store.add_skill("pod_check", "Check pod health",
            "List all pods and check status", ["list pods", "check status"],
            ["pod", "health", "check"], "manual")
        plan = await builder.build_team("Check pod health")
        assert isinstance(plan.skill_injections, dict)
