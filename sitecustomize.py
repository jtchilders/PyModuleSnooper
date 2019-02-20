'''PyModuleSnooper: log loaded module paths on CPython shutdown

PyRats relies on AST and parsing the .py file *before* interpreter begins
execution.  This precludes catching dynamic imports and does not *follow*
dependencies.

This approach uses atexit() to inspect sys.modules and log all loaded modules
upon interpreter shutdown.  It should log under most normal termination
circumstances. Atexit() should be preferred over registering signal handlers,
because users may register their own handlers.

* This will run on SIGINT (ctrl+c)
  or on any non-fatal Python exceptions (SyntaxError, ValueError, etc...)
* It will NOT run for unhandled signals (SIGTERM, SIGKILL)
* It will NOT run if os._exit() is invoked directly
* It will NOT run if CPython interpreter itself crashes
* Refer to https://docs.python.org/3.6/library/atexit.html
'''

import atexit
from datetime import datetime
import json
import logging
import os
import socket
import sys

DATETIME_FMT = '%m-%d-%Y %H:%M:%S.%f'
LOGFILE_ROOT = os.path.join('/projects', 'datascience', 'PyModuleSnooper', 'log')

class DictLogger:
    '''Set up logger to emit message to system log facility'''
    def __init__(self):
        now = datetime.now()
        self._info = {
            'timestamp' : now.strftime(DATETIME_FMT),
            'sys.executable': sys.executable,
            'sys.path': sys.path,
            'cobalt_envs':
                { k:v for k,v in os.environ.items() 
                  if k.startswith('COBALT')
                },
        }

        logger = logging.getLogger("PyModuleSnooper")
        logger.propagate = False
        logger.setLevel(logging.INFO)

        # LOGROOT/year/month/day/CobaltID/hostname.PID.hour.minute.second.m
        year,month,day = map(str, (now.year,now.month,now.day))
        job_id = os.environ.get('COBALT_JOBID', 'no-ID')
        log_dir = os.path.join(LOGFILE_ROOT, year, month, day, job_id)
        os.makedirs(log_dir, exist_ok=True)

        fname = '{}.{}.{}'.format(
            socket.gethostname(), os.getpid(), now.strftime('%H.%M.%S.%f')
        )
        log_path = os.path.join(log_dir, fname)
        handler_file = logging.FileHandler(log_path)
        formatter = logging.Formatter('%(message)s')
        handler_file.formatter = formatter
        logger.addHandler(handler_file)
        self._logger = logger

    def log_modules(self, modules_dict):
        self._info['modules'] = modules_dict
        self._logger.info(json.dumps(self._info))

def is_mpi_rank_nonzero():
    '''False if not using mpi4py, or MPI has been finalized, or MPI has
    not been initialized, or rank is 0. Otherwise, returns True if rank > 0.'''
    MPI = None
    if 'mpi4py' in sys.modules:
        if hasattr(sys.modules['mpi4py'], 'MPI'):
            MPI = sys.modules['mpi4py'].MPI

    if MPI is None: 
        return False
    elif MPI.Is_finalized():
        return False
    elif not MPI.Is_initialized():
        return False
    else:
        return MPI.COMM_WORLD.Get_rank() > 0

def inspect_and_log():
    '''Grab paths of all loaded modules and log them'''
    if is_mpi_rank_nonzero(): return
    if os.environ.get('DISABLE_PYMODULE_SNOOP', False): return

    os.umask(0o002) # NEEDED so that subsequent Appends from other users allowed!
    logger = DictLogger()
    modules_dict = {
        module_name : module.__file__
        for module_name, module in sys.modules.items()
        if hasattr(module, '__file__')
    }
    logger.log_modules(modules_dict)

if not os.environ.get('DISABLE_PYMODULE_SNOOP', False):
    atexit.register(inspect_and_log)
