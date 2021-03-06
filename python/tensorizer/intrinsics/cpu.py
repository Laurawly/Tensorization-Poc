import tvm
from tvm import te
from .analyzer import _index2ramps
import functools
from .. import tune
from topi import get_const_tuple

def initializer(store, axis, dtype, lanes):
    ramps = _index2ramps(store.index, axis)
    assert 'x' not in store.value.dtype
    assert len(ramps) == 1
    return tvm.tir.Store(store.buffer_var, tvm.tir.const(0, '%sx%d' % (dtype, lanes)), ramps[0])
  
def loader(load, axis, cast_type=None):
    ramps = _index2ramps(load.index, axis, load.dtype)
    assert 'x' not in load.dtype
    loads = []
    total_lanes = 0
    is_broadcast = False
    if len(ramps) == 3 and isinstance(ramps[1], str) and isinstance(ramps[2], int):
        is_broadcast = True
        ri_cast = ramps[1]
        br_lanes = ramps[2]
        ramps = ramps[:1]
    for ramp in ramps:
        lanes = int(ramp.dtype.split('x')[1])
        dtype = load.dtype + 'x' + str(lanes)
        total_lanes += lanes
        loads.append(tvm.tir.Load(dtype, load.buffer_var, ramp))
    if is_broadcast:
        assert len(loads) == 1
        res = tvm.tir.call_intrin(ri_cast, 'tir.reinterpret', loads[0])
        res = tvm.tir.Broadcast(res, br_lanes)
    elif len(loads) == 1:
        res = loads[0]
    else:
        res = tvm.tir.Shuffle(loads, list(range(total_lanes)))
    if cast_type is not None:
        res = tvm.tir.call_intrin(cast_type, 'tir.reinterpret', res)
    return res

def writer(store, axis, operands, llvm_intrin, dtype):
    ramps = _index2ramps(store.index, axis)
    assert 'x' not in store.value.dtype
    assert len(ramps) == 1
    vnni = tvm.tir.call_llvm_intrin(dtype, llvm_intrin,
                                    tvm.tir.const(3, 'uint32'),
                                    *operands)
    return tvm.tir.Store(store.buffer_var, vnni, ramps[0])

def schedule(outs, strides, pattern, pragma, max_threads):

    from topi.util import traverse_inline
    sch = tvm.te.create_schedule([i.op for i in outs])
    output = outs[0].op

    def callback(op):
        if len(list(op.reduce_axis)):
            from .looptiler import analyze_tiling
            points = list(analyze_tiling(op, pattern))
            fobj = lambda x: (2 ** -x[0]) * (2 ** -x[1]) * x[2] * (x[3] * x[3] if 2 <= x[3] <= 8 else 1.0 / x[3])
            points.sort(key=fobj)
            points = points[::-1]
            #for x in points[::-1]:
            #    print((2 ** -x[0]), (2 ** -x[1]), x[2], (x[3] * x[3] if 2 <= x[3] <= 8 else 1.0 / x[3]))
            #    print(x[-1])

            a, b = op.input_tensors
            tune.ashape = get_const_tuple(a.shape)
            tune.bshape = get_const_tuple(b.shape)
            try:
                tune.strides = strides
            except:
                tune.strides = 'dense'

            if tune.cpu_idx is None:
                to_apply = points[0][-1]
                #with open('/home/ubuntu/Tensorization-PoC/cpu-shapes.log', 'a') as f:
                #    f.write(f'{tune.ashape} {tune.bshape} {tune.strides}\n')
                if (tune.ashape, tune.bshape, tune.strides) in tune.x86.keys():
                    to_apply = points[tune.x86[(tune.ashape, tune.bshape, tune.strides)]][-1]
            else:
                tune.total_idx = len(points)
                to_apply = points[tune.cpu_idx][-1]

            to_schedule = output
            loops = []
            parallel_level = None
            for i in range(len(output.axis)):

                if isinstance(to_apply[i][0], tuple) and to_apply[i][0][1] == 'parallel':
                    to_schedule = op
                    if str(op) != str(output):
                        outer, inner = sch[output].split(output.axis[i], nparts=to_apply[i][0][0])
                        parallel_level = outer
                        sch[op].compute_at(sch[output], outer)
                        if i == len(output.axis) - 1:
                            sch[output].vectorize(inner)
                        else:
                            sch[output].vectorize(output.axis[-1])

                to_append = []
                to_split = to_schedule.axis[i]

                for j in to_apply[i][1:][::-1]:
                    if isinstance(j, int):
                        outer, inner = sch[to_schedule].split(to_split, j)
                        to_split = outer
                    else:
                        outer, inner = sch[to_schedule].split(to_split, j[0])
                        to_split = outer

                    to_append = [inner] + to_append
                to_append = [to_split] + to_append
                loops += to_append

            for i in range(len(op.reduce_axis)):
                to_split = op.reduce_axis[i]
                to_append = []
                for j in to_apply[i + len(op.axis)][1:][::-1]:
                    if isinstance(j, int):
                        outer, inner = sch[op].split(to_split, j)
                        to_split = outer
                    else:
                        outer, inner = sch[op].split(to_split, j[0])
                        to_split = outer
                    to_append = [inner] + to_append
                to_append = [to_split] + to_append
                loops += to_append

            annot = []
            for i, elem in enumerate(to_apply):
                for j in elem:
                    if isinstance(j, int):
                        annot.append(None if i < len(op.axis) else 'reduce')
                    else:
                        annot.append(j[1])
            assert len(annot) == len(loops), '%d != %d' % (len(annot), len(loops))


            unroll, stencil, simple, reduction = [], [], [], []
            for i, elem in enumerate(zip(annot, loops)):
                # print(elem)
                hint, axis = elem
                if unroll and hint is None:
                    unroll.append(axis)
                elif hint == 'parallel':
                    fusion = sch[output].fuse(*(simple + [parallel_level if parallel_level is not None else axis]))
                    sch[output].parallel(fusion)
                    if str(op) != str(output):
                        sch[op].compute_at(sch[output], fusion)
                    simple = []
                elif hint == 'unroll':
                    unroll.append(axis)
                elif hint == 'offload':
                    stencil.append(axis)
                elif hint == 'reduction':
                    reduction.append(axis)
                else:
                    simple.append(axis)
            for i in unroll:
                sch[op].unroll(i)
            sch[op].pragma(stencil[0], 'tensorize', pragma)
            if str(op) != str(output):
                # print(simple, reduction, unroll, stencil, sep='\n')
                sch[op].reorder(*(simple + reduction + unroll + stencil))
            else:
                sch[op].reorder(*([fusion] + simple + reduction + unroll + stencil))

    traverse_inline(sch, output, callback)

    return sch

x86_init = functools.partial(initializer, dtype='int32', lanes=16)
x86_loader = functools.partial(loader, cast_type='int32x16')
x86_writeback = functools.partial(writer, llvm_intrin='llvm.x86.avx512.vpdpbusd.512', dtype='int32x16')
from .pattern import x86_vnni
x86_schedule = functools.partial(schedule, pattern=x86_vnni, pragma='vnni', max_threads=10000)

arm_init = functools.partial(initializer, dtype='int32', lanes=4)
arm_acc = functools.partial(loader, cast_type='int32x4')
arm_operand = functools.partial(loader, cast_type='int8x16')
arm_writeback = functools.partial(writer, llvm_intrin='llvm.aarch64.neon.sdot.v4i32.v16i8', dtype='int32x4')
from .pattern import arm_sdot128_i8i16
arm_schedule = functools.partial(schedule, pattern=arm_sdot128_i8i16, pragma='vdot', max_threads=10000)