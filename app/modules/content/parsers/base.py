import abc
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class ParsedSection:
    section_number: str
    title: str
    content_markdown: str
    page_number: Optional[int] = None
    children: List["ParsedSection"] = None
    ordinal: int = 0

    def __post_init__(self):
        if self.children is None:
            self.children = []

class BaseParser(abc.ABC):
    @abc.abstractmethod
    def parse(self, file_bytes: bytes) -> List[ParsedSection]:
        """Parse the document and return a list of root sections."""
        pass
