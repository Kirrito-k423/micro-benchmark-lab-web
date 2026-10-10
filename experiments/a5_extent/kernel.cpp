#include "kernel_operator.h"
using namespace AscendC;

// Total bytes are a logical request. A request larger than a UB window is tiled.
template<bool Store, bool Set>
__aicore__ inline void WindowEvent(uint32_t bank) {
    const auto event = bank ? EVENT_ID1 : EVENT_ID0;
    if constexpr (Store) {
        if constexpr (Set) SetFlag<HardEvent::MTE3_S>(event);
        else WaitFlag<HardEvent::MTE3_S>(event);
    } else {
        if constexpr (Set) SetFlag<HardEvent::MTE2_S>(event);
        else WaitFlag<HardEvent::MTE2_S>(event);
    }
}

template<int Api, bool Store>
__aicore__ inline void CopyTile(LocalTensor<uint32_t> ub, GlobalTensor<uint32_t> gm, uint32_t bytes) {
    if constexpr (Api == 0) {
        if constexpr (Store) DataCopy(gm, ub, bytes / 4);
        else DataCopy(ub, gm, bytes / 4);
    } else if constexpr (Api == 1) {
        const DataCopyParams p{1, static_cast<uint16_t>(bytes / 32), 0, 0};
        if constexpr (Store) DataCopy(gm, ub, p);
        else DataCopy(ub, gm, p);
    } else {
        // This overload's blockLen is uint16_t bytes, so use at most 32 KiB.
        const DataCopyParams p{1, static_cast<uint16_t>(bytes), 0, 0};
        if constexpr (Store) DataCopyPad(gm, ub, p);
        else DataCopyPad(ub, gm, p, DataCopyPadParams{false, 0, 0, 0});
    }
}

template<int Api, bool Store, int Windows, bool Trace>
__aicore__ inline void Work(GM_ADDR input, GM_ADDR output, GM_ADDR records,
    uint32_t total, uint32_t tile, uint32_t repeats, uint32_t stamp, uint32_t verify) {
    TPipe pipe;
    TBuf<TPosition::VECCALC> dataBuf, timerBuf;
    pipe.InitBuffer(dataBuf, Windows * tile);
    if constexpr (Trace) pipe.InitBuffer(timerBuf, 64);
    auto data = dataBuf.Get<uint32_t>();
    GlobalTensor<uint32_t> x, y;
    x.SetGlobalBuffer(reinterpret_cast<__gm__ uint32_t*>(input));
    y.SetGlobalBuffer(reinterpret_cast<__gm__ uint32_t*>(output));
    const uint32_t tiles = total / tile;
    if constexpr (Store) {
        Duplicate(data, stamp, Windows * tile / 4);
        SetFlag<HardEvent::V_MTE3>(EVENT_ID0); WaitFlag<HardEvent::V_MTE3>(EVENT_ID0);
    } else {
        Duplicate(data, uint32_t(0), Windows * tile / 4);
        SetFlag<HardEvent::V_MTE2>(EVENT_ID0); WaitFlag<HardEvent::V_MTE2>(EVENT_ID0);
    }
    // GetSystemCycle runs on Scalar: exclude asynchronous Duplicate completion explicitly.
    SetFlag<HardEvent::V_S>(EVENT_ID0); WaitFlag<HardEvent::V_S>(EVENT_ID0);
    uint64_t begin = 0, end = 0;
    if constexpr (Trace) begin = GetSystemCycle();
    for (uint32_t request = 0; request < repeats; ++request) {
        for (uint32_t i = 0; i < tiles; ++i) {
            const uint32_t bank = i % Windows;
            if constexpr (Windows == 2) {
                if (i >= 2) WindowEvent<Store, false>(bank);
            }
            if constexpr (Store) CopyTile<Api, true>(data[bank * tile / 4], y[i * tile / 4], tile);
            else CopyTile<Api, false>(data[bank * tile / 4], x[i * tile / 4], tile);
            WindowEvent<Store, true>(bank);
            if constexpr (Windows == 1) WindowEvent<Store, false>(bank);
            // Separate untimed functional launch: every read tile is exported and checked.
            if constexpr (!Store) {
                if (verify) {
                    if constexpr (Windows == 2) WindowEvent<false, false>(bank);
                    SetFlag<HardEvent::MTE2_MTE3>(EVENT_ID0); WaitFlag<HardEvent::MTE2_MTE3>(EVENT_ID0);
                    DataCopy(y[i * tile / 4], data[bank * tile / 4], tile / 4);
                    SetFlag<HardEvent::MTE3_MTE2>(EVENT_ID0); WaitFlag<HardEvent::MTE3_MTE2>(EVENT_ID0);
                    // Restore the consumed event for the ordinary reuse/drain protocol.
                    if constexpr (Windows == 2) WindowEvent<false, true>(bank);
                }
            }
        }
        // Each logical request completes independently, including its last DMA.
        if constexpr (Windows == 2) {
            WindowEvent<Store, false>(0);
            if (tiles >= 2) WindowEvent<Store, false>(1);
        }
    }
    if constexpr (Trace) end = GetSystemCycle();
    if constexpr (!Store) {
        if (!verify) {
            SetFlag<HardEvent::MTE2_MTE3>(EVENT_ID0); WaitFlag<HardEvent::MTE2_MTE3>(EVENT_ID0);
            DataCopy(y, data, Windows * tile / 4);
        }
    }
    if constexpr (Trace) {
        auto time = timerBuf.Get<uint64_t>();
        time.SetValue(0, begin); time.SetValue(1, end);
        time.SetValue(2, total); time.SetValue(3, tile);
        time.SetValue(4, repeats); time.SetValue(5, tiles);
        time.SetValue(6, Windows); time.SetValue(7, 0x414b4c4558544e31ULL);
        GlobalTensor<uint64_t> ticks;
        ticks.SetGlobalBuffer(reinterpret_cast<__gm__ uint64_t*>(records));
        SetFlag<HardEvent::S_MTE3>(EVENT_ID0); WaitFlag<HardEvent::S_MTE3>(EVENT_ID0);
        DataCopy(ticks, time, 8);
    }
    SetFlag<HardEvent::MTE3_S>(EVENT_ID0); WaitFlag<HardEvent::MTE3_S>(EVENT_ID0);
}

