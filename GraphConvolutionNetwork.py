import math
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F

def init_weights(m):
    classname = m.__class__.__name__
    if classname.find('Conv2d') != -1 or classname.find('ConvTranspose2d') != -1:
        nn.init.kaiming_uniform_(m.weight)
        nn.init.zeros_(m.bias)
    elif classname.find('BatchNorm') != -1:
        nn.init.normal_(m.weight, 1.0, 0.02)
        nn.init.zeros_(m.bias)
    elif classname.find('Linear') != -1:
        nn.init.xavier_normal_(m.weight)
        nn.init.zeros_(m.bias)

class GraphConvolution(nn.Module):
    """
    Document : https://github.com/tkipf/pygcn
               https://github.com/bamos/block
    """

    def __init__(self, in_features, out_features, bias = True):
        '''
        参数解释
        (构造第一层GCN的时候)
        in_features:  64
        out_features: 128

        (构造第二层GCN的时候)
        in_features:  64
        out_features: 128
        '''

        super(GraphConvolution, self).__init__()

        self.in_features = in_features
        self.out_features = out_features

        self.FC = nn.Linear(in_features, out_features) # ! 只定义了一个全连接层？
        self.FC.apply(init_weights) # 初始化

    def forward(self, input, adj):
        '''
        参数解释
        input：对图像提取特征之后的一个tensor，shape是batch * 6 * 64
        adj  ：6 * 6经过初始化后的矩阵
        '''

        batchSize, numOfNode = input.size(0), adj.size(0)
        support = self.FC(input) # support的shape(batch * 6 * 128)
        Adj = adj.repeat(batchSize, 1, 1) # 代表只拓展第一维
        output = torch.bmm(Adj, support) # 将Adj和support矩阵相乘，output的shape（batch，128），这就是paper说的用图像初始化邻接矩阵？

        return output
        
        # In order to support batch operation, we should design a funtion like scipy.linalg.block_diag to bulid Adj Matrix.
        # Adj Matrix should be [batchSize * numNode, batchSize * numNode]

        # Abandoned Code 1:
        # Adj = torch.zeros((numOfNode*batchSize, numOfNode*batchSize), 
        #                   dtype=torch.float, 
        #                   requires_grad=True).cuda() if input.is_cuda else torch.zeros((numOfNode*batchSize, numOfNode*batchSize), 
        #                                                                                dtype=torch.float, 
        #                                                                                requires_grad=True)
        # for index in range(batchSize):
        #     Adj[index*numOfNode:(index+1)*numOfNode, index*numOfNode:(index+1)*numOfNode] = adj
        # output = torch.mm(Adj, support.view(batchSize*numOfNode, -1))
        # output = output.view(batchSize, numOfNode, -1)

        # Abandoned Code 2:
        # Adj = block.block_diag([adj.cpu() for i in range(batchSize)])
        # if input.is_cuda:
        #     Adj = Adj.cuda()
        # output = torch.mm(Adj, support.view(batchSize*numOfNode, -1))
        # output = output.view(batchSize, numOfNode, -1)

