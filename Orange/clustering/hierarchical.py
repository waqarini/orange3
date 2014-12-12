from collections import namedtuple, deque
from operator import attrgetter
import heapq
import numpy

import Orange.distance

import scipy.cluster.hierarchy

SINGLE = "single"
AVERAGE = "average"
COMPLETE = "complete"
WEIGHTED = "weighted"
WARD = "ward"


def condensedform(X, mode="upper"):
    X = numpy.asarray(X)
    assert len(X.shape) == 2
    assert X.shape[0] == X.shape[1]

    N = X.shape[0]

    if mode == "upper":
        i, j = numpy.triu_indices(N, k=1)
    elif mode == "lower":
        i, j = numpy.tril_indices(N, k=-1)
    else:
        raise ValueError("invalid mode")
    return X[i, j]


def squareform(X, mode="upper"):
    X = numpy.asarray(X)
    k = X.shape[0]
    N = int(numpy.ceil(numpy.sqrt(k * 2)))
    assert N * (N - 1) // 2 == k
    matrix = numpy.zeros((N, N), dtype=X.dtype)
    if mode == "upper":
        i, j = numpy.triu_indices(N, k=1)
        matrix[i, j] = X
        m, n = numpy.tril_indices(N, k=-1)
        matrix[m, n] = matrix.T[m, n]
    elif mode == "lower":
        i, j = numpy.tril_indices(N, k=-1)
        matrix[i, j] = X
        m, n = numpy.triu_indices(N, k=1)
        matrix[m, n] = matrix.T[m, n]
    return matrix


def data_clustering(data, distance=Orange.distance.Euclidean,
                    linkage=AVERAGE):
    """
    Return the hierarchical clustering of the data set's rows.

    :param Orange.data.Table data: Data set to cluster.
    :param Orange.distance.Distance distance: A distance measure.
    :param str linkage:
    """
    matrix = distance(data)
    return dist_matrix_clustering(matrix, linkage=linkage)


def feature_clustering(data, distance=Orange.distance.PearsonR,
                       linkage=AVERAGE):
    """
    Return the hierarchical clustering of the data set's columns.

    :param Orange.data.Table data: Data set to cluster.
    :param Orange.distance.Distance distance: A distance measure.
    :param str linkage:
    """
    matrix = distance(data, axis=1)
    return dist_matrix_clustering(matrix, linkage=linkage)


def dist_matrix_clustering(matrix, linkage=AVERAGE):
    """
    Return the hierarchical clustering using a precomputed distance matrix.

    :param Orange.misc.DistMatrix matrix:
    :param str linkage:
    """
    # Extract compressed upper triangular distance matrix.
    distances = condensedform(matrix.X)
    Z = scipy.cluster.hierarchy.linkage(distances, method=linkage)
    return tree_from_linkage(Z)


def sample_clustering(X, linkage=AVERAGE, metric="euclidean"):
    assert len(X.shape) == 2
    Z = scipy.cluster.hierarchy.linkage(X, method=linkage, metric=metric)
    return tree_from_linkage(Z)


Tree = namedtuple("Tree", ["value", "branches"])

ClusterData = namedtuple("Cluster", ["range", "height"])
SingletonData = namedtuple("Singleton", ["range", "height", "index"])


class _Ranged(object):

    @property
    def first(self):
        return self.range[0]

    @property
    def last(self):
        return self.range[-1]


class ClusterData(ClusterData, _Ranged):
    __slots__ = ()


class SingletonData(SingletonData, _Ranged):
    __slots__ = ()


class Tree(Tree):
    def __new__(cls, value, branches=()):
        if not isinstance(branches, tuple):
            raise TypeError()

        return super().__new__(cls, value, branches)

    @property
    def is_leaf(self):
        return not bool(self.branches)

    @property
    def left(self):
        return self.branches[0]

    @property
    def right(self):
        return self.branches[-1]


def tree_from_linkage(linkage):
    """
    Return a Tree representation of a clustering encoded in a linkage matrix.

    .. seealso:: scipy.cluster.hierarchy.linkage

    """
    T = {}
    N, _ = linkage.shape
    N = N + 1
    order = []
    for i, (c1, c2, d, _) in enumerate(linkage):
        if c1 < N:
            left = Tree(SingletonData(range=(len(order), len(order) + 1),
                                      height=0.0, index=int(c1)),
                        ())
            order.append(c1)
        else:
            left = T[c1]

        if c2 < N:
            right = Tree(SingletonData(range=(len(order), len(order) + 1),
                                       height=0.0, index=int(c2)),
                         ())
            order.append(c2)
        else:
            right = T[c2]

        t = Tree(ClusterData(range=(left.value.first, right.value.last),
                             height=d),
                 (left, right))
        T[N + i] = t

    root = T[N + N - 2]
    T = {}

    leaf_idx = 0
    for node in postorder(root):
        if node.is_leaf:
            T[node] = Tree(
                node.value._replace(range=(leaf_idx, leaf_idx + 1)), ())
            leaf_idx += 1
        else:
            left, right = T[node.left].value, T[node.right].value
            assert left.first < right.first

            t = Tree(
                node.value._replace(range=(left.range[0], right.range[1])),
                tuple(T[ch] for ch in node.branches)
            )
            assert t.value.range[0] <= t.value.range[-1]
            assert left.first == t.value.first and right.last == t.value.last
            assert t.value.first < right.first
            assert t.value.last > left.last
            T[node] = t

    return T[root]


