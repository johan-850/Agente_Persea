from pydantic import BaseModel, Field


class ReporteEntrada(BaseModel):
    texto: str
    remitente: str


class Persona(BaseModel):
    nombre: str


class Insumo(BaseModel):
    producto: str
    cantidad: float | None = None
    unidad: str | None = None


class ReporteExtraido(BaseModel):
    lote: str | None = None
    tipo_labor: str | None = None
    supervisor: str | None = None
    personas: list[str] = Field(default_factory=list)
    cantidad_personas: int | None = None
    insumos: list[Insumo] = Field(default_factory=list)
    canecas: float | None = None
    litros_totales: float | None = None
    lanzas: int | None = None
    hora_inicio: str | None = None
    hora_fin: str | None = None
    nota: str | None = None
    es_alerta: bool = False
    tipo_alerta: str | None = None
    prioridad: str | None = None
