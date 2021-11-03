'''
This module us for utilty functions that take as input and / or return Container subclasses such as Index, Series, or Frame, and that need to be shared by multiple such Container classes.
'''

from collections import defaultdict
from itertools import zip_longest
from functools import partial
import datetime
from fractions import Fraction
import typing as tp
from enum import Enum
import zipfile
import json
import struct
from ast import literal_eval

import numpy as np
from numpy import char as npc
from numpy.lib.format import read_array


from arraykit import column_2d_filter

from static_frame.core.index_base import IndexBase
from static_frame.core.util import AnyCallable
from static_frame.core.util import Bloc2DKeyType
from static_frame.core.util import concat_resolved
from static_frame.core.util import DEFAULT_SORT_KIND
from static_frame.core.util import DepthLevelSpecifier
from static_frame.core.util import DTYPE_BOOL
from static_frame.core.util import DTYPE_OBJECT
from static_frame.core.util import DTYPE_STR
from static_frame.core.util import DTYPE_STR_KINDS
from static_frame.core.util import DtypesSpecifier
from static_frame.core.util import DtypeSpecifier
from static_frame.core.util import GetItemKeyType
from static_frame.core.util import IndexConstructor
from static_frame.core.util import IndexConstructors
from static_frame.core.util import IndexInitializer
from static_frame.core.util import iterable_to_array_1d
from static_frame.core.util import NULL_SLICE
from static_frame.core.util import slice_to_ascending_slice
from static_frame.core.util import STATIC_ATTR
from static_frame.core.util import UFunc
from static_frame.core.util import ufunc_set_iter
from static_frame.core.util import INT_TYPES
from static_frame.core.util import NameType
from static_frame.core.util import is_dtype_specifier
from static_frame.core.util import is_mapping
from static_frame.core.util import BoolOrBools
from static_frame.core.util import BOOL_TYPES
from static_frame.core.rank import rank_1d
from static_frame.core.rank import RankMethod
from static_frame.core.util import PathSpecifier
from static_frame.core.exception import AxisInvalid

if tp.TYPE_CHECKING:
    import pandas as pd #pylint: disable=W0611 #pragma: no cover
    from static_frame.core.type_blocks import TypeBlocks #pylint: disable=W0611,C0412 #pragma: no cover
    from static_frame.core.series import Series #pylint: disable=W0611,C0412 #pragma: no cover
    from static_frame.core.frame import Frame #pylint: disable=W0611,C0412 #pragma: no cover
    from static_frame.core.index_hierarchy import IndexHierarchy #pylint: disable=W0611,C0412 #pragma: no cover
    from static_frame.core.index_auto import IndexAutoFactory #pylint: disable=W0611,C0412 #pragma: no cover
    from static_frame.core.index_auto import IndexDefaultFactory #pylint: disable=W0611,C0412 #pragma: no cover
    from static_frame.core.index_auto import IndexAutoFactoryType #pylint: disable=W0611,C0412 #pragma: no cover
    from static_frame.core.quilt import Quilt #pylint: disable=W0611,C0412 #pragma: no cover
    from static_frame.core.container import ContainerOperand #pylint: disable=W0611,C0412 #pragma: no cover



class ContainerMap:

    _map: tp.Optional[tp.Dict[str, tp.Type['ContainerOperand']]] = None

    @classmethod
    def _update_map(cls) -> None:
        from static_frame.core.frame import Frame
        from static_frame.core.frame import FrameGO
        from static_frame.core.frame import FrameHE
        from static_frame.core.series import Series
        from static_frame.core.series import SeriesHE
        from static_frame.core.index import Index
        from static_frame.core.index import IndexGO
        from static_frame.core.index_hierarchy import IndexHierarchy
        from static_frame.core.index_hierarchy import IndexHierarchyGO
        from static_frame.core.index_datetime import IndexDate
        from static_frame.core.index_datetime import IndexDateGO
        from static_frame.core.index_datetime import IndexYear
        from static_frame.core.index_datetime import IndexYearGO
        from static_frame.core.index_datetime import IndexYearMonth
        from static_frame.core.index_datetime import IndexYearMonthGO
        from static_frame.core.index_datetime import IndexMinute
        from static_frame.core.index_datetime import IndexMinuteGO
        from static_frame.core.index_datetime import IndexSecond
        from static_frame.core.index_datetime import IndexSecondGO
        from static_frame.core.index_datetime import IndexMillisecond
        from static_frame.core.index_datetime import IndexMillisecondGO
        from static_frame.core.index_datetime import IndexMicrosecond
        from static_frame.core.index_datetime import IndexMicrosecondGO
        from static_frame.core.index_datetime import IndexNanosecond
        from static_frame.core.index_datetime import IndexNanosecondGO

        cls._map = {k: v for k, v in locals().items() if v is not cls}

    # @staticmethod
    # def cls_to_str(cls: tp.Type['ContainerOperand']) -> str:
    #     return

    @classmethod
    def str_to_cls(cls, name: str) -> tp.Type['ContainerOperand']:
        if cls._map is None:
            cls._update_map()
        return cls._map[name] #type: ignore #pylint: disable=unsubscriptable-object


def get_col_dtype_factory(
        dtypes: DtypesSpecifier,
        columns: tp.Optional[tp.Sequence[tp.Hashable]],
        ) -> tp.Callable[[int], np.dtype]:
    '''
    Return a function, or None, to get values from a DtypeSpecifier by integer column positions.

    Args:
        columns: In common usage in Frame constructors, ``columns`` is a reference to a mutable list that is assigned column labels when processing data (and before this function is called). Columns can also be an ``Index``.
    '''
    from static_frame.core.series import Series

    # dtypes are either a dtype initializer, mappable by name, or an ordered sequence
    # NOTE: might verify that all keys in dtypes are in columns, though that might be slow

    if is_mapping(dtypes):
        is_map = True
        is_element = False
    elif is_dtype_specifier(dtypes):
        is_map = False
        is_element = True
    else: # an iterable of types
        is_map = False
        is_element = False

    if columns is None and is_map:
        raise RuntimeError('cannot lookup dtypes by name without supplied columns labels')

    def get_col_dtype(col_idx: int) -> DtypeSpecifier:
        nonlocal dtypes # might mutate a generator into a tuple
        if is_element:
            return dtypes
        if is_map:
            # mappings can be incomplete
            return dtypes.get(columns[col_idx], None) #type: ignore
        # NOTE: dtypes might be a generator deferred until this function is called; if so, realize here; INVALID_ITERABLE_FOR_ARRAY (dict_values, etc) do not have __getitem__,
        if not hasattr(dtypes, '__len__') or not hasattr(dtypes, '__getitem__'):
            dtypes = tuple(dtypes) #type: ignore
        return dtypes[col_idx] #type: ignore

    return get_col_dtype


def is_static(value: IndexConstructor) -> bool:
    try:
        # if this is a class constructor
        return getattr(value, STATIC_ATTR) #type: ignore
    except AttributeError:
        pass
    # assume this is a class method
    return getattr(value.__self__, STATIC_ATTR) #type: ignore


def pandas_version_under_1() -> bool:
    import pandas
    return not hasattr(pandas, 'NA') # object introduced in 1.0

