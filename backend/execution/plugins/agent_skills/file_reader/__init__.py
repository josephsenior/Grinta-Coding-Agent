"""Expose file reader agent skills for runtime plugins."""

from backend.execution.plugins.agent_skills.file_reader.file_readers import (
    parse_audio as parse_audio,
)
from backend.execution.plugins.agent_skills.file_reader.file_readers import (
    parse_docx as parse_docx,
)
from backend.execution.plugins.agent_skills.file_reader.file_readers import (
    parse_image as parse_image,
)
from backend.execution.plugins.agent_skills.file_reader.file_readers import (
    parse_latex as parse_latex,
)
from backend.execution.plugins.agent_skills.file_reader.file_readers import (
    parse_pdf as parse_pdf,
)
from backend.execution.plugins.agent_skills.file_reader.file_readers import (
    parse_pptx as parse_pptx,
)
from backend.execution.plugins.agent_skills.file_reader.file_readers import (
    parse_video as parse_video,
)
