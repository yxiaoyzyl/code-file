import heapq
from filecmp import cmp
from collections import defaultdict


class Edge(object):

    def __init__(self, start, end, weight):
        self.start = start
        self.end = end
        self.weight = weight

    # For heapq.
    def __cmp__(self, other):
        return cmp(self.weight, other.weight)


class Graph(object):

    def __init__(self):
        # The adjacency list.
        self.adj = defaultdict(list)

    def add_e(self, start, end, weight=0):
        self.adj[start].append(Edge(start, end, weight))

    def shorest_path(self, src):
        """
        返回从源和数组到每个顶点的距离，数组表示在索引 i 处，在访问节点 i 之前访问过的节点。
        形式 (dist, previous)。
        """
        dist = {src: 0}     # 去往各个目的地所需代价
        visited = []        # 已遍历路由器
        full_path = {}      # 记录去往各个节点的全路径，{'end': [path]}格式
        queue = []
        heapq.heappush(queue, (dist[src], src))     # 将(累计代价，目的地)加入到queue中，形成堆队列
        while queue:
            distance, current = heapq.heappop(queue)
            if current in visited:
                continue
            visited.append(current)

            # 依次遍历邻居节点，找寻代价最小的邻居
            for edge in self.adj[current]:
                # 计算去往邻居的累积代价
                cum_cost = dist[current] + edge.weight
                # 邻居节点
                end = edge.end
                if end not in dist or cum_cost < dist[end]:
                    # 记录完整路径
                    full_path[end] = full_path[current][:-1] + [current, end] if current in full_path else [current, end]
                    dist[end] = cum_cost
                    heapq.heappush(queue, (dist[end], end))
        return dist, full_path
