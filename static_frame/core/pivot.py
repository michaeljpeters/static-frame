import typing as tp
from functools import partial
from collections import defaultdict
from itertools import repeat
from itertools import product
from itertools import chain

import numpy as np
from arraykit import resolve_dtype
from arraykit import resolve_dtype_iter

from static_frame.core.index_base import IndexBase
from static_frame.core.index import Index
from static_frame.core.index_hierarchy import IndexHierarchy
from static_frame.core.util import DepthLevelSpecifier
from static_frame.core.util import IndexConstructor
from static_frame.core.util import UFunc
from static_frame.core.util import ufunc_dtype_to_dtype
from static_frame.core.util import ufunc_unique
from static_frame.core.util import ufunc_unique1d
from static_frame.core.util import EMPTY_TUPLE
from static_frame.core.util import DEFAULT_FAST_SORT_KIND
from static_frame.core.util import dtype_from_element

from static_frame.core.container_util import index_from_optional_constructor
from static_frame.core.type_blocks import TypeBlocks

if tp.TYPE_CHECKING:
    from static_frame.core.frame import Frame #pylint: disable=W0611 #pragma: no cover
    from static_frame.core.series import Series #pylint: disable=W0611 #pragma: no cover



#-------------------------------------------------------------------------------
def extrapolate_column_fields(
        columns_fields: tp.Sequence[tp.Hashable],
        group: tp.Tuple[tp.Hashable, ...],
        data_fields: tp.Sequence[tp.Hashable],
        func_fields: tp.Iterable[tp.Hashable],
        ) -> tp.Iterable[tp.Hashable]:
    '''"Determine columns to be reatined from gruop and data fields.
    Used in Frame.pivot.

    Args:
        group: a unique label from the the result of doing a group-by with the `columns_fields`.
    '''
    # NOTE: this will work correctly with no_func=True

    columns_fields_len = len(columns_fields)
    data_fields_len = len(data_fields)

    sub_columns: tp.Iterable[tp.Hashable]

    if columns_fields_len == 1 and data_fields_len == 1:
        if not func_fields:
            sub_columns = group # already a tuple
        else:
            sub_columns = [group + (label,) for label in func_fields]
    elif columns_fields_len == 1 and data_fields_len > 1:
        # create a sub heading for each data field
        if not func_fields:
            sub_columns = list(product(group, data_fields))
        else:
            sub_columns = list(product(group, data_fields, func_fields))
    elif columns_fields_len > 1 and data_fields_len == 1:
        if not func_fields:
            sub_columns = (group,)
        else:
            sub_columns = [group + (label,) for label in func_fields]
    else: # group is already a tuple of the partial column label; need to extend with each data field
        if not func_fields:
            sub_columns = [group + (field,) for field in data_fields]
        else:
            sub_columns = [group + (field, label) for field in data_fields for label in func_fields]

    return sub_columns

def pivot_records_dtypes(
        dtype_map: 'Series',
        data_fields: tp.Iterable[tp.Hashable],
        func_single: tp.Optional[UFunc],
        func_map: tp.Sequence[tp.Tuple[tp.Hashable, UFunc]]
        ) -> tp.Iterator[np.dtype]:
    '''
    Iterator of ordered dtypes, providing multiple dtypes per field when func_map is provided.
    '''
    for field in data_fields:
        dtype = dtype_map[field]
        if func_single:
            yield ufunc_dtype_to_dtype(func_single, dtype)
        else: # we assume
            for _, func in func_map:
                yield ufunc_dtype_to_dtype(func, dtype)

