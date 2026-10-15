from pydantic import BaseModel, ConfigDict, Field


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    document_id: str
    source_path: str
    title: str
    section_id: str
    section_path: str
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=2000)
    content_hash: str

    def embedding_text(self) -> str:
        return f"{self.title}\n{self.section_path}\n\n{self.content}"


class SearchResult(BaseModel):
    chunk: Chunk
    distance: float = Field(allow_inf_nan=False)
