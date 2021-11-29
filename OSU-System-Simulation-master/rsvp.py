import random
import time
import uuid

CREATE_CONN_INTERVAL = 15  # 15 seconds
K_FACTOR = 3            # suggestion value
# REFRESH_PERIOD = 30   # seconds
REFRESH_PERIOD = 10     # seconds, for test only
LIFE_TIME = int((K_FACTOR + 0.5) * 1.5 * REFRESH_PERIOD)  # seconds
CLEANUP_INTERVAL = 1    # seconds


class PathMsg:

    def __init__(self, src_ip, dst_ip, request_bw):
        self.msg_type = '0x01'
        self.lsp_id = None

        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.tos = None
        self.request_bw = request_bw
        self.route = None
        self.time_value = None      # 记录REFRESH_PERIOD

    def set_lsp_id(self, lsp_id=None):
        # random.seed(time.time())
        # self.lsp_id = random.random()       
        self.lsp_id = str(uuid.uuid1()) if lsp_id is None else lsp_id

    def set_time_value(self, time_value):
        self.time_value = time_value

    def set_route(self, route):
        self.route = route

class ResvMsg:

    def __init__(self, lsp_id, src_ip, dst_ip, request_bw):
        self.msg_type = '0x02'
        self.lsp_id = lsp_id
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.request_bw = request_bw
        self.route = None
        self.style = None


class PathErrMsg():

    def __init__(self, lsp_id, src_ip, dst_ip, err_msg, route):
        self.msg_type = '0x03'
        self.lsp_id = lsp_id
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.err_msg = err_msg
        self.route = route


class ResvErrMsg():

    def __init__(self, lsp_id, src_ip, dst_ip, err_msg, route):
        self.msg_type = '0x04'
        self.lsp_id = lsp_id
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.err_msg = err_msg
        self.route = route


class PathTearMsg():

    def __init__(self, lsp_id, src_ip, dst_ip, route):
        self.msg_type = '0x05'
        self.lsp_id = lsp_id
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.route = route


class ResvTearMsg():

    def __init__(self, lsp_id, src_ip, dst_ip, route):
        self.msg_type = '0x06'
        self.lsp_id = lsp_id
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.route = route


class RouteObject():

    def __init__(self, src_ip, dst_ip, path):
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.path = path

    # 获取当前设备在路径表中的索引值, 加1后是下一跳地址索引值
    def get_next_hop(self, current_hop):
        current_hop_id = self.path.index(current_hop)
        next_hop = self.path[current_hop_id + 1]
        return next_hop

    # 减1是上一跳地址索引值
    def get_prev_hop(self, current_hop):
        current_hop_id = self.path.index(current_hop)
        prev_hop = self.path[current_hop_id - 1]
        return prev_hop


class PSB():

    def __init__(self, lsp_id, prv_hop, interface):
        self.lsp_id = lsp_id
        self.prv_hop = prv_hop
        self.interface = interface
        self.cleanup = 0


class RSB():

    def __init__(self, lsp_id, next_hop, request_bw, interface):
        self.lsp_id = lsp_id
        self.next_hop = next_hop
        self.request_bw = request_bw
        self.interface = interface
        self.cleanup = 0


class Connection():

    def __init__(self, src_ip, dst_ip, request_bw, route):
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.request_bw = request_bw
        self.path = route
        self.real_bw = []


class State_Block():

    def creatPSB(pathMsg, hop, pre_iface, iface):
        # 检查端口的资源是否够用
        if pathMsg.request_bw < iface.ava_bw:
            # 资源充足，将路径状态信息保存在psb中
            psb = PSB(pathMsg.lsp_id, hop, pre_iface)
            iface.psb[pathMsg.lsp_id] = psb
            return psb

    def creatRSB(resvMsg, hop, pre_iface, iface):
        # if resvMsg.request_bw < iface.ava_bw and iface.psb[resvMsg.lsp_id].prv_hop==hop:
        if resvMsg.request_bw < iface.ava_bw:
            # # 资源可用，将资源状态保存在rsb中，并为连接预留资源
            rsb = RSB(resvMsg.lsp_id, hop, resvMsg.request_bw, pre_iface)
            iface.rsb[resvMsg.lsp_id] = rsb
            Resource.reservation(iface, resvMsg)
            return rsb

    @staticmethod
    def del_psb(iface, uuid):
        if uuid in iface.psb:
            del iface.psb[uuid]

    @staticmethod
    def del_rsb(iface, uuid):
        if uuid in iface.rsb:
            iface.ava_bw += iface.rsb[uuid].request_bw
            iface.use_bw -= iface.rsb[uuid].request_bw
            del iface.rsb[uuid]


# 资源管理
class Resource():

    def reservation(interface, resvMsg):
        # conn = Connection(resvMsg.src_ip, resvMsg.dst_ip, resvMsg.request_bw, resvMsg.route)
        # if interface.conn_insert(resvMsg.lsp_id, conn):         
        # 预留资源，可用带宽减少
        interface.ava_bw = interface.ava_bw - resvMsg.request_bw
        interface.use_bw = interface.use_bw + resvMsg.request_bw

    def release(interface, Msg):
        # if interface.conn_del(Msg.lsp_id):
        # 释放占用资源，可用带宽增加
        interface.ava_bw = interface.ava_bw + interface.connection[Msg.lsp_id].bandWidth
        interface.use_bw = interface.use_bw - interface.connection[Msg.lsp_id].bandWidth