def pivot_records_items(
        blocks: TypeBlocks,
        group_fields_iloc: tp.Iterable[tp.Hashable],
        group_depth: int,
        data_fields_iloc: tp.Iterable[tp.Hashable],
        func_single: tp.Optional[UFunc],
        func_map: tp.Sequence[tp.Tuple[tp.Hashable, UFunc]],
        func_no: bool,
        kind: str,
        ) -> tp.Iterator[tp.Tuple[tp.Hashable, tp.Sequence[tp.Any]]]:
    '''
    Given a Frame and pivot parameters, perform the group by ont he group_fields and within each group,
    '''
    # NOTE: this delivers results by label, row for use in a Frame.from_records_items constructor
    group_key = group_fields_iloc if group_depth > 1 else group_fields_iloc[0] #type: ignore
    record_size = len(data_fields_iloc) * (1 if (func_single or func_no) else len(func_map))
    record: tp.List[tp.Any]

    for label, _, part in blocks.group(axis=0, key=group_key, kind=kind):
        if func_no:
            if len(part) != 1:
                raise RuntimeError('pivot requires aggregation of values; provide a `func` argument.')
            record = [part._extract(0, column_key) for column_key in data_fields_iloc]
        elif func_single:
            record = [func_single(part._extract_array_column(column_key)) for
                    column_key in data_fields_iloc]
        else:
            record = [None] * record_size # This size can be pre allocated,
            pos = 0
            for column_key in data_fields_iloc:
                values = part._extract_array_column(column_key)
                for _, func in func_map:
                    record[pos] = func(values)
                    pos += 1
        yield label, record

from static_frame.core.util import NameType


def pivot_items_to_block(
        blocks: TypeBlocks,
        group_fields_iloc: tp.Iterable[tp.Hashable],
        group_depth: int,
        data_field_iloc: tp.Hashable,
        func_single: tp.Optional[UFunc],
        dtype: tp.Optional[np.dtype],
        fill_value: tp.Any,
        fill_value_dtype: np.dtype,
        index_outer: 'IndexBase',
        kind: str,
        ) -> np.ndarray:
    '''
    Specialized generator of pairs for when we have only one data_field and one function.
    '''
    from static_frame.core.series import Series
    group_key = group_fields_iloc if group_depth > 1 else group_fields_iloc[0] #type: ignore

    if func_single and dtype is not None:
        array = np.full(len(index_outer),
                fill_value,
                dtype=resolve_dtype(dtype, fill_value_dtype),
                )
        for label, _, values in blocks.group_extract(
                axis=0,
                key=group_key,
                extract=data_field_iloc,
                kind=kind,
                ):
            array[index_outer._loc_to_iloc(label)] = func_single(values)
        array.flags.writeable = False
        return array

    if func_single and dtype is None:
        def gen() -> tp.Iterator[tp.Tuple[int, tp.Any]]:
            for label, _, values in blocks.group_extract(
                    axis=0,
                    key=group_key,
                    extract=data_field_iloc,
                    kind=kind,
                    ):
                yield index_outer._loc_to_iloc(label), func_single(values)
        post = Series.from_items(gen())
        if len(post) == len(index_outer):
            array = np.empty(len(index_outer), dtype=post.dtype)
        else:
            array = np.full(len(index_outer),
                    fill_value,
                    dtype=resolve_dtype(post.dtype, fill_value_dtype),
                    )
        array[post.index.values] = post.values
        array.flags.writeable = False
        return array

    # func_no scenario
    if group_depth == 1:
        # NOTE: can replace _extract_array_column with an iterator of values
        labels = [index_outer._loc_to_iloc(label) for label in blocks._extract_array_column(group_key)]
    else:
        # NOTE: can replace _extract_array_column with an iterator of values
        labels = [index_outer._loc_to_iloc(tuple(label)) for label in blocks._extract_array(column_key=group_key)]

    values = blocks._extract_array_column(data_field_iloc)
    assert dtype == values.dtype

    if len(values) == len(index_outer):
        array = np.empty(len(index_outer), dtype=dtype)
    else:
        array = np.full(len(index_outer),
                fill_value,
                dtype=resolve_dtype(values.dtype, fill_value_dtype),
                )
    array[labels] = values
    array.flags.writeable = False
    return array

from static_frame.core.util import iterable_to_array_1d

