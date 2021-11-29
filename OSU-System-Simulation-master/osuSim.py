# 系统模块
import sys
import websockets
import socket
import time
import configparser
import asyncio
import random
import threading
import logging
from threading import *
import functools

# 项目模块
import ospf
import rsvp
import log
import connectServer  #!!!! connectServer，用于和client通信


# 重写Thread中的方法，实现多定时任务不间断执行
class RepeatingTimer(Thread):
    def __init__(self, interval, callback, args = ()):
        super().__init__()
        self.stop_event = Event()
        self.interval = interval
        self.callback = callback
        self.args = args

    def run(self):
        while not self.stop_event.wait(self.interval):
            if self.args:
                self.callback(self.args)
            else:
                self.callback()

    def stop(self):
        self.stop_event.set()


def mktimer(interval, callback, args = ()):
    timer = RepeatingTimer(interval, callback, args)
    return timer


# 服务端消息接收协议
class RxProtocol(asyncio.Protocol):
    def __init__(self, osu, name):
        self.osu = osu
        self.iface_name = name

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        packet = eval(data.decode())
        # log('Data received: %s '%(packet))
        logging.info('%s-Received data: %s '%(self.osu._hostname, packet))
        self.transport.close()
        # Hello包处理
        if 'seen' in packet.keys():
            neighbor_id = packet['osu_id']
            # log('Seen %s' % (neighbor_id, ))
            logging.info('%s-Seen %s' % (self.osu._hostname, neighbor_id, ))
            # Reset Dead timer
            if neighbor_id in self.osu._timers.keys():
                self.osu._timers[neighbor_id].stop()
            self.osu._timers[neighbor_id] = mktimer(ospf.DEAD_INTERVAL, self.osu._break_adjacency, (neighbor_id, ))
            self.osu._timers[neighbor_id].start()
            self.osu._seen[neighbor_id] = (self.iface_name, packet['address'], packet['netmask'])
            if self.osu._hostname in packet['seen']:
                self.osu._sync_lsdb(neighbor_id)
        # LSP包处理
        elif 'adv_osu' in packet.keys():
            # Insert to Link State database
            packets = ospf.LinkStatePacket(packet['adv_osu'], packet['age'], packet['seq_no'], packet['networks'], packet['tlv'])
            if self.osu._lsdb.insert(packets):
                if packets.adv_osu == self.osu._hostname:
                    self.osu._advertise()
                else:
                    logging.info('%s-Received LSA of %s via %s and merged to the LSDB' % (self.osu._hostname, packets.adv_osu, self.iface_name))
                    self.osu._flood(packets, self.iface_name)
                    self.osu._update_routing_table()
            elif packets.adv_osu == self.osu._hostname and packets.seq_no == 1:
                self.osu._advertise()
        elif 'msg_type' in packet.keys():
            # 判断是PathMsg
            if packet['msg_type'] == '0x01':
                # logging.info('%s-********Received data: %s '%(self.osu._hostname, packet))
                pathMsg = rsvp.PathMsg(packet['src_ip'], packet['dst_ip'], packet['request_bw'])
                pathMsg.lsp_id = packet['lsp_id']
                pathMsg.route = packet['route']
                self.osu._path(pathMsg)
            # 判断是ResvMsg
            elif packet['msg_type'] == '0x02':
                # logging.info('%s-########Received data: %s '%(self.osu._hostname, packet))
                resvMsg = rsvp.ResvMsg(packet['lsp_id'], packet['src_ip'], packet['dst_ip'], packet['request_bw'])
                resvMsg.route = packet['route']
                self.osu._resv(resvMsg)
            elif packet['msg_type'] == '0x03':
                pathErrMsg = rsvp.PathErrMsg(packet['lsp_id'], packet['src_ip'], packet['dst_ip'], packet['err_msg'], packet['route'])
                self.osu._pathErr(pathErrMsg)
            elif packet['msg_type'] == '0x04':
                resvErrMsg = rsvp.ResvErrMsg(packet['lsp_id'], packet['src_ip'], packet['dst_ip'], packet['err_msg'], packet['route'])
                self.osu._resvErr(resvErrMsg)
            elif packet['msg_type'] == '0x05':
                pathTearMsg = rsvp.PathTearMsg(packet['lsp_id'], packet['src_ip'], packet['dst_ip'], packet['route'])
                self.osu._pathTear(pathTearMsg)
            elif packet['msg_type'] == '0x06':
                resvTearMsg = rsvp.ResvTearMsg(packet['lsp_id'], packet['src_ip'], packet['dst_ip'], packet['route'])
                self.osu._resvTear(resvTearMsg)
            else:
                pass         
        else:
            pass


# 客户端消息发送协议
class TxProtocol(asyncio.Protocol):
    def __init__(self, message, on_con_lost):
        self.message = str(message.__dict__)
        self.on_con_lost = on_con_lost
    def connection_made(self, transport):
        transport.write(self.message.encode())
        # logging.info('Data sent: %s '%(self.message))
    def connection_lost(self, exc):
        self.on_con_lost.set_result(True)


