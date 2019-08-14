import tvm
import topi
import numpy as np


n, k, m = 4096, 4096, 4096
a = tvm.placeholder((n, k), 'int8', name='a')
b = tvm.placeholder((m, k), 'int8', name='b')

packed_b = tvm.compute((m // 16, k // 4, 16, 4), lambda w, x, y, z: b[w * 16 + y, x * 4 + z], name='packed_b')

red = tvm.reduce_axis((0, k), name='k')
c = tvm.compute((n, m),
        lambda x, y: tvm.sum(a[x, red].astype('int32') * packed_b[y // 16, red // 4, y % 16, red % 4].astype('int32'), axis=red),
        name='c')

sch = tvm.create_schedule(c.op)


#
sch[packed_b].vectorize(packed_b.op.axis[-1])
sch[packed_b].unroll(packed_b.op.axis[-2])

x, y = c.op.axis
r = c.op.reduce_axis[0]
yo, yi = sch[c].split(y, 16)
ro, ri = sch[c].split(r, 4)

#
import vnni
with tvm.build_config(add_lower_pass= [(1, vnni.vnni_transformation)]):
    sch[c].pragma(yi, 'vnni')
    roo, roi = sch[c].split(ro, 16)
    cached_a = sch.cache_read(a, 'global', [c])
    sch[cached_a].vectorize(cached_a.op.axis[1])
    xo, xi = sch[c].split(x, 32)
    sch[cached_a].compute_at(sch[c], xi)
    sch[c].reorder(xo, yo, roo, xi, roi, yi, ri)
    print(tvm.lower(sch, [a, b, c], simple_mode=True))
    module = tvm.build(sch, [a, b, c], target='llvm -mcpu=cascadelake')

    np_a = np.random.randint(0, 64, (n, k), dtype='int8')
    np_b = np.random.randint(0, 64, (m, k), dtype='int8')
    np_c = np.dot(np_a.astype('int32'), np_b.astype('int32').T)

    nd_a = tvm.nd.array(np_a)
    nd_b = tvm.nd.array(np_b)
    nd_c = tvm.nd.array(np.zeros((n, m), dtype='int32'))

    module(nd_a, nd_b, nd_c)
    tvm.testing.assert_allclose(nd_c.asnumpy(), np_c)

    module = module.time_evaluator(module.entry_name, tvm.cpu(0), number=10)
    print(module(nd_a, nd_b, nd_c).mean)