def pivot_items_to_frame(
        blocks: TypeBlocks,
        group_fields_iloc: tp.Iterable[tp.Hashable],
        group_depth: int,
        data_field_iloc: tp.Hashable,
        func_single: tp.Optional[UFunc],
        frame_cls: tp.Type['Frame'],
        name: NameType,
        dtype: np.dtype,
        index_constructor: IndexConstructor,
        columns_constructor: IndexConstructor,
        kind: str,
        ) -> 'Frame':
    '''
    Specialized generator of pairs for when we have only one data_field and one function.
    This version returns a Frame.
    '''

    from static_frame.core.series import Series
    group_key = group_fields_iloc if group_depth > 1 else group_fields_iloc[0] #type: ignore

    if func_single:
        labels = []
        values = []
        for label, _, v in blocks.group_extract(
                axis=0,
                key=group_key,
                extract=data_field_iloc,
                kind=kind,
                ):
            labels.append(label)
            values.append(func_single(v))

        if dtype is None:
            array, _ = iterable_to_array_1d(values, count=len(values))
        else:
            array = np.array(values, dtype=dtype)
        array.flags.writeable = False
        index = index_constructor(labels)
        return frame_cls.from_elements(array,
                index=index,
                own_index=True,
                columns=(name,),
                columns_constructor=columns_constructor,
                )

    # func_no scenario
    if group_depth == 1:
        index = index_constructor(blocks._extract_array_column(group_key))
    else:
        index = index_constructor(tuple(label) for label in blocks._extract_array(column_key=group_key))

    array = blocks._extract_array_column(data_field_iloc)
    assert dtype == array.dtype

    return frame_cls.from_elements(array,
            index=index,
            own_index=True,
            columns=(name,),
            columns_constructor=columns_constructor,
            )




# def pivot_items_to_frame(
#         blocks: TypeBlocks,
#         group_fields_iloc: tp.Iterable[tp.Hashable],
#         group_depth: int,
#         data_field_iloc: tp.Hashable,
#         func_single: tp.Optional[UFunc],
#         frame_cls: tp.Type['Frame'],
#         name: NameType,
#         dtype: np.dtype,
#         index_constructor: IndexConstructor,
#         columns_constructor: IndexConstructor,
#         kind: str,
#         ) -> 'Frame':

    # from static_frame.core.frame import Frame
    # group_key = group_fields_iloc if group_depth > 1 else group_fields_iloc[0] #type: ignore

    # if func_single:
    #     # this approach shown to be slower
    #     index = []
    #     def gen():
    #         for label, _, sub in blocks.group(axis=0, key=group_key, kind=kind):
    #             # import ipdb; ipdb.set_trace()
    #             values = sub._extract_array_column(data_field_iloc)
    #             index.append(label)
    #             yield func_single(values) # cannot know the dtype

    #     return frame_cls.from_elements(
    #             gen(),
    #             columns=(name,),
    #             index=index,
    #             index_constructor=index_constructor,
    #             columns_constructor=columns_constructor,
    #             dtype=dtype,
    #             )
    # # func_no scenario
    # # labels via blocks._extract_array_column(group_key) must be unique
    # if group_depth == 1:
    #     return frame_cls.from_elements(
    #             blocks._extract_array_column(data_field_iloc),
    #             index=blocks._extract_array_column(group_key),
    #             columns=(name,),
    #             index_constructor=index_constructor,
    #             columns_constructor=columns_constructor,
    #             dtype=dtype,
    #             )
    # raise NotImplementedError()