# 定义消息传输方法
def IfaceTx(loop, address, port, data):
    asyncio.set_event_loop(loop)
    async def init_tx_client():
        try:
            # 当服务端未启动时，直接启动客户端发送消息会报错
            on_con_lost = loop.create_future()
            transport, protocol = await loop.create_connection(
                lambda: TxProtocol(data, on_con_lost),
                address, port)
        except OSError:
            pass
        else:
            try:
                await on_con_lost
            finally:
                transport.close()
    future = asyncio.gather(init_tx_client())
    loop.run_until_complete(future)
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()


class Route(object):
    def __init__(self, dest, gateway, netmask, metric, iface):
        self.dest = dest
        self.gateway = gateway
        self.netmask = netmask
        self.metric = metric
        self.iface = iface


class RoutingTable(list): # RoutingTable[Route1, Route2...]
    def __repr__(self):
        routes = ['Dest\tGateway\tNetmask\tMetric\tInterface']
        for r in self:
            routes.append("%s\t%s\t%s\t%.2f\t%s" % (r.dest, r.gateway, r.netmask, r.metric, r.iface))
        return '\n'.join(routes)
    def clear(self):
        del self[:]


class Control(object):

    def creat_conn(osu, packet):
        pathMsg = rsvp.PathMsg(packet['src_ip'], packet['dst_ip'], int(packet['bandwidth']))
        pathMsg.set_lsp_id()                                    # 设置LSP标识符（LSP ID）：随机
        pathMsg.route = osu.shortestPath[packet['dst_ip']] # 根据目的地址dst，计算最短路径
        osu._path(pathMsg)
    
    def tear_conn(osu, packet):
        pass



class OSU(object):

    def __init__(self, hostname, webSocket_port):
        self._hostname = hostname
        self.webSocket_port = webSocket_port
        self._table = RoutingTable()
        self._lsdb = ospf.Database()
        self._interfaces = {}
        self._neighbors = {}
        self._seen = {}
        self.shortestPath = {}
        self._init_timers()

    @staticmethod
    def _get_netadd(addr, netmask):
        addr = addr.split('.')
        netmask = netmask.split('.')
        netadd = []
        for i in range(4):
            netadd.append(str(int(addr[i]) & int(netmask[i])))
        return '.'.join(netadd)

    def _init_timers(self):
        self._dead_timer = None
        self._timers = {}
        self._timers['lsdb'] = mktimer(ospf.AGE_INTERVAL, self._update_lsdb)
        self._timers['refresh_lsa'] = mktimer(ospf.LS_REFRESH_TIME, self._refresh_lsa)
        self._timers['hello'] = mktimer(ospf.HELLO_INTERVAL, self._hello)
<<<<<<< HEAD
        self._timers['rsvp_refresh'] = mktimer(rsvp.REFRESH_TIME, self._rsvp_refresh)
        # self._timers['createConnTest'] = mktimer(rsvp.CREATE_CONN_INTERVAL, self._createConnTest)
=======
        self._timers['rsvp_refresh'] = mktimer(rsvp.REFRESH_PERIOD, self._rsvp_refresh_timer)
        # self._timers['rsvp_cleanup'] = mktimer(rsvp.CLEANUP_INTERVAL, self._rsvp_cleanup_timer)
        self._timers['createConnTest'] = mktimer(rsvp.CREATE_CONN_INTERVAL, self._createConnTest)
