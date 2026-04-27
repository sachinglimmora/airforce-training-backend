import abc
from dataclasses import dataclass


@dataclass
class ParsedSection:
    section_number: str
    title: str
    content_markdown: str
    page_number: int | None = None
    children: list["ParsedSection"] = None
    ordinal: int = 0

    def __post_init__(self):
        if self.children is None:
            self.children = []


class BaseParser(abc.ABC):
    @abc.abstractmethod
    def parse(self, file_bytes: bytes) -> list[ParsedSection]:
        """Parse the document and return a list of root sections."""
        pass
