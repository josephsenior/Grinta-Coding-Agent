"""Expose file reader agent skills for runtime plugins."""

from backend.runtime.plugins.agent_skills.file_reader.file_readers import (
    parse_audio as parse_audio,
    parse_docx as parse_docx,
    parse_image as parse_image,
    parse_latex as parse_latex,
    parse_pdf as parse_pdf,
    parse_pptx as parse_pptx,
    parse_video as parse_video,
)
