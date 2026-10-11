#include <acl/acl.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <random>
#include <sstream>
#include <stdexcept>
#include <vector>

extern "C" void launch_duplex(void*,void*,void*,void*,void*,uint32_t,uint32_t,uint32_t,uint64_t,uint32_t,uint32_t,uint32_t);
extern "C" void launch_duplex_verify(void*,void*,void*,uint32_t,uint32_t,uint64_t);
static void Check(aclError rc,const char* action){if(rc)throw std::runtime_error(std::string(action)+" ACL="+std::to_string(rc));}
#define AC(call) Check((call),#call)
static uint32_t Input(uint64_t i){return 0x13579bdfu ^ (uint32_t(i)*2654435761u);}
static uint64_t Ceil(uint64_t n,uint64_t unit){return (n+unit-1)/unit*unit;}
struct Resources {
    int device=0;bool initialized=false,selected=false;
    void *x=nullptr,*y=nullptr,*retained=nullptr,*ticks=nullptr;
    aclrtStream stream=nullptr;aclrtEvent begin=nullptr,end=nullptr;
    void freeData(){for(void** p:{&x,&y,&retained,&ticks})if(*p){AC(aclrtFree(*p));*p=nullptr;}}
    ~Resources(){
        if(stream)aclrtSynchronizeStream(stream);
        for(void* p:{x,y,retained,ticks})if(p)aclrtFree(p);
        if(begin)aclrtDestroyEvent(begin);if(end)aclrtDestroyEvent(end);
        if(stream)aclrtDestroyStream(stream);
        if(selected)aclrtResetDevice(device);if(initialized)aclFinalize();
    }
};
struct Shape {uint32_t id,cores,tile;uint64_t requestedRing,targetBytes;};
struct Samples {
    std::vector<double> traced,plain,warmTrace,warmPlain,hostTrace,hostPlain;
    std::vector<std::vector<uint64_t>> ticks;
    std::vector<uint32_t> traceStamps,plainStamps;
};
template<class T> static void Array(std::ostream& out,const char* name,const std::vector<T>& v){
    out<<",\""<<name<<"\":[";for(size_t i=0;i<v.size();++i)out<<(i?",":"")<<v[i];out<<']';
}
int main(int argc,char** argv){
 try{
    if(argc!=10)throw std::runtime_error("DEVICE PLAN POLICY WARMUP SAMPLES SEED OUTPUT EXPECTED_UB EXPECTED_AIV");
    Resources r;r.device=std::stoi(argv[1]);const std::string policy=argv[3];
    if(policy!="normal"&&policy!="huge-first")throw std::runtime_error("Invalid allocation policy");
    const auto allocation=policy=="normal"?ACL_MEM_MALLOC_NORMAL_ONLY:ACL_MEM_MALLOC_HUGE_FIRST;
    const int warmup=std::stoi(argv[4]),samples=std::stoi(argv[5]);
    if(warmup<1||samples<2)throw std::runtime_error("Invalid sample count");
    std::mt19937 random(std::stoul(argv[6]));
    AC(aclInit(nullptr));r.initialized=true;AC(aclrtSetDevice(r.device));r.selected=true;
    int64_t aiv=0,ub=0;AC(aclrtGetDeviceInfo(r.device,static_cast<aclrtDevAttr>(201),&aiv));
    AC(aclrtGetDeviceInfo(r.device,static_cast<aclrtDevAttr>(204),&ub));
    const char* soc=aclrtGetSocName();
    if(!soc||std::string(soc).find("950")==std::string::npos||aiv!=std::stoll(argv[9])||ub!=std::stoll(argv[8]))
        throw std::runtime_error("Hardware differs from frozen plan");
    std::ifstream in(argv[2]);if(!in)throw std::runtime_error("Unreadable plan");
    std::vector<Shape> shapes;std::string line;
    while(std::getline(in,line)){
        std::replace(line.begin(),line.end(),',',' ');std::istringstream row(line);Shape c{};
        if(!(row>>c.id>>c.cores>>c.tile>>c.requestedRing>>c.targetBytes)||!c.cores||c.cores>aiv||
            !c.tile||c.tile%32||uint64_t(c.tile)*4+64+32768>uint64_t(ub)||
            !c.requestedRing||c.requestedRing>(uint64_t(2)<<30)||c.targetBytes<c.requestedRing)
            throw std::runtime_error("Invalid shape");
        shapes.push_back(c);
    }
    if(shapes.empty())throw std::runtime_error("Empty plan");
    AC(aclrtCreateStream(&r.stream));AC(aclrtCreateEventWithFlag(&r.begin,ACL_EVENT_TIME_LINE));
    AC(aclrtCreateEventWithFlag(&r.end,ACL_EVENT_TIME_LINE));
    std::ofstream out(argv[7]);if(!out)throw std::runtime_error("Cannot create output");out<<std::setprecision(17);
    for(const auto& c:shapes){
        r.freeData();const uint64_t bank=2*uint64_t(c.tile);
        const uint64_t perCoreRing=Ceil((c.requestedRing+c.cores-1)/c.cores,bank);
        const uint64_t ring=perCoreRing*c.cores,tail=bank*c.cores;
        const uint64_t groups64=std::max<uint64_t>(2,Ceil(Ceil(c.targetBytes,uint64_t(c.cores)*c.tile)/(uint64_t(c.cores)*c.tile),2));
        if(groups64>0xffffffffu||groups64*c.tile<perCoreRing)throw std::runtime_error("Incomplete ring coverage");
        const uint32_t groups=groups64;const uint64_t moved=groups64*c.cores*c.tile;
        const uint64_t inputAlloc=std::max(uint64_t(2)<<20,ring+128);
        const uint64_t outputAlloc=std::max(uint64_t(2)<<20,ring+128);
        size_t freeBytes=0,totalBytes=0;AC(aclrtGetMemInfo(ACL_HBM_MEM,&freeBytes,&totalBytes));
        if(inputAlloc+outputAlloc+tail+128+c.cores*64>freeBytes/2)throw std::runtime_error("Insufficient free GM");
        AC(aclrtMalloc(&r.x,inputAlloc,allocation));AC(aclrtMalloc(&r.y,outputAlloc,allocation));
        AC(aclrtMalloc(&r.retained,tail+128,ACL_MEM_MALLOC_NORMAL_ONLY));
        AC(aclrtMalloc(&r.ticks,c.cores*64,ACL_MEM_MALLOC_NORMAL_ONLY));
        if(r.x==r.y||r.x==r.retained||r.y==r.retained)throw std::runtime_error("Aliased buffers");
        std::vector<uint32_t> input(ring/4),actual((ring+128)/4),retained((tail+128)/4);
        for(uint64_t i=0;i<input.size();++i)input[i]=Input(i);
        AC(aclrtMemset(r.x,inputAlloc,0xa5,inputAlloc));
        AC(aclrtMemcpy(r.x,inputAlloc,input.data(),ring,ACL_MEMCPY_HOST_TO_DEVICE));
        // One independent full read oracle for every allocation/shape.
        AC(aclrtMemset(r.y,outputAlloc,0xa5,ring+128));
        launch_duplex_verify(r.stream,r.x,r.y,c.cores,c.tile,perCoreRing);AC(aclrtSynchronizeStream(r.stream));
        AC(aclrtMemcpy(actual.data(),actual.size()*4,r.y,ring+128,ACL_MEMCPY_DEVICE_TO_HOST));
        for(uint64_t i=0;i<ring/4;++i)if(actual[i]!=input[i])throw std::runtime_error("Full read oracle mismatch");
        for(uint64_t i=ring/4;i<actual.size();++i)if(actual[i]!=0xa5a5a5a5u)throw std::runtime_error("Full read guard mismatch");
        std::array<Samples,4> data;std::vector<std::vector<int>> launchOrder;
        for(int s=0;s<warmup+samples;++s){
            std::vector<int> order(8);std::iota(order.begin(),order.end(),0);std::shuffle(order.begin(),order.end(),random);
            launchOrder.push_back(order);
            for(int code:order){
                const uint32_t mode=code/2,trace=code%2;
                const uint32_t stamp=0x60000000u^(97*c.id+17*s+code+1);
                AC(aclrtMemset(r.y,outputAlloc,0xa5,ring+128));
                AC(aclrtMemset(r.retained,tail+128,0xa5,tail+128));AC(aclrtMemset(r.ticks,c.cores*64,0,c.cores*64));
                const auto start=std::chrono::steady_clock::now();
                AC(aclrtRecordEvent(r.begin,r.stream));
                launch_duplex(r.stream,r.x,r.y,r.retained,r.ticks,c.cores,mode,c.tile,perCoreRing,groups,stamp,trace);
                AC(aclrtRecordEvent(r.end,r.stream));AC(aclrtSynchronizeStream(r.stream));
                const double hostUs=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-start).count();
                float ms=0;AC(aclrtEventElapsedTime(&ms,r.begin,r.end));if(!(ms>0))throw std::runtime_error("Invalid common event");
                std::vector<uint64_t> tick(c.cores*8);AC(aclrtMemcpy(tick.data(),tick.size()*8,r.ticks,tick.size()*8,ACL_MEMCPY_DEVICE_TO_HOST));
                for(uint32_t core=0;core<c.cores;++core){
                    const uint64_t* t=tick.data()+core*8;
                    if(trace){
                        if(t[1]<=t[0]||t[4]!=core||t[5]!=groups||t[6]!=mode||t[7]!=0x414b4c4455504c31ULL||
                            (t[2]&&(t[2]<t[0]||t[2]>t[1]))||(t[3]&&(t[3]<t[0]||t[3]>t[1])))throw std::runtime_error("Invalid core receipt");
                    }else for(int j=0;j<8;++j)if(t[j])throw std::runtime_error("Plain emitted ticks");
                }
                AC(aclrtMemcpy(actual.data(),actual.size()*4,r.y,ring+128,ACL_MEMCPY_DEVICE_TO_HOST));
                for(uint32_t core=0;core<c.cores;++core){
                    const uint32_t expected=mode==1||mode==2?(0x9e3779b9u*(core+1))^stamp:0xa5a5a5a5u;
                    const uint64_t start=uint64_t(core)*perCoreRing/4;
                    for(uint64_t i=0;i<perCoreRing/4;++i)if(actual[start+i]!=expected)throw std::runtime_error("Full write/untouched target mismatch");
                }
                for(uint64_t i=ring/4;i<actual.size();++i)if(actual[i]!=0xa5a5a5a5u)throw std::runtime_error("Write guard mismatch");
                AC(aclrtMemcpy(retained.data(),retained.size()*4,r.retained,tail+128,ACL_MEMCPY_DEVICE_TO_HOST));
                for(uint32_t core=0;core<c.cores;++core)for(uint32_t b=0;b<2;++b){
                    const uint64_t src=uint64_t(core)*perCoreRing+(uint64_t(groups-2+b)*c.tile)%perCoreRing;
                    const uint64_t dst=(uint64_t(core)*2+b)*c.tile/4;
                    for(uint32_t i=0;i<c.tile/4;++i){
                        const uint32_t expected=mode==0||mode==2?Input(src/4+i):0;
                        if(retained[dst+i]!=expected)throw std::runtime_error("Full retained read window mismatch");
                    }
                }
                for(uint64_t i=tail/4;i<retained.size();++i)if(retained[i]!=0xa5a5a5a5u)throw std::runtime_error("Retained guard mismatch");
                uint32_t guard[32];AC(aclrtMemcpy(guard,128,static_cast<uint8_t*>(r.x)+ring,128,ACL_MEMCPY_DEVICE_TO_HOST));
                for(auto v:guard)if(v!=0xa5a5a5a5u)throw std::runtime_error("Input guard mismatch");
                auto& d=data[mode];
                if(s<warmup)(trace?d.warmTrace:d.warmPlain).push_back(ms);
                else{
                    (trace?d.traced:d.plain).push_back(ms);(trace?d.hostTrace:d.hostPlain).push_back(hostUs);
                    (trace?d.traceStamps:d.plainStamps).push_back(stamp);if(trace)d.ticks.push_back(std::move(tick));
                }
            }
        }
        for(uint32_t mode=0;mode<4;++mode){
            const auto& d=data[mode];const uint64_t readBytes=mode==0||mode==2?moved:0,writeBytes=mode==1||mode==2?moved:0;
            out<<"{\"id\":"<<c.id*4+mode<<",\"shape_id\":"<<c.id<<",\"mode\":"<<mode<<",\"cores\":"<<c.cores
                <<",\"tile_bytes\":"<<c.tile<<",\"windows_per_direction\":2,\"requested_ring_bytes\":"<<c.requestedRing
                <<",\"actual_ring_bytes_per_direction\":"<<ring<<",\"per_core_ring_bytes\":"<<perCoreRing
                <<",\"target_bytes_per_direction\":"<<c.targetBytes<<",\"groups\":"<<groups
                <<",\"read_bytes\":"<<readBytes<<",\"write_bytes\":"<<writeBytes<<",\"moved_bytes\":"<<readBytes+writeBytes
                <<",\"input_allocation_bytes\":"<<inputAlloc<<",\"output_allocation_bytes\":"<<outputAlloc
                <<",\"retained_allocation_bytes\":"<<tail+128<<",\"policy\":\""<<policy<<"\",\"soc\":\""<<soc
                <<"\",\"available_aiv\":"<<aiv<<",\"ub_bytes\":"<<ub<<",\"full_read_oracle\":true"
                <<",\"correctness\":true,\"validated_every_launch\":true,\"independent_addresses\":true,\"guard_bytes\":128";
            Array(out,"trace_event_ms",d.traced);Array(out,"plain_event_ms",d.plain);Array(out,"warmup_trace_event_ms",d.warmTrace);
            Array(out,"warmup_plain_event_ms",d.warmPlain);Array(out,"trace_host_us",d.hostTrace);Array(out,"plain_host_us",d.hostPlain);
            Array(out,"trace_stamps",d.traceStamps);Array(out,"plain_stamps",d.plainStamps);
            out<<",\"launch_order\":[";for(size_t i=0;i<launchOrder.size();++i){out<<(i?",[":"[");for(size_t j=0;j<8;++j)out<<(j?",":"")<<launchOrder[i][j];out<<']';}
            out<<"],\"core_raw_ticks\":[";for(size_t i=0;i<d.ticks.size();++i){out<<(i?",[":"[");for(size_t j=0;j<d.ticks[i].size();++j)out<<(j?",\"":"\"")<<d.ticks[i][j]<<'"';out<<']';}
            out<<"]}\n";out.flush();
        }
        std::cout<<"PASS shape="<<c.id<<" cores="<<c.cores<<" per-direction-ring="<<ring<<std::endl;
    }
    return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