def pivot_core(
        *,
        frame: 'Frame',
        index_fields: tp.List[tp.Hashable],
        columns_fields: tp.List[tp.Hashable],
        data_fields: tp.List[tp.Hashable],
        func_fields: tp.Tuple[tp.Hashable, ...],
        func_single: tp.Optional[UFunc],
        func_map: tp.Sequence[tp.Tuple[tp.Hashable, UFunc]],
        fill_value: object = np.nan,
        index_constructor: IndexConstructor = None,
        kind: str = DEFAULT_FAST_SORT_KIND,
        ) -> 'Frame':
    '''Core implementation of Frame.pivot(). The Frame has already been reduced to just relevant columns, and all fields groups are normalized as lists of hashables.
    '''
    from static_frame.core.series import Series
    from static_frame.core.frame import Frame

    func_no = func_single is None and func_map is EMPTY_TUPLE

    data_fields_len = len(data_fields)
    index_depth = len(index_fields)

    # all are lists of hashables; get converted to lists of integers
    columns_loc_to_iloc = frame.columns._loc_to_iloc
    index_fields_iloc: tp.Sequence[int] = columns_loc_to_iloc(index_fields) #type: ignore
    data_fields_iloc: tp.Sequence[int] = columns_loc_to_iloc(data_fields) #type: ignore
    columns_fields_iloc: tp.Sequence[int] = columns_loc_to_iloc(columns_fields) #type: ignore

    # For data fields, we add the field name, not the field values, to the columns.
    columns_name = tuple(columns_fields)
    if data_fields_len > 1 or not columns_fields:
        # if no columns_fields, have to add values label
        columns_name = tuple(chain(*columns_fields, ('values',)))
    if len(func_map) > 1:
        columns_name = columns_name + ('func',)

    columns_depth = len(columns_name)

    if columns_depth == 1:
        columns_name = columns_name[0] # type: ignore
        columns_constructor = partial(frame._COLUMNS_CONSTRUCTOR, name=columns_name)
    else:
        columns_constructor = partial(frame._COLUMNS_HIERARCHY_CONSTRUCTOR.from_labels,
                depth_reference=columns_depth,
                name=columns_name)

    dtype_map = frame.dtypes # returns a Series
    if func_no:
        dtypes_per_data_fields = tuple(dtype_map[field] for field in data_fields)
        if data_fields_len == 1:
            dtype_single = dtype_map[data_fields[0]]
    else:
        dtypes_per_data_fields = tuple(pivot_records_dtypes(
                dtype_map=dtype_map,
                data_fields=data_fields,
                func_single=func_single,
                func_map=func_map,
                ))
        if func_single and data_fields_len == 1:
            dtype_single = ufunc_dtype_to_dtype(func_single, dtype_map[data_fields[0]])

    fill_value_dtype = dtype_from_element(fill_value)

    #---------------------------------------------------------------------------
    # first major branch: if we are only grouping be index fields

    if not columns_fields: # group by is only index_fields
        columns = data_fields if (func_no or func_single) else tuple(
                product(data_fields, func_fields)
                )

        # NOTE: at this time we do not automatically give back an IndexHierarchy when index_depth is == 1, as the order of the resultant values may not be hierarchable.
        name_index = index_fields[0] if index_depth == 1 else tuple(index_fields)
        if index_constructor:
            index_constructor = partial(index_constructor, name=name_index)
        else:
            index_constructor = partial(Index, name=name_index)

        if len(columns) == 1: # length of columns is equal to length of datafields, func_map not needed
            f = pivot_items_to_frame(blocks=frame._blocks,
                    group_fields_iloc=index_fields_iloc,
                    group_depth=index_depth,
                    data_field_iloc=data_fields_iloc[0],
                    func_single=func_single,
                    frame_cls=frame.__class__,
                    name=columns[0],
                    dtype=dtype_single,
                    index_constructor=index_constructor,
                    columns_constructor=columns_constructor,
                    kind=kind,
                    )
        else:
            f = frame.from_records_items(
                    pivot_records_items(
                            blocks=frame._blocks,
                            group_fields_iloc=index_fields_iloc,
                            group_depth=index_depth,
                            data_fields_iloc=data_fields_iloc,
                            func_single=func_single,
                            func_map=func_map,
                            func_no=func_no,
                            kind=kind,
                    ),
                    columns_constructor=columns_constructor,
                    columns=columns,
                    index_constructor=index_constructor,
                    dtypes=dtypes_per_data_fields,
                    )

        # have to rename columns if derived in from_concat:
        # NOTE: not sure if have to call call columns_constructor
        columns_final = (f.columns.rename(columns_name) if columns_depth == 1
                else columns_constructor(f.columns))
        return f.relabel(columns=columns_final) #type: ignore

    #---------------------------------------------------------------------------
    # second major branch: we are only grouping by index and columns fields

    # avoid doing a multi-column-style selection if not needed
    if len(columns_fields) == 1:
        # columns_group = columns_fields[0]
        retuple_group_label = True
    else:
        # columns_group = columns_fields
        retuple_group_label = False

    columns_loc_to_iloc = frame.columns._loc_to_iloc
    # group by on 1 or more columns fields
    # NOTE: explored doing one group on index and columns that insert into pre-allocated arrays, but that proved slower than this approach
    group_key = columns_fields_iloc if len(columns_fields_iloc) > 1 else columns_fields_iloc[0]

    index_outer = pivot_outer_index(frame=frame,
                index_fields=index_fields,
                index_depth=index_depth,
                index_constructor=index_constructor,
                )

    # collect subframes based on an index of tuples and columns of tuples (if depth > 1)
    sub_blocks = []
    sub_columns_collected: tp.List[tp.Hashable] = []

    for group, _, sub in frame._blocks.group(axis=0, key=group_key, kind=kind):
        # derive the column fields represented by this group
        sub_columns = extrapolate_column_fields(
                columns_fields,
                group if not retuple_group_label else (group,),
                data_fields,
                func_fields,
                )
        sub_columns_collected.extend(sub_columns)

        # NOTE: used to pre-extract index to check if grouping was necessary; this prooved too expensive when doing grouping
        # sub is TypeBlocks unique value in columns_group; this may or may not have unique index fields; if not, it needs to be aggregated
        # if index_depth == 1:
        #     sub_index_labels = sub._extract_array_column(index_fields_iloc[0])
        #     sub_index_labels_unique = ufunc_unique1d(sub_index_labels)
        # else: # match to an index of tuples; the order might not be the same as IH
        #     # NOTE: might be able to keep arays and concat below
        #     sub_index_labels = tuple(zip(*(
        #             sub._extract_array_column(columns_loc_to_iloc(f))
        #             for f in index_fields)))
        #     sub_index_labels_unique = set(sub_index_labels)
        # if sub_index_labels are not unique we need to aggregate
        # if len(sub_index_labels_unique) != len(sub_index_labels):

        sub_frame: Frame

        # if sub_columns length is 1, that means that we only need to extract one column out of the sub Frame
        if len(sub_columns) == 1:
            sub_block = pivot_items_to_block(blocks=sub,
                            group_fields_iloc=index_fields_iloc,
                            group_depth=index_depth,
                            data_field_iloc=data_fields_iloc[0],
                            func_single=func_single,
                            dtype=dtype_single,
                            index_outer=index_outer,
                            fill_value=fill_value,
                            fill_value_dtype=fill_value_dtype,
                            kind=kind,
                            )
            sub_blocks.append(sub_block)
        else:
            sub_frame = Frame.from_records_items(
                    pivot_records_items(
                            blocks=sub,
                            group_fields_iloc=index_fields_iloc,
                            group_depth=index_depth,
                            data_fields_iloc=data_fields_iloc,
                            func_single=func_single,
                            func_map=func_map,
                            func_no=func_no,
                            kind=kind,
                            ),
                    dtypes=dtypes_per_data_fields,
                    )
            sub_frame = sub_frame.reindex(index_outer,
                    own_index=True,
                    fill_value=fill_value,
                    )
            sub_blocks.extend(sub_frame._blocks._blocks)

        # else:
        #     # we have unique values per index item, but may not have a complete index
        #     if func_no:
        #         if len(data_fields) == 1:
        #             sub_frame = Frame(
        #                     sub._extract_array_column(data_fields_iloc[0]),
        #                     index=sub_index_labels,
        #                     index_constructor=index_constructor,
        #                     own_data=True)
        #         else:
        #             sub_frame = Frame(
        #                     sub._extract(row_key=None,
        #                             column_key=data_fields_iloc),
        #                     index=sub_index_labels,
        #                     index_constructor=index_constructor,
        #                     own_data=True)
        #     elif func_single:
        #         # NOTE: apply function with func_single is akward
        #         if len(data_fields) == 1:
        #             sub_frame = Frame(
        #                     sub._extract_array_column(data_fields_iloc[0]),
        #                     index=sub_index_labels,
        #                     index_constructor=index_constructor,
        #                     own_data=True,
        #                     )
        #         else:
        #             sub_frame = Frame(
        #                     sub._extract(row_key=None,
        #                             column_key=data_fields_iloc),
        #                     index=sub_index_labels,
        #                     index_constructor=index_constructor,
        #                     own_data=True)
        #     else:
        #         def blocks() -> tp.Iterator[np.ndarray]:
        #             for field in data_fields_iloc:
        #                 for _, func in func_map:
        #                     yield sub._extract_array_column(field)
        #         sub_frame = Frame(
        #                 TypeBlocks.from_blocks(blocks()),
        #                 index=sub_index_labels,
        #                 own_data=True,
        #                 )
        # can we avoid this reindex if we create sub_frame correctly from the begining
        # sub_frame = sub_frame.reindex(index_outer,
        #         own_index=True,
        #         fill_value=fill_value,
        #         )
        # if sub_frame.ndim == 1:
        #     sub_blocks.append(sub_frame.values)
        # else:
        #     sub_blocks.extend(sub_frame._blocks._blocks) # type: ignore

    tb = TypeBlocks.from_blocks(sub_blocks)
    return frame.__class__(tb,
            index=index_outer,
            columns=columns_constructor(sub_columns_collected),
            own_data=True,
            own_index=True,
            own_columns=True,
            )


