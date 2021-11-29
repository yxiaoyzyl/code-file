import random
import time
from matplotlib import pyplot
import matplotlib.pyplot as plt

BANDWIDTH_UP_LIMIT = 100000

class flow():

    def __init__(self, timeStamp, src_ip, dst_ip, bandwidth, bw_up_limit):
        self.timeStamp = timeStamp
        self.src_ip = src_ip
        self.dst_ip = dst_ip
        self.bandwidth = bandwidth
        self.bw_up_limit = bw_up_limit

    def print(self):
        print("timeStamp:%s \tsrc_ip:%s \tdst_ip:%s \tbandwidth:%s \tbw_up_limit:%s"\
            %(self.timeStamp, self.src_ip, self.dst_ip, self.bandwidth, self.bw_up_limit))

class flowGenerator():
    def generator(current_ip):
        flows = []
        timeStamp = time.time()
        src_ip = current_ip
        OSU_ip = ['OSU1', 'OSU2', 'OSU3', 'OSU4', 'OSU5']
        OSU_ip.remove(src_ip)
        for i in range(random.randint(0, 10)):
            dst_ip = OSU_ip[random.randint(0, len(OSU_ip)-1)]
            bandwidth = random.randint(750, 1250)
            conn_num = random.randint(80, 200)
            #bw_up_limit = int(BANDWIDTH_UP_LIMIT / conn_num)
            bw_up_limit=1250
            # f = flow(timeStamp, src_ip, dst_ip, bandwidth, bw_up_limit)
            f = [timeStamp, src_ip, dst_ip, bandwidth, bw_up_limit]
            flows.append(f)
        return flows

class flowpredictor:
    def predict(data,pre,w): 
        if len(data)==1 :
            data[0].append(0)            
        step=2
        data.insert(len(data),[data[len(data)-1][0]+0.5,0,0,0,0])
        i=len(data)-2
        if(i==0):
            a,t1=0,0
        else:
            a = data[i - 1][3]
            t1 = data[i - 1][0]
        b = data[i][3]
        t2 = data[i][0]
        k = (b - a) / (t2 - t1)
        N=data[i][4]
        if a<b:
            if b < w:
                x = b ** 2
                if x <= w:
                    result = x
                    data[i+1].append(result)
                else:
                    x1 = k * (t2 - t1) + b
                if x1 >= N:
                    w = N
                    result = w
                    data[i+1].append(result)
                else:
                    result = x1
                    data[i+1].append(result)
            else:
                x1 = k * (t2 - t1) + b
                if x1 >= N:
                    w = N
                    result = w
                    data[i+1].append(result)
                else:
                    result = x1
                    data[i+1].append(result)
        else:
            x1 = k * (t2 - t1) + b
            result = x1
            data[i+1].append(result)
        if abs(data[i+1][5]-b)<=step/2 :
            if data[i+1][5]>b:
                data[i+1][5]=b+step
            else:
                data[i+1][5]=b-step
        else:
            if data[i+1][5]>b:
                data[i+1][5]=b+round(abs(data[i+1][5]-b)/step)*step
            else:
                data[i+1][5]=b-round(abs(data[i+1][5]-b)/step)*step
        if data[i+1][5] <= 700:
            data[i+1][5] = 700
        if len(data)>2:
            data[len(data)-2].append(pre) 
        return data,w

    def showflowpre(data):
        #data=flowpredictor.predict(data)     
        times=[j[0] for j in data]
        actual=[j[3] for j in data]
        predicted=[j[5] for j in data]
        plt.plot(times[0:len(data)-1], actual[0:len(data)-1], marker='o', mec='r', mfc='w', label='actual flow')
        plt.plot(times[1:len(data)], predicted[1:len(data)], marker='*', ms=10, label='predicted flow')
        plt.legend()  # 让图例生效
        #plt.xticks([j[0] for j in data], names, rotation=1)
        plt.xticks([j[0] for j in data])
        #plt.yticks([0,100,200,300,400,500,600,700,800,900,1000,1100,1200,1300,1400,1500])
        plt.ylim(0,1500)
        plt.margins(0)
        #plt.subplots_adjust(bottom=0.10)
        plt.xlabel('times')  # X轴标签
        plt.ylabel("bandwidth")  # Y轴标签
        #plt.autoscale(enable=True, axis='both', tight=None)
        #pyplot.yticks([j[3] for j in data])
        plt.title("Comparison between actual flow and predicted flow of {}".format(data[0][2])) #标题
        plt.savefig("./{}flow.jpg".format(data[0][2]))
        plt.clf()