>>>>>>> 8cec0a4d6b7448fd4ab398aa7c1574c5aebc3276

    def _rsvp_cleanup_timer(self):
        # 该函数功能：1. 遍历PSB、RSB，选出非本机生成的连接；2. 每次对cleanup属性加1
        for iface_name in self._interfaces:
            interface = self._interfaces[iface_name]
            for uuid in interface.psb:
                interface.psb[uuid].cleanup += 1
                if interface.psb[uuid].cleanup > rsvp.LIFE_TIME:
                    # 删除PSB
                    #rsvp.State_Block.del_psb(interface, uuid)
                    logging.info("{}-/*Delete PSB of {}*/".format(self._hostname, uuid))
            for uuid in interface.rsb:
                interface.rsb[uuid].cleanup += 1
                if interface.rsb[uuid].cleanup > rsvp.LIFE_TIME:
                    # 删除RSB
                    #rsvp.State_Block.del_rsb(interface, uuid)
                    logging.info("{}-//*Delete RSB of {}*//".format(self._hostname, uuid))
        return None

    def _rsvp_refresh_timer(self):
        # 该函数功能：1. 遍历connection，选出以本节点为源节点的连接；2. 进入到Refresh流程。
        # 遍历所有已启用端口，检查存储其中的PSB
        # 具体的刷新流程
        for iface_name in self._interfaces:
            interface = self._interfaces[iface_name]
            for uuid in interface.connection.keys():
                # 若该连接起源于本机
                if interface.connection[uuid].src_ip == self._hostname:
                    out_iface_list = [interface.rsb[uuid].interface]
                    self._rsvp_path_refresh(interface.psb[uuid], interface.connection[uuid], out_iface_list)
                    logging.info("{}-****Time to Refresh****uuid is {}, the rest of time is {}"
                                 .format(self._hostname, uuid, interface.psb[uuid].cleanup))
                    self._rsvp_resv_refresh(interface.rsb[uuid], interface.connection[uuid], out_iface_list)
                    logging.info("{}-****Time to Refresh****uuid is {}, the rest of time is {}"
                                 .format(self._hostname, uuid, interface.rsb[uuid].cleanup))
        return None

    def _rsvp_path_refresh(self, spec_psb, spec_conn, out_iface_list):
        """
        两种情况进入PATH REFRESH
        1 - refresh timer 到期
        2 - 在PATH消息处理过程中，Path_Refresh_Needed标志位被设置
        步骤：
        1 - 初始化一个PATH消息
        2 - 设置TIME_VALUE
        3 - 将PSB中的发送方描述符添加至PATH消息中
        4 - 设PHOP的值为本机端口地址
        5 - 将该PATH消息传送至对应（多个）端口
        刷新过程中path消息发送的过程
        """
        # 1 - 初始化一个PATH消息
        PATH_MSG = rsvp.PathMsg(spec_conn.src_ip, spec_conn.dst_ip, spec_conn.request_bw)
        # 2 - 设置TIME_VALUE
        PATH_MSG.set_time_value(rsvp.REFRESH_PERIOD)
        # 3 - 将PSB中的发送方描述符添加至PATH消息中
        PATH_MSG.set_lsp_id(spec_psb.lsp_id)
        PATH_MSG.set_route(spec_conn.path)
        # 5 - 将该PATH消息传送至对应（多个）端口
        for iface in out_iface_list:
            iface.transmit(PATH_MSG)
        return None

    def _rsvp_resv_refrsh(self, spec_rsb, spec_conn, out_iface_list):
        # 初始化一个resv消息
        RESV_MSG = rsvp.ResvMsg(spec_conn.dst_ip, spec_conn.scr_ip, spec_conn.request_bw)
        # 设置resv消息的TIME_VALUE
        RESV_MSG.set_time_value(rsvp.REFRESH_PERIOD)
        # 将RSB中的发送方描述符添加至RESV消息中
        RESV_MSG.set_lsp_id(spec_rsb.lsp_id)
        RESV_MSG.set_route(spec_conn.resv)
        for iface in out_iface_list:
            iface.transmit(RESV_MSG)
        return None

    def _update_lsdb(self):
        flushed = self._lsdb.update()
        if flushed:
            logging.info('%s-LSA(s) of %s reached MaxAge and was/were flushed from the LSDB' % (self._hostname, ', '.join(flushed), ))

    def _refresh_lsa(self):
        if self._hostname in self._lsdb:
            logging.info('Refreshing own LSA')
            self._advertise()

    def _hello(self):
        # 建立邻接
        seen = self._seen.keys()
        for iface in self._interfaces.values():
            packet = ospf.HelloPacket(self._hostname, iface.address, iface.netmask, list(seen))
            iface.transmit(packet)
        for neighbor_id in list(self._seen.keys()):
            if neighbor_id not in self._neighbors:
                self._sync_lsdb(neighbor_id)

    def _update_routing_table(self):
        logging.info('%s-Recalculating shortest paths and updating routing table'%(self._hostname,))
        # 清除当前路由表内容
        # 计算当前主机最短路径
        self._table.clear()
        paths, self.shortestPath = self._lsdb.get_shortest_paths(self._hostname)
        logging.info('%s-The next_hop in the shortest path: %s'%(self._hostname, paths))
        logging.info('%s-Full paths: %s'%(self._hostname, self.shortestPath))
        if not paths:
            return
        networks = {}
        for node, lsa in self._lsdb.items():
            for network, data in lsa.networks.items():    # networks(neighbor_id, cost, address, netmask)
                if network not in networks:
                    networks[network] = {}
                networks[network][node] = data[1]  # cost
        gateways = {}
        for network, nodes in networks.items():
            if len(nodes) != 2:
                continue
            n1, n2 = nodes.keys()
            if self._hostname in nodes:
                # 假设路由器通过自己的接口发送数据，即使成本更高
                dest = next_hop = (n2 if n1 == self._hostname else n1)
                cost = nodes[self._hostname]
            else:
                # 确定哪个节点是到目标网络的较短路径
                dest = (n1 if paths[n1][1] + nodes[n1] < paths[n2][1] + nodes[n2] else n2)
                next_hop, cost = paths[dest]
                # 获取实际成本
                cost += nodes[dest]
            # 获取其他信息
            iface, gateway = self._neighbors[next_hop][:2]
            netmask = self._lsdb[dest].networks[network][3]
            if self._hostname in nodes:
                gateways[cost] = (gateway, iface)
                gateway = '-'
            r = Route(network, gateway, netmask, cost, iface)
            self._table.append(r)
        if gateways:
            cost = min(gateways.keys())
            gateway, iface = gateways[cost]
            self._table.append(Route('0.0.0.0', gateway, '0.0.0.0', cost, iface))

    def _break_adjacency(self, neighbor_id):
        self._dead_timer = self._timers[neighbor_id]
        del self._timers[neighbor_id]
        del self._neighbors[neighbor_id]
        del self._seen[neighbor_id]
        logging.info('%s-%s is down'%(self._hostname, neighbor_id))
        self._advertise()

    def _flood(self, packet, source_iface=None):
        # 向其他接口泛洪接收到的数据包
        if packet.adv_osu == self._hostname:
            logging.info('%s-Flooding own LSA'%(self._hostname,))
        else:
            logging.info('%s-Flooding LSA of %s' % (self._hostname, packet.adv_osu, ))
        interfaces = []
        for data in self._neighbors.values():
            interfaces.append(data[0])
        if source_iface in interfaces:
            interfaces.remove(source_iface)
        for iface_name in interfaces:
            iface = self._interfaces[iface_name]
            iface.transmit(packet)

    def _advertise(self):
        networks = {}
        link_enable_ports = []
        for neighbor_id, data in self._neighbors.items():
            iface_name, address, netmask = data
            iface = self._interfaces[iface_name]
            # todo 需要修改CSOT
            cost = ospf.BANDWIDTH_BASE / float(iface.bandwidth)
            netadd = self._get_netadd(address, netmask)
            networks[netadd] = (neighbor_id, cost, address, netmask)
            link_enable_ports.append(iface.name)
        # 创建新的或更新现有的 LSA
        if self._hostname in self._lsdb:
            lsa = self._lsdb[self._hostname]
            lsa.seq_no += 1
            lsa.age = 1
            lsa.networks = networks
            for iface_name in link_enable_ports:
                # lth: 有新端口上线
                if iface_name not in lsa.tlv.keys():
                    iface = self._interfaces[iface_name]
                    lsa.init_tlv(iface_name=iface_name,
                                 lcl_id=self._hostname,
                                 rmt_id=iface.link,
                                 max_bw=iface.bandwidth,
                                 ava_bw=iface.ava_bw,
                                 use_bw=iface.use_bw,
                                 av_delay=iface.av_delay)
                # lth: 更新链路信息
                else:
                    iface = self._interfaces[iface_name]
                    lsa.tlv[iface_name]['val']['32'] = iface.ava_bw
                    lsa.tlv[iface_name]['val']['33'] = iface.use_bw
        else:
            lsa = ospf.LinkStatePacket(self._hostname, 1, 1, networks, {})
            for iface_name in link_enable_ports:
                iface = self._interfaces[iface_name]
                lsa.init_tlv(iface_name=iface_name,
                             lcl_id=self._hostname,
                             rmt_id=iface.link,
                             max_bw=iface.bandwidth,
                             ava_bw=iface.ava_bw,
                             use_bw=iface.use_bw,
                             av_delay=iface.av_delay)
        self._lsdb.insert(lsa)
        # 向邻居泛洪 LSA
        self._flood(lsa)
        self._update_routing_table()

    def _sync_lsdb(self, neighbor_id):
        topology_changed = (neighbor_id not in self._neighbors)
        if topology_changed:
            logging.info('%s-Adjacency established with %s' % (self._hostname, neighbor_id, ))
        self._neighbors[neighbor_id] = self._seen[neighbor_id]
        if self._hostname not in self._lsdb:
            logging.info('%s-Creating initial LSA'%(self._hostname,))
            self._advertise()
        elif topology_changed:
            self._advertise()
            # 与邻居同步LSDB
            iface_name = self._neighbors[neighbor_id][0]
            iface = self._interfaces[iface_name]
            for lsa in list(self._lsdb.values()):
                iface.transmit(lsa)

    def iface_create(self, name, bandwidth, port):
        if name not in self._interfaces:
            self._interfaces[name] = Interface(name, bandwidth, port, self)

    def iface_config(self, name, address, netmask, link, host, port):
        iface = self._interfaces[name]
        iface.address = address
        iface.netmask = netmask
        iface.link = link
        iface.remote_end_host = host
        iface.remote_end_port = port

    def find_iface(self, hop):
        seen = list(self._seen.keys())
        _iface = None
        if hop in seen:
            for iface in self._interfaces.values():
                if hop == iface.link:
                    _iface = iface
                    return _iface         

    def IfaceRx(self, loop, name):
        #为子线程设置自己的事件循环
        asyncio.set_event_loop(loop)
        async def init_rx_server():
            # OSU调用消息接收协议：--(OSU, name)
            server = await loop.create_server(
                    lambda: RxProtocol(self, name),  
                    '127.0.0.1', self._interfaces[name].port)
            async with server:
                    await server.serve_forever()
        future = asyncio.gather(init_rx_server())
        loop.run_until_complete(future)

    def ControlPortRx(self, loop):
        asyncio.set_event_loop(loop)
        start_server = websockets.serve(
            functools.partial(connectServer.ConServer_logic, self), 
            "localhost", self.webSocket_port)
        asyncio.get_event_loop().run_until_complete(start_server)
        asyncio.get_event_loop().run_forever()

    def start(self):
        # 启动控制端口
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=self.ControlPortRx, args=(loop,))
        thread.daemon = True
        thread.start()
        # 启动定时任务
        for t in self._timers.values():
            t.start()
        for name in self._interfaces.keys():
            # 为启动服务端创建一个事件循环thread_loop
            thread_loop = asyncio.new_event_loop()
            t = threading.Thread(target=self.IfaceRx, args=(thread_loop,name,))
            t.daemon = True
            t.start()

    def _createConnTest(self):
        
        for dst in self.shortestPath.keys():
            request_bw = random.randint(2, 10000)
            pathMsg = rsvp.PathMsg(self._hostname, dst, request_bw)
            pathMsg.set_lsp_id()
            pathMsg.route = self.shortestPath[dst]
            self._path(pathMsg)

    # 处理PathMsg，向下游沿途保存路径状态
    def _path(self, pathMsg):
        """
        当PATH消息到达后，其处理过程如下：
        1 - 初始化两个标志位为False，Path_Refresh_Needed及Resv_Refresh_Needed
        2 - 将PATH消息与PSB进行匹配
            2.1 - 若不存在PSB，新建PSB，设Path_Refresh_Needed=True
            2.2 - 若存在PSB，若PHOP字段发生变化，将其复制至PSB，并设Path_Refresh_Needed=True，Resv_Refresh_Needed=True
            2.3 - 重置PSB内cleanup=0
            2.4 - 判断Path_Refresh_Needed。若为True，则进入PATH REFRESH事件；若为False，丢弃PATH消息并返回
            2.5 - 判断Resv_Refresh_Needed，同2.4
            2.6 - [可选]触发UPDATE TRAFFIC CONTROL事件
        3 - 丢弃PATH消息并返回
        """
        routeObject = rsvp.RouteObject(pathMsg.src_ip, pathMsg.dst_ip, pathMsg.route)
        prv_hop = routeObject.get_prev_hop(self._hostname)
        pre_iface = self.find_iface(prv_hop)        # 上一跳端口，同时也是接收该消息的端口

        Path_Refresh_Needed = False
        Resv_Refresh_Needed = False
        lsp_id = pathMsg.lsp_id

        try:
            # 不存在PSB
            if lsp_id not in pre_iface.psb:
                Path_Refresh_Needed = True
                #todo 创建PSB
                pass
            # 存在PSB
            else:
                # 判断PSB信息是否有变动
                if pre_iface.psb[lsp_id].prv_hop != prv_hop:
                    pre_iface.psb[lsp_id].prv_hop = prv_hop
                    Path_Refresh_Needed = True
                    Resv_Refresh_Needed = True
                pre_iface.psb[lsp_id].cleanup = 0

            if Path_Refresh_Needed:
                next_hop = routeObject.get_next_hop(self._hostname)
                next_iface = self.find_iface(next_hop)
                self._rsvp_path_refresh(pre_iface.psb[lsp_id], pre_iface.connection[lsp_id], [next_iface])

            if Resv_Refresh_Needed:
                next_hop = routeObject.get_next_hop(self._hostname)
                next_iface = self.find_iface(next_hop)
                self._rsvp_resv_refresh(pre_iface.rsb[lsp_id], pre_iface.connection[lsp_id], [next_iface])
        except:
            pass

        # 判断是不是第一跳，不是第一跳
        if pathMsg.src_ip != self._hostname:
            prv_hop = routeObject.get_prev_hop(self._hostname)
            pre_iface = self.find_iface(prv_hop)
            if pre_iface:
                if rsvp.State_Block.creatPSB(pathMsg, prv_hop, pre_iface, pre_iface):
                    logging.info('%s-PSB created successfully by %s —> lsp_id: %s'%(self._hostname, pre_iface.name, pathMsg.lsp_id, ))
                else:
                    # 此处应当返回资源不足，连接创建失败的消息，后续根据PathErrorMsg补充
                    pathErrMsg = rsvp.PathErrMsg(pathMsg.lsp_id, pathMsg.dst_ip, pathMsg.src_ip, self._hostname, pathMsg.route)
                    pathErrMsg.route.reverse()
                    self._pathErr(pathErrMsg)
            # 判断是不是最后一跳，不是最后一跳
            if pathMsg.dst_ip != self._hostname:
            # 循环遍历当前设备所有接口，找出与上一条连接的接口
                next_hop = routeObject.get_next_hop(self._hostname)
                next_iface = self.find_iface(next_hop)
                if next_iface:
                    if rsvp.State_Block.creatPSB(pathMsg, prv_hop, pre_iface, next_iface):
                        logging.info('%s-PSB created successfully by %s —> lsp_id: %s'%(self._hostname, next_iface.name, pathMsg.lsp_id, ))
                        next_iface.transmit(pathMsg)
                    else:
                        # 此处应当返回资源不足，连接创建失败的消息，后续根据PathErrorMsg补充
                        pathErrMsg = rsvp.PathErrMsg(pathMsg.lsp_id, pathMsg.dst_ip, pathMsg.src_ip, self._hostname, pathMsg.route)
                        pathErrMsg.route.reverse()
                        self._pathErr(pathErrMsg)
            # 是最后一跳，触发_pathResv方法，开始向上游逐一回复resvMsg
            else:
                # 封装resvMsg，逆着回发消息，源地址和目的地址调换位置赋值
                resvMsg = rsvp.ResvMsg(pathMsg.lsp_id, pathMsg.dst_ip, pathMsg.src_ip, pathMsg.request_bw)
                # 原来的路径应当逆序赋值给resvMsg中的路由
                resvMsg.route = pathMsg.route
                resvMsg.route.reverse()
                self._resv(resvMsg)
        else:
            next_hop = routeObject.get_next_hop(self._hostname)
            next_iface = self.find_iface(next_hop)
            if next_iface:
                if rsvp.State_Block.creatPSB(pathMsg, None, None, next_iface):
                    logging.info('%s-PSB created successfully by %s —> lsp_id: %s'%(self._hostname, next_iface.name, pathMsg.lsp_id, ))
                    next_iface.transmit(pathMsg)
                else:
                    # 此处应当返回资源不足，连接创建失败的消息，后续根据PathErrorMsg补充
                    pathErrMsg = rsvp.PathErrMsg(pathMsg.lsp_id, pathMsg.dst_ip, pathMsg.src_ip, self._hostname, pathMsg.route)
                    pathErrMsg.route.reverse()
                    self._pathErr(pathErrMsg)


    # 处理resvMsg，向上游沿途预留资源
    def _resv(self, resvMsg):
        routeObject = rsvp.RouteObject(resvMsg.src_ip, resvMsg.dst_ip, resvMsg.route)
        if resvMsg.src_ip != self._hostname:
            prv_hop = routeObject.get_prev_hop(self._hostname)
            pre_iface = self.find_iface(prv_hop)
            if pre_iface:
                if rsvp.State_Block.creatRSB(resvMsg, prv_hop, pre_iface, pre_iface):
                    logging.info('%s-RSB created successfully by %s —> lsp_id: %s'%(self._hostname, pre_iface.name, resvMsg.lsp_id, ))
                else:
                # 抢占资源，连接创建失败，后续根据ResvMsgErr补充
                    resvErrMsg = rsvp.ResvErrMsg(resvMsg.lsp_id, resvMsg.dst_ip, resvMsg.src_ip, self._hostname, resvMsg.route)
                    resvErrMsg.route.reverse()
                    self._resvErr(resvErrMsg)
            if resvMsg.dst_ip != self._hostname:
                next_hop = routeObject.get_next_hop(self._hostname)
                next_iface = self.find_iface(next_hop)
                if next_iface:
                    if rsvp.State_Block.creatRSB(resvMsg, prv_hop, pre_iface, next_iface):
                        logging.info('%s-RSB created successfully by %s —> lsp_id: %s'%(self._hostname, next_iface.name, resvMsg.lsp_id,))
                        next_iface.transmit(resvMsg)
                    else:
                    # 抢占资源，连接创建失败，后续根据ResvMsgErr补充
                        resvErrMsg = rsvp.ResvErrMsg(resvMsg.lsp_id, resvMsg.dst_ip, resvMsg.src_ip, self._hostname, resvMsg.route)
                        resvErrMsg.route.reverse()
                        self._resvErr(resvErrMsg)
            else:
                conn = rsvp.Connection(resvMsg.dst_ip, resvMsg.src_ip, resvMsg.request_bw, resvMsg.route)