def pandas_to_numpy(
        container: tp.Union['pd.Index', 'pd.Series', 'pd.DataFrame'],
        own_data: bool,
        fill_value: tp.Any = np.nan
        ) -> np.ndarray:
    '''Convert Pandas container to a numpy array in pandas 1.0, where we might have Pandas extension dtypes that may have pd.NA. If no pd.NA, can go back to numpy types.

    If coming from a Pandas extension type, will convert pd.NA to `fill_value` in the resulting object array. For object dtypes, pd.NA may pass on into SF; the only way to find them is an expensive iteration and `is` comparison, which we are not sure we want to do at this time.

    Args:
        fill_value: if replcaing pd.NA, what to replace it with. Ultimately, this can use FillValueAuto to avoid going to object in all cases.
    '''
    # NOTE: only to be used with pandas 1.0 and greater

    if container.ndim == 1: # Series, Index
        dtype_src = container.dtype
        ndim = 1
    elif container.ndim == 2: # DataFrame, assume contiguous dtypes
        dtypes = container.dtypes.unique()
        assert len(dtypes) == 1
        dtype_src = dtypes[0]
        ndim = 2
    else:
        raise NotImplementedError(f'no handling for ndim {container.ndim}') #pragma: no cover

    if isinstance(dtype_src, np.dtype):
        dtype = dtype_src
        is_extension_dtype = False
    elif hasattr(dtype_src, 'numpy_dtype'):
        # only int, uint dtypes have this attribute
        dtype = dtype_src.numpy_dtype
        is_extension_dtype = True
    else:
        dtype = None # resolve below
        is_extension_dtype = True

    if is_extension_dtype:
        isna = container.isna() # returns a NumPy Boolean type sometimes
        if not isinstance(isna, np.ndarray):
            isna = isna.values
        hasna = isna.any() # will work for ndim 1 and 2

        from pandas import StringDtype #pylint: disable=E0611
        from pandas import BooleanDtype #pylint: disable=E0611
        # from pandas import DatetimeTZDtype
        # from pandas import Int8Dtype
        # from pandas import Int16Dtype
        # from pandas import Int32Dtype
        # from pandas import Int64Dtype
        # from pandas import UInt16Dtype
        # from pandas import UInt32Dtype
        # from pandas import UInt64Dtype
        # from pandas import UInt8Dtype

        if isinstance(dtype_src, BooleanDtype):
            dtype = DTYPE_OBJECT if hasna else DTYPE_BOOL
        elif isinstance(dtype_src, StringDtype):
            # trying to use a dtype argument for strings results in a converting pd.NA to a string "<NA>"
            dtype = DTYPE_OBJECT if hasna else DTYPE_STR
        else:
            # if an extension type and it hasna, have to go to object; otherwise, set to None or the dtype obtained above
            dtype = DTYPE_OBJECT if hasna else dtype

        # NOTE: in some cases passing the dtype might raise an exception, but it appears we are handling all of those cases by looking at hasna and selecting an object dtype
        array = container.to_numpy(copy=not own_data, dtype=dtype)

        if hasna:
            # if hasna and extension dtype, should be an object array; replace pd.NA objects with fill_value (np.nan)
            assert array.dtype == DTYPE_OBJECT
            array[isna] = fill_value

    else: # not an extension dtype
        if own_data:
            array = container.values
        else:
            array = container.values.copy()

    array.flags.writeable = False
    return array

def df_slice_to_arrays(*,
        part: 'pd.DataFrame',
        column_ilocs: range,
        get_col_dtype: tp.Optional[tp.Callable[[int], np.dtype]],
        pdvu1: bool,
        own_data: bool,
        ) -> tp.Iterator[np.ndarray]:
    '''
    Given a slice of a DataFrame, extract an array and optionally convert dtypes. If dtypes are provided, they are read with iloc positions given by `columns_ilocs`.
    '''
    if pdvu1:
        array = part.values
        if own_data:
            array.flags.writeable = False
    else:
        array = pandas_to_numpy(part, own_data=own_data)

    if get_col_dtype:
        assert len(column_ilocs) == array.shape[1]
        for col, iloc in enumerate(column_ilocs):
            # use iloc to get dtype
            dtype = get_col_dtype(iloc)
            if dtype is None or dtype == array.dtype:
                yield array[NULL_SLICE, col]
            else:
                yield array[NULL_SLICE, col].astype(dtype)
    else:
        yield array



#---------------------------------------------------------------------------
def index_from_optional_constructor(
        value: tp.Union[IndexInitializer, 'IndexAutoFactory'],
        *,
        default_constructor: IndexConstructor,
        explicit_constructor: tp.Union[IndexConstructor, 'IndexDefaultFactory', None] = None,
        ) -> IndexBase:
    '''
    Given a value that is an IndexInitializer (which means it might be an Index), determine if that value is really an Index, and if so, determine if a copy has to be made; otherwise, use the default_constructor. If an explicit_constructor is given, that is always used.
    '''
    # NOTE: this might return an own_index flag to show callers when a new index has been created
    # NOTE: do not pass `name` here; instead, partial contstuctors if necessary
    from static_frame.core.index_auto import IndexAutoFactory
    from static_frame.core.index_auto import IndexDefaultFactory

    if isinstance(value, IndexAutoFactory):
        return value.to_index(
                default_constructor=default_constructor, #type: ignore
                explicit_constructor=explicit_constructor,
                )

    if explicit_constructor:
        if isinstance(explicit_constructor, IndexDefaultFactory):
            # partial the default constructor with a name argument
            return explicit_constructor(default_constructor)(value)
        return explicit_constructor(value)

    # default constructor could be a function with a STATIC attribute
    if isinstance(value, IndexBase):
        # if default is STATIC, and value is not STATIC, get an immutable
        if is_static(default_constructor):
            if not value.STATIC:
                # v: ~S, dc: S, use immutable alternative
                return value._IMMUTABLE_CONSTRUCTOR(value)
            # v: S, dc: S, both immutable
            return value
        else: # default constructor is mutable
            if not value.STATIC:
                # v: ~S, dc: ~S, both are mutable
                return value.copy()
            # v: S, dc: ~S, return a mutable version of something that is not mutable
            return value._MUTABLE_CONSTRUCTOR(value)

    # cannot always determine static status from constructors; fallback on using default constructor
    return default_constructor(value)

def index_from_optional_constructors(
        value: tp.Union[np.ndarray, tp.Iterable[tp.Hashable]],
        *,
        depth: int,
        default_constructor: IndexConstructor,
        explicit_constructors: IndexConstructors = None,
        ) -> tp.Tuple[tp.Optional[IndexBase], bool]:
    '''For scenarios here `index_depth` is the primary way of specifying index creation from a data source and the returned index might be an `IndexHierarchy`. Note that we do not take `name` or `continuation_token` here, but expect constructors to be appropriately partialed.
    '''
    if depth == 0:
        index = None
        own_index = False
    elif depth == 1:
        if not explicit_constructors:
            explicit_constructor = None
        elif callable(explicit_constructors):
            explicit_constructor = explicit_constructors
        else:
            if len(explicit_constructors) != 1:
                raise RuntimeError('Cannot specify multiple index constructors for depth 1 indicies.')
            explicit_constructor = explicit_constructors[0]

        index = index_from_optional_constructor(
                value,
                default_constructor=default_constructor,
                explicit_constructor=explicit_constructor,
                )
        own_index = True
    else:
        # if depth is > 1, the default constructor is expected to be an IndexHierarchy, and explicit constructors are optionally provided `index_constructors`
        if callable(explicit_constructors):
            explicit_constructors = [explicit_constructors] * depth
        # default_constructor is an IH type
        index = default_constructor(
                value,
                index_constructors=explicit_constructors
                )
        own_index = True
    return index, own_index


