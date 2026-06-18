"""Crash logging: the global exception hook for uncaught, fatal errors.

Application-wide logging configuration (level, handlers, log file) will join this
module later, when it is lifted out of SteempegApp during the controller split.
"""
import logging
import traceback
import logging
import os
from datetime import datetime


def global_exception_handler(exc_type, exc_value, exc_traceback):
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(f"CRITICAL FATAL CRASH:\n{error_msg}")
    try:
        logging.critical(f"UNCAUGHT FATAL ERROR:\n{error_msg}")
    except:  # noqa: E722  (last-ditch handler; never let logging failure mask the crash)
        pass
def setup_logging(logs_dir, version_str):
    """Configure file logging for a run and return the path of the created log file."""
    log_filename = os.path.join(logs_dir, f"steempeg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logging.basicConfig(
        filename=log_filename,
        level=logging.DEBUG,  # Everything here
        format='[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        encoding='utf-8',
    )
    logging.info("=" * 40)
    logging.info(f"STEEMPEG {version_str} RUNNING")
    logging.info("=" * 40)
    return log_filename