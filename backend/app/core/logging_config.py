import logging

def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True
    )