def postorder(tree, branches=attrgetter("branches")):
    stack = deque([tree])
    visited = set()

    while stack:
        current = stack.popleft()
        children = branches(current)
        if children:
            # yield the item on the way up
            if current in visited:
                yield current
            else:
                # stack = children + [current] + stack
                stack.extendleft([current])
                stack.extendleft(reversed(children))
                visited.add(current)

        else:
            yield current
            visited.add(current)


def preorder(tree, branches=attrgetter("branches")):
    stack = deque([tree])
    while stack:
        current = stack.popleft()
        yield current
        children = branches(current)
        if children:
            stack.extendleft(reversed(children))


def leaves(tree, branches=attrgetter("branches")):
    """
    Return an iterator over the leaf nodes in a tree structure.
    """
    return (node for node in postorder(tree, branches)
            if node.is_leaf)


def prune(cluster, level=None, height=None, condition=None):
    """
    Prune the clustering instance ``cluster``.

    :param Tree cluster: Cluster root node to prune.
    :param int level: If not `None` prune all clusters deeper then `level`.
    :param float height:
        If not `None` prune all clusters with height lower then `height`.
    :param function condition:
        If not `None condition must be a `Tree -> bool` function
        evaluating to `True` if the cluster should be pruned.

    .. note::
        At least one `level`, `height` or `condition` argument needs to
        be supplied.

    """
    if not any(arg is not None for arg in [level, height, condition]):
        raise ValueError("At least one pruning argument must be supplied")

    level_check = height_check = condition_check = lambda cl: False

    if level is not None:
        cluster_depth = cluster_depths(cluster)
        level_check = lambda cl: cluster_depth[cl] >= level

    if height is not None:
        height_check = lambda cl: cl.value.height <= height

    if condition is not None:
        condition_check = condition

    def check_all(cl):
        return level_check(cl) or height_check(cl) or condition_check(cl)

    T = {}

    for node in postorder(cluster):
        if check_all(node):
            if node.is_leaf:
                T[node] = node
            else:
                T[node] = Tree(node.value, ())
        else:
            T[node] = Tree(node.value,
                           tuple(T[ch] for ch in node.branches))
    return T[cluster]


def cluster_depths(cluster):
    """
    Return a dictionary mapping :class:`Tree` instances to their depth.

    :param Tree cluster: Root cluster
    :rtype: class:`dict`

    """
    depths = {}
    depths[cluster] = 0
    for cluster in preorder(cluster):
        cl_depth = depths[cluster]
        depths.update(dict.fromkeys(cluster.branches, cl_depth + 1))
    return depths


def top_clusters(tree, k):
    """
    Return `k` topmost clusters from hierarchical clustering.

    :param Tree root: Root cluster.
    :param int k: Number of top clusters.

    :rtype: list of :class:`Tree` instances
    """
    def item(node):
        return ((node.is_leaf, -node.value.height), node)

    heap = [item(tree)]

    while len(heap) < k:
        key, cl = heapq.heappop(heap)
        if cl.is_leaf:
            assert all(n.is_leaf for _, n in heap)
            heapq.heappush(heap, (key, cl))
            break

        left, right = cl.left, cl.right
        heapq.heappush(heap, item(left))
        heapq.heappush(heap, item(right))

    return [n for _, n in heap]


class HierarchicalClustering(object):
    def __init__(self, n_clusters=2, linkage=AVERAGE):
        self.n_clusters = n_clusters
        self.linkage = linkage

    def fit(self, X):
        self.tree = dist_matrix_clustering(X, linkage=self.linkage)
        cut = top_clusters(self.tree, self.n_clusters)
        labels = numpy.zeros(self.tree.value.last)

        for i, cl in enumerate(cut):
            indices = [leaf.value.index for leaf in leaves(cl)]
            labels[indices] = i

        self.labels = labels

    def fit_predict(self, X, y=None):
        self.fit(X)
        return self.labels