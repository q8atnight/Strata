// include/strata/prefill/gemm.hpp - plan v0.3 P5: the batched projections of prompt processing.
//
// Every projection of a chunk of T tokens is Y[T, N] = X[T, K] . W[N, K]^T with W row-major (the GGUF / pack layout)
// and FP32 outputs.  Weights are BF16 on the device - either already (the pack's BF16 tensors) or dequantized from
// their native GGUF blocks into a reusable scratch (`dequant_bf16`) right before the product - and activations are
// rounded to BF16, which is also what llama.cpp's batched CUDA path does.  Tensor-core GEMM through cuBLAS.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

namespace strata::prefill {

class Gemm {
public:
    Gemm() = default;
    ~Gemm();
    Gemm(const Gemm&) = delete;
    Gemm& operator=(const Gemm&) = delete;

    /// `scratch_elems`: BF16 elements of the dequantization scratch (the largest weight dequantized at once).
    bool init(void* stream, int64_t scratch_elems, std::string& err);
    /// The same with caller-owned device buffers (the prompt path borrowing expert-cache slots).
    bool init_external(void* stream, uint16_t* scratch, int64_t scratch_elems, void* workspace, size_t ws_bytes,
                       std::string& err);

    /// Y[T, N] (fp32, row stride ldy) = X[T, K] (bf16, row-major) . W[N, K]^T (bf16, row-major).  `beta` = 1 adds.
    void bf16(const uint16_t* X, const uint16_t* W, float* Y, int64_t T, int64_t N, int64_t K, int64_t ldy = 0,
              float beta = 0.0f);

    /// Y = X . W^T with both in FP16 (bits).
    void f16(const uint16_t* X, const uint16_t* W, float* Y, int64_t T, int64_t N, int64_t K, int64_t ldy = 0,
             float beta = 0.0f);

    /// W given as native GGUF blocks of `ggml_type`, dequantized to FP16 in the scratch, X in FP16.
    void native(const uint16_t* X, int ggml_type, const void* W_blocks, float* Y, int64_t T, int64_t N, int64_t K,
                int64_t ldy = 0, float beta = 0.0f);

    /// P1: the same for a SUBSET of W's rows, given as `nruns` ranges [r0, r0 + rows): each range is dequantized
    /// into consecutive rows of the scratch and one product writes Y's columns in run order (Y[T, sum rows]).
    void native_runs(const uint16_t* X, int ggml_type, const void* W_blocks, const int64_t* r0, const int64_t* rows,
                     int nruns, float* Y, int64_t T, int64_t K, int64_t ldy, int64_t N_ref);

    /// P1: only the dequantization of native_runs, into `dst` (FP16, rows in run order).
    void dequant_runs(int ggml_type, const void* W_blocks, const int64_t* r0, const int64_t* rows, int nruns,
                      int64_t K, uint16_t* dst);

    /// P1: Y = X . W^T in FP16 like f16, for a SUBSET of a bigger weight's rows, with the same bits the full product
    /// [T_ref tokens x N_ref rows] gives: cuBLAS' K order depends only on the split-K factor and the reduction
    /// scheme (measured: every tensor-core kernel with the same split gives the same bits; GemmEx picks split-K 2 for
    /// N=6144 and none for N=10240 at T=8192, and other ones for the subsets) - so the subset takes a cublasLt
    /// algorithm with the split the full shape's first heuristic choice has (= what GemmEx runs, measured).
    void f16_exact(const uint16_t* X, const uint16_t* W, float* Y, int64_t T, int64_t N, int64_t K, int64_t ldy,
                   int64_t T_ref, int64_t N_ref);

    /// Caller-owned buffers only: the scratch and workspace moved (the prompt path laid its buffers out again).
    void rebind(uint16_t* scratch, int64_t scratch_elems, void* workspace, size_t ws_bytes);

    uint16_t* scratch() const { return scratch_; }
    int64_t scratch_elems() const { return scratch_elems_; }
    void* stream() const { return stream_; }

private:
    void* handle_ = nullptr;
    void* stream_ = nullptr;
    uint16_t* scratch_ = nullptr;
    int64_t scratch_elems_ = 0;
    void* workspace_ = nullptr;
    bool external_ = false;
    void* hipblaslt_state_ = nullptr;
    void* lt_ = nullptr;      // P1: cublasLt handle (created on first use)
    void* lt_cache_ = nullptr;
};



}  // namespace strata::prefill