def index_from_optional_constructors_deferred(
        *,
        depth: int,
        default_constructor: IndexConstructor,
        explicit_constructors: IndexConstructors = None,
        ) -> tp.Callable[
                [tp.Union[np.ndarray, tp.Iterable[tp.Hashable]]],
                tp.Optional[IndexBase]]:
    '''
    Partial `index_from_optional_constructors` for all args except `value`; only return the Index, ignoring the own_index Boolean.
    '''
    def func(
            value: tp.Union[np.ndarray, tp.Iterable[tp.Hashable]],
            ) -> tp.Optional[IndexBase]:
        # drop the own_index Boolean
        index, _ = index_from_optional_constructors(value,
                depth=depth,
                default_constructor=default_constructor,
                explicit_constructors=explicit_constructors,
                )
        return index
    return func


def index_constructor_empty(
        index: tp.Union[IndexInitializer, 'IndexAutoFactoryType']
        ) -> bool:
    '''
    Determine if an index is empty (if possible) or an IndexAutoFactory.
    '''
    from static_frame.core.index_auto import IndexAutoFactory
    if index is None or index is IndexAutoFactory:
        return True
    elif (not isinstance(index, IndexBase)
            and hasattr(index, '__len__')
            and len(index) == 0 #type: ignore
            ):
        return True
    return False

def matmul(
        lhs: tp.Union['Series', 'Frame', np.ndarray, tp.Sequence[float]],
        rhs: tp.Union['Series', 'Frame', np.ndarray, tp.Sequence[float]],
        ) -> tp.Any: #tp.Union['Series', 'Frame']:
    '''
    Implementation of matrix multiplication for Series and Frame
    '''
    from static_frame.core.series import Series
    from static_frame.core.frame import Frame

    # for a @ b = c
    # if a is 2D: a.columns must align b.index
    # if b is 1D, a.columns bust align with b.index
    # if a is 1D: len(a) == b.index (len of b), returns w columns of B

    if not isinstance(rhs, (np.ndarray, Series, Frame)):
        # try to make it into an array
        rhs = np.array(rhs)

    if not isinstance(lhs, (np.ndarray, Series, Frame)):
        # try to make it into an array
        lhs = np.array(lhs)

    if isinstance(lhs, np.ndarray):
        lhs_type = np.ndarray
    elif isinstance(lhs, Series):
        lhs_type = Series
    else: # normalize subclasses
        lhs_type = Frame

    if isinstance(rhs, np.ndarray):
        rhs_type = np.ndarray
    elif isinstance(rhs, Series):
        rhs_type = Series
    else: # normalize subclasses
        rhs_type = Frame

    if rhs_type == np.ndarray and lhs_type == np.ndarray:
        return np.matmul(lhs, rhs)


    own_index = True
    constructor = None

    if lhs.ndim == 1: # Series, 1D array
        # result will be 1D or 0D
        columns = None

        if lhs_type == Series and (rhs_type == Series or rhs_type == Frame):
            aligned = lhs._index.union(rhs._index)
            # if the aligned shape is not the same size as the originals, we do not have the same values in each and cannot proceed (all values go to NaN)
            if len(aligned) != len(lhs._index) or len(aligned) != len(rhs._index):
                raise RuntimeError('shapes not alignable for matrix multiplication') #pragma: no cover

        if lhs_type == Series:
            if rhs_type == np.ndarray:
                if lhs.shape[0] != rhs.shape[0]: # works for 1D and 2D
                    raise RuntimeError('shapes not alignable for matrix multiplication')
                ndim = rhs.ndim - 1 # if 2D, result is 1D, of 1D, result is 0
                left = lhs.values
                right = rhs # already np
                if ndim == 1:
                    index = None # force auto increment integer
                    own_index = False
                    constructor = lhs.__class__
            elif rhs_type == Series:
                ndim = 0
                left = lhs.reindex(aligned).values
                right = rhs.reindex(aligned).values
            else: # rhs is Frame
                ndim = 1
                left = lhs.reindex(aligned).values
                right = rhs.reindex(index=aligned).values
                index = rhs._columns
                constructor = lhs.__class__
        else: # lhs is 1D array
            left = lhs
            right = rhs.values
            if rhs_type == Series:
                ndim = 0
            else: # rhs is Frame, len(lhs) == len(rhs.index)
                ndim = 1
                index = rhs._columns
                constructor = Series # cannot get from argument

    elif lhs.ndim == 2: # Frame, 2D array

        if lhs_type == Frame and (rhs_type == Series or rhs_type == Frame):
            aligned = lhs._columns.union(rhs._index)
            # if the aligned shape is not the same size as the originals, we do not have the same values in each and cannot proceed (all values go to NaN)
            if len(aligned) != len(lhs._columns) or len(aligned) != len(rhs._index):
                raise RuntimeError('shapes not alignable for matrix multiplication')

        if lhs_type == Frame:
            if rhs_type == np.ndarray:
                if lhs.shape[1] != rhs.shape[0]: # works for 1D and 2D
                    raise RuntimeError('shapes not alignable for matrix multiplication')
                ndim = rhs.ndim
                left = lhs.values
                right = rhs # already np
                index = lhs._index

                if ndim == 1:
                    constructor = Series
                else:
                    constructor = lhs.__class__
                    columns = None # force auto increment index
            elif rhs_type == Series:
                # a.columns must align with b.index
                ndim = 1
                left = lhs.reindex(columns=aligned).values
                right = rhs.reindex(aligned).values
                index = lhs._index  # this axis is not changed
                constructor = rhs.__class__
            else: # rhs is Frame
                # a.columns must align with b.index
                ndim = 2
                left = lhs.reindex(columns=aligned).values
                right = rhs.reindex(index=aligned).values
                index = lhs._index
                columns = rhs._columns
                constructor = lhs.__class__ # give left precedence
        else: # lhs is 2D array
            left = lhs
            right = rhs.values
            if rhs_type == Series: # returns unindexed Series
                ndim = 1
                index = None
                own_index = False
                constructor = rhs.__class__
            else: # rhs is Frame, lhs.shape[1] == rhs.shape[0]
                if lhs.shape[1] != rhs.shape[0]: # works for 1D and 2D
                    raise RuntimeError('shapes not alignable for matrix multiplication')
                ndim = 2
                index = None
                own_index = False
                columns = rhs._columns
                constructor = rhs.__class__
    else:
        raise NotImplementedError(f'no handling for {lhs}')

    # NOTE: np.matmul is not the same as np.dot for some arguments
    data = np.matmul(left, right)

    if ndim == 0:
        return data

    assert constructor is not None

    data.flags.writeable = False
    if ndim == 1:
        return constructor(data,
                index=index,
                own_index=own_index,
                )
    return constructor(data,
            index=index,
            own_index=own_index,
            columns=columns
            )


