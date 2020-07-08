python3 run.py --symbol-file=models/imagenet-inception-bn-quantized.json --param-file=models/imagenet-inception-bn-quantized.params --image-shape=3,224,224 --ctx=cpu --num-inference-batches=5
python3 run.py --symbol-file=models/inceptionv3-quantized.json --param-file=models/inceptionv3-quantized.params --image-shape=3,299,299 --ctx=cpu --num-inference-batches=5
python3 run.py --symbol-file=models/mobilenetv1-quantized.json --param-file=models/mobilenetv1-quantized.params --image-shape=3,224,224 --ctx=cpu --num-inference-batches=5
python3 run.py --symbol-file=models/mobilenetv2-quantized.json --param-file=models/mobilenetv2-quantized.params --image-shape=3,224,224 --ctx=cpu --num-inference-batches=5
python3 run.py --symbol-file=models/resnet101_v1-quantized.json --param-file=models/resnet101_v1-quantized.params --image-shape=3,224,224 --ctx=cpu --num-inference-batches=5
python3 run.py --symbol-file=models/resnet-152-quantized.json --param-file=models/resnet-152-quantized.params --image-shape=3,224,224 --ctx=cpu --num-inference-batches=5
python3 run.py --symbol-file=models/resnet18_v1-quantized.json --param-file=models/resnet18_v1-quantized.params --image-shape=3,224,224 --ctx=cpu --num-inference-batches=5
python3 run.py --symbol-file=models/resnet50_v1b-quantized.json --param-file=models/resnet50_v1b-quantized.params --image-shape=3,224,224 --ctx=cpu --num-inference-batches=5
python3 run.py --symbol-file=models/resnet50_v1-quantized.json --param-file=models/resnet50_v1-quantized.params --image-shape=3,224,224 --ctx=cpu --num-inference-batches=5
