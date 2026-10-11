#include "kernel_operator.h"
using namespace AscendC;

template<bool Write, bool Set>
__aicore__ inline void Done(uint32_t bank) {
    const auto event = bank ? EVENT_ID1 : EVENT_ID0;
    if constexpr (Write) {
        if constexpr (Set) SetFlag<HardEvent::MTE3_S>(event);
        else WaitFlag<HardEvent::MTE3_S>(event);
    } else {
        if constexpr (Set) SetFlag<HardEvent::MTE2_S>(event);
        else WaitFlag<HardEvent::MTE2_S>(event);
    }
}

// The MTE2 read buffer and MTE3 write buffer are independent. No GM aliases.
template<bool Read, bool Write, bool Control, bool Trace>
__aicore__ inline void Work(GM_ADDR input, GM_ADDR output, GM_ADDR retained,
    GM_ADDR records, uint32_t tile, uint64_t perCoreRing, uint32_t groups,
    uint32_t stamp, uint32_t mode) {
    const uint32_t core = GetBlockIdx();
    TPipe pipe;
    TBuf<TPosition::VECCALC> readBuf, writeBuf, timerBuf;
    pipe.InitBuffer(readBuf, 2 * tile);
    pipe.InitBuffer(writeBuf, 2 * tile);
    if constexpr (Trace) pipe.InitBuffer(timerBuf, 64);
    auto read = readBuf.Get<uint32_t>(); auto write = writeBuf.Get<uint32_t>();
    Duplicate(read, uint32_t(0), 2 * tile / 4);
    Duplicate(write, (0x9e3779b9u * (core + 1)) ^ stamp, 2 * tile / 4);
    SetFlag<HardEvent::V_MTE2>(EVENT_ID0); WaitFlag<HardEvent::V_MTE2>(EVENT_ID0);
    SetFlag<HardEvent::V_MTE3>(EVENT_ID0); WaitFlag<HardEvent::V_MTE3>(EVENT_ID0);
    SetFlag<HardEvent::V_S>(EVENT_ID0); WaitFlag<HardEvent::V_S>(EVENT_ID0);
    GlobalTensor<uint32_t> x,y,z;
    x.SetGlobalBuffer(reinterpret_cast<__gm__ uint32_t*>(input));
    y.SetGlobalBuffer(reinterpret_cast<__gm__ uint32_t*>(output));
    z.SetGlobalBuffer(reinterpret_cast<__gm__ uint32_t*>(retained));
    const uint64_t base = uint64_t(core) * perCoreRing;
    uint64_t begin = 0, end = 0, readObserved = 0, writeObserved = 0;
    SyncAll();
    if constexpr (Trace) begin = GetSystemCycle();
    uint64_t cursor = 0;
    for (uint32_t i=0; i<groups; ++i) {
        const uint32_t bank = i & 1;
        if (i >= 2) {
            if constexpr (Read) Done<false,false>(bank);
            if constexpr (Write) Done<true,false>(bank);
        }
        // Submit both directions before any completion wait for this group.
        if constexpr (Read && !Control) DataCopy(read[bank*tile/4],x[(base+cursor)/4],tile/4);
        if constexpr (Write && !Control) DataCopy(y[(base+cursor)/4],write[bank*tile/4],tile/4);
        if constexpr (Read) Done<false,true>(bank);
        if constexpr (Write) Done<true,true>(bank);
        if constexpr (Control) asm volatile("" ::: "memory");
        cursor += tile; if (cursor == perCoreRing) cursor = 0;
    }
    if constexpr (Read) {
        Done<false,false>(0); Done<false,false>(1);
        if constexpr (Trace) readObserved = GetSystemCycle();
    }
    if constexpr (Write) {
        Done<true,false>(0); Done<true,false>(1);
        if constexpr (Trace) writeObserved = GetSystemCycle();
    }
    if constexpr (Trace) end = GetSystemCycle();
    // Scalar observation stamps are upper bounds; do not divide bytes by them.
    SyncAll();
    SetFlag<HardEvent::MTE2_MTE3>(EVENT_ID0); WaitFlag<HardEvent::MTE2_MTE3>(EVENT_ID0);
    DataCopy(z[uint64_t(core)*2*tile/4],read,2*tile/4);
    if constexpr (Trace) {
        auto time = timerBuf.Get<uint64_t>();
        time.SetValue(0,begin); time.SetValue(1,end);
        time.SetValue(2,readObserved); time.SetValue(3,writeObserved);
        time.SetValue(4,core); time.SetValue(5,groups);
        time.SetValue(6,mode); time.SetValue(7,0x414b4c4455504c31ULL);
        GlobalTensor<uint64_t> ticks;
        ticks.SetGlobalBuffer(reinterpret_cast<__gm__ uint64_t*>(records));
        SetFlag<HardEvent::S_MTE3>(EVENT_ID0); WaitFlag<HardEvent::S_MTE3>(EVENT_ID0);
        DataCopy(ticks[core*8],time,8);
    }
    SetFlag<HardEvent::MTE3_S>(EVENT_ID0); WaitFlag<HardEvent::MTE3_S>(EVENT_ID0);
}