#-------------------------------------------------------------------------------

def pivot_outer_index(
        frame: 'Frame',
        index_fields: tp.Sequence[tp.Hashable],
        index_depth: int,
        index_constructor: IndexConstructor = None,
        ) -> IndexBase:

    index_loc = index_fields if index_depth > 1 else index_fields[0]

    if index_depth == 1:
        index_values = ufunc_unique1d(
                frame._blocks._extract_array_column(
                        frame._columns._loc_to_iloc(index_loc)),
                )
        index_values.flags.writeable = False
        name = index_fields[0]
        index_inner = index_from_optional_constructor(
                index_values,
                default_constructor=partial(Index, name=name),
                explicit_constructor=None if index_constructor is None else partial(index_constructor, name=name),
                )
    else: # > 1
        # NOTE: this might force type an undesirable consolidation
        index_values = ufunc_unique(
                frame._blocks._extract_array(
                        column_key=frame._columns._loc_to_iloc(index_loc)),
                axis=0)
        index_values.flags.writeable = False
        # NOTE: if index_types need to be provided to an IH here, they must be partialed in the single-argument index_constructor
        name = tuple(index_fields)
        index_inner = index_from_optional_constructor( # type: ignore
                index_values,
                default_constructor=partial(
                        IndexHierarchy.from_labels,
                        name=name,
                        ),
                explicit_constructor=None if index_constructor is None else partial(index_constructor, name=name),
                ).flat()
    return index_inner


