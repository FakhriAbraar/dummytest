import logging
import sys

from loguru import logger

from app.settings import settings


class InterceptHandler(logging.Handler):

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


def configure_logging() -> None:  # pragma: no cover
    intercept_handler = InterceptHandler()

    logging.basicConfig(handlers=[intercept_handler], level=logging.NOTSET)

    for logger_name in logging.root.manager.loggerDict:
        if logger_name.startswith("uvicorn."):
            logging.getLogger(logger_name).handlers = []

    logging.getLogger("uvicorn").handlers = [intercept_handler]
    logging.getLogger("uvicorn.access").handlers = [intercept_handler]

    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level.value,
    )