def axis_window_items( *,
        source: tp.Union['Series', 'Frame', 'Quilt'],
        size: int,
        axis: int = 0,
        step: int = 1,
        window_sized: bool = True,
        window_func: tp.Optional[AnyCallable] = None,
        window_valid: tp.Optional[AnyCallable] = None,
        label_shift: int = 0,
        start_shift: int = 0,
        size_increment: int = 0,
        as_array: bool = False,
        ) -> tp.Iterator[tp.Tuple[tp.Hashable, tp.Any]]:
    '''Generator of index, window pairs. When ndim is 2, axis 0 returns windows of rows, axis 1 returns windows of columns.

    Args:
        as_array: if True, the window is returned as an array instead of a SF object.
    '''
    # see doc_str window for docs

    from static_frame.core.frame import Frame
    from static_frame.core.quilt import Quilt
    from static_frame.core.series import Series

    if size <= 0:
        raise RuntimeError('window size must be greater than 0')
    if step < 0:
        raise RuntimeError('window step cannot be less than than 0')

    source_ndim = source.ndim
    values: tp.Optional[np.ndarray] = None

    if source_ndim == 1:
        assert isinstance(source, Series) # for mypy
        labels = source._index
        if as_array:
            values = source.values
    else:
        labels = source._index if axis == 0 else source._columns #type: ignore

        if isinstance(source, Frame) and axis == 0 and as_array:
            # for a Frame, when collecting rows, it is more efficient to pre-consolidate blocks prior to slicing. Note that this results in the same block coercion necessary for each window (which is not the same for axis 1, where block coercion is not required)
            values = source._blocks.values

    if start_shift >= 0:
        count_window_max = len(labels)
    else: # add for iterations when less than 0
        count_window_max = len(labels) + abs(start_shift)

    idx_left_max = count_window_max - 1
    idx_left = start_shift
    count = 0

    while True:
        # idx_left, size can change over iterations
        idx_right = idx_left + size - 1

        # floor idx_left at 0 so as to not wrap
        idx_left_floored = idx_left if idx_left > 0 else 0
        idx_right_floored = idx_right if idx_right > -1 else -1 # will add one

        key = slice(idx_left_floored, idx_right_floored + 1)

        if source_ndim == 1:
            if as_array:
                window = values[key] #type: ignore
            else:
                window = source._extract_iloc(key)
        else:
            if axis == 0: # extract rows
                if as_array and values is not None:
                    window = values[key]
                elif as_array:
                    window = source._extract_array(key) #type: ignore
                else: # use low level iloc selector
                    window = source._extract(row_key=key) #type: ignore
            else: # extract columns
                if as_array:
                    window = source._extract_array(NULL_SLICE, key) #type: ignore
                else:
                    window = source._extract(column_key=key) #type: ignore

        valid = True
        try:
            idx_label = idx_right + label_shift
            if idx_label < 0: # do not wrap around
                raise IndexError()
            #if we cannot get a label, the window is invalid
            label = labels.iloc[idx_label]
        except IndexError: # an invalid label has to be dropped
            valid = False

        if valid and window_sized and window.shape[axis] != size:
            valid = False
        if valid and window_valid and not window_valid(window):
            valid = False

        if valid:
            if window_func:
                window = window_func(window)
            yield label, window

        idx_left += step
        size += size_increment
        count += 1

        if count > count_window_max or idx_left > idx_left_max or size < 0:
            break

def get_block_match(
        width: int,
        values_source: tp.List[np.ndarray],
        ) -> tp.Iterator[np.ndarray]:
    '''Utility method for assignment. Draw from values to provide as many columns as specified by width. Use `values_source` as a stack to draw and replace values.
    '''
    # see clip().get_block_match() for one example of drawing values from another sequence of blocks, where we take blocks and slices from blocks using a list as a stack

    if width == 1: # no loop necessary
        v = values_source.pop()
        if v.ndim == 1:
            yield v
        else: # ndim == 2
            if v.shape[1] > 1: # more than one column
                # restore remained to values source
                values_source.append(v[NULL_SLICE, 1:])
            yield v[NULL_SLICE, 0]
    else:
        width_found = 0
        while width_found < width:
            v = values_source.pop()
            if v.ndim == 1:
                yield v
                width_found += 1
                continue
            # ndim == 2
            width_v = v.shape[1]
            width_needed = width - width_found
            if width_v <= width_needed:
                yield v
                width_found += width_v
                continue
            # width_v > width_needed
            values_source.append(v[NULL_SLICE, width_needed:])
            yield v[NULL_SLICE, :width_needed]
            break

def bloc_key_normalize(
        key: Bloc2DKeyType,
        container: 'Frame'
        ) -> np.ndarray:
    '''
    Normalize and validate a bloc key. Return a same sized Boolean array.
    '''
    from static_frame.core.frame import Frame

    if isinstance(key, Frame):
        bloc_frame = key.reindex(
                index=container._index,
                columns=container._columns,
                fill_value=False
                )
        bloc_key = bloc_frame.values # shape must match post reindex
    elif key.__class__ is np.ndarray:
        bloc_key = key
        if bloc_key.shape != container.shape:
            raise RuntimeError(f'bloc {bloc_key.shape} must match shape {container.shape}')
    else:
        raise RuntimeError(f'invalid bloc_key, must be Frame or array, not {key}')

    if not bloc_key.dtype == bool:
        raise RuntimeError('cannot use non-Boolean dtype as bloc key')

    return bloc_key


def key_to_ascending_key(key: GetItemKeyType, size: int) -> GetItemKeyType:
    '''
    Normalize all types of keys into an ascending formation.

    Args:
        size: the length of the container on this axis
    '''
    from static_frame.core.frame import Frame
    from static_frame.core.series import Series

    if key.__class__ is slice:
        return slice_to_ascending_slice(key, size=size) #type: ignore

    if isinstance(key, str) or not hasattr(key, '__len__'):
        return key

    if key.__class__ is np.ndarray:
        # array first as not truthy
        if key.dtype == bool: #type: ignore
            return key
        return np.sort(key, kind=DEFAULT_SORT_KIND)

    if not len(key): #type: ignore
        return key

    if isinstance(key, list):
        return sorted(key)

    if isinstance(key, Series):
        return key.sort_index()

    if isinstance(key, Frame):
        # for usage in assignment we need columns to be sorted
        return key.sort_columns()

    raise RuntimeError(f'unhandled key {key}')


def rehierarch_from_type_blocks(*,
        labels: 'TypeBlocks',
        depth_map: tp.Sequence[int],
        index_cls: tp.Type['IndexHierarchy'],
        index_constructors: tp.Optional[IndexConstructors] = None,
        name: tp.Optional[tp.Hashable] = None,
        ) -> tp.Tuple['IndexBase', np.ndarray]:
    '''
    Given labels suitable for a hierarchical index, order them into a hierarchy using the given depth_map.

    Args:
        index_cls: provide a class, from which the constructor will be called.
    '''

    depth = labels.shape[1] # number of columns

    if depth != len(depth_map):
        raise RuntimeError('must specify new depths for all depths')
    if set(range(depth)) != set(depth_map):
        raise RuntimeError('all depths must be specified')

    labels_post = labels._extract(row_key=NULL_SLICE, column_key=list(depth_map))
    labels_sort = np.full(labels_post.shape, 0)

    # get ordering of values found in each level
    order: tp.List[tp.Dict[tp.Hashable, int]] = [defaultdict(int) for _ in range(depth)]

    for (idx_row, idx_col), label in labels.element_items():
        if label not in order[idx_col]:
            # Map label to an integer representing the observed order.
            order[idx_col][label] = len(order[idx_col])
        # Fill array for sorting based on observed order.
        labels_sort[idx_row, idx_col] = order[idx_col][label]

    # Reverse depth_map for lexical sorting, which sorts by rightmost column first.
    order_lex = np.lexsort(
            [labels_sort[NULL_SLICE, i] for i in reversed(depth_map)])

    labels_post = labels_post._extract(row_key=order_lex)

    index = index_cls._from_type_blocks(
            blocks=labels_post,
            index_constructors=index_constructors,
            name=name,
            own_blocks=True,
            )
    return index, order_lex