<<<<<<< HEAD
=======

>>>>>>> 8cec0a4d6b7448fd4ab398aa7c1574c5aebc3276
                if pre_iface.conn_insert(resvMsg.lsp_id, conn):
                    logging.info('%s-RSB created successfully by %s —> lsp_id: %s'%(self._hostname, pre_iface.name, resvMsg.lsp_id, ))
                    logging.info("%s-The %s connection between %s and %s is successfully created"%(self._hostname, resvMsg.request_bw, resvMsg.dst_ip, resvMsg.src_ip))
        else:
            next_hop = routeObject.get_next_hop(self._hostname)
            next_iface = self.find_iface(next_hop)
            if next_iface:
                if rsvp.State_Block.creatRSB(resvMsg, None, None, next_iface):
                    logging.info('%s-RSB created successfully by %s —> lsp_id: %s'%(self._hostname, next_iface.name, resvMsg.lsp_id,))
                    next_iface.transmit(resvMsg)
                else:
                    resvErrMsg = rsvp.ResvErrMsg(resvMsg.lsp_id, resvMsg.dst_ip, resvMsg.src_ip, self._hostname, resvMsg.route)
                    resvErrMsg.route.reverse()
                    self._resvErr(resvErrMsg)            
            # 资源变化，通告LSA消息
            # self._advertise()

    def _pathErr(self, pathErrMsg):
        routeObject = rsvp.RouteObject(pathErrMsg.src_ip, pathErrMsg.dst_ip, pathErrMsg.route)
        if pathErrMsg.dst_ip != self._hostname:
            next_hop = routeObject.get_next_hop(self._hostname)
            next_iface = self.find_iface(next_hop)
            if next_iface:
                    next_iface.transmit(pathErrMsg)
        else:
            logging.info('%s-Error in %s processing pathMsg'%(self._hostname, pathErrMsg.err_msg ))
            pathTearMsg = rsvp.PathTearMsg(pathErrMsg.lsp_id, pathErrMsg.dst_ip, pathErrMsg.src_ip, pathErrMsg.route)
            pathTearMsg.route.reverse()
            self._pathTear(pathTearMsg)


    def _resvErr(self, resvErrMsg):
        routeObject = rsvp.RouteObject(resvErrMsg.src_ip, resvErrMsg.dst_ip, resvErrMsg.route)
        if resvErrMsg.dst_ip != self._hostname:
            next_hop = routeObject.get_next_hop(self._hostname)
            next_iface = self.find_iface(next_hop)
            if next_iface:
                next_iface.transmit(resvErrMsg)
        else:
            logging.info('%s-Error in %s processing resvMsg'%(self._hostname, resvErrMsg.err_msg ))
            resvTearMsg = rsvp.ResvTearMsg(resvErrMsg.lsp_id, resvErrMsg.dst_ip, resvErrMsg.src_ip, resvErrMsg.route)
            resvTearMsg.route.reverse()
            self._resvTear(resvTearMsg)


    def _pathTear(self, pathTearMsg):
        routeObject = rsvp.RouteObject(pathTearMsg.src_ip, pathTearMsg.dst_ip, pathTearMsg.route)
        if pathTearMsg.src_ip != self._hostname:
            prv_hop = routeObject.get_prev_hop(self._hostname)
            pre_iface = self.find_iface(prv_hop)
            if pre_iface:
                if pathTearMsg.lsp_id in pre_iface.psb:
                    pre_iface.psb.pop(pathTearMsg.lsp_id)
                    logging.info('%s-PSB of lsp_id(%s) successfully tear by pathTear'%(self._hostname, pathTearMsg.lsp_id, ))
        if pathTearMsg.dst_ip != self._hostname:
            next_hop = routeObject.get_next_hop(self._hostname)
            next_iface = self.find_iface(next_hop)
            if next_iface:
                if pathTearMsg.lsp_id in next_iface.psb:
                    next_iface.psb.pop(pathTearMsg.lsp_id)
                    logging.info('%s-PSB of lsp_id(%s) successfully tear by pathTear'%(self._hostname, pathTearMsg.lsp_id, ))
                next_iface.transmit(pathTearMsg)
        else:
            logging.info('%s-lsp_psb(id: %s) successfully tear by pathTear'%(self._hostname, pathTearMsg.lsp_id, ))

    def _resvTear(self, resvTearMsg):
        routeObject = rsvp.RouteObject(resvTearMsg.src_ip, resvTearMsg.dst_ip, resvTearMsg.route)
        if resvTearMsg.src_ip != self._hostname:
            prv_hop = routeObject.get_prev_hop(self._hostname)
            pre_iface = self.find_iface(prv_hop)
            if pre_iface:
                if resvTearMsg.lsp_id in pre_iface.rsb:
                    rsvp.Resource.release(pre_iface, resvTearMsg)
                    pre_iface.rsb.pop(resvTearMsg.lsp_id) 
                    logging.info('%s-RSB of lsp_id(%s) successfully tear by resvTear'%(self._hostname, resvTearMsg.lsp_id, ))
                if resvTearMsg.lsp_id in pre_iface.psb:
                    pre_iface.psb.pop(resvTearMsg.lsp_id)
                    logging.info('%s-PSB of lsp_id(%s) successfully tear by resvTear'%(self._hostname, resvTearMsg.lsp_id, ))
        if resvTearMsg.dst_ip != self._hostname:
            next_hop = routeObject.get_next_hop(self._hostname)
            next_iface = self.find_iface(next_hop)
            if next_iface:
                if resvTearMsg.lsp_id in next_iface.rsb:
                    rsvp.Resource.release(next_iface, resvTearMsg)
                    next_iface.rsb.pop(resvTearMsg.lsp_id) 
                    logging.info('%s-RSB of lsp_id(%s) successfully tear by resvTear'%(self._hostname, resvTearMsg.lsp_id, ))
                if resvTearMsg.lsp_id in next_iface.psb:
                    next_iface.psb.pop(resvTearMsg.lsp_id)
                    logging.info('%s-PSB of lsp_id(%s) successfully tear by resvTear'%(self._hostname, resvTearMsg.lsp_id, ))
                next_iface.transmit(resvTearMsg) 
        else:
            prv_hop = routeObject.get_prev_hop(self._hostname)
            pre_iface = self.find_iface(prv_hop)
            if pre_iface:
                pre_iface.conn_del(resvTearMsg.lsp_id)
                logging.info('%s-lsp_psb|rsb(id: %s) successfully tear by resvTear'%(self._hostname, resvTearMsg.lsp_id, ))


