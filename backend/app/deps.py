"""Application dependency container (singletons wired at startup)."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, get_settings
from .core.job_manager import JobManager
from .core.model_registry import ModelRegistry
from .core.progress_manager import ProgressManager
from .database.db import Database
from .database.repositories import GenerationRepository, ModelRepository, SettingsRepository
from .engines.engine_manager import EngineManager
from .services.ffmpeg import FFmpegService
from .services.generation_service import GenerationService
from .services.model_installation import ModelInstallationService
from .services.thumbnail_service import ThumbnailService
from .services.video_assembly import VideoAssemblyService


@dataclass
class Container:
    settings: Settings
    db: Database
    generations: GenerationRepository
    models_repo: ModelRepository
    settings_repo: SettingsRepository
    registry: ModelRegistry
    progress: ProgressManager
    engines: EngineManager
    ffmpeg: FFmpegService
    assembly: VideoAssemblyService
    thumbnails: ThumbnailService
    generation_service: GenerationService
    installer: ModelInstallationService
    jobs: JobManager


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    settings.ensure_directories()

    db = Database(settings.data_dir / "nova.db")
    db.initialize()

    generations = GenerationRepository(db)
    models_repo = ModelRepository(db)
    settings_repo = SettingsRepository(db)

    registry = ModelRegistry(settings)
    progress = ProgressManager()
    engines = EngineManager(settings)
    ffmpeg = FFmpegService(settings)
    assembly = VideoAssemblyService(ffmpeg)
    thumbnails = ThumbnailService(ffmpeg)

    generation_service = GenerationService(
        settings=settings, engine_manager=engines, registry=registry,
        generations=generations, models_repo=models_repo, settings_repo=settings_repo,
        ffmpeg=ffmpeg, assembly=assembly, thumbnails=thumbnails, progress=progress,
    )
    installer = ModelInstallationService(settings, registry, models_repo, progress)
    jobs = JobManager(settings, generations, generation_service, progress)

    return Container(
        settings=settings, db=db, generations=generations, models_repo=models_repo,
        settings_repo=settings_repo, registry=registry, progress=progress, engines=engines,
        ffmpeg=ffmpeg, assembly=assembly, thumbnails=thumbnails,
        generation_service=generation_service, installer=installer, jobs=jobs,
    )
