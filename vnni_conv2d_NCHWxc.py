# TODO(@were): Simplify the usage of linear detection.
# TODO(@were): Support masking.
# TODO(@were): Integrate it to TVM.

import tvm
import topi
import numpy as np

with tvm.target.create('llvm'):
    N, C, H, W, c = 1, 2, 192, 192, 4
    kN, C, kH, kW, kc, kn = 1, C, 32, 32, c, 16
    image = tvm.placeholder((N, C, H, W, c), dtype='int8', name='input')
    kernel = tvm.placeholder((kN, C, kH, kW, kc, kn), dtype='int8', name='kernel')

    conv = topi.nn.conv2d_NCHWc(image, kernel, stride=(1, 1), padding=(0, 0), dilation=(1, 1),
                                layout='NCHW%dc' % c, out_layout = 'NCHW4c', out_dtype='int32')
    print(conv.shape)
    print(kernel.shape)

    sch = tvm.create_schedule(conv.op)

    n, c0, h, w, c1 = conv.op.axis
    rc, rh, rw = conv.op.reduce_axis
    rco, rci = sch[conv].split(rc, c)
    c1o, c1i = sch[conv].split(c1, 16)
    rwo, rwi = sch[conv].split(rw, 16)

    in_cache = sch.cache_read(image, 'global', [conv])
    sch[in_cache].compute_at(sch[conv], w)
    axis = sch[in_cache].fuse(in_cache.op.axis[3], in_cache.op.axis[4])
    sch[in_cache].vectorize(axis)


    #sch[conv].parallel(h)
    sch[conv].reorder(n, c0, h, rh, c1o, rco, rwo, w, rwi, c1i, rci)
    sch[conv].pragma(c1i, 'vnni')

    print(tvm.lower(sch, [image, kernel, conv], simple_mode=True))
    answer_ref = tvm.build(sch, [image, kernel, conv])

    import vnni
    with tvm.build_config(add_lower_pass= [(1, vnni.vnni_transformation)]):
        print(tvm.lower(sch, [image, kernel, conv], simple_mode=True))
        module = tvm.build(sch, [image, kernel, conv], target='llvm -mcpu=cascadelake')

        shapes = [i.shape for i in [image, kernel]]
        shapes = [list(map(lambda x: x.value, i)) for i in shapes]
        out_shape = list(map(lambda x: x.value, conv.shape)) 
        types = ['int8', 'int8', 'int32']
        args = [tvm.ndarray.array(np.random.randint(0, 127, i, j)) for i, j in zip(shapes, types)]
        out = tvm.ndarray.array(np.zeros(out_shape).astype('int32'))
        ans = tvm.ndarray.array(np.zeros(out_shape).astype('int32'))

        module.save('vnni.ll')
        module(args[0], args[1], out)
        answer_ref(args[0], args[1], ans)
        tvm.testing.assert_allclose(out.asnumpy(), ans.asnumpy())

        vannila = answer_ref.time_evaluator(answer_ref.entry_name, tvm.cpu(0), number=10)
        vnni = module.time_evaluator(module.entry_name, tvm.cpu(0), number=10)
        print(vannila(args[0], args[1], ans).mean)
        print(vnni(args[0], args[1], out).mean)