class GCN(nn.Module):
    def __init__(self,  dim_in, dim_hid, dim_out, link1=0.8, link2=0.5, link3=0.9, link4=0.4, link5=0.25, mask=None):
        super(GCN, self).__init__()

        assert mask in [None, 'link1', 'link2', 'link3', 'link4', 'link5'], "Mask should be None or link1 or link2 or link3 or link4 or link5."

        self.gcn_1 = GraphConvolution(dim_in, dim_hid)
        self.gcn_2 = GraphConvolution(dim_hid, dim_out)
        self.dropout = nn.Dropout()
        self.relu = nn.ReLU()

        self.link1 = link1 # link 1 : Global-Local (Same Domain)
        self.link2 = link2 # link 2 : Local-Local (Same Domain)
        self.link3 = link3 # link 3 : Corresponding location (Cross Domain)
        self.link4 = link4 # link 4 : Global-Local (Cross Domain)
        self.link5 = link5 # link 5 : Local-Local (Cross Domain)

        adj = np.zeros((12,12))

        # link1
        adj[0, :6] = self.link1
        adj[6, 6:] = self.link1
        adj[:6, 0] = self.link1
        adj[6:, 6] = self.link1

        # link2 
        adj[1:6, 1:6] = self.link2
        adj[7: , 7: ] = self.link2

        # link4
        adj[0, 6:] = self.link4
        adj[6, :6] = self.link4
        adj[:6, 6] = self.link4
        adj[6:, 0] = self.link4

        # link5
        adj[1:6, 7: ] = self.link5
        adj[7: , 1:6] = self.link5
        
        # link3
        for i in range(12):
            adj[i, (i+6)%12] = self.link3

        # self link
        for i in range(12):
            adj[i,i] = 1.0

        self.adj = nn.Parameter(torch.FloatTensor(adj))
            
        if mask is None:
            self.mask = None 
        elif mask=='link1':
            mask = np.ones((12,12))
            mask[0, 1:6] = 0.0
            mask[1:6, 0] = 0.0
            mask[6, 7: ] = 0.0
            mask[7: , 6] = 0.0
            self.mask = torch.FloatTensor(mask)
        elif mask=='link2':
            mask = np.ones((12,12))
            mask[1:6, 1:6] = 0.0
            mask[7: , 7: ] = 0.0
            for i in range(12):
                mask[i,i] = 1.0
            self.mask = torch.FloatTensor(mask)
        elif mask=='link3':
            mask = np.ones((12,12))
            for i in range(12):
                mask[i, (i+6)%12] = 0.0
            self.mask = torch.FloatTensor(mask)
        elif mask=='link4':
            mask = np.ones((12,12))
            mask[0, 7: ] = 0.0
            mask[6, 1:6] = 0.0
            mask[1:6, 6] = 0.0
            mask[7: , 0] = 0.0
            self.mask = torch.FloatTensor(mask)
        elif mask=='link5':
            mask = np.ones((12,12))
            mask[1:6, 7: ] = 0.0
            mask[7: , 1:6] = 0.0
            self.mask = torch.FloatTensor(mask)

    def forward(self, x):

        if self.mask is None:
            adj = self.adj
        else:
            adj = self.adj * self.mask

        x = self.gcn_1(x, adj)
        x = self.relu(x)
        x = self.dropout(x)
        x = self.gcn_2(x, adj)
        return x