class Interface():
    # OSU接口
    def __init__(self, name, bandwidth, port, osu, av_delay=None):
        self.name = name
        self.bandwidth = bandwidth
        self.port = port
        self.osu = osu
        self.address = None
        self.netmask = None
        self.link = None
        self.remote_end_host = None
        self.remote_end_port = None
        self.ava_bw = bandwidth
        self.use_bw = 0
        self.bd_change_rng = 20
        self.av_delay = av_delay
        self.connNum = 0
        self.connection = {}
        self.psb = {}
        self.rsb = {}
        # self.monitor_port_thread()

    def transmit(self, packet):
        # 通过接口发送数据包
        thread_loop = asyncio.new_event_loop()
        t = threading.Thread(target=IfaceTx, args=(thread_loop,self.remote_end_host, self.remote_end_port, packet,))
        t.daemon = True
        t.start()

    # 在没有RSVP的条件下，随机修改端口带宽
    def change_port_bd(self):
        time.sleep(60)
        while True:
            time_sleep = random.randint(1, 10)
            time.sleep(time_sleep)
            rsv_bd = int(self.bandwidth)
            change_bd = random.randint(0, 10)
            self.bandwidth = str(rsv_bd - change_bd) if rsv_bd - change_bd >= 0 else '10000'

    def monitor_port_bd(self):
        current_bd = int(self.bandwidth)
        while True:
            if abs(current_bd - int(self.bandwidth)) > self.bd_change_rng:
                current_bd = int(self.bandwidth)
                logging.info('%s-%s has triggered the flooding, and the bandwidth remained %s'%(self.osu._hostname, self.name, self.bandwidth))
                self.osu._advertise()

    def monitor_port_thread(self):
        change_thread = threading.Thread(target=self.change_port_bd)
        monitor_thread = threading.Thread(target=self.monitor_port_bd)
        change_thread.start()
        monitor_thread.start()

    # 连接管理-插入连接
    def conn_insert(self, lsp_id, conn):
        if lsp_id not in self.connection:
            self.connection[lsp_id] = conn
            self.connNum += 1
            return True
        else:
            return False

    # 连接管理-删除连接
    def conn_del(self, lsp_id):
        if lsp_id in self.connection:
            del self.connection[lsp_id]
            self.connNum -= 1
            return True
        else:
            return False

    # 连接管理-修改连接
    def conn_update(self, lsp_id, conn):
        if lsp_id in self.connection:
            self.connection[lsp_id] = conn
            return True
        else:
            return False

    # 连接管理-查询单条连接
    def conn_find(self, lsp_id):
        if lsp_id in self.connection:
            return self.connection[lsp_id]
        else:
            return False

    # 连接管理-查询所有连接
    def conn_find(self, lsp_id):
        if self.connection:
            return self.connection
        else:
            return False