def rehierarch_from_index_hierarchy(*,
        labels: 'IndexHierarchy',
        depth_map: tp.Sequence[int],
        index_constructors: tp.Optional[IndexConstructors] = None,
        name: tp.Optional[tp.Hashable] = None,
        ) -> tp.Tuple['IndexBase', np.ndarray]:
    '''
    Alternate interface that updates IndexHierarchy cache before rehierarch.
    '''
    if labels._recache:
        labels._update_array_cache()

    return rehierarch_from_type_blocks(
            labels=labels._blocks,
            depth_map=depth_map,
            index_cls=labels.__class__,
            index_constructors=index_constructors,
            name=name,
            )

def array_from_value_iter(
        key: tp.Hashable,
        idx: int,
        get_value_iter: tp.Callable[[tp.Hashable], tp.Iterator[tp.Any]],
        get_col_dtype: tp.Optional[tp.Callable[[int], np.dtype]],
        row_count: int,
        ) -> np.ndarray:
    '''
    Return a single array given keys and collections.

    Args:
        get_value_iter: Iterator of a values
        dtypes: if an
        key: hashable for looking up field in `get_value_iter`.
        idx: integer position to extract from dtypes
    '''
    # for each column, try to get a dtype, or None
    # if this value is None we cannot tell if it was explicitly None or just was not specified
    dtype = None if get_col_dtype is None else get_col_dtype(idx)

    # NOTE: shown to be faster to try fromiter in some performance tests
    # values, _ = iterable_to_array_1d(get_value_iter(key), dtype=dtype)

    values = None
    if dtype is not None:
        try:
            values = np.fromiter(
                    get_value_iter(key),
                    count=row_count,
                    dtype=dtype)
            values.flags.writeable = False
        except (ValueError, TypeError):
            # the dtype may not be compatible, so must fall back on using np.array to determine the type, i.e., ValueError: cannot convert float NaN to integer
            pass
    if values is None:
        # returns an immutable array
        values, _ = iterable_to_array_1d(
                get_value_iter(key),
                dtype=dtype
                )
    return values

#-------------------------------------------------------------------------------
# utilities for binary operator applications with type blocks

def apply_binary_operator(*,
        values: np.ndarray,
        other: tp.Any,
        other_is_array: bool,
        operator: UFunc,
        ) -> np.ndarray:
    '''
    Utility to handle binary operator application.
    '''
    if (values.dtype.kind in DTYPE_STR_KINDS or
            (other_is_array and other.dtype.kind in DTYPE_STR_KINDS)):
        operator_name = operator.__name__

        if operator_name == 'add':
            result = npc.add(values, other)
        elif operator_name == 'radd':
            result = npc.add(other, values)
        elif operator_name == 'mul' or operator_name == 'rmul':
            result = npc.multiply(values, other)
        else:
            result = operator(values, other)
    else:
        result = operator(values, other)

    if result is False or result is True:
        if not other_is_array and (
                isinstance(other, str) or not hasattr(other, '__len__')
                ):
            # only expand to the size of the array operand if we are comparing to an element
            result = np.full(values.shape, result, dtype=DTYPE_BOOL)
        elif other_is_array and other.size == 1:
            # elements in arrays of 0 or more dimensions are acceptable; this is what NP does for arithmetic operators when the types are compatible
            result = np.full(values.shape, result, dtype=DTYPE_BOOL)
        else:
            raise ValueError('operands could not be broadcast together')
            # raise on unaligned shapes as is done for arithmetic operators

    result.flags.writeable = False
    return result

def apply_binary_operator_blocks(*,
        values: tp.Iterable[np.ndarray],
        other: tp.Iterable[np.ndarray],
        operator: UFunc,
        apply_column_2d_filter: bool,
    ) -> tp.Iterator[np.ndarray]:
    '''
    Application from iterators of arrays, to iterators of arrays.
    '''
    if apply_column_2d_filter:
        values = (column_2d_filter(op) for op in values)
        other = (column_2d_filter(op) for op in other)

    for a, b in zip_longest(values, other):
        yield apply_binary_operator(
                values=a,
                other=b,
                other_is_array=True,
                operator=operator,
                )

def apply_binary_operator_blocks_columnar(*,
        values: tp.Iterable[np.ndarray],
        other: np.ndarray,
        operator: UFunc,
    ) -> tp.Iterator[np.ndarray]:
    '''
    Application from iterators of arrays, to iterators of arrays. Will return iterator of all 1D arrays, as we will break down larger blocks in values into 1D arrays.

    Args:
        other: 1D array to be applied to each column of the blocks.
    '''
    assert other.ndim == 1
    for block in values:
        if block.ndim == 1:
            yield apply_binary_operator(
                    values=block,
                    other=other,
                    other_is_array=True,
                    operator=operator,
                    )
        else:
            for i in range(block.shape[1]):
                yield apply_binary_operator(
                        values=block[NULL_SLICE, i],
                        other=other,
                        other_is_array=True,
                        operator=operator,
                        )

#-------------------------------------------------------------------------------

def arrays_from_index_frame(
        container: 'Frame',
        depth_level: tp.Optional[DepthLevelSpecifier],
        columns: GetItemKeyType
        ) -> tp.Iterator[np.ndarray]:
    '''
    Given a Frame, return an iterator of index and / or columns as 1D or 2D arrays.
    '''
    if depth_level is not None:
        # NOTE: a 1D index of tuples will be taken as a 1D array of tuples; there is no obvious way to treat this as 2D array without guessing that we are trying to match an IndexHierarchy
        # NOTE: if a multi-column selection, might be better to yield one depth at a time
        yield container.index.values_at_depth(depth_level)
    if columns is not None:
        column_key = container.columns._loc_to_iloc(columns)
        yield from container._blocks._slice_blocks(column_key=column_key)


def key_from_container_key(
        index: IndexBase,
        key: GetItemKeyType,
        expand_iloc: bool = False,
        ) -> GetItemKeyType:
    '''
    Unpack selection values from another Index, Series, or ILoc selection.
    '''
    # PERF: do not do comparisons if key is not a Container or SF object
    if not hasattr(key, 'STATIC'):
        return key

    from static_frame.core.index import Index
    from static_frame.core.index import ILoc
    from static_frame.core.series import Series
    from static_frame.core.series import SeriesHE

    if isinstance(key, Index):
        # if an Index, we simply use the values of the index
        key = key.values
    elif isinstance(key, Series) and key.__class__ is not SeriesHE:
        # Series that are not hashable are unpacked into an array; SeriesHE can be used as a key
        if key.dtype == DTYPE_BOOL:
            # if a Boolean series, sort and reindex
            if not key.index.equals(index):
                key = key.reindex(index,
                        fill_value=False,
                        check_equals=False,
                        ).values
            else: # the index is equal
                key = key.values
        else:
            # For all other Series types, we simply assume that the values are to be used as keys in the IH. This ignores the index, but it does not seem useful to require the Series, used like this, to have a matching index value, as the index and values would need to be identical to have the desired selection.
            key = key.values
    elif expand_iloc and key.__class__ is ILoc:
        # realize as Boolean array
        array = np.full(len(index), False)
        array[key.key] = True #type: ignore
        key = array

    # detect and fail on Frame?
    return key


