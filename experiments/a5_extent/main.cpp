#include <acl/acl.h>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <stdexcept>
#include <vector>

extern "C" void launch_extent(void*,void*,void*,void*,uint32_t,uint32_t,uint32_t,uint32_t,
    uint32_t,uint32_t,uint32_t,uint32_t,uint32_t);
static void Check(aclError rc,const char* action) {
    if(rc)throw std::runtime_error(std::string(action)+" ACL="+std::to_string(rc));
}
#define AC(call) Check((call),#call)
static uint32_t InputValue(uint64_t i) { return 0x13579bdfu ^ (uint32_t(i)*2654435761u); }
struct Resources {
    int device; bool initialized=false,selected=false;
    void *x=nullptr,*out=nullptr,*ticks=nullptr;
    aclrtStream stream=nullptr; aclrtEvent begin=nullptr,end=nullptr;
    void freeData(){if(x){AC(aclrtFree(x));x=nullptr;}if(out){AC(aclrtFree(out));out=nullptr;}}
    ~Resources(){
        if(stream)aclrtSynchronizeStream(stream);
        for(void* p:{x,out,ticks})if(p)aclrtFree(p);
        if(begin)aclrtDestroyEvent(begin);if(end)aclrtDestroyEvent(end);
        if(stream)aclrtDestroyStream(stream);
        if(selected)aclrtResetDevice(device);if(initialized)aclFinalize();
    }
};
struct Case { uint32_t id,api,direction,bytes,tile,windows,repeats; };
int main(int argc,char** argv) {
    try {
        if(argc!=9)throw std::runtime_error("DEVICE PLAN POLICY WARMUP SAMPLES SEED OUTPUT EXPECTED_UB");
        Resources r{};r.device=std::stoi(argv[1]);
        const std::string policy=argv[3];
        if(policy!="normal"&&policy!="huge-first")throw std::runtime_error("Unsupported allocation policy");
        const auto allocation=policy=="normal"?ACL_MEM_MALLOC_NORMAL_ONLY:ACL_MEM_MALLOC_HUGE_FIRST;
        const int warmup=std::stoi(argv[4]),samples=std::stoi(argv[5]);
        if(warmup<1||samples<1)throw std::runtime_error("Invalid sample count");
        std::mt19937 random(std::stoul(argv[6]));
        AC(aclInit(nullptr));r.initialized=true;AC(aclrtSetDevice(r.device));r.selected=true;
        int64_t aiv=0,ub=0;
        AC(aclrtGetDeviceInfo(r.device,static_cast<aclrtDevAttr>(201),&aiv));
        AC(aclrtGetDeviceInfo(r.device,static_cast<aclrtDevAttr>(204),&ub));
        const char* soc=aclrtGetSocName();
        if(!soc||std::string(soc).find("950")==std::string::npos||aiv<1||ub!=std::stoll(argv[8]))
            throw std::runtime_error("Hardware differs from frozen plan");
        std::ifstream in(argv[2]);if(!in)throw std::runtime_error("Unreadable plan");
        std::vector<Case> cases;std::string line;
        while(std::getline(in,line)) {
            std::replace(line.begin(),line.end(),',',' ');std::istringstream row(line);Case c{};
            if(!(row>>c.id>>c.api>>c.direction>>c.bytes>>c.tile>>c.windows>>c.repeats))
                throw std::runtime_error("Invalid plan row");
            if(c.api>2||c.direction>1||c.bytes<32||c.bytes>(4u<<20)||(c.bytes&(c.bytes-1))||
                !c.tile||c.tile%32||c.bytes%c.tile||c.tile>65536||(c.api==2&&c.tile>32768)||
                (c.windows!=1&&c.windows!=2)||!c.repeats||c.repeats>8192||
                uint64_t(c.windows)*c.tile+64+32768>uint64_t(ub))throw std::runtime_error("Invalid geometry");
            cases.push_back(c);
        }
        if(cases.empty())throw std::runtime_error("Empty plan");
        AC(aclrtCreateStream(&r.stream));AC(aclrtCreateEventWithFlag(&r.begin,ACL_EVENT_TIME_LINE));
        AC(aclrtCreateEventWithFlag(&r.end,ACL_EVENT_TIME_LINE));
        AC(aclrtMalloc(&r.ticks,64,ACL_MEM_MALLOC_NORMAL_ONLY));
        std::ofstream out(argv[7]);if(!out)throw std::runtime_error("Unreadable output");out<<std::setprecision(17);
        for(const auto& c:cases) {
            r.freeData();
            const uint32_t sinkBytes=c.windows*c.tile;
            const uint32_t inputBytes=std::max(2u<<20,c.bytes);
            const uint32_t outputBytes=std::max(2u<<20,std::max(c.bytes,sinkBytes)+128);
            size_t freeBytes=0,totalBytes=0;AC(aclrtGetMemInfo(ACL_HBM_MEM,&freeBytes,&totalBytes));
            if(uint64_t(inputBytes)+outputBytes+64>freeBytes/2)throw std::runtime_error("Insufficient free GM");
            AC(aclrtMalloc(&r.x,inputBytes,allocation));AC(aclrtMalloc(&r.out,outputBytes,allocation));
            std::vector<uint32_t> input(c.bytes/4),actual((std::max(c.bytes,sinkBytes)+128)/4);
            for(size_t i=0;i<input.size();++i)input[i]=InputValue(i);
            AC(aclrtMemcpy(r.x,inputBytes,input.data(),c.bytes,ACL_MEMCPY_HOST_TO_DEVICE));
            // An independent untimed launch validates all read tiles, not only the retained UB tail.
            AC(aclrtMemset(r.out,outputBytes,0xa5,outputBytes));
            launch_extent(r.stream,r.x,r.out,r.ticks,c.api,0,c.bytes,c.tile,c.windows,1,0,0,1);
            AC(aclrtSynchronizeStream(r.stream));
            AC(aclrtMemcpy(actual.data(),actual.size()*4,r.out,c.bytes+128,ACL_MEMCPY_DEVICE_TO_HOST));
            for(size_t i=0;i<input.size();++i)if(actual[i]!=input[i])throw std::runtime_error("Full read oracle mismatch");
            for(size_t i=input.size();i<input.size()+32;++i)if(actual[i]!=0xa5a5a5a5u)throw std::runtime_error("Full read guard mismatch");
            std::vector<double> traceMs,plainMs,warmTrace,warmPlain,host;
            std::vector<std::vector<uint64_t>> ticks;
            std::vector<std::vector<uint32_t>> stamps;
            std::vector<uint32_t> order;
            for(int s=0;s<warmup+samples;++s) {
                const uint32_t first=random()%2;order.push_back(first);
                std::vector<uint32_t> pairStamp;
                for(uint32_t pass=0;pass<2;++pass) {
                    const uint32_t trace=(first+pass)%2;
                    const uint32_t stamp=0x60000000u ^ (97*c.id+17*s+trace+1);
                    pairStamp.push_back(stamp);
                    const uint32_t validBytes=c.direction?c.bytes:sinkBytes;
                    AC(aclrtMemset(r.out,outputBytes,0xa5,validBytes+128));AC(aclrtMemset(r.ticks,64,0,64));
                    const auto start=std::chrono::steady_clock::now();
                    AC(aclrtRecordEvent(r.begin,r.stream));
                    launch_extent(r.stream,r.x,r.out,r.ticks,c.api,c.direction,c.bytes,c.tile,c.windows,c.repeats,stamp,trace,0);
                    AC(aclrtRecordEvent(r.end,r.stream));AC(aclrtSynchronizeStream(r.stream));
                    const double hostUs=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count();
                    float ms=0;AC(aclrtEventElapsedTime(&ms,r.begin,r.end));
                    if(!(ms>0))throw std::runtime_error("Nonpositive ACL time");
                    std::vector<uint64_t> tick(8);AC(aclrtMemcpy(tick.data(),64,r.ticks,64,ACL_MEMCPY_DEVICE_TO_HOST));
                    if(trace&&(tick[1]<=tick[0]||tick[2]!=c.bytes||tick[3]!=c.tile||tick[4]!=c.repeats||
                        tick[5]!=c.bytes/c.tile||tick[6]!=c.windows||tick[7]!=0x414b4c4558544e31ULL))
                        throw std::runtime_error("Invalid timing receipt");
                    if(!trace&&std::any_of(tick.begin(),tick.end(),[](uint64_t v){return v!=0;}))throw std::runtime_error("Plain launch emitted ticks");
                    AC(aclrtMemcpy(actual.data(),actual.size()*4,r.out,validBytes+128,ACL_MEMCPY_DEVICE_TO_HOST));
                    for(uint32_t i=0;i<validBytes/4;++i) {
                        uint32_t expected=stamp;
                        if(!c.direction) {
                            const uint32_t bank=(i*4)/c.tile;
                            int64_t last=int64_t(c.bytes/c.tile)-1;
                            while(last>=0&&uint32_t(last)%c.windows!=bank)--last;
                            expected=last<0?0:InputValue((uint64_t(last)*c.tile+i*4%c.tile)/4);
                        }
                        if(actual[i]!=expected)throw std::runtime_error("Timed result mismatch case="+std::to_string(c.id));
                    }
                    for(uint32_t i=validBytes/4;i<validBytes/4+32;++i)
                        if(actual[i]!=0xa5a5a5a5u)throw std::runtime_error("Timed guard mismatch");
                    if(s<warmup)(trace?warmTrace:warmPlain).push_back(ms);
                    else {
                        (trace?traceMs:plainMs).push_back(ms);
                        if(trace){host.push_back(hostUs);ticks.push_back(std::move(tick));}
                    }
                }
                stamps.push_back(std::move(pairStamp));
            }
            out<<"{\"id\":"<<c.id<<",\"api\":"<<c.api<<",\"direction\":"<<c.direction<<",\"total_bytes\":"<<c.bytes
                <<",\"tile_bytes\":"<<c.tile<<",\"windows\":"<<c.windows<<",\"repeats\":"<<c.repeats
                <<",\"tiles_per_request\":"<<c.bytes/c.tile<<",\"moved_bytes\":"<<uint64_t(c.bytes)*c.repeats
                <<",\"working_set_bytes\":"<<c.bytes<<",\"input_allocation_bytes\":"<<inputBytes
                <<",\"output_allocation_bytes\":"<<outputBytes<<",\"policy\":\""<<policy<<"\",\"soc\":\""<<soc
                <<"\",\"available_aiv\":"<<aiv<<",\"ub_bytes\":"<<ub<<",\"full_read_oracle\":true"
                <<",\"correctness\":true,\"validated_every_launch\":true,\"guard_bytes\":128";
            auto array=[&](const char* name,const auto& values){out<<",\""<<name<<"\":[";for(size_t i=0;i<values.size();++i)out<<(i?",":"")<<values[i];out<<']';};
            array("trace_event_ms",traceMs);array("plain_event_ms",plainMs);array("warmup_trace_event_ms",warmTrace);
            array("warmup_plain_event_ms",warmPlain);array("host_launch_sync_us",host);array("trace_order",order);
            out<<",\"raw_ticks\":[";
            for(size_t i=0;i<ticks.size();++i){out<<(i?",[":"[");for(size_t j=0;j<8;++j)out<<(j?",\"":"\"")<<ticks[i][j]<<'"';out<<']';}
            out<<"],\"launch_stamps\":[";
            for(size_t i=0;i<stamps.size();++i){out<<(i?",[":"[");for(size_t j=0;j<2;++j)out<<(j?",":"")<<stamps[i][j];out<<']';}
            out<<"}\n";out.flush();std::cout<<"PASS "<<c.id<<" bytes="<<c.bytes<<" api="<<c.api<<" direction="<<c.direction<<" windows="<<c.windows<<std::endl;
        }
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