def sim_run(conf_file_path):
    log.start_thread_logging()
    AdjList = {}
    cp = configparser.ConfigParser()
    cp.read(conf_file_path, encoding='utf-8')
    hostname = cp.get('Local','hostname')
    webSocket_port =  cp.get('WebSocket_port','port')
    osu = OSU(hostname, webSocket_port)

    ifaces = [i for i in cp.sections() if i.startswith('Local:')]
    for iface in ifaces:
        # 创建接口
        name = iface.split(':')[1]
        bandwidth = int(cp.get(iface, 'bandwidth'))
        port = int(cp.get(iface, 'port'))
        try:
            osu.iface_create(name, bandwidth, port)
            logging.info('%s-%s up' % (osu._hostname, name, ))
        except socket.error:
            sys.exit(1)
        # 配置接口
        address = cp.get(iface, 'address')
        netmask = cp.get(iface, 'netmask')
        link = cp.get(iface, 'link')
        host = cp.get(link, 'host')
        port = int(cp.get(link, 'port'))
        osu.iface_config(name, address, netmask, link, host, port)
        bandwidth = int(bandwidth)
        if bandwidth < 1000:
            bandwidth = '%d bps' % (bandwidth, )
        elif bandwidth < 1000000:
            bandwidth = '%.1f kbps' % (bandwidth / 1000.0, )
        elif bandwidth < 1000000000:
            bandwidth = '%.1f Mbps' % (bandwidth / 1000000.0, )
        else:
            bandwidth = '%.1f Gbps' % (bandwidth / 1000000000.0, )
        cols = [name, address, netmask, bandwidth, link]
        for val in cols:
            AdjList.setdefault(cols[0],[]).append(val)
    osu.start()
