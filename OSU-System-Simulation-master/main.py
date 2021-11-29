import os
import threading
import logging

import log
import osuSim


log.config_root_logger()
nums = [1, 2, 3, 4, 5]
try:
    for i in nums:
        os.remove('log/OSU{}.log'.format(i))
    os.remove('log/MainThread.log')
except:
    pass

log.config_root_logger()
thd = []
for str in nums:
    thd.append(threading.Thread(target=osuSim.sim_run,
                                args=("topologies/osu{}.cfg".format(str),),
                                name='OSU{}'.format(str)))
    thd[str-1].start()