#-------------------------------------------------------------------------------

class PivotIndexMap(tp.NamedTuple):
    targets_unique: tp.Iterable[tp.Hashable]
    target_depth: int
    target_select: np.ndarray
    group_to_target_map: tp.Dict[tp.Optional[tp.Hashable], tp.Dict[tp.Any, int]]
    group_depth: int
    group_select: np.ndarray
    group_to_dtype: tp.Dict[tp.Optional[tp.Hashable], np.dtype]

def pivot_index_map(*,
        index_src: IndexBase,
        depth_level: DepthLevelSpecifier,
        dtypes_src: tp.Optional[tp.Sequence[np.dtype]],
        ) -> PivotIndexMap:
    '''
    Args:
        dtypes_src: must be of length equal to axis
    '''
    # We are always moving levels from one axis to another; after application, the expanded axis will always be hierarchical, while the contracted axis may or may not be. From the contract axis, we need to divide the depths into two categories: targets (the depths to be moved and added to expand axis) and groups (unique combinations that remain on the contract axis after removing targets).

    # Unique target labels are added to labels on the expand axis; unique group labels become the new contract axis.

    target_select = np.full(index_src.depth, False)
    target_select[depth_level] = True
    group_select = ~target_select

    group_arrays = []
    target_arrays = []
    for i, v in enumerate(target_select):
        if v:
            target_arrays.append(index_src.values_at_depth(i))
        else:
            group_arrays.append(index_src.values_at_depth(i))

    group_depth = len(group_arrays)
    target_depth = len(target_arrays)
    group_to_dtype: tp.Dict[tp.Optional[tp.Hashable], np.dtype] = {}
    targets_unique: tp.Iterable[tp.Hashable]

    if group_depth == 0:
        # targets must be a tuple
        group_to_target_map = {
                None: {v: idx for idx, v in enumerate(zip(*target_arrays))}
                }
        targets_unique = [k for k in group_to_target_map[None]]
        if dtypes_src is not None:
            group_to_dtype[None] = resolve_dtype_iter(dtypes_src)
    else:
        group_to_target_map = defaultdict(dict)
        targets_unique = dict() # Store targets in order observed

        for axis_idx, (group, target, dtype) in enumerate(zip(
                zip(*group_arrays), # get tuples of len 1 to depth
                zip(*target_arrays),
                (dtypes_src if dtypes_src is not None else repeat(None)),
                )):
            if group_depth == 1:
                group = group[0]
            # targets are transfered labels; groups are the new columns
            group_to_target_map[group][target] = axis_idx
            targets_unique[target] = None #type: ignore

            if dtypes_src is not None:
                if group in group_to_dtype:
                    group_to_dtype[group] = resolve_dtype(group_to_dtype[group], dtype)
                else:
                    group_to_dtype[group] = dtype

    return PivotIndexMap( #pylint: disable=E1120
            targets_unique=targets_unique,
            target_depth=target_depth,
            target_select=target_select,
            group_to_target_map=group_to_target_map, #type: ignore
            group_depth=group_depth,
            group_select=group_select,
            group_to_dtype=group_to_dtype
            )


