import dijkstra


TIME_SCALE = 20     # 1 minute (60 seconds) is to 3 seconds (60 / 3 = 20)


def _scale_time(minutes):
    return 60.0 * minutes / TIME_SCALE


BANDWIDTH_BASE = 10e7           # 100 Mbps
HELLO_INTERVAL = 10             # 10 seconds
DEAD_INTERVAL = 4 * HELLO_INTERVAL  # 为 HELLO_INTERVAL 的四倍
AGE_INTERVAL = _scale_time(1)   # 1 minute
LS_REFRESH_TIME = _scale_time(30)   # 30 minutes - LSA刷新时间
MAX_AGE = _scale_time(60)       # 1 hour - LSA老化时间


class LinkStatePacket(object):

    def __init__(self, osu_id, age, seq_no, networks, tlv: dict):
        # 报文首部
        self.adv_osu = osu_id
        self.age = age          # 老化时间范围：0-3600秒
        self.seq_no = seq_no

        # RTR_LSA 净荷
        self.networks = networks

        # TE_LSA 净荷，一个字典
        self.tlv = tlv

    def __repr__(self):
        stat = "Adv OSU: {}, Age: {}, Seq: {}, Networks: {}, TLV: {}"\
            .format(self.adv_osu, self.age, self.seq_no, self.networks, self.tlv)
        return stat

    def init_tlv(self, iface_name, lcl_id, rmt_id, max_bw, ava_bw, use_bw, av_delay=None):
        # 初始化链路tlv
        link_tlv = Link_TLV()
        link_tlv.init_lrrid_tlv(lcl_id, rmt_id)
        link_tlv.init_max_bw_tlv(max_bw)
        link_tlv.init_ava_bw_tlv(ava_bw)
        link_tlv.init_use_bw_tlv(use_bw)
        link_tlv.init_av_delay(av_delay)

        # 将链路tlv赋值到净荷区
        self.tlv[iface_name] = link_tlv.__dict__


class HelloPacket(object):

    def __init__(self, osu_id, address, netmask, seen):
        self.osu_id = osu_id
        self.address = address
        self.netmask = netmask
        self.seen = seen


# Type-Length-Value结构
class TLV:

    def __init__(self, tpe, val):
        self.type = tpe
        self.val = val


class Link_TLV(TLV):

    def __init__(self, tpe=2, val=None):
        super().__init__(tpe, val)
        self.type = tpe
        self.val = {}

    # 初始化最大带宽子TLV - TE隧道可以使用的带宽上限值（通常接口带宽）
    def init_max_bw_tlv(self, max_bw: float):
        # 带宽单位 Byte/s
        self.val['6'] = max_bw

    # 初始化链路标识TLV
    def init_lrrid_tlv(self, lcl_id: str, rmt_id: str):
        self.val['10'] = (lcl_id, rmt_id)

    # 初始化平均时延子TLV
    def init_av_delay(self, av_delay: float):
        # 时延单位 微妙
        self.val['27'] = av_delay

    # 初始化可用带宽子TLV
    # 隧道可分配带宽，初值默认为最大带宽
    def init_ava_bw_tlv(self, ava_bw: float):
        self.val['32'] = ava_bw

    # 初始化占用带宽子TLV
    # 提供给隧道后剩余的带宽，初值默认为0
    def init_use_bw_tlv(self, use_bw: float):
        self.val['33'] = use_bw


class Database(dict):

    def _flush(self):
        """Flush old entries"""
        flushed = []
        for osu_id in self:
            if self[osu_id].age > MAX_AGE:
                flushed.append(osu_id)
        map(self.pop, flushed)      # 将对应flushed内的LSA记录删除
        return flushed

    def insert(self, lsa):
        """
        插入分如下情况：
        1 - 本地无通告记录
        2 - LSA更新（比较序列号大小）
        返回布尔值
        """
        if lsa.adv_osu not in self or lsa.seq_no > self[lsa.adv_osu].seq_no:
            self[lsa.adv_osu] = lsa
            return True
        else:
            return False

    def remove(self, osu_id):
        """Remove LSA from osu_id"""
        if osu_id in self:
            del self[osu_id]

    def update(self):
        """
        通过老化LSA和刷新过期的LSA来更新LSDB
        """
        for adv_osu in self:
            self[adv_osu].age += 1
        return self._flush()

    def get_shortest_paths(self, osu_id):
        """Return a list of shortest paths from osu_id to all other nodes"""
        g = dijkstra.Graph()
        nodes = []
        paths = {}
        for lsa in self.values():
            nodes.append(lsa.adv_osu)
            for data in lsa.networks.values():
                neighbor_id, cost = data[:2]
                g.add_e(lsa.adv_osu, neighbor_id, cost)
        if osu_id in nodes:
            nodes.remove(osu_id)

        # Find a shortest path from osu_id to dest
        dist, full_path = g.shorest_path(osu_id)

        for dest in nodes:
            # Trace the path back using the prev array.
            try:
                cost = dist[dest]
            except KeyError:
                continue
            else:
                next_hop = (full_path[dest][1] if dest in full_path else dest)
                paths[dest] = (next_hop, cost)
        return paths, full_path