#---------------------------------------------------------------------------
class ManyToOneType(Enum):
    CONCAT = 0
    UNION = 1
    INTERSECT = 2


def _index_many_to_one(
        indices: tp.Iterable[IndexBase],
        cls_default: tp.Type[IndexBase],
        many_to_one_type: ManyToOneType,
        ) -> IndexBase:
    '''
    Given multiple Index objects, combine them. Preserve name and index type if aligned, and handle going to GO if the default class is GO.

    Args:
        indices: can be a generator
        cls_default: Default Index class to be used if no alignment of classes; also used to determine if result Index should be static or mutable.
    '''
    from static_frame.core.index_auto import IndexAutoFactory

    array_processor: tp.Callable[[tp.Iterable[np.ndarray]], np.ndarray]

    if many_to_one_type is ManyToOneType.UNION:
        array_processor = partial(ufunc_set_iter,
                union=True,
                assume_unique=True)
    elif many_to_one_type is ManyToOneType.INTERSECT:
        array_processor = partial(ufunc_set_iter,
                union=False,
                assume_unique=True)
    elif many_to_one_type is ManyToOneType.CONCAT:
        array_processor = concat_resolved

    indices_iter = iter(indices)
    try:
        index = next(indices_iter)
    except StopIteration:
        return cls_default.from_labels(())

    arrays = [index.values]

    name_first = index.name
    name_aligned = True

    cls_first = index.__class__
    cls_aligned = True

    # if we are unioning we can give back an index_auto_aligned
    index_auto_aligned = (many_to_one_type is not ManyToOneType.CONCAT
            and index.ndim == 1
            and index._map is None #type: ignore
            )

    # if IndexHierarchy, collect index_types generators
    if index.ndim == 2:
        depth_first = index.depth
        index_types_gen = [index._levels.index_types()] #type: ignore
        index_types_aligned = True
    else: # for 1D we ignore this
        index_types_aligned = False

    for index in indices_iter:
        arrays.append(index.values)
        if name_aligned and index.name != name_first:
            name_aligned = False
        if cls_aligned and index.__class__ != cls_first:
            cls_aligned = False
        if index_auto_aligned and (index.ndim != 1 or index._map is not None): #type: ignore
            index_auto_aligned = False

        if index_types_aligned and index.ndim == 2 and index.depth == depth_first:
            index_types_gen.append(index._levels.index_types()) #type: ignore
        else:
            index_types_aligned = False

    name = name_first if name_aligned else None
    if index_auto_aligned:
        if many_to_one_type is ManyToOneType.UNION:
            size = max(a.size for a in arrays)
        elif many_to_one_type is ManyToOneType.INTERSECT:
            size = min(a.size for a in arrays)
        return IndexAutoFactory(size, name=name).to_index(default_constructor=cls_default)

    if index_types_aligned:
        # all depths are already aligned
        index_constructors = []
        for types in zip(*index_types_gen):
            if all(types[0] == t for t in types[1:]):
                index_constructors.append(types[0])
            else: # assume this is always a 1D index
                index_constructors.append(cls_default)

    if cls_aligned:
        if cls_default.STATIC and not cls_first.STATIC:
            # default is static but aligned is mutable
            constructor = cls_first._IMMUTABLE_CONSTRUCTOR.from_labels #type: ignore
        elif not cls_default.STATIC and cls_first.STATIC:
            # default is mutable but aligned is static
            constructor = cls_first._MUTABLE_CONSTRUCTOR.from_labels #type: ignore
        else:
            constructor = cls_first.from_labels
    else:
        constructor = cls_default.from_labels

    # returns an immutable array
    array = array_processor(arrays)

    if index_types_aligned:
        return constructor(array, name=name, index_constructors=index_constructors) #type: ignore
    return constructor(array, name=name) #type: ignore

def index_many_concat(
        indices: tp.Iterable[IndexBase],
        cls_default: tp.Type[IndexBase],
        ) -> tp.Optional[IndexBase]:
    return _index_many_to_one(indices, cls_default, ManyToOneType.CONCAT)

def index_many_set(
        indices: tp.Iterable[IndexBase],
        cls_default: tp.Type[IndexBase],
        union: bool,
        ) -> tp.Optional[IndexBase]:
    '''
    Given multiple Index objects, union them. Preserve name and index type if aligned.
    '''
    return _index_many_to_one(indices,
            cls_default,
            ManyToOneType.UNION if union else ManyToOneType.INTERSECT,
            )


#-------------------------------------------------------------------------------
def apex_to_name(
        rows: tp.Sequence[tp.Sequence[tp.Hashable]],
        depth_level: tp.Optional[DepthLevelSpecifier],
        axis: int, # 0 is by row (for index), 1 is by column (for columns)
        axis_depth: int,
        ) -> NameType:
    '''
    Utility for translating apex values (the upper left corner created be index/columns) in the appropriate name.
    '''
    if depth_level is None:
        return None
    if axis == 0:
        if isinstance(depth_level, INT_TYPES):
            row = rows[depth_level]
            if axis_depth == 1: # return a single label
                return row[0] if row[0] != '' else None
            else:
                return tuple(row)
        else: # its a list selection
            targets = [rows[level] for level in depth_level]
            # combine into tuples
            if axis_depth == 1:
                return next(zip(*targets))
            else:
                return tuple(zip(*targets))
    elif axis == 1:
        if isinstance(depth_level, INT_TYPES):
            # depth_level refers to position in inner row
            row = [r[depth_level] for r in rows]
            if axis_depth == 1: # return a single label
                return row[0] if row[0] != '' else None
            else:
                return tuple(row)
        else: # its a list selection
            targets = (tuple(row[level] for level in depth_level) for row in rows) #type: ignore
            # combine into tuples
            if axis_depth == 1:
                return next(targets) #type: ignore
            else:
                return tuple(targets)

    raise AxisInvalid(f'invalid axis: {axis}')


def container_to_exporter_attr(container_type: tp.Type['Frame']) -> str:
    from static_frame.core.frame import Frame
    from static_frame.core.frame import FrameGO
    from static_frame.core.frame import FrameHE

    if container_type is Frame:
        return 'to_frame'
    elif container_type is FrameGO:
        return 'to_frame_go'
    elif container_type is FrameHE:
        return 'to_frame_he'
    raise NotImplementedError(f'no handling for {container_type}')

def frame_to_frame(
        frame: 'Frame',
        container_type: tp.Type['Frame'],
        ) -> 'Frame':
    if frame.__class__ is container_type:
        return frame
    f = getattr(frame, container_to_exporter_attr(container_type))
    return f() # type: ignore

