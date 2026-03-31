'''
Define custom exception handling
'''

import sys
import traceback
import time
import logging
from pathlib import Path

def exception_logger(loggername):       
    def decorator(func):
        def wrapper(*args, **kwargs):          
            try:
                return func(*args, **kwargs)
            except Exception as e:
                ce = CustomException(e, sys)
                logger = logging.getLogger(loggername)               
                logger.debug(ce.error_message)
                #raise ce
                return None
        return wrapper
    return decorator

def parse_error_traceback(error_detail:sys):
    _,_,exc_tb=error_detail.exc_info()
    return exc_tb
    
def get_error_message(error, type, tb):    
    error_message=f"{type}:{error} occurred in {tb.name} (line {tb.lineno}) of {Path(tb.filename).name}"
    return error_message
 
class CustomException(Exception):
    
    def __init__(self, error):
        super().__init__(error)     
        # select element index 1 traceback frame (index 0 corresponds to decorator function level)
        self.tb = traceback.extract_tb(error.__traceback__)[1]
        self.error_type = type(error).__name__
        self.error_message = get_error_message(error, self.error_type, self.tb)

    def __str__(self):
        return self.error_message
     
