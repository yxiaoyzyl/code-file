import threading
import logging
import logging.config


class ThreadLogFilter(logging.Filter):
    def __init__(self, thread_name, *args, **kwargs):
        logging.Filter.__init__(self, *args, **kwargs)
        self.thread_name = thread_name

    def filter(self, record):
        if record.msg.find(self.thread_name) == 0:
            return True
        return False


def start_thread_logging():
    """
     Add a log handler to separate file for current thread
    """
    thread_name = threading.Thread.getName(threading.current_thread())
    log_file = 'log/{}.log'.format(thread_name)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    log_filter = ThreadLogFilter(thread_name)

    log_handler = logging.FileHandler(log_file)
    log_handler.setLevel(logging.INFO)
    log_handler.setFormatter(formatter)
    log_handler.addFilter(log_filter)

    logger = logging.getLogger()
    logger.addHandler(log_handler)

    return log_handler


def stop_thread_logging(log_handler):
    # Remove thread log handler from root logger
    logging.getLogger().removeHandler(log_handler)

    # Close the thread log handler so that the lock on log file can be released
    log_handler.close()


def config_root_logger():
    log_file = 'log/MainThread.log'

    formatter ="%(asctime)s - %(levelname)s - %(message)s"

    logging.config.dictConfig({
        'version': 1,
        'formatters': {
            'root_formatter': {
                'format': formatter
            }
        },
        'handlers': {
            # 'console': {
            #     'level': 'INFO',
            #     'class': 'logging.StreamHandler',
            #     'formatter': 'root_formatter'
            # },
            'log_file': {
                'class': 'logging.FileHandler',
                # 'level': 'DEBUG',
                'level': 'INFO',
                'filename': log_file,
                'formatter': 'root_formatter',
            }
        },
        'loggers': {
            '': {
                'handlers': [
                    # 'console',
                    'log_file'
                ],
                # 'level': 'DEBUG',
                'level': 'INFO',
                'propagate': True
            }
        }
    })