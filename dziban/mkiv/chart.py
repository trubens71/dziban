from copy import deepcopy
import re

from draco.js import data2schema, schema2asp
from draco.run import run as draco, DRACO_LP
from vega import VegaLite
from scipy.stats import zscore

from .base import Base
from .field import Field
from .channel import Channel
from .util import filter_sols, foreach, construct_graph

class Chart(Field, Channel):
  DEFAULT_NAME = '\"view\"'
  ANCHOR_NAME = '\"anchor\"'

  def __init__(self, data):
    Base.__init__(self, data)
    Field.__init__(self)
    Channel.__init__(self)
    self._id = 0
    self._mark = None
    self._name = Chart.DEFAULT_NAME

  def mark(self, value):
    clone = self.clone()
    clone._mark = value
    return clone

  def _get_asp_partial(self):
    vid = self._name
    asp = ['visualization({0}).'.format(vid)]
    asp += schema2asp(self._schema)

    if (self._mark is not None):
      mark = 'mark({0},{1}).'.format(vid, self._mark)
      asp.append(mark)

    min_encodings = max([len(x) for x in [self._selectedfields, self._selectedchannels]])

    for i in range(min_encodings):
      eid = 'e{0}'.format(i)
      asp.append('encoding({0},{1}).'.format(vid, eid))

    for enc in self._encodings:
      asp += enc.to_asp(vid)

    return asp

  def _get_draco_sol(self):
    partial = self._get_asp_partial()
    anchor = self._get_anchor_asp()

    query = partial + anchor

    if (anchor):
      files = list(filter(lambda file : file != 'optimize.lp', DRACO_LP))
      opt_draco_files = files + ['optimize_draco.lp']
      best_draco = draco(query, files=opt_draco_files, topk=True, k=50, silence_warnings=True)

      opt_graphscape_files = files + ['optimize_graphscape.lp']
      best_graphscape = draco(query, files=opt_graphscape_files, topk=True, k=50, silence_warnings=True)

      sol = self._find_best(best_draco + best_graphscape)
      return sol
    else:
      sol = draco(query)
      return sol

  def _find_best(self, sols):
    good = filter_sols(sols)
    
    d = [v.d for v in good]
    g = [v.g for v in good]

    dz = zscore(d)
    gz = zscore(g)

    combined = [(v, dz[i] + gz[i]) for i,v in enumerate(good)]
    best_v, _ = min(combined, key = lambda x : x[1])

    return best_v

  def _get_asp_complete(self):
    sol = self._get_draco_sol()
    return sol.props[self._name]

  def anchor(self, other):
    clone = self.clone()

    anchor_clone = other.clone()
    anchor_clone._name = Chart.ANCHOR_NAME[:-1] + str(clone._id) + '\"'
    clone._id += 1

    clone._anchor = anchor_clone
    return clone

  def _get_anchor_asp(self):
    if (self._anchor is None):
      return []
    
    REGEX = re.compile(r'(\w+)\(([\w\.\"\/]+)(,([\w\"\.]+))?(,([\w\.\"]+))?\)')

    anchor_complete = self._anchor._get_asp_complete()
    asp = ['base({0}).'.format(self._anchor._name)] + anchor_complete

    def inc_predicate(dict, pred):
      (count, params) = dict[pred]
      dict[pred] = (count + 1, params)

    predicates = {}
    for fact in anchor_complete:
      [predicate, v, _, __, ___, ____] = REGEX.findall(fact)[0]
      if (predicate == 'visualization'):
        vis = v

      if (predicate in ('visualization')):
        continue
      elif (predicate in ('encoding', 'zero', 'log', 'mark')):
        if (predicate not in predicates): predicates[predicate] = (0, 1)
        inc_predicate(predicates, predicate)
      elif (predicate in ('field', 'type', 'channel', 'bin', 'aggregate')):
        if (predicate not in predicates): predicates[predicate] = (0, 2)
        inc_predicate(predicates, predicate)

    one_arg_p = ['encoding', 'zero', 'log', 'mark', 'stack']
    two_arg_p = ['channel', 'type', 'field', 'aggregate', 'bin']
    
    for p in one_arg_p:
      if (p not in predicates):
        predicates[p] = (0, 1)

    for p in two_arg_p:
      if (p not in predicates):
        predicates[p] = (0, 2)

    for p in predicates:
      (count, params) = predicates[p]
      constraint = ':- not {{ {0}({1}'.format(p,vis)
      for _ in range(params):
        constraint += ',_'
      constraint += ') }} = {0}.'.format(count)
      asp.append(constraint)

    return asp

  def _get_vegalite(self):
    sol = self._get_draco_sol()

    vegalite = sol.as_vl(Chart.DEFAULT_NAME)
    return vegalite

  def _get_render(self):
    vegalite = self._get_vegalite()
    return VegaLite(vegalite, self._data)

  def _repr_mimebundle_(self, include=None, exclude=None):
    return self._get_render()._repr_mimebundle_(include, exclude)