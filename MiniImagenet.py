import os
import torch
from torch.utils.data import Dataset
from torchvision.transforms import transforms
import numpy as np
import collections
from PIL import Image
import csv
import random

import pandas
from utils.print import highlight

class MiniImagenet(Dataset):
    """
    put mini-imagenet files as :
    root :
        |- images/*.jpg includes all imgeas
        |- train.csv
        |- test.csv
        |- val.csv
    NOTICE: meta-learning is different from general supervised learning, especially the concept of batch and set.
    batch: contains several sets
    sets: conains n_way * k_shot for meta-train set, n_way * n_query for meta-test set.

    how to download dataset:
        * step 0 : download data (choose one)
            * https://drive.google.com/open?id=1HkgrkAwukzEZA0TpO7010PkAOREb2Nuk
            * https://www.dropbox.com/s/ed1s1dgei9kxd2p/mini-imagenet.zip?dl=0
        * step 1 : extract the data
            `unzip mini-imagenet.zip miniimagenet`
            (there would be a "images" folder in miniimagenet after extracted)
        * step 2 : download label
            * https://github.com/twitter/meta-learning-lstm/tree/master/data/miniImagenet
        * step 3 : put label data inside miniimagenet folder
    """

    def __init__(self, root, mode, batchsz, n_way, k_shot, k_query, resize, startidx=0):
        """

        :param root: root path of mini-imagenet
        :param mode: train, val or test
        :param batchsz: batch size of sets, not batch of imgs
        :param n_way:
        :param k_shot:
        :param k_query: num of qeruy imgs per class
        :param resize: resize to
        :param startidx: start to index label from startidx
        """

        self.batchsz = batchsz  # batch of set, not batch of imgs
        self.n_way = n_way  # n-way
        self.k_shot = k_shot  # k-shot
        self.k_query = k_query  # for evaluation (meta-test)
        self.setsz = self.n_way * self.k_shot  # num of samples per set
        self.querysz = self.n_way * self.k_query  # number of samples per set for evaluation
        self.resize = resize  # resize to
        self.startidx = startidx  # index label not from 0, but from startidx
        print('shuffle DB :%s, b:%d, %d-way, %d-shot, %d-query, resize:%d' % (
        mode, batchsz, n_way, k_shot, k_query, resize))

        if mode == 'train':
            self.transform = transforms.Compose([lambda x: Image.open(x).convert('RGB'),
                                                 transforms.Resize((self.resize, self.resize)),
                                                 # transforms.RandomHorizontalFlip(),
                                                 # transforms.RandomRotation(5),
                                                 transforms.ToTensor(),
                                                 transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
                                                 ])
        else:
            self.transform = transforms.Compose([lambda x: Image.open(x).convert('RGB'),
                                                 transforms.Resize((self.resize, self.resize)),
                                                 transforms.ToTensor(),
                                                 transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
                                                 ])

        self.path = os.path.join(root, 'images')  # image path

        # csv file:
        #   filename                , label
        #   n01532829000000005.jpg  , n01532829
        #   n01532829000000006.jpg  , n01532829
        # csvdata is dictionary , key is label, value is all the filename
        print(highlight('\tLoad CSV file : ' + os.path.join(root, mode + '.csv'), 'green' ))
        csvdata = self.loadCSV(os.path.join(root, mode + '.csv'))  # csv path
        #print('\t',type(csvdata), len(csvdata.keys()), end='\n\n')

        # all img names
        # [
        #   [ 'img1', 'img2' ...], # first class
        #   [ 'img3', 'img4' ...], # second class
        # ]
        self.data = []
        self.img2label = {}

        for i, (label, imgs) in enumerate(csvdata.items()):

            self.data.append(imgs)  # [[img1, img2, ...], [img111, ...]]
            self.img2label[label] = i + self.startidx  # {"img_name[:9]":label}

        # total classes
        self.cls_num = len(self.data)

        self.create_batch(self.batchsz)

        # import pdb
        # pdb.set_trace()
    def loadCSV(self, csvf):
        """
        return a dict saving the information of csv
        :param splitFile: csv file name
        :return: {label:[file1, file2 ...]}
        """

        # pandas is too nice!
        # groupby('label')['filename'].apply(list) this would be dataFrame

        dictLabels_v2 = pandas.read_csv(csvf).groupby('label')['filename'].apply(list).to_dict()

        dictLabels = {}
        with open(csvf) as csvfile:
            csvreader = csv.reader(csvfile, delimiter=',')
            next(csvreader, None)  # skip (filename, label)
            for i, row in enumerate(csvreader):
                filename = row[0]
                label = row[1]
                # append filename to current label
                if label in dictLabels.keys():
                    dictLabels[label].append(filename)
                else:
                    dictLabels[label] = [filename]

        return dictLabels

    def create_batch(self, batchsz):
        """
        create batch for meta-learning.
        ×episode× here means batch, and it means how many sets we want to retain.
        :param batchsz: batch size
        :return:
        """
        self.support_x_batch = []  # support set batch
        self.query_x_batch = []  # query set batch
        for b in range(batchsz):  # for each batch
            # 1.select n_way classes randomly
            #   replace=False means no duplicate
            selected_cls = np.random.choice(self.cls_num, self.n_way, replace=False)
            np.random.shuffle(selected_cls)

            support_x = []
            query_x = []
            for cls in selected_cls:
                # 2. select k_shot + k_query for each class
                selected_imgs_idx = np.random.choice(len(self.data[cls]), self.k_shot + self.k_query, False)
                np.random.shuffle(selected_imgs_idx)
                indexDtrain = np.array(selected_imgs_idx[:self.k_shot])  # idx for Dtrain
                indexDtest = np.array(selected_imgs_idx[self.k_shot:])  # idx for Dtest
                support_x.append(
                    np.array(self.data[cls])[indexDtrain].tolist())  # get all images filename for current Dtrain
                query_x.append(np.array(self.data[cls])[indexDtest].tolist())

                # shuffle the correponding relation between support set and query set
            random.shuffle(support_x)
            random.shuffle(query_x)

            self.support_x_batch.append(support_x)  # append set to current sets
            self.query_x_batch.append(query_x)  # append sets to current sets

        # support_x_batch looks like
        # [
        #   [ first batch
        #       [ 5 ways
        #           ['img1'], 1 shot
        #           ['img6'], 1 shot
        #           ['img4'], 1 shot
        #           ['img3'], 1 shot
        #           ['img5'], 1 shot
        #       ]
        #   ],
        #   [ second batch
        #   ],...
        # ]


    def __getitem__(self, index):
        """
        index means index of sets, 0<= index <= batchsz-1
        :param index:
        :return:
        """
        # self.setsz : num of samples per set
        # self.resize : Resize to

        # [setsz, 3, resize, resize]
        support_x = torch.FloatTensor(self.setsz, 3, self.resize, self.resize)

        # [setsz]
        support_y = np.zeros((self.setsz), dtype=np.int)

        # [querysz, 3, resize, resize]
        query_x = torch.FloatTensor(self.querysz, 3, self.resize, self.resize)

        # [querysz]
        query_y = np.zeros((self.querysz), dtype=np.int)