def prepare_values_for_lex(
        *,
        ascending: BoolOrBools = True,
        values_for_lex: tp.Optional[tp.Iterable[np.ndarray]],
        ) -> tp.Tuple[bool, tp.Optional[tp.Iterable[np.ndarray]]]:
    '''Prepare values for lexical sorting; assumes values have already been collected in reverse order. If ascending is an element and values_for_lex is None, this function is pass through.
    '''
    asc_is_element = isinstance(ascending, BOOL_TYPES)
    if not asc_is_element:
        ascending = tuple(ascending) #type: ignore
        if values_for_lex is None or len(ascending) != len(values_for_lex): #type: ignore
            raise RuntimeError(f'Multiple ascending values must match number of arrays selected.')
        # values for lex are in reversed order; thus take ascending reversed
        values_for_lex_post = []
        for asc, a in zip(reversed(ascending), values_for_lex):
            # if not ascending, replace with an inverted dense rank
            if not asc:
                values_for_lex_post.append(
                        rank_1d(a, method=RankMethod.DENSE, ascending=False))
            else:
                values_for_lex_post.append(a)
        values_for_lex = values_for_lex_post

    return asc_is_element, values_for_lex

def sort_index_for_order(
        index: IndexBase,
        ascending: BoolOrBools,
        kind: str,
        key: tp.Optional[tp.Callable[[IndexBase], tp.Union[np.ndarray, IndexBase]]],
        ) -> np.ndarray:
    '''Return an integer array defing the new ordering.
    '''
    # cfs is container_for_sort
    if key:
        cfs = key(index)
        cfs_is_array = cfs.__class__ is np.ndarray
        if cfs_is_array:
            cfs_depth = 1 if cfs.ndim == 1 else cfs.shape[1]
        else:
            cfs_depth = cfs.depth
        if len(cfs) != len(index):
            raise RuntimeError('key function returned a container of invalid length')
    else:
        cfs = index
        cfs_is_array = False
        cfs_depth = cfs.depth

    asc_is_element: bool
    # argsort lets us do the sort once and reuse the results
    if cfs_depth > 1:
        if cfs_is_array:
            values_for_lex = [cfs[NULL_SLICE, i] for i in range(cfs.shape[1]-1, -1, -1)]
        else: # cfs is an IndexHierarchy
            values_for_lex = [cfs.values_at_depth(i)
                    for i in range(cfs.depth-1, -1, -1)]

        asc_is_element, values_for_lex = prepare_values_for_lex( #type: ignore
                ascending=ascending,
                values_for_lex=values_for_lex,
                )
        order = np.lexsort(values_for_lex)
    else:
        # depth is 1
        asc_is_element = isinstance(ascending, BOOL_TYPES)
        if not asc_is_element:
            raise RuntimeError(f'Multiple ascending values not permitted.')

        v = cfs if cfs_is_array else cfs.values
        order = np.argsort(v, kind=kind)

    if asc_is_element and not ascending:
        # NOTE: if asc is not an element, then ascending Booleans have already been applied to values_for_lex
        order = order[::-1]
    return order

#-------------------------------------------------------------------------------

class MessagePackElement:
    '''
    Handle encoding/decoding of elements found in object arrays not well supported by msgpack. Many of these cases were found through Hypothesis testing.
    '''

    @staticmethod
    def encode(
            a: tp.Any,
            packb: AnyCallable,
            ) -> tp.Tuple[str, tp.Any]:

        if isinstance(a, datetime.datetime): #msgpack-numpy has an issue with datetime
            year = str(a.year).zfill(4) #datetime returns inconsistent year string for <4 digit years on some systems
            d = year + ' ' + a.strftime('%a %b %d %H:%M:%S:%f')
            return ('DT', d)
        elif isinstance(a, datetime.date):
            year = str(a.year).zfill(4) #datetime returns inconsistent year string for <4 digit years on some systems
            d = year + ' ' + a.strftime('%a %b %d')
            return ('D', d)
        elif isinstance(a, datetime.time):
            return ('T', a.strftime('%H:%M:%S:%f'))
        elif isinstance(a, np.ndarray): #recursion not covered by msgpack-numpy
            return ('A', packb(a)) #recurse packb
        elif isinstance(a, Fraction): #msgpack-numpy has an issue with fractions
            return ('F',  str(a))
        elif isinstance(a, int) and len(str(a)) >=19:
            #msgpack-python has an overflow issue with large ints
            return ('I', str(a))
        return ('', a)


    @staticmethod
    def decode(
            pair: tp.Tuple[str, tp.Any],
            unpackb: AnyCallable,
            ) -> tp.Any:
        dt = datetime.datetime

        (typ, d) = pair
        if typ == 'DT': #msgpack-numpy has an issue with datetime
            return dt.strptime(d, '%Y %a %b %d %H:%M:%S:%f')
        elif typ == 'D':
            return dt.strptime(d, '%Y %a %b %d').date()
        elif typ == 'T':
            return dt.strptime(d, '%H:%M:%S:%f').time()
        elif typ == 'F': #msgpack-numpy has an issue with fractions
            return Fraction(d)
        elif typ == 'I': #msgpack-python has an issue with very large int values
            return int(d)
        elif typ == 'A': #recursion not covered by msgpack-numpy
            return unpackb(d) #recurse unpackb
        return d


#-------------------------------------------------------------------------------

class NPYConverter:
    '''Optimized implementation based on numpy/lib/format.py
    '''
    # BUFFER_SIZE_NUMERATOR = 16 * 1024 ** 2
    MAGIC_PREFIX = b'\x93NUMPY' + bytes((3, 0)) # version 3.0
    MAGIC_LEN = len(MAGIC_PREFIX)
    ARRAY_ALIGN = 64
    STRUCT_FMT = '<I'

    @classmethod
    def _encode_header(cls, header: str) -> bytes:
        '''
        Takes a string header, and attaches the prefix and padding to it.
        This is hard-coded to only use Version 3.0
        '''
        header = header.encode('utf8')
        hlen = len(header) + 1

        padlen = cls.ARRAY_ALIGN - (
               (cls.MAGIC_LEN + struct.calcsize(cls.STRUCT_FMT) + hlen) % cls.ARRAY_ALIGN
               )
        prefix = cls.MAGIC_PREFIX + struct.pack(cls.STRUCT_FMT, hlen + padlen)
        postfix = b' ' * padlen + b'\n'

        return prefix + header + postfix

    @classmethod
    def to_npy(cls, file: tp.IO[bytes], array: np.ndarray):
        '''Write an NPY 3.0 file to the open, writeable, binary file given by ``file``.
        '''
        if array.dtype == DTYPE_OBJECT:
            raise ValueError('no support for object dtypes')

        flags = array.flags
        fortran_order = True if flags.f_contiguous else False

        header = f'{{"descr":"{array.dtype.str}","fortran_order":{fortran_order},"shape":{array.shape}}}'
        file.write(cls._encode_header(header))

        if flags.f_contiguous and not flags.c_contiguous:
            file.write(array.T.tobytes())
        else:
            file.write(array.tobytes())

    @classmethod
    def _decode_header(cls,
            file: tp.IO[bytes],
            ) -> tp.ValuesView[tp.Any]:
        '''Extract and decode the header.
        '''
        length_size = file.read(struct.calcsize(cls.STRUCT_FMT))
        length_header = struct.unpack(cls.STRUCT_FMT, length_size)[0]
        header = file.read(length_header).decode('utf8')
        return literal_eval(header).values()

    @classmethod
    def from_npy(cls, file: tp.IO[bytes]) -> np.ndarray:
        '''Read an NPY 3.0 file.
        '''
        _ = file.read(cls.MAGIC_LEN)

        dtype, fortran_order, shape = cls._decode_header(file)
        # import ipdb; ipdb.set_trace()


