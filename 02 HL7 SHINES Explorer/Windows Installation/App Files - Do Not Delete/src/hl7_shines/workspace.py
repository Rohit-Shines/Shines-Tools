from __future__ import annotations

from dataclasses import dataclass, field
import uuid

from .models import HL7Message


@dataclass
class Workspace:
    title: str
    messages: list[HL7Message] = field(default_factory=list)
    draft: str = ""
    source_path: str = ""
    selected_index: int = 0
    message_filter: str = ""
    dirty: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def selected_message(self) -> HL7Message | None:
        if not self.messages:
            return None
        self.selected_index = min(max(self.selected_index, 0), len(self.messages) - 1)
        return self.messages[self.selected_index]

    def searchable_text(self) -> str:
        values = [self.title, self.source_path, self.draft[:1000]]
        for message in self.messages[:20]:
            values.extend(message.metadata().values())
            values.append(message.message_type)
        return " ".join(values).casefold()

    def clone(self, title: str | None = None) -> "Workspace":
        # Messages are reparsed by the controller when deep-copy semantics are needed.
        return Workspace(
            title=title or f"{self.title} Copy",
            messages=list(self.messages),
            draft=self.draft,
            source_path=self.source_path,
            selected_index=self.selected_index,
            message_filter=self.message_filter,
            dirty=self.dirty,
        )