class GCNwithIntraAndInterMatrix(nn.Module):
    def __init__(self, dim_in, dim_hid, dim_out,
                 Link1=0.8, Link2=0.5, Link3=0.9, Link4=0.4, Link5=0.25,
                 useIntraGCN=True, useInterGCN=True, useRandomMatrix=False, useAllOneMatrix=False):
        '''
        参数解释
        dim_in : 64
        dim_hid: 128
        dim_out: 64
        link1:
        link2:
        link3:
        link4:
        link5:
        useIntroGCN: true
        useInterGCN: true
        useRandomMatirx: false
        useAllOneMatrix: false
        '''

        super(GCNwithIntraAndInterMatrix, self).__init__()

        self.useIntraGCN = useIntraGCN
        self.useInterGCN = useInterGCN
        self.useRandomMatrix = useRandomMatrix
        self.useAllOneMatrix = useAllOneMatrix

        # 定义了两层GCN
        self.IntraGCN_1 = GraphConvolution(dim_in, dim_hid)
        self.IntraGCN_2 = GraphConvolution(dim_hid, dim_out)

        self.InterGCN = GraphConvolution(dim_out, dim_out) # ! 为什么这个只有一层

        self.Dropout = nn.Dropout()
        self.ReLU = nn.ReLU()

        self.Link1 = Link1 # Link 1 : Global-Local (Same Domaim)
        self.Link2 = Link2 # Link 2 : Local-Local (Same Domain)
        self.Link3 = Link3 # Link 3 : Corresponding location (Cross Domain)
        self.Link4 = Link4 # Link 4 : Global-Local (Cross Domain)
        self.Link5 = Link5 # Link 5 : Local-Local (Cross Domain)

        # ! Intra Adjacency Matrix 域内邻接矩阵  为什么邻接矩阵的shape是6*6
        if self.useRandomMatrix:  # 给邻矩阵随机赋0~1间的随机浮点数
            IntraAdjMatrix = torch.rand((6, 6), dtype=torch.float, requires_grad=True)
        elif self.useAllOneMatrix:# 全部置1
            IntraAdjMatrix = torch.ones((6, 6), dtype=torch.float, requires_grad=True)
        else: # ! 否则直接置0,然后根据预设值进行修改，为什么要进行这样的初始化呢？？？？？
            IntraAdjMatrix = torch.zeros((6, 6), dtype=torch.float, requires_grad=True)
            
            # Link 1 : Global-Local (Same Domain)
            IntraAdjMatrix[0, 1:] = self.Link1
            IntraAdjMatrix[1:, 0] = self.Link1

            # Link 2 : Local-Local (Same Domain)
            IntraAdjMatrix[1:, 1:] = self.Link2

            # Self Link 自我相连
            for i in range(6):
                IntraAdjMatrix[i, i] = 1.0

        self.IntraAdjMatrix = nn.Parameter(IntraAdjMatrix, requires_grad=True)

        # Inter Adjacency Matrix
        if self.useRandomMatrix:
            InterAdjMatrix = torch.rand((12, 12), dtype=torch.float, requires_grad=True)
        elif self.useAllOneMatrix:
            InterAdjMatrix = torch.ones((12, 12), dtype=torch.float, requires_grad=True)
        else:
            InterAdjMatrix = torch.zeros((12, 12), dtype=torch.float, requires_grad=True)

            # Link 4 : Global-Local (Cross Domain)
            InterAdjMatrix[0, 7:] = self.Link4
            InterAdjMatrix[1:6, 6] = self.Link4

            InterAdjMatrix[6, 1:6] = self.Link4
            InterAdjMatrix[7:, 0] = self.Link4

            # Link 5 : Local-Local (Cross Domain)
            InterAdjMatrix[1:6, 7:] = self.Link5
            InterAdjMatrix[7:, 1:6] = self.Link5

            # Link 3 : Corresponding location (Cross Domain)
            for i in range(12):
                InterAdjMatrix[i, (i+6) % 12] = self.Link3

            # Self Link
            for i in range(12):
                InterAdjMatrix[i, i] = 1.0

        self.InterAdjMatrix = nn.Parameter(InterAdjMatrix, requires_grad=True)

        # Inter Mask Matrix
        InterMaskMatrix = torch.ones((12, 12), dtype=torch.float, requires_grad=False)

        InterMaskMatrix[:6, :6] = 0
        InterMaskMatrix[6:, 6:] = 0

        for i in range(12):
            InterMaskMatrix[i,i] = 1

        self.register_buffer('InterMaskMatrix', InterMaskMatrix)        

    def forward(self, feature): # Size of feature : Batch * 12 * 64

        # Update Intra/Inter Adj Matrix 
        self.InterAdjMatrix.data.copy_(self.InterAdjMatrix * self.InterMaskMatrix) 
        '''
        A.copy_（B*C）这里有两个key points
        B * C: 就是将B和C矩阵中的每个对应位置的值直接相乘，因此B和C的shape必须完全一样
        copy_: 就是将B*C的结果复制到A中
        '''
        self.IntraAdjMatrix.data.clamp_(min=0) # clamp_的作用是将tensor中小于min的值变为min
        self.InterAdjMatrix.data.clamp_(min=0)

        self.IntraAdjMatrix.data.copy_(self.IntraAdjMatrix / self.IntraAdjMatrix.sum(dim=1, keepdim=True))      
        self.InterAdjMatrix.data.copy_(self.InterAdjMatrix / self.InterAdjMatrix.sum(dim=1, keepdim=True))

        # Get Source/Target Feature(把feature划分成两部分)
        SourceFeature = feature.narrow(1, 0, 6)  # Batch * 6 * 64 把第二维的前6个赋值给Source
        TargetFeature = feature.narrow(1, 6, 6)  # Batch * 6 * 64

        # Intra GCN
        if self.useIntraGCN:
            SourceFeature = self.IntraGCN_1(SourceFeature, self.IntraAdjMatrix)  # Batch * 6 * 128
            SourceFeature = self.Dropout(self.ReLU(SourceFeature))               # Batch * 6 * 128
            SourceFeature = self.IntraGCN_2(SourceFeature, self.IntraAdjMatrix)  # Batch * 6 * 64

            TargetFeature = self.IntraGCN_1(TargetFeature, self.IntraAdjMatrix)  # Batch * 6 * 128
            TargetFeature = self.Dropout(self.ReLU(TargetFeature))               # Batch * 6 * 128
            TargetFeature = self.IntraGCN_2(TargetFeature, self.IntraAdjMatrix)  # Batch * 6 * 64

        # Concate Source/Target Feature 重新汇集两个特征图
        Feature = torch.cat((SourceFeature, TargetFeature), 1)  # Batch * 12 * 64

        # Inter GCN
        if self.useInterGCN:
            Feature = self.InterGCN(Feature, self.InterAdjMatrix) # Batch * 12 * 64

        return Feature