if __name__ == '__main__':
    OSU1data,OSU2data,OSU3data,OSU4data,OSU5data=[],[],[],[],[]
    count=0
    w1,w2,w3,w4,w5=1500,1500,1500,1500,1500
    while True:
        current_ip = 'OSU1'
        flows = flowGenerator.generator(current_ip)
        OSU1count,OSU2count,OSU3count,OSU4count,OSU5count=0,0,0,0,0
        pre1,pre2,pre3,pre4,pre5=0,0,0,0,0
        for i in range(len(flows)):
            if flows[i][2]=="OSU1":
                OSU1count=OSU1count+1
                if OSU1count>0:
                    continue
                    # OSU1data[len(OSU1data)-1][4]=flows[i][4]+flows[i-1][4]
                    # OSU1data[len(OSU1data)-1][3]=flows[i][3]+flows[i-1][3]
                else :
                    if len(OSU1data)>1:
                        pre1=OSU1data[len(OSU1data)-1][5]
                        del OSU1data[len(OSU1data)-1]
                    print("加上OSU1的数据是：{}".format(flows[i]))
                    OSU1data.append(flows[i])
                    flowpre1,w1=flowpredictor.predict(OSU1data,pre1,w1)
                    print("预测后的OSU1data：{}".format(flowpre1))
            elif flows[i][2]=="OSU2":
                OSU2count=OSU2count+1
                if OSU2count>1:
                    continue
                    OSU2data[len(OSU2data)-1][4]=flows[i][4]+flows[i-1][4]
                    OSU2data[len(OSU2data)-1][3]=flows[i][3]+flows[i-1][3]
                else :
                    if len(OSU2data)>1:
                        pre2=OSU2data[len(OSU2data)-1][5]
                        del OSU2data[len(OSU2data)-1]
                    print("加上OSU2数据是：{}".format(flows[i]))
                    OSU2data.append(flows[i])
                    flowpre2,w2=flowpredictor.predict(OSU2data,pre2,w2)                   
                    print("预测后的OSU2data：{}".format(flowpre2))
            elif flows[i][2]=="OSU3":
                OSU3count=OSU3count+1
                if OSU3count>1:
                    continue
                    OSU3data[len(OSU3data)-1][4]=flows[i][4]+flows[i-1][4]
                    OSU3data[len(OSU3data)-1][3]=flows[i][3]+flows[i-1][3]
                else :
                    if len(OSU3data)>1:
                        pre3=OSU3data[len(OSU3data)-1][5]
                        del OSU3data[len(OSU3data)-1]
                    print("加上OSU3的数据是：{}".format(flows[i]))
                    OSU3data.append(flows[i])
                    flowpre3,w3=flowpredictor.predict(OSU3data,pre3,w3)
                    print("预测后的OSU3data：{}".format(flowpre3))
            elif flows[i][2]=="OSU4":
                OSU4count=OSU4count+1
                if OSU4count>1:
                    continue
                    OSU4data[len(OSU4data)-1][4]=flows[i][4]+flows[i-1][4]
                    OSU4data[len(OSU4data)-1][3]=flows[i][3]+flows[i-1][3]
                else :
                    if len(OSU4data)>1:
                        pre4=OSU4data[len(OSU4data)-1][5]
                        del OSU4data[len(OSU4data)-1]
                    print("加上OSU4的数据是：{}".format(flows[i]))
                    OSU4data.append(flows[i])
                    flowpre4,w4=flowpredictor.predict(OSU4data,pre4,w4)
                    print("预测后的OSU4data：{}".format(flowpre4))
            elif flows[i][2]=="OSU5":
                OSU5count=OSU5count+1
                if OSU5count>1:
                    continue
                    OSU5data[len(OSU5data)-1][4]=flows[i][4]+flows[i-1][4]
                    OSU5data[len(OSU5data)-1][3]=flows[i][3]+flows[i-1][3]
                else :
                    if len(OSU5data)>1:
                        pre5=OSU5data[len(OSU5data)-1][5]
                        del OSU5data[len(OSU5data)-1]
                    print("加上OSU5的数据是：{}".format(flows[i]))
                    OSU5data.append(flows[i])
                    flowpre5,w5=flowpredictor.predict(OSU5data,pre5,w5)
                    print("预测后的OSU5data：{}".format(flowpre5))
            print("------------------------------")
        count=count+1
        if count==50:
            break
        print("---------------------------------------------------------------------------------------------------------------------------------------------------------------------")
        time.sleep(0.5)        
        # timeArray=time.localtime()
        # otherStyleTime = time.strftime("%Y-%m-%d %H:%M:%S", timeArray)
        # print(otherStyleTime)    
    flowpredictor.showflowpre(flowpre2)
    flowpredictor.showflowpre(flowpre3)
    flowpredictor.showflowpre(flowpre4)
    flowpredictor.showflowpre(flowpre5)
#    for i in range(len(flows)):
#        flows[i].print()