# len(self.support_x_batch[index]) == n_way
# len(self.support_x_batch[index][0]) == k_shot
# len(flatten_support_x) == n_way * k_shot
        flatten_support_x = [os.path.join(self.path, item)
                             for sublist in self.support_x_batch[index] for item in sublist]

# print('flatten support x size',len(flatten_support_x))
# print('support x batch item size',len(self.support_x_batch[index]))
# print('support x item of item size ', len(self.support_x_batch[index][0]))

        support_y = np.array(
            [self.img2label[item[:9]]  # filename:n0153282900000005.jpg, the first 9 characters treated as label
             for sublist in self.support_x_batch[index] for item in sublist]).astype(np.int32)

        flatten_query_x = [os.path.join(self.path, item)
                           for sublist in self.query_x_batch[index] for item in sublist]
        query_y = np.array([self.img2label[item[:9]]
                            for sublist in self.query_x_batch[index] for item in sublist]).astype(np.int32)

# print('global:', support_y, query_y)

        # support_y: [setsz]
        # query_y: [querysz]
        # unique(remove duplicated) size [n-way] : would return a sorted result
        #   so we need shuffle again
        unique = np.unique(support_y )
        random.shuffle(unique)

        # relative means the label ranges from 0 to n-way
        support_y_relative = np.zeros(self.setsz)
        query_y_relative = np.zeros(self.querysz)
        for idx, l in enumerate(unique):
            support_y_relative[support_y == l] = idx
            query_y_relative[query_y == l] = idx

# print('relative:', support_y_relative, query_y_relative)

        # open image & transform here
        for i, path in enumerate(flatten_support_x):
            support_x[i] = self.transform(path)

        for i, path in enumerate(flatten_query_x):
            query_x[i] = self.transform(path)

# print(support_set_y)
# return support_x, torch.LongTensor(support_y), query_x, torch.LongTensor(query_y)

        return support_x, torch.LongTensor(support_y_relative), query_x, torch.LongTensor(query_y_relative)

    def __len__(self):
        # as we have built up to batchsz of sets, you can sample some small batch size of sets.
        return self.batchsz


if __name__ == '__main__':
    # the following episode is to view one set of images via tensorboard.
    from torchvision.utils import make_grid
    from matplotlib import pyplot as plt
    from tensorboardX import SummaryWriter
    import time

    plt.ion()

    tb = SummaryWriter('runs', 'mini-imagenet')
    mini = MiniImagenet('../../data/miniimagenet/', mode='train', n_way=6, k_shot=3, k_query=2, batchsz=1000, resize=168)

    for i, set_ in enumerate(mini):
        # support_x: [k_shot*n_way, 3, 84, 84]
        support_x, support_y, query_x, query_y = set_

        support_x = make_grid(support_x, nrow=3)
        query_x = make_grid(query_x, nrow=4)

        fig, ax = plt.subplots(1,2)



        ax[0].imshow(support_x.transpose(2, 0).numpy())

        ax[1].imshow(query_x.transpose(2, 0).numpy())

        plt.pause(0.5)

        tb.add_image('support_x', support_x)
        tb.add_image('query_x', query_x)

        time.sleep(5)

    tb.close()