template<bool Trace>
__aicore__ inline void Entry(GM_ADDR x,GM_ADDR y,GM_ADDR retained,GM_ADDR ticks,
    uint32_t mode,uint32_t tile,uint64_t perCoreRing,uint32_t groups,uint32_t stamp) {
    if (mode==0) Work<true,false,false,Trace>(x,y,retained,ticks,tile,perCoreRing,groups,stamp,mode);
    else if (mode==1) Work<false,true,false,Trace>(x,y,retained,ticks,tile,perCoreRing,groups,stamp,mode);
    else if (mode==2) Work<true,true,false,Trace>(x,y,retained,ticks,tile,perCoreRing,groups,stamp,mode);
    else Work<true,true,true,Trace>(x,y,retained,ticks,tile,perCoreRing,groups,stamp,mode);
}
extern "C" __global__ __aicore__ void duplex_trace(GM_ADDR x,GM_ADDR y,GM_ADDR z,GM_ADDR t,
    uint32_t mode,uint32_t tile,uint64_t ring,uint32_t groups,uint32_t stamp) {
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);
    Entry<true>(x,y,z,t,mode,tile,ring,groups,stamp);
}
extern "C" __global__ __aicore__ void duplex_plain(GM_ADDR x,GM_ADDR y,GM_ADDR z,GM_ADDR t,
    uint32_t mode,uint32_t tile,uint64_t ring,uint32_t groups,uint32_t stamp) {
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);
    Entry<false>(x,y,z,t,mode,tile,ring,groups,stamp);
}
extern "C" void launch_duplex(void* stream,void* x,void* y,void* z,void* t,uint32_t cores,
    uint32_t mode,uint32_t tile,uint64_t ring,uint32_t groups,uint32_t stamp,uint32_t trace) {
    if (trace) duplex_trace<<<cores,4*tile+64,stream>>>(static_cast<uint8_t*>(x),
        static_cast<uint8_t*>(y),static_cast<uint8_t*>(z),static_cast<uint8_t*>(t),mode,tile,ring,groups,stamp);
    else duplex_plain<<<cores,4*tile,stream>>>(static_cast<uint8_t*>(x),
        static_cast<uint8_t*>(y),static_cast<uint8_t*>(z),static_cast<uint8_t*>(t),mode,tile,ring,groups,stamp);
}

// Independent, untimed oracle exports every read tile, not just the retained tail.
extern "C" __global__ __aicore__ void duplex_verify(GM_ADDR input,GM_ADDR output,
    uint32_t tile,uint64_t perCoreRing) {
    KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);
    TPipe pipe; TBuf<TPosition::VECCALC> buf; pipe.InitBuffer(buf,tile);
    auto data=buf.Get<uint32_t>();
    GlobalTensor<uint32_t> x,y;
    x.SetGlobalBuffer(reinterpret_cast<__gm__ uint32_t*>(input));
    y.SetGlobalBuffer(reinterpret_cast<__gm__ uint32_t*>(output));
    const uint64_t base=uint64_t(GetBlockIdx())*perCoreRing;
    for(uint64_t cursor=0;cursor<perCoreRing;cursor+=tile) {
        DataCopy(data,x[(base+cursor)/4],tile/4);
        SetFlag<HardEvent::MTE2_MTE3>(EVENT_ID0); WaitFlag<HardEvent::MTE2_MTE3>(EVENT_ID0);
        DataCopy(y[(base+cursor)/4],data,tile/4);
        SetFlag<HardEvent::MTE3_MTE2>(EVENT_ID0); WaitFlag<HardEvent::MTE3_MTE2>(EVENT_ID0);
    }
    SetFlag<HardEvent::MTE3_S>(EVENT_ID0); WaitFlag<HardEvent::MTE3_S>(EVENT_ID0);
}
extern "C" void launch_duplex_verify(void* stream,void* x,void* y,uint32_t cores,
    uint32_t tile,uint64_t perCoreRing) {
    duplex_verify<<<cores,tile,stream>>>(static_cast<uint8_t*>(x),static_cast<uint8_t*>(y),tile,perCoreRing);
}
