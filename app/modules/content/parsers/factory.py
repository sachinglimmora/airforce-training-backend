from typing import Type
from app.modules.content.parsers.base import BaseParser

class ParserFactory:
    _parsers = {}

    @classmethod
    def register(cls, source_type: str, parser_cls: Type[BaseParser]):
        cls._parsers[source_type] = parser_cls

    @classmethod
    def get_parser(cls, source_type: str) -> BaseParser:
        parser_cls = cls._parsers.get(source_type)
        if not parser_cls:
            # Fallback to a generic parser or raise error
            raise ValueError(f"No parser registered for source type: {source_type}")
        return parser_cls()

# Generic parser for testing/fallback
class GenericParser(BaseParser):
    def parse(self, file_bytes: bytes) -> list:
        from app.modules.content.parsers.base import ParsedSection
        # Mock parsing: extract some text and create sections
        # In real life, this would use pypdf or an LLM
        text = file_bytes.decode("utf-8", errors="ignore")
        return [
            ParsedSection(
                section_number="1",
                title="Introduction",
                content_markdown=text[:1000],
                ordinal=1
            )
        ]

ParserFactory.register("fcom", GenericParser)
ParserFactory.register("qrh", GenericParser)
ParserFactory.register("amm", GenericParser)
ParserFactory.register("sop", GenericParser)
ParserFactory.register("syllabus", GenericParser)