class NPZConverter:
    FILE_META = '__meta__.json'
    KEY_NAMES = '__names__'
    KEY_TYPES = '__types__'
    KEY_DEPTHS = '__depths__'
    KEY_TYPES_INDEX = '__types_index__'
    KEY_TYPES_COLUMNS = '__types_columns__'

    KEY_TEMPLATE_VALUES_INDEX = '__values_index_{}__.npy'
    KEY_TEMPLATE_VALUES_COLUMNS = '__values_columns_{}__.npy'
    KEY_TEMPLATE_BLOCKS = '__blocks_{}__.npy'

    @staticmethod
    def _index_encode(
            *,
            payload_json: tp.Dict[str, tp.Hashable],
            payload_npy: tp.Dict[str, np.ndarray],
            index: 'IndexBase',
            key_template_values: str,
            key_types: str,
            depth: int,
            include: bool,
            ) -> None:
        '''
        Args:
            payload_json: mutates in place with json components
            payload_npy: mutates in place with npy components
        '''
        if depth == 1 and index._map is None: #type: ignore
            pass # do not store anything
        elif include:
            if depth == 1:
                payload_npy[key_template_values.format(0)] = index.values
            else:
                for i in range(depth):
                    payload_npy[key_template_values.format(i)] = index.values_at_depth(i)
                payload_json[key_types] = [cls.__name__ for cls in index.index_types.values] # type: ignore

    @classmethod
    def to_npz(cls,
            *,
            frame: 'Frame',
            fp: PathSpecifier, # not sure file-like StringIO works
            include_index: bool = True,
            include_columns: bool = True,
            allow_pickle: bool = True,
            ) -> None:
        '''
        Write a :obj:`Frame` as an npz file.
        '''
        payload_json: tp.Dict[str, tp.Any] = {}
        payload_npy: tp.Dict[str, np.ndarray] = {}

        payload_json[cls.KEY_NAMES] = [frame._name,
                frame._index._name,
                frame._columns._name,
                ]
        # do not store Frame class as caller will determine
        payload_json[cls.KEY_TYPES] = [
                frame._index.__class__.__name__,
                frame._columns.__class__.__name__,
                ]

        # store shape, index depths
        depth_index = frame._index.depth
        depth_columns = frame._columns.depth

        payload_json[cls.KEY_DEPTHS] = [
                len(frame._blocks._blocks),
                depth_index,
                depth_columns]

        cls._index_encode(
                payload_json=payload_json,
                payload_npy=payload_npy,
                index=frame._index,
                key_template_values=cls.KEY_TEMPLATE_VALUES_INDEX,
                key_types=cls.KEY_TYPES_INDEX,
                depth=depth_index,
                include=include_index,
                )

        cls._index_encode(
                payload_json=payload_json,
                payload_npy=payload_npy,
                index=frame._columns,
                key_template_values=cls.KEY_TEMPLATE_VALUES_COLUMNS,
                key_types=cls.KEY_TYPES_COLUMNS,
                depth=depth_columns,
                include=include_columns,
                )

        with zipfile.ZipFile(fp, 'w', zipfile.ZIP_STORED) as zf:
            for label, array in payload_npy.items():
                bio = zf.open(label, 'w')
                # np.save(bio, array, allow_pickle=allow_pickle)
                NPYConverter.to_npy(bio, array)
                bio.close()
            for i, array in enumerate(frame._blocks._blocks):
                label = cls.KEY_TEMPLATE_BLOCKS.format(i)
                bio = zf.open(label, 'w')
                NPYConverter.to_npy(bio, array)
                # np.save(bio, array, allow_pickle=allow_pickle)
                bio.close()
            zf.writestr(cls.FILE_META, json.dumps(payload_json))

    @staticmethod
    def _index_decode(*,
            zf: zipfile.ZipFile,
            zf_labels: tp.FrozenSet[str],
            allow_pickle: bool,
            payload_json: tp.Dict[str, tp.Any],
            key_template_values: str,
            key_types: str,
            depth: int,
            cls_index: tp.Type['IndexBase'],
            name: NameType,
            ) -> tp.Optional['IndexBase']:
        '''Build index or columns.
        '''
        from static_frame.core.type_blocks import TypeBlocks

        if key_template_values.format(0) not in zf_labels:
            index = None
        elif depth == 1:
            bio = zf.open(key_template_values.format(0))
            values_index = read_array(bio,
                    allow_pickle=allow_pickle,
                    )
            values_index.flags.writeable = False
            index = cls_index(values_index, name=name)
        else:
            def blocks() -> tp.Iterator[np.ndarray]:
                for i in range(depth):
                    bio = zf.open(key_template_values.format(i))
                    array = read_array(bio,
                            allow_pickle=allow_pickle,
                            )
                    array.flags.writeable = False
                    yield array

            index_tb = TypeBlocks.from_blocks(blocks())
            index_constructors = [ContainerMap.str_to_cls(name)
                    for name in payload_json[key_types]]

            index = cls_index._from_type_blocks(index_tb, #type: ignore
                    name=name,
                    index_constructors=index_constructors,
                    )
        return index

    @classmethod
    def from_npz(cls,
            *,
            constructor: tp.Type['Frame'],
            fp: PathSpecifier,
            allow_pickle: bool = True,
            ) -> 'Frame':
        '''
        Create a :obj:`Frame` from an npz file.
        '''
        from static_frame.core.type_blocks import TypeBlocks

        with zipfile.ZipFile(fp) as zf:
            zf_labels = frozenset(zf.namelist())

            payload_json = json.loads(zf.read(cls.FILE_META))
            name, name_index, name_columns = payload_json[cls.KEY_NAMES]
            block_count, depth_index, depth_columns = payload_json[cls.KEY_DEPTHS]
            cls_index, cls_columns = (ContainerMap.str_to_cls(name)
                    for name in payload_json[cls.KEY_TYPES])

            index = cls._index_decode(
                    zf=zf,
                    zf_labels=zf_labels,
                    allow_pickle=allow_pickle,
                    payload_json=payload_json,
                    key_template_values=cls.KEY_TEMPLATE_VALUES_INDEX,
                    key_types=cls.KEY_TYPES_INDEX,
                    depth=depth_index,
                    cls_index=cls_index,
                    name=name_index,
                    )

            columns = cls._index_decode(
                    zf=zf,
                    zf_labels=zf_labels,
                    allow_pickle=allow_pickle,
                    payload_json=payload_json,
                    key_template_values=cls.KEY_TEMPLATE_VALUES_COLUMNS,
                    key_types=cls.KEY_TYPES_COLUMNS,
                    depth=depth_columns,
                    cls_index=cls_columns,
                    name=name_columns,
                    )

            def blocks() -> tp.Iterator[np.ndarray]:
                for i in range(block_count):
                    bio = zf.open(cls.KEY_TEMPLATE_BLOCKS.format(i))
                    array = read_array(bio, allow_pickle=allow_pickle)
                    array.flags.writeable = False
                    yield array

            tb = TypeBlocks.from_blocks(blocks())

        return constructor(tb,
                own_data=True,
                index=index,
                own_index = False if index is None else True,
                columns=columns,
                own_columns = False if columns is None else True,
                name=name,
                )










