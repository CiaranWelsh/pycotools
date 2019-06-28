import viz
import tasks
import errors
import misc
import model
import os

import logging.config

import warnings

warnings.filterwarnings("ignore", message=".*numpy.dtype.*")
warnings.filterwarnings("ignore", message=".*numpy.ufunc.*")

global LOG_FILENAME
LOG_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'logging_config.conf')

if os.path.isfile(LOG_CONFIG_FILE) is not True:
    raise Exception
logging.config.fileConfig(LOG_CONFIG_FILE,
                          disable_existing_loggers=False)

LOG = logging.getLogger('root')

LOG.warning('While still operational, this version of PyCoTools is no longer being '
            'developed. For the latest version, please see "https://github.com/CiaranWelsh/pycotools3"')


