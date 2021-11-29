# 2-【1】
# 文件名称：NetManager.py
# 文件功能：网络连接的管理和维护
#        （1）定义发送数据包 （2）定义数据发送方法 （3）定义消息接收处理办法


import time
import asyncio
import threading
import websockets

# 全局变量
Pack_Number=0
# 字典：存储所有业务连接
"""
car_list = []
Service_Connection_dict={ 'uuid': 'tkhllluuuid', 
                          'src_ip': 'OSU3', 
                          'dst_ip': 'OSU5', 
                          'bandwidth': 520,
                          'real_bandwidth': 123
                        }
"""

# 1、数据包结构声明
class NetManagMsg:
    def __init__(self, src_ip, dst_ip, bandwidth, Pack_Number):
        self.conn_msg_type = '0x01'      # 增加业务：0x01 （后续删除业务、修改业务可以继续扩展）
        self.src_ip = src_ip             # 源地址
        self.dst_ip = dst_ip             # 目的地址
        self.bandwidth = bandwidth       # 业务占用带宽大小
        self.Pack_Number = Pack_Number   # 业务计数  


# 2、数据发送方法
async def NetTransmit(websocket, packet):
     # websocket发送数据包
     packet = str(packet.__dict__)          #对象转字符串
     await websocket.send(packet.encode())  #字符串编码再发送



# 3、设置websocket通信的服务器 IP、Port
async def SetSeverPort(src_ip):
     #src_ip = packet['src_ip']
     if src_ip=='OSU1':
          OSU_PORT = "1028"
     elif src_ip=='OSU2':
          OSU_PORT = "2002"
     elif src_ip=='OSU3':
          OSU_PORT = "3002"    
     elif src_ip=='OSU4':
          OSU_PORT = "4002"
     elif src_ip=='OSU5':
          OSU_PORT = "5001"
     else:
          print(" 起始OSU 不存在 ")
          pass
     return OSU_PORT   



# 4、客户端主逻辑 
async def main_logic():
   
     # 3-1、实例化一个包，一直循环发 （起始带端口/目的端口/带宽）
     global Pack_Number   #全局变量
     Pack_Number += 1
     print(f"\n发包序号：{Pack_Number}")
     packet = NetManagMsg('OSU3','OSU5',500,Pack_Number)
     src_ip = packet.src_ip

     # 3-2、设置socket通信的服务器 IP、Port
     OSU_PORT = await SetSeverPort(src_ip)

     # 3-3、连接到服务器  'ws://localhost:1028'
     async with websockets.connect('ws://localhost:' + OSU_PORT) as websocket:
          # 3-4、发送数据包
          await NetTransmit(websocket, packet)
     time.sleep(1)         #延时1s
     return Pack_Number    #返回修改结果给全局变量
    


# 【循环执行】
while True:  
     asyncio.get_event_loop().run_until_complete(main_logic())