#-------------------------------------------------------------------------------
class PivotDeriveConstructors(tp.NamedTuple):
    contract_dst: tp.Optional[tp.Iterable[tp.Hashable]]
    contract_constructor: IndexConstructor
    expand_constructor: IndexConstructor

def pivot_derive_constructors(*,
        contract_src: IndexBase,
        expand_src: IndexBase,
        group_select: np.ndarray, # Boolean
        group_depth: int,
        target_select: np.ndarray,
        # target_depth: int,
        group_to_target_map: tp.Dict[tp.Hashable, tp.Tuple[tp.Hashable]],
        expand_is_columns: bool,
        frame_cls: tp.Type['Frame'],
        ) -> PivotDeriveConstructors:
    '''
    pivot_stack: columns is contract, index is expand
    pivot_unstack: index is contract, columns is expand
    '''
    # NOTE: group_select, target_select operate on the contract axis
    if expand_is_columns:
        contract_cls = Index
        contract_cls_hierarchy = IndexHierarchy
        expand_cls_hierarchy = frame_cls._COLUMNS_HIERARCHY_CONSTRUCTOR
    else: # contract is columns
        contract_cls = frame_cls._COLUMNS_CONSTRUCTOR
        contract_cls_hierarchy = frame_cls._COLUMNS_HIERARCHY_CONSTRUCTOR
        expand_cls_hierarchy = IndexHierarchy

    # NOTE: not propagating name attr, as not obvious how it should when depths are exiting and entering

    # contract axis may or may not be IndexHierarchy after extracting depths
    if contract_src.depth == 1: # will removed that one level, thus need IndexAuto
        contract_dst = None
        contract_constructor = contract_cls
    else:
        contract_src_types = contract_src.index_types.values
        contract_dst_types = contract_src_types[group_select]
        if group_depth == 0:
            contract_dst = None
            contract_constructor = contract_cls
        elif group_depth == 1:
            contract_dst = list(group_to_target_map.keys())
            contract_constructor = contract_dst_types[0]
        else:
            contract_dst = list(group_to_target_map.keys())
            contract_constructor = partial( #type: ignore
                    contract_cls_hierarchy.from_labels,
                    index_constructors=contract_dst_types,
                    )

    # expand axis will always be IndexHierarchy after adding depth
    if expand_src.depth == 1:
        expand_types = [expand_src.__class__]
    else:
        expand_types = list(expand_src._levels.index_types()) #type: ignore

    if contract_src.depth == 1:
        expand_types.append(contract_src.__class__)
    else:
        expand_types.extend(contract_src_types[target_select])

    expand_constructor = partial(
            expand_cls_hierarchy.from_labels,
            index_constructors=expand_types,
            # name=expand_src.name,
            )

    # NOTE: expand_dst labels will come from the values generator
    return PivotDeriveConstructors( #pylint: disable=E1120
            contract_dst=contract_dst,
            contract_constructor=contract_constructor,
            expand_constructor=expand_constructor,
            )