template<int Api, bool Trace>
__aicore__ inline void Select(GM_ADDR x, GM_ADDR y, GM_ADDR r, uint32_t direction,
    uint32_t total, uint32_t tile, uint32_t windows, uint32_t repeats, uint32_t stamp, uint32_t verify) {
    if (direction) {
        if (windows == 1) Work<Api, true, 1, Trace>(x,y,r,total,tile,repeats,stamp,verify);
        else Work<Api, true, 2, Trace>(x,y,r,total,tile,repeats,stamp,verify);
    } else {
        if (windows == 1) Work<Api, false, 1, Trace>(x,y,r,total,tile,repeats,stamp,verify);
        else Work<Api, false, 2, Trace>(x,y,r,total,tile,repeats,stamp,verify);
    }
}

template<bool Trace>
__aicore__ inline void Entry(GM_ADDR x, GM_ADDR y, GM_ADDR r, uint32_t api, uint32_t direction,
    uint32_t total, uint32_t tile, uint32_t windows, uint32_t repeats, uint32_t stamp, uint32_t verify) {
    if (api == 0) Select<0,Trace>(x,y,r,direction,total,tile,windows,repeats,stamp,verify);
    else if (api == 1) Select<1,Trace>(x,y,r,direction,total,tile,windows,repeats,stamp,verify);
    else Select<2,Trace>(x,y,r,direction,total,tile,windows,repeats,stamp,verify);
}

extern "C" __global__ __aicore__ void extent_trace(GM_ADDR x, GM_ADDR y, GM_ADDR r, uint32_t api,
    uint32_t direction, uint32_t total, uint32_t tile, uint32_t windows, uint32_t repeats, uint32_t stamp, uint32_t verify) {
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);
    Entry<true>(x,y,r,api,direction,total,tile,windows,repeats,stamp,verify);
}
extern "C" __global__ __aicore__ void extent_plain(GM_ADDR x, GM_ADDR y, GM_ADDR r, uint32_t api,
    uint32_t direction, uint32_t total, uint32_t tile, uint32_t windows, uint32_t repeats, uint32_t stamp, uint32_t verify) {
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);
    Entry<false>(x,y,r,api,direction,total,tile,windows,repeats,stamp,verify);
}
extern "C" void launch_extent(void* stream, void* x, void* y, void* r, uint32_t api, uint32_t direction,
    uint32_t total, uint32_t tile, uint32_t windows, uint32_t repeats, uint32_t stamp, uint32_t trace, uint32_t verify) {
    if (trace) extent_trace<<<1, windows * tile + 64, stream>>>(static_cast<uint8_t*>(x),static_cast<uint8_t*>(y),
        static_cast<uint8_t*>(r),api,direction,total,tile,windows,repeats,stamp,verify);
    else extent_plain<<<1, windows * tile, stream>>>(static_cast<uint8_t*>(x),static_cast<uint8_t*>(y),
        static_cast<uint8_t*>(r),api,direction,total,tile,windows,repeats,stamp,verify);
}
