"""Validación de video: extensión, MIME type y tamaño."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from app.config import settings


class VideoValidationError(ValueError):
    """El video no cumple las reglas de la API."""

    def __init__(self, message: str, *, field: str = "video") -> None:
        super().__init__(message)
        self.message = message
        self.field = field


#: Firmas binarias conocidas -> MIME. Se usa para no confiar sólo en el
#: `Content-Type` que envía el cliente.
_MAGIC_SIGNATURES: tuple[tuple[int, bytes, str], ...] = (
    (4, b"ftyp", "video/mp4"),  # ISO-BMFF: mp4 / mov / m4v
    (0, b"\x1a\x45\xdf\xa3", "video/webm"),  # Matroska / WebM
)

_ISO_BRAND_MIME = {
    b"qt  ": "video/quicktime",
    b"moov": "video/quicktime",
}


def sniff_content_type(header: bytes) -> str | None:
    """Detecta el MIME type a partir de los primeros bytes del fichero."""
    for offset, signature, mime in _MAGIC_SIGNATURES:
        if header[offset : offset + len(signature)] == signature:
            if mime == "video/mp4":
                brand = header[8:12]
                return _ISO_BRAND_MIME.get(brand, "video/mp4")
            return mime
    return None


def normalize_extension(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


@dataclass(slots=True)
class ValidatedVideo:
    filename: str
    content_type: str
    extension: str


def validate_filename(filename: str | None) -> str:
    """Sanea el nombre de fichero: sin rutas, no vacío."""
    if not filename:
        raise VideoValidationError("El fichero debe tener nombre", field="file")
    # Acepta separadores POSIX y Windows: el cliente puede ser cualquiera.
    safe = PureWindowsPath(PurePosixPath(filename).name).name.strip().replace("\x00", "")
    if not safe or safe in {".", ".."}:
        raise VideoValidationError("Nombre de fichero inválido", field="file")
    return safe[:255]


def validate_video(
    *,
    filename: str | None,
    declared_content_type: str | None,
    header_bytes: bytes | None = None,
    size_bytes: int | None = None,
) -> ValidatedVideo:
    """Valida extensión, MIME y tamaño. Lanza `VideoValidationError`."""
    safe_name = validate_filename(filename)
    extension = normalize_extension(safe_name)

    if extension not in settings.allowed_extensions:
        raise VideoValidationError(
            f"Extensión '{extension or 'sin extensión'}' no permitida. "
            f"Permitidas: {', '.join(sorted(settings.allowed_extensions))}",
            field="file",
        )

    sniffed = sniff_content_type(header_bytes) if header_bytes else None
    declared = (declared_content_type or "").split(";")[0].strip().lower()
    guessed = (mimetypes.guess_type(safe_name)[0] or "").lower()

    # Preferimos lo detectado en los bytes; si no, lo declarado; si no, la extensión.
    content_type = sniffed or declared or guessed
    if not content_type:
        raise VideoValidationError("No se pudo determinar el MIME type del video")

    if content_type not in settings.allowed_mime_types:
        raise VideoValidationError(
            f"MIME type '{content_type}' no permitido. "
            f"Permitidos: {', '.join(sorted(settings.allowed_mime_types))}"
        )

    if header_bytes and sniffed is None:
        raise VideoValidationError(
            "El contenido del fichero no parece un video (mp4/mov/webm)", field="file"
        )

    if size_bytes is not None:
        if size_bytes <= 0:
            raise VideoValidationError("El video está vacío", field="file")
        if size_bytes > settings.max_video_size_bytes:
            raise VideoValidationError(
                f"El video pesa {size_bytes / 1024 / 1024:.1f} MB y el máximo "
                f"es {settings.max_video_size_mb} MB"
            )

    return ValidatedVideo(filename=safe_name, content_type=content_type, extension=extension)
