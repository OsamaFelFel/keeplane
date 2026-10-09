# Run Qwen3 4B beside the Docker preview

The optional Qwen3 4B runner uses llama.cpp on this computer. Keeplane's app
and gateway remain in Docker. The model file is downloaded once and stays out
of Git. These commands reproduce the configuration tested on the current Mac.

From this repository:

```sh
mkdir -p models
curl -L --fail --output models/qwen3-4b-instruct-2507-q4_k_m.gguf \
  https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/ae44f08e1392f39c0e474af10c3ff8355c8b6688/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
shasum -a 256 models/qwen3-4b-instruct-2507-q4_k_m.gguf
git clone https://github.com/ggml-org/llama.cpp.git ../llama.cpp-keeplane-preview
git -C ../llama.cpp-keeplane-preview checkout 3d65c90d04d337e88f2b1f7f0061f40a5324e662
cmake -S ../llama.cpp-keeplane-preview -B ../llama.cpp-keeplane-preview/build-keeplane \
  -DGGML_METAL=OFF -DGGML_BLAS=ON -DGGML_BLAS_VENDOR=Apple
cmake --build ../llama.cpp-keeplane-preview/build-keeplane --target llama-server -j 6
python3 scripts/run_local_qwen3.py \
  --runner-binary ../llama.cpp-keeplane-preview/build-keeplane/bin/llama-server \
  --model-file models/qwen3-4b-instruct-2507-q4_k_m.gguf
```

The expected model SHA-256 is
`2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e`.
The start script verifies both the model hash and the llama.cpp source commit.
Keep the runner terminal open. Its health endpoint is
`http://127.0.0.1:14424/health` and it serves 12,288 active context tokens.

Start the [Docker preview](local-preview.md) and, for admin approval, the
[protected preview](accounts-local.md). On **Models and routing**, choose
**Add model** → **Local runner**, enter
`http://host.docker.internal:14424`, and choose **Find models**. Select
`qwen3-4b-instruct`, choose its approved data classes, then add it. The
gateway checks an answer before Keeplane saves the model. The host address
is explicitly allowed only in this local preview. Stop the native runner
with Ctrl-C when finished.

The model is an optional local trial, not a release default. It needs enough
host memory and CPU to run alongside Docker. Model discovery and a real answer
are checked by the [Qwen3 local cases](../../tests/e2e/qwen3-local-cases.md).
