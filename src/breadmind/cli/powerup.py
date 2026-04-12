"""Interactive Lessons (/powerup) — teach BreadMind features.

Each lesson has steps with descriptions and optional demo commands
that users can follow along with.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LessonStep:
    title: str
    description: str
    demo_command: str = ""  # Command to demonstrate
    expected_output: str = ""  # What the user should see


@dataclass
class Lesson:
    id: str
    title: str
    category: str  # "basics", "tools", "memory", "advanced"
    steps: list[LessonStep] = field(default_factory=list)
    estimated_minutes: int = 5


class PowerUpManager:
    """Interactive lessons teaching BreadMind features.

    Each lesson has steps with descriptions and optional demo commands.
    """

    def __init__(self) -> None:
        self._lessons: list[Lesson] = []
        self._completed: set[str] = set()
        self._init_lessons()

    def _init_lessons(self) -> None:
        """Initialize built-in lessons."""
        self._lessons = [
            Lesson(
                id="basics-chat",
                title="Your First Conversation",
                category="basics",
                estimated_minutes=3,
                steps=[
                    LessonStep(
                        title="Start a chat",
                        description="Learn how to start a conversation with BreadMind.",
                        demo_command="breadmind chat",
                        expected_output="Chat session started",
                    ),
                    LessonStep(
                        title="Ask a question",
                        description="Type a natural language question and see the response.",
                    ),
                ],
            ),
            Lesson(
                id="basics-tools",
                title="Using Built-in Tools",
                category="basics",
                estimated_minutes=5,
                steps=[
                    LessonStep(
                        title="List available tools",
                        description="See all the tools BreadMind can use.",
                        demo_command="breadmind tools list",
                    ),
                    LessonStep(
                        title="Run a shell command",
                        description="Ask BreadMind to run a command for you.",
                        demo_command='breadmind chat "list files in current directory"',
                    ),
                ],
            ),
            Lesson(
                id="memory-basics",
                title="Memory System",
                category="memory",
                estimated_minutes=5,
                steps=[
                    LessonStep(
                        title="Working memory",
                        description="Learn about session context that persists within a conversation.",
                    ),
                    LessonStep(
                        title="Episodic memory",
                        description="Understand how past interactions are stored and recalled.",
                    ),
                ],
            ),
            Lesson(
                id="tools-mcp",
                title="MCP Tool Integration",
                category="tools",
                estimated_minutes=10,
                steps=[
                    LessonStep(
                        title="What is MCP?",
                        description="Model Context Protocol allows connecting external tools.",
                    ),
                    LessonStep(
                        title="Add an MCP server",
                        description="Configure BreadMind to use an MCP tool server.",
                        demo_command="breadmind mcp add",
                    ),
                ],
            ),
            Lesson(
                id="advanced-plugins",
                title="Plugin Development",
                category="advanced",
                estimated_minutes=15,
                steps=[
                    LessonStep(
                        title="Plugin structure",
                        description="Learn how BreadMind plugins are organised.",
                    ),
                    LessonStep(
                        title="Create a plugin",
                        description="Scaffold and build your first plugin.",
                        demo_command="breadmind plugin create my-plugin",
                    ),
                ],
            ),
            Lesson(
                id="advanced-streaming",
                title="Streaming Responses",
                category="advanced",
                estimated_minutes=5,
                steps=[
                    LessonStep(
                        title="Enable streaming",
                        description="Configure real-time streaming output.",
                    ),
                ],
            ),
        ]

    def list_lessons(self, category: str | None = None) -> list[Lesson]:
        if category is None:
            return list(self._lessons)
        return [lesson for lesson in self._lessons if lesson.category == category]

    def get_lesson(self, lesson_id: str) -> Lesson | None:
        for lesson in self._lessons:
            if lesson.id == lesson_id:
                return lesson
        return None

    def mark_complete(self, lesson_id: str) -> None:
        self._completed.add(lesson_id)

    def get_progress(self) -> dict:
        """Return completion stats."""
        total = len(self._lessons)
        completed = len(self._completed & {lesson.id for lesson in self._lessons})
        return {
            "total": total,
            "completed": completed,
            "remaining": total - completed,
            "percent": round(completed / total * 100, 1) if total else 0.0,
        }

    def get_next_recommended(self) -> Lesson | None:
        """Get the next recommended lesson based on progress."""
        for lesson in self._lessons:
            if lesson.id not in self._completed:
                return lesson
        return None

    def render_step(self, step: LessonStep) -> str:
        """Render a lesson step as formatted text."""
        lines = [f"## {step.title}", "", step.description]
        if step.demo_command:
            lines.extend(["", f"  $ {step.demo_command}"])
        if step.expected_output:
            lines.extend(["", f"  Expected: {step.expected_output}"])
        return "\n".join(lines)
