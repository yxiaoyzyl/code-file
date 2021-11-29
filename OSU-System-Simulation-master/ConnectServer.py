import asyncio
import osuSim
import websockets
from websockets.exceptions import ConnectionClosed


# 1、接收客户端消息并处理
async def recv_client_msg(websocket, osu):
    try:
        packet = await websocket.recv()
        recv_packet = eval(packet.decode())
        if 'conn_msg_type' in recv_packet.keys():
            if recv_packet['conn_msg_type'] == '0x01':
                osuSim.Control.creat_conn(osu, recv_packet)

        # src_ip = recv_packet['src_ip']
        # dst_ip = recv_packet['dst_ip']
        # bandwidth = recv_packet['bandwidth']
        # Pack_Number = recv_packet['Pack_Number']

        # response_packet = f"{Pack_Number}、【增加业务】:  源地址{src_ip} 目的地址{dst_ip} 占用带宽{bandwidth}"
        # print(f"\n{response_packet}")
        # await websocket.send(response_packet)
    except ConnectionClosed:
        pass
 

# 2、服务器端主逻辑
#    websocket和path是该函数被回调时自动传过来的，不需要自己传
async def ConServer_logic(osu, websocket, path):
    # print(path)
    await recv_client_msg(websocket, osu)
