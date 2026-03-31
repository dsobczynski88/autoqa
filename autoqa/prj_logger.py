import sys
import time
import logging
from autoqa.prj_exception import CustomException

def timing(loggername):
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(loggername)
            start_time = time.perf_counter()
            logger.debug(f"Entering: {func.__name__}")
            output = func(*args, **kwargs)
            logger.debug(f"Exiting: {func.__name__}")
            end_time = time.perf_counter()
            elapsed_time = end_time - start_time
            logger.debug(f"{func.__name__} completed in {elapsed_time:.6f} seconds")
            return output
        return wrapper
    return decorator

def get_logs(loggername):        
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(loggername)
            start_time = time.perf_counter()
            logger.debug(f"Entering: {func.__name__}")
            try:
                output = func(*args, **kwargs)
            except Exception as e:
                ce = CustomException(e)
                logger = logging.getLogger(loggername)                
                logger.debug(ce.error_message)
                output = None
            finally:
                #logger.debug(f"Exiting: {func.__name__}")
                end_time = time.perf_counter()
                elapsed_time = end_time - start_time
                logger.debug(f"{func.__name__} completed in {elapsed_time:.6f} seconds")
                try:
                    return output
                except Exception as e:
                    logger.debug(f"The following error occurred: {e}")
                    return None
        return wrapper
    return decorator

class ProjectLogger:
    def __init__(self, name, log_file):
        self._name = name
        self._log_file = log_file
        self._logger = logging.getLogger(self._name)
        self._logger.setLevel(logging.DEBUG)

    @property
    def name(self):
        return self._name

    @property
    def log_file(self):
        return self._log_file

    @name.setter
    def name(self, new_name):
        self._name = new_name

    @log_file.setter
    def log_file(self, new_log_file):
        self._log_file = new_log_file

    def config(self):
        # create handlers
        file_handler = logging.FileHandler(self._log_file)
        console_handler = logging.StreamHandler(sys.stdout)

        # set logging levels
        file_handler.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)

        # create formatters and add to handlers
        file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_format = logging.Formatter('%(name)s - %(levelname)s - %(message)s')

        file_handler.setFormatter(file_format)
        console_handler.setFormatter(console_format)

        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)
        return self

    def get_logger(self):
        